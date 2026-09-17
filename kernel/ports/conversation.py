"""对话状态管理接口定义

定义 LLM 对话历史的管理接口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from kernel.ports.llm import Message, ToolCall


@dataclass
class ConversationConfig:
    """对话配置"""
    max_history_messages: int = 50  # 最大历史消息数
    max_history_tokens: int = 8000  # 最大历史 token 数
    truncation_strategy: str = "sliding_window"  # sliding_window, summarize, drop_old
    preserve_system: bool = True  # 截断时保留系统消息


@runtime_checkable
class ConversationPort(Protocol):
    """对话状态管理接口
    
    负责管理 LLM 对话的消息历史，支持：
    - 添加各类消息（系统、用户、助手、工具）
    - 消息历史查询和截断
    - Token 估算和限制
    """
    
    def add_system_message(
        self,
        content: str,
        *,
        name: Optional[str] = None,
    ) -> Message:
        """添加系统消息
        
        Args:
            content: 消息内容
            name: 可选的名称标识
            
        Returns:
            创建的消息对象
        """
        ...
    
    def add_user_message(
        self,
        content: str,
        *,
        name: Optional[str] = None,
    ) -> Message:
        """添加用户消息"""
        ...
    
    def add_assistant_message(
        self,
        content: Optional[str] = None,
        *,
        tool_calls: Optional[List[ToolCall]] = None,
    ) -> Message:
        """添加助手消息
        
        Args:
            content: 文本内容（可选）
            tool_calls: 工具调用列表（可选）
        """
        ...
    
    def add_tool_result(
        self,
        tool_call_id: str,
        result: str,
        *,
        name: Optional[str] = None,
    ) -> Message:
        """添加工具执行结果
        
        Args:
            tool_call_id: 对应的工具调用 ID
            result: 执行结果（字符串形式）
            name: 工具名称
        """
        ...
    
    def add_message(self, message: Message) -> Message:
        """直接添加消息对象"""
        ...
    
    def get_messages(
        self,
        *,
        include_system: bool = True,
        max_messages: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> List[Message]:
        """获取消息历史
        
        Args:
            include_system: 是否包含系统消息
            max_messages: 最大消息数限制
            max_tokens: 最大 token 数限制
            
        Returns:
            消息列表
        """
        ...
    
    def get_last_n_messages(self, n: int) -> List[Message]:
        """获取最近 n 条消息"""
        ...
    
    def get_system_messages(self) -> List[Message]:
        """获取所有系统消息"""
        ...
    
    def clear(self, *, keep_system: bool = True) -> None:
        """清空消息历史
        
        Args:
            keep_system: 是否保留系统消息
        """
        ...
    
    def truncate(
        self,
        max_messages: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> int:
        """截断历史消息
        
        Args:
            max_messages: 最大消息数
            max_tokens: 最大 token 数
            
        Returns:
            被移除的消息数量
        """
        ...
    
    def estimate_tokens(self) -> int:
        """估算当前历史的 token 数量"""
        ...
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        ...
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """从字典恢复状态"""
        ...
    
    def clone(self) -> "ConversationPort":
        """创建副本"""
        ...


@dataclass
class ConversationState:
    """对话状态数据类
    
    用于持久化和传输对话状态。
    """
    messages: List[Message] = field(default_factory=list)
    config: ConversationConfig = field(default_factory=ConversationConfig)
    metadata: Dict[str, Any] = field(default_factory=dict)
    total_tokens_used: int = 0
    
    def add_message(self, message: Message) -> None:
        """添加消息"""
        self.messages.append(message)
    
    def get_messages_for_llm(self) -> List[Dict[str, Any]]:
        """转换为 LLM API 格式"""
        result = []
        for msg in self.messages:
            item: Dict[str, Any] = {"role": msg.role.value}
            if msg.content is not None:
                item["content"] = msg.content
            if msg.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            if msg.tool_call_id:
                item["tool_call_id"] = msg.tool_call_id
            if msg.name:
                item["name"] = msg.name
            result.append(item)
        return result
