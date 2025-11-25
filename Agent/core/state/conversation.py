"""会话状态管理器。"""

from __future__ import annotations

from typing import Any, Dict, List
import json


class ConversationState:
    """保存与 LLM 往返的消息列表。"""

    def __init__(self) -> None:
        self._messages: List[Dict[str, Any]] = []
        self._max_messages: int | None = None

    @property
    def messages(self) -> List[Dict[str, Any]]:
        """返回当前消息（只读副本）。"""

        return list(self._messages)

    def add_system_message(self, content: str) -> None:
        self._messages.append({"role": "system", "content": content})

    def add_user_message(self, content: str) -> None:
        self._messages.append({"role": "user", "content": content})

    def add_assistant_message(
        self,
        content: str,
        tool_calls: List[Dict[str, Any]],
    ) -> None:
        """追加助手消息（需原样保留 tool_calls）。"""

        message: Dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            normalized_calls: List[Dict[str, Any]] = []
            for call in tool_calls:
                args = call.get("arguments", {})
                if not isinstance(args, str):
                    args = json.dumps(args, ensure_ascii=False)
                normalized_calls.append(
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": args,
                        },
                    }
                )
            message["tool_calls"] = normalized_calls
        self._messages.append(message)

    def add_tool_result(self, result: Dict[str, Any]) -> None:
        """追加与 tool_call_id 对齐的工具结果消息。"""

        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": result.get("tool_call_id"),
                "name": result.get("name"),
                "content": result.get("content"),
                "error": result.get("error"),
            }
        )

    def set_history_limit(self, max_messages: int | None) -> None:
        """设置可选的历史保留上限，便于后续裁剪。"""

        self._max_messages = max_messages

    def prune_history(self) -> None:
        """超出上限时裁剪最早的非 system 消息。"""

        if not self._max_messages or len(self._messages) <= self._max_messages:
            return
        system_msgs = [m for m in self._messages if m.get("role") == "system"]
        others = [m for m in self._messages if m.get("role") != "system"]
        keep = others[-(self._max_messages - len(system_msgs)) :]
        self._messages = system_msgs + keep
