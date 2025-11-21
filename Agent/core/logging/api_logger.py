"""Simple API logger that stores request/response pairs per session.

同时支持：
- 结构化 JSON 日志：便于程序/脚本后处理；
- 面向人工审查的精简中文日志：对关键会话（如 agent_session）输出摘要信息。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class APILogger:
    """Writes structured request/response logs to ./log/api_log."""

    def __init__(
        self,
        base_dir: str | Path = "log/api_log",
        human_dir: str | Path | None = "log/human_log",
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

    def _log_path(self, label: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return self.base_dir / f"{label}_{timestamp}.log"

    def start(self, label: str, payload: Dict[str, Any]) -> Path:
        """Create a new log file and write the request payload."""

        path = self._log_path(label)
        self._write_section(path, "REQUEST", payload)

        # 对关键会话（例如 agent_session）额外创建一份中文摘要日志
        if self.human_dir is not None and label == "agent_session":
            human_path = self.human_dir / path.name.replace(".log", ".md")
            self._init_human_session(human_path, payload)
            self._human_paths[path] = human_path

        return path

    def append(self, path: Path, section: str, payload: Any) -> None:
        """Append a JSON section to an existing log file."""

        self._write_section(path, section, payload)
        self._append_human(path, section, payload)

    def _write_section(self, path: Path, heading: str, payload: Any) -> None:
        with path.open("a", encoding="utf-8") as fp:
            fp.write(f"=== {heading} ===\n")
            json.dump(payload, fp, ensure_ascii=False, indent=2)
            fp.write("\n\n")

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
            with path.open("w", encoding="utf-8") as fp:
                fp.write("# 代码审查会话日志（人类可读版）\n\n")
                fp.write(f"- 模型提供方: `{provider}`\n")
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
        human_path = self._human_paths.get(path)
        if human_path is None:
            return

        try:
            with human_path.open("a", encoding="utf-8") as fp:
                # LLM 调用请求
                if section.startswith("LLM_CALL_") and section.endswith("_REQUEST"):
                    call_index = payload.get("call_index")
                    model = payload.get("model")
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
                    finish_reason = assistant.get("finish_reason")
                    tool_names = [c.get("name") for c in tool_calls if c.get("name")]
                    fp.write(f"## 第 {call_index} 次 LLM 调用（回复）\n\n")
                    fp.write(
                        f"- finish_reason: `{finish_reason}`\n"
                        f"- 请求的工具: {', '.join(tool_names) if tool_names else '（无）'}\n\n"
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
