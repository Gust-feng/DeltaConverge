"""Conversation state manager."""

from __future__ import annotations

from typing import Any, Dict, List
import json


class ConversationState:
    """Stores the rolling list of messages exchanged with the LLM."""

    def __init__(self) -> None:
        self._messages: List[Dict[str, Any]] = []
        self._max_messages: int | None = None

    @property
    def messages(self) -> List[Dict[str, Any]]:
        """Return current messages (read-only)."""

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
        """Append assistant message (tool_calls must be preserved verbatim)."""

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
        """Append a tool result message aligning with tool_call_id."""

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
        """Set optional retention limit for future pruning."""

        self._max_messages = max_messages

    def prune_history(self) -> None:
        """Prune oldest non-system messages when exceeding limit."""

        if not self._max_messages or len(self._messages) <= self._max_messages:
            return
        system_msgs = [m for m in self._messages if m.get("role") == "system"]
        others = [m for m in self._messages if m.get("role") != "system"]
        keep = others[-(self._max_messages - len(system_msgs)) :]
        self._messages = system_msgs + keep
