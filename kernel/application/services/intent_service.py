"""意图缓存读取、写入、流式分析与缓存管理服务。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from kernel.ports.intent import CachePort, IntentPort


def _is_digest(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value.lower())


class IntentService:
    """意图与缓存能力；具体实现通过端口注入，默认使用 infrastructure 适配器。"""

    def __init__(
        self,
        *,
        intent_port: Optional[IntentPort] = None,
        cache_port: Optional[CachePort] = None,
    ) -> None:
        # 允许测试注入替身；默认惰性使用 infrastructure 的旧 API 适配器。
        self._intent_port = intent_port
        self._cache_port = cache_port

    def _intent(self) -> IntentPort:
        if self._intent_port is not None:
            return self._intent_port
        from kernel.infrastructure.intent_adapter import LegacyIntentAdapter

        self._intent_port = LegacyIntentAdapter()
        return self._intent_port

    def _cache(self) -> CachePort:
        if self._cache_port is not None:
            return self._cache_port
        from kernel.infrastructure.intent_adapter import LegacyCacheAdapter

        self._cache_port = LegacyCacheAdapter()
        return self._cache_port

    def get_intent(self, project_root: Optional[str], project_name: Optional[str] = None) -> Dict[str, Any]:
        intent = self._intent()

        root = (project_root or "").strip()
        if root:
            result = intent.get_intent_cache(root)
            if result.get("found"):
                return result
        else:
            result = {
                "found": False,
                "project_name": project_name or "",
                "content": None,
                "created_at": None,
                "updated_at": None,
                "source": None,
            }

        # Fallback for legacy callers that only know the cache file name.
        if project_name:
            fallback = self._read_cache_by_name(project_name)
            if fallback is not None:
                cached_root = str(fallback.get("project_root") or "").strip()
                if cached_root:
                    candidate = intent.get_intent_cache(cached_root)
                    if candidate.get("found"):
                        return candidate
                return {
                    "found": True,
                    "project_name": fallback.get("project_name") or project_name,
                    "content": self._extract_content(fallback),
                    "created_at": fallback.get("created_at") or fallback.get("timestamp"),
                    "updated_at": fallback.get("updated_at"),
                    "source": fallback.get("source") or ("agent" if "response" in fallback else None),
                }
        return result

    def update_intent(self, project_root: str, content: str) -> Dict[str, Any]:
        if not (project_root or "").strip():
            raise ValueError("project_root is required")
        if not content or not content.strip():
            raise ValueError("Content cannot be empty")
        return self._intent().update_intent_cache(project_root, content)

    async def stream_analysis(
        self,
        project_root: str,
        *,
        model: Optional[str] = None,
        force_refresh: bool = False,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Normalize legacy intent SSE events into the flat legacy UI contract."""
        async for event in self._intent().run_intent_analysis_sse(
            project_root,
            force_refresh=force_refresh,
            model=model,
        ):
            event_type = event.get("type")
            payload: Optional[Dict[str, Any]] = None

            if event_type == "content":
                delta = event.get("delta") or event.get("content_delta") or ""
                if delta:
                    payload = {"type": "chunk", "content": delta}
            elif event_type == "reasoning":
                delta = event.get("delta") or ""
                if delta:
                    payload = {"type": "thought", "content": delta}
            elif event_type == "progress":
                message = event.get("message") or event.get("stage")
                if message:
                    payload = {"type": "thought", "content": message}
            elif event_type == "final":
                result = event.get("result") or {}
                content = result.get("content") if isinstance(result, dict) else result
                if not isinstance(content, str):
                    content = str(content) if content else ""
                payload = {"type": "final", "content": content}
            elif event_type == "error":
                payload = {"type": "error", "message": event.get("message", "unknown error")}
            elif event_type == "done":
                payload = {"type": "done"}

            if payload is None:
                continue
            yield payload
            if payload["type"] == "done":
                break

    def get_cache_stats(self) -> Dict[str, Any]:
        stats = dict(self._cache().get_cache_stats())
        entries = self.list_intent_caches()
        if entries:
            stats["projects_cached"] = [entry["project_name"] for entry in entries]
        return stats

    def list_intent_caches(self) -> List[Dict[str, Any]]:
        entries = [dict(entry) for entry in self._cache().list_intent_caches()]
        for entry in entries:
            entry["project_name"] = self._display_project_name(entry)
        return entries

    def clear_intent_cache(self, project_name: Optional[str] = None) -> Dict[str, Any]:
        target = (project_name or "").strip() or None
        if target:
            # List output exposes the human project name, while the file is
            # normally named by digest. Resolve the display name back to a stem.
            for entry in self.list_intent_caches():
                if entry["project_name"] == target:
                    target = Path(str(entry["file_path"])).stem
                    break
        result = dict(self._cache().clear_intent_cache(target))
        result["project"] = project_name
        return result

    def _read_cache_by_name(self, project_name: str) -> Optional[Dict[str, Any]]:
        return self._cache().get_intent_cache(project_name)

    @staticmethod
    def _extract_content(data: Dict[str, Any]) -> str:
        content = data.get("content")
        if not content and isinstance(data.get("response"), dict):
            content = data["response"].get("content")
        return content or ""

    @staticmethod
    def _display_project_name(entry: Dict[str, Any]) -> str:
        name = str(entry.get("project_name") or "")
        if not _is_digest(name):
            return name
        try:
            data = json.loads(Path(str(entry.get("file_path") or "")).read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return name
        if not isinstance(data, dict):
            return name
        project_name = str(data.get("project_name") or "").strip()
        if project_name:
            return project_name
        project_root = str(data.get("project_root") or "").strip()
        if project_root:
            return Path(project_root).name or name
        return name
