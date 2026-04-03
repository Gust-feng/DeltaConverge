"""Legacy 对话状态适配器

包装旧内核的 ConversationState，实现新的 ConversationPort 接口。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from kernel.ports.conversation import ConversationPort
from kernel.ports.llm import Message, MessageRole, ToolCall

logger = logging.getLogger(__name__)


class LegacyConversationAdapter(ConversationPort):
    """包装旧 ConversationState 的适配器"""
    
    def __init__(self, legacy_state: Any = None) -> None:
        """
        Args:
            legacy_state: Agent.core.state.conversation.ConversationState 实例
        """
        if legacy_state is None:
            from Agent.core.state.conversation import ConversationState
            legacy_state = ConversationState()
        
        self._state = legacy_state
    
    def add_system_message(
        self,
        content: str,
        *,
        name: Optional[str] = None,
    ) -> Message:
        """添加系统消息"""
        self._state.add_system_message(content)
        return Message(role=MessageRole.SYSTEM, content=content, name=name)
    
    def add_user_message(
        self,
        content: str,
        *,
        name: Optional[str] = None,
    ) -> Message:
        """添加用户消息"""
        self._state.add_user_message(content)
        return Message(role=MessageRole.USER, content=content, name=name)
    
    def add_assistant_message(
        self,
        content: Optional[str] = None,
        *,
        tool_calls: Optional[List[ToolCall]] = None,
    ) -> Message:
        """添加助手消息"""
        # 旧状态可能不支持 tool_calls，简化处理
        if content:
            self._state.add_assistant_message(content)
        
        return Message(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
        )
    
    def add_tool_result(
        self,
        tool_call_id: str,
        result: str,
        *,
        name: Optional[str] = None,
    ) -> Message:
        """添加工具执行结果"""
        # 旧状态可能不直接支持 tool 角色
        # 将其作为 user 消息添加
        self._state.add_user_message(f"Tool {name or tool_call_id} result: {result}")
        
        return Message(
            role=MessageRole.TOOL,
            content=result,
            tool_call_id=tool_call_id,
            name=name,
        )
    
    def add_message(self, message: Message) -> Message:
        """直接添加消息对象"""
        if message.role == MessageRole.SYSTEM:
            self.add_system_message(message.content or "")
        elif message.role == MessageRole.USER:
            self.add_user_message(message.content or "")
        elif message.role == MessageRole.ASSISTANT:
            self.add_assistant_message(message.content, tool_calls=message.tool_calls)
        elif message.role == MessageRole.TOOL:
            self.add_tool_result(
                message.tool_call_id or "",
                message.content or "",
                name=message.name,
            )
        
        return message
    
    def get_messages(
        self,
        *,
        include_system: bool = True,
        max_messages: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> List[Message]:
        """获取消息历史"""
        # 从旧状态获取消息
        legacy_messages = self._state.get_messages()
        
        messages = []
        for msg in legacy_messages:
            role_str = msg.get("role", "user")
            role_map = {
                "system": MessageRole.SYSTEM,
                "user": MessageRole.USER,
                "assistant": MessageRole.ASSISTANT,
                "tool": MessageRole.TOOL,
            }
            role = role_map.get(role_str, MessageRole.USER)
            
            content = msg.get("content")
            tool_calls = None
            tool_call_id = None
            name = msg.get("name")
            
            # 处理 tool_calls
            if "tool_calls" in msg:
                tool_calls = [
                    ToolCall(
                        id=tc.get("id", ""),
                        name=tc.get("function", {}).get("name", ""),
                        arguments=tc.get("function", {}).get("arguments", ""),
                    )
                    for tc in msg["tool_calls"]
                ]
            
            if "tool_call_id" in msg:
                tool_call_id = msg["tool_call_id"]
            
            messages.append(
                Message(
                    role=role,
                    content=content,
                    tool_calls=tool_calls,
                    tool_call_id=tool_call_id,
                    name=name,
                )
            )
        
        # 过滤
        if not include_system:
            messages = [m for m in messages if m.role != MessageRole.SYSTEM]
        
        if max_messages:
            messages = messages[-max_messages:]
        
        # TODO: 处理 max_tokens
        
        return messages
    
    def get_last_n_messages(self, n: int) -> List[Message]:
        """获取最近 n 条消息"""
        return self.get_messages(max_messages=n)
    
    def get_system_messages(self) -> List[Message]:
        """获取所有系统消息"""
        all_messages = self.get_messages()
        return [m for m in all_messages if m.role == MessageRole.SYSTEM]
    
    def clear(self, *, keep_system: bool = True) -> None:
        """清空消息历史"""
        if keep_system:
            system_msgs = self.get_system_messages()
            self._state.clear()
            for msg in system_msgs:
                self.add_system_message(msg.content or "")
        else:
            self._state.clear()
    
    def truncate(
        self,
        max_messages: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> int:
        """截断历史消息"""
        # 旧状态可能不直接支持截断
        logger.warning("truncate not fully implemented in legacy adapter")
        return 0
    
    def estimate_tokens(self) -> int:
        """估算当前历史的 token 数量"""
        messages = self.get_messages()
        total_chars = sum(len(m.content or "") for m in messages)
        return total_chars // 4  # 简化估算
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "messages": [
                {
                    "role": m.role.value,
                    "content": m.content,
                    "tool_calls": [
                        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                        for tc in (m.tool_calls or [])
                    ] if m.tool_calls else None,
                    "tool_call_id": m.tool_call_id,
                    "name": m.name,
                }
                for m in self.get_messages()
            ]
        }
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """从字典恢复状态"""
        self.clear(keep_system=False)
        for msg_dict in data.get("messages", []):
            role = MessageRole(msg_dict["role"])
            message = Message(
                role=role,
                content=msg_dict.get("content"),
                tool_calls=[
                    ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                    for tc in (msg_dict.get("tool_calls") or [])
                ] if msg_dict.get("tool_calls") else None,
                tool_call_id=msg_dict.get("tool_call_id"),
                name=msg_dict.get("name"),
            )
            self.add_message(message)
    
    def clone(self) -> "ConversationPort":
        """创建副本"""
        new_adapter = LegacyConversationAdapter()
        new_adapter.from_dict(self.to_dict())
        return new_adapter
