"""简单的 API 日志器，按会话存储请求/响应，输出 JSONL + 可选人类摘要。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from Agent.core.logging.context import generate_trace_id
from Agent.core.logging.utils import safe_payload, utc_iso


class APILogger:
    """将请求/响应结构化日志写入 ./log/api_log。"""

    # 同一 trace_id 复用一份日志文件，避免一轮对话生成多个文件
    _session_paths: Dict[str, Path] = {}
    _human_paths: Dict[str, Path] = {}

    def __init__(
        self,
        base_dir: str | Path = "log/api_log",
        human_dir: str | Path | None = "log/human_log",
        trace_id: str | None = None,
        *,
        max_chars: int = 2000,
        max_items: int = 30,
        redacted_keys: Iterable[str] | None = None,
        enable_stream_chunks: bool = False,
        stream_chunk_sample_rate: int = 20,
        stream_chunk_limit: int = 200,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.human_dir: Optional[Path]
        if human_dir is not None:
            self.human_dir = Path(human_dir)
            self.human_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.human_dir = None
        # 映射结构化日志路径 -> 人类可读日志路径（仅对部分 label 使用）
        self._human_paths: Dict[Path, Path] = {}
        self.trace_id = trace_id or generate_trace_id()
        self.max_chars = max_chars
        self.max_items = max_items
        self.enable_stream_chunks = enable_stream_chunks
        self.stream_chunk_sample_rate = max(1, stream_chunk_sample_rate)
        self.stream_chunk_limit = max(1, stream_chunk_limit)
        self.redacted_keys: Set[str] = set(
            redacted_keys
            or {
                "unified_diff",
                "unified_diff_with_lines",
                "context",
                "code_snippets",
                "file_context",
                "full_file",
                "function_context",
            }
        )
        # 跟踪流式 chunk 数量，便于在 SUMMARY 中补充统计
        self._chunk_seen: Dict[Path, int] = {}
        self._chunk_logged: Dict[Path, int] = {}
        self.session_path: Optional[Path] = None

    def _log_path(self, label: str) -> Path:
        """找到或创建当前 trace 的唯一日志文件路径。"""

        if self.session_path and self.session_path.exists():
            return self.session_path
        if self.trace_id in APILogger._session_paths:
            cached = APILogger._session_paths[self.trace_id]
            self.session_path = cached
            return cached

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = self.base_dir / f"{timestamp}_{self.trace_id}.jsonl"
        APILogger._session_paths[self.trace_id] = path
        self.session_path = path
        return path

    def _write_entry(self, path: Path, section: str, payload: Any, label: str | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "section": section,
            "label": label,
            "payload": safe_payload(
                payload,
                max_chars=self.max_chars,
                max_items=self.max_items,
                redacted_keys=self.redacted_keys,
            ),
            "trace_id": self.trace_id,
            "ts": utc_iso(),
        }
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")

    def start(self, label: str, payload: Dict[str, Any]) -> Path:
        """创建新日志文件并写入请求负载。"""

        # 目录可能在运行期间被清理，确保每次 start 前都存在
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if self.human_dir is not None:
            self.human_dir.mkdir(parents=True, exist_ok=True)

        path = self._log_path(label)
        enriched = dict(payload)
        enriched.setdefault("trace_id", self.trace_id)
        enriched.setdefault("label", label)
        self._write_entry(path, "REQUEST", enriched, label=label)
        # 初始化流式计数
        self._chunk_seen[path] = 0
        self._chunk_logged[path] = 0

        # 对关键会话（例如 agent_session）额外创建一份中文摘要日志
        if self.human_dir is not None and label == "agent_session":
            human_path = APILogger._human_paths.get(self.trace_id)
            if human_path is None:
                human_path = self.human_dir / path.name.replace(".jsonl", ".md")
                APILogger._human_paths[self.trace_id] = human_path
                self._init_human_session(human_path, enriched)

        return path

    def append(self, path: Path, section: str, payload: Any) -> None:
        """向已有日志文件追加一个 JSON 段落。"""

        enriched = dict(payload)
        enriched.setdefault("trace_id", self.trace_id)

        # 针对流式 chunk 做采样/限频，避免日志爆炸
        if section.startswith("RESPONSE_CHUNK"):
            seen = self._chunk_seen.get(path, 0) + 1
            self._chunk_seen[path] = seen

            if not self.enable_stream_chunks:
                return
            if seen > self.stream_chunk_limit:
                if seen == self.stream_chunk_limit + 1:
                    self._write_entry(
                        path,
                        "RESPONSE_CHUNK_SKIPPED",
                        {
                            "reason": "stream_chunk_limit",
                            "limit": self.stream_chunk_limit,
                            "trace_id": self.trace_id,
                        },
                    )
                return

            should_log = (
                seen == 1
                or seen % self.stream_chunk_sample_rate == 0
                or seen == self.stream_chunk_limit
            )
            if not should_log:
                return

            enriched = dict(enriched)
            enriched["chunk_index"] = seen
            self._chunk_logged[path] = self._chunk_logged.get(path, 0) + 1
            self._write_entry(path, section, enriched, label=enriched.get("label"))
            return

        # 在 SUMMARY 中附带 chunk 统计，便于回放
        if section == "RESPONSE_SUMMARY":
            if path in self._chunk_seen:
                enriched = dict(enriched)
                enriched.setdefault("chunk_count", self._chunk_seen[path])
                enriched.setdefault("chunks_logged", self._chunk_logged.get(path, 0))
                if not self.enable_stream_chunks and self._chunk_seen[path] > 0:
                    enriched.setdefault("chunk_logging", "suppressed")

        self._write_entry(path, section, enriched, label=enriched.get("label"))
        self._append_human(path, section, enriched)

    # ------------------------------------------------------------------
    # 人类可读日志（中文摘要）
    # ------------------------------------------------------------------

    @staticmethod
    def _truncate(text: str | None, limit: int = 800) -> str:
        if not text:
            return ""
        if len(text) <= limit:
            return text
        return text[: limit - 20] + "\n...(内容较长，已截断)"

    def _init_human_session(self, path: Path, payload: Dict[str, Any]) -> None:
        """初始化一次审查会话的人类可读日志（目前仅用于 agent_session）。"""

        try:
            provider = payload.get("provider", "unknown")
            files = payload.get("files") or []
            tools = payload.get("tools_exposed") or []
            trace_id = payload.get("trace_id") or "-"
            with path.open("w", encoding="utf-8") as fp:
                fp.write("# 代码审查会话日志（人类可读版）\n\n")
                fp.write(f"- 模型提供方: `{provider}`\n")
                fp.write(f"- trace_id: `{trace_id}`\n")
                fp.write(f"- 涉及文件数: {len(files)}\n")
                if files:
                    fp.write("- 部分文件列表:\n")
                    for p in files[:10]:
                        fp.write(f"  - `{p}`\n")
                    if len(files) > 10:
                        fp.write(f"  - ... 共 {len(files)} 个文件\n")
                fp.write(f"- 暴露给模型的工具: {', '.join(tools) if tools else '（无）'}\n\n")
                fp.write("> 提示：本文件为调试/人工审查使用，仅保留关键信息；\n")
                fp.write("> 若需完整 JSON，请查看 log/api_log 下对应的 agent_session 日志。\n\n")
        except Exception:
            # 摘要日志失败不影响主日志
            return

    def _append_human(self, path: Path, section: str, payload: Any) -> None:
        """根据结构化日志追加一条中文摘要记录。"""

        if self.human_dir is None:
            return
        trace_id = payload.get("trace_id") or self.trace_id
        human_path = APILogger._human_paths.get(trace_id)
        if human_path is None:
            return

        try:
            with human_path.open("a", encoding="utf-8") as fp:
                # LLM 调用请求
                if section.startswith("LLM_CALL_") and section.endswith("_REQUEST"):
                    call_index = payload.get("call_index")
                    model = payload.get("model")
                    trace_id = payload.get("trace_id") or "-"
                    messages: List[Dict[str, Any]] = payload.get("messages") or []
                    tools = payload.get("tools") or []
                    # 提取最近一条 user 消息
                    user_content = ""
                    for m in reversed(messages):
                        if m.get("role") == "user":
                            user_content = m.get("content") or ""
                            break
                    tool_names: List[str] = []
                    for t in tools:
                        fn = t.get("function") if isinstance(t, dict) else None
                        if isinstance(fn, dict) and fn.get("name"):
                            tool_names.append(fn["name"])
                    fp.write(f"## 第 {call_index} 次 LLM 调用（请求）\n\n")
                    fp.write(f"- 模型: `{model}`\n")
                    fp.write(f"- trace_id: `{trace_id}`\n")
                    fp.write(
                        f"- 可用工具: {', '.join(tool_names) if tool_names else '（无）'}\n\n"
                    )
                    if user_content:
                        fp.write("**用户输入摘录：**\n\n")
                        fp.write(self._truncate(user_content))
                        fp.write("\n\n")

                # LLM 调用响应
                elif section.startswith("LLM_CALL_") and section.endswith("_RESPONSE"):
                    call_index = payload.get("call_index")
                    assistant = payload.get("assistant_message") or {}
                    content = assistant.get("content") or ""
                    tool_calls = assistant.get("tool_calls") or []
                    trace_id = payload.get("trace_id") or "-"
                    finish_reason = assistant.get("finish_reason")
                    tool_names = [c.get("name") for c in tool_calls if c.get("name")]
                    usage = assistant.get("usage") or payload.get("usage") or {}
                    in_tok = usage.get("input_tokens") or usage.get("prompt_tokens")
                    out_tok = usage.get("output_tokens") or usage.get("completion_tokens")
                    total_tok = usage.get("total_tokens")
                    fp.write(f"## 第 {call_index} 次 LLM 调用（回复）\n\n")
                    fp.write(
                        f"- finish_reason: `{finish_reason}`\n"
                        f"- trace_id: `{trace_id}`\n"
                        f"- 请求的工具: {', '.join(tool_names) if tool_names else '（无）'}\n"
                        f"- tokens: total={total_tok or '-'} (in={in_tok or '-'}, out={out_tok or '-'})\n\n"
                    )
                    if content:
                        fp.write("**回复内容摘录：**\n\n")
                        fp.write(self._truncate(content))
                    fp.write("\n\n")

                # 工具执行结果
                elif section.startswith("TOOLS_EXECUTION_"):
                    call_index = payload.get("call_index")
                    approved = payload.get("approved_calls") or []
                    results = payload.get("results") or []
                    fp.write(f"## 工具执行（call_index={call_index}）\n\n")
                    if not approved:
                        fp.write("- 本轮没有获批的工具调用。\n\n")
                    else:
                        for call, result in zip(approved, results):
                            name = call.get("name")
                            args = call.get("arguments", {})
                            err = result.get("error")
                            content = result.get("content") or ""
                            fp.write(f"- 工具 `{name}` 调用：\n")
                            fp.write(
                                f"  - 参数: {self._truncate(json.dumps(args, ensure_ascii=False), 300)}\n"
                            )
                            if err:
                                fp.write(f"  - 结果: 失败（{self._truncate(err, 200)}）\n")
                            else:
                                fp.write(
                                    f"  - 结果摘录: {self._truncate(str(content), 200)}\n"
                                )
                        fp.write("\n")

                # 会话结束
                elif section == "SESSION_END":
                    call_index = payload.get("call_index")
                    final_content = payload.get("final_content") or ""
                    fp.write("## 会话结束\n\n")
                    fp.write(f"- 最后一次调用序号: {call_index}\n\n")
                    if final_content:
                        fp.write("**最终审查结论：**\n\n")
                        fp.write(self._truncate(str(final_content), 1200))
                        fp.write("\n\n")

        except Exception:
            # 摘要日志写入失败不影响主流程或结构化日志
            return
