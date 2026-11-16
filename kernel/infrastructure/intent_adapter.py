"""旧 Agent 意图与缓存 API 的端口实现。

把 ``Agent.core.api.intent`` / ``Agent.core.api.cache`` 的调用集中在这里，
application 层通过 ``IntentPort`` / ``CachePort`` 使用，不再直接 import 旧模块。
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional


class LegacyIntentAdapter:
    """实现 IntentPort：读取、写入与流式分析项目意图。"""

    def get_intent_cache(self, project_root: str) -> Dict[str, Any]:
        from Agent.core.api.intent import IntentAPI

        return IntentAPI.get_intent_cache(project_root)

    def update_intent_cache(self, project_root: str, content: str) -> Dict[str, Any]:
        from Agent.core.api.intent import IntentAPI

        return IntentAPI.update_intent_cache(project_root, content)

    async def run_intent_analysis_sse(
        self,
        project_root: str,
        *,
        force_refresh: bool = False,
        model: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        from Agent.core.api.intent import IntentAPI

        async for event in IntentAPI.run_intent_analysis_sse(
            project_root,
            force_refresh=force_refresh,
            model=model,
        ):
            yield event


class LegacyCacheAdapter:
    """实现 CachePort：意图缓存的统计、列举与清理。"""

    def get_cache_stats(self) -> Dict[str, Any]:
        from Agent.core.api.cache import CacheAPI

        return CacheAPI.get_cache_stats()

    def list_intent_caches(self) -> List[Dict[str, Any]]:
        from Agent.core.api.cache import CacheAPI

        return CacheAPI.list_intent_caches()

    def get_intent_cache(self, name: str) -> Optional[Dict[str, Any]]:
        from Agent.core.api.cache import CacheAPI

        return CacheAPI.get_intent_cache(name)

    def clear_intent_cache(self, target: Optional[str] = None) -> Dict[str, Any]:
        from Agent.core.api.cache import CacheAPI

        return CacheAPI.clear_intent_cache(target)


__all__ = ["LegacyCacheAdapter", "LegacyIntentAdapter"]
