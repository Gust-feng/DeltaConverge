"""工具系统接口定义

定义工具注册、执行和策略的抽象接口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Type,
    Union,
    runtime_checkable,
)

from kernel.ports.llm import ToolSpec


class ToolCategory(str, Enum):
    """工具类别"""
    FILE = "file"           # 文件操作
    CODE = "code"           # 代码分析
    SEARCH = "search"       # 搜索
    GIT = "git"             # Git 操作
    EXTERNAL = "external"   # 外部服务
    SYSTEM = "system"       # 系统工具
    CUSTOM = "custom"       # 自定义


class ApprovalMode(str, Enum):
    """审批模式"""
    AUTO = "auto"           # 自动执行
    CONFIRM = "confirm"     # 需要确认
    DENY = "deny"           # 禁止执行


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema
    
    # 元信息
    category: ToolCategory = ToolCategory.CUSTOM
    version: str = "1.0.0"
    
    # 执行配置
    approval_mode: ApprovalMode = ApprovalMode.AUTO
    timeout: float = 30.0  # 秒
    max_retries: int = 0
    
    # 执行函数
    handler: Optional[Callable[..., Any]] = None
    
    # 可选的严格模式（参数必须完全匹配 schema）
    strict: bool = False
    
    def to_tool_spec(self) -> ToolSpec:
        """转换为 LLM ToolSpec"""
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            strict=self.strict,
        )


@dataclass
class ToolCallResult:
    """工具调用结果"""
    tool_name: str
    tool_call_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0
    
    def to_string(self) -> str:
        """转换为字符串（用于 LLM 消息）"""
        if self.success:
            if isinstance(self.result, str):
                return self.result
            return str(self.result)
        return f"Error: {self.error}"


@dataclass
class ToolPolicy:
    """工具策略配置"""
    # 启用的工具列表，None 表示全部启用
    enabled_tools: Optional[List[str]] = None
    
    # 禁用的工具列表
    disabled_tools: List[str] = field(default_factory=list)
    
    # 审批规则覆盖
    approval_overrides: Dict[str, ApprovalMode] = field(default_factory=dict)
    
    # 全局配置
    default_approval: ApprovalMode = ApprovalMode.AUTO
    max_concurrent_calls: int = 5
    total_timeout: float = 120.0


@runtime_checkable
class ToolRegistryPort(Protocol):
    """工具注册表接口
    
    负责管理工具的注册和查询。
    """
    
    def register(
        self,
        tool: ToolDefinition,
        *,
        overwrite: bool = False,
    ) -> None:
        """注册工具
        
        Args:
            tool: 工具定义
            overwrite: 是否覆盖已存在的同名工具
        """
        ...
    
    def register_function(
        self,
        name: str,
        handler: Callable[..., Any],
        *,
        description: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        category: ToolCategory = ToolCategory.CUSTOM,
        approval_mode: ApprovalMode = ApprovalMode.AUTO,
    ) -> ToolDefinition:
        """注册函数为工具
        
        自动从函数签名推断参数 schema。
        """
        ...
    
    def get(self, name: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        ...
    
    def list_tools(
        self,
        *,
        category: Optional[ToolCategory] = None,
        enabled_only: bool = False,
    ) -> List[ToolDefinition]:
        """列出工具"""
        ...
    
    def get_tool_specs(
        self,
        names: Optional[List[str]] = None,
    ) -> List[ToolSpec]:
        """获取 LLM 工具规格列表"""
        ...
    
    def has_tool(self, name: str) -> bool:
        """检查工具是否存在"""
        ...
    
    def unregister(self, name: str) -> bool:
        """注销工具"""
        ...


@runtime_checkable
class ToolRuntimePort(Protocol):
    """工具运行时接口
    
    负责工具的执行和生命周期管理。
    """
    
    @property
    def registry(self) -> ToolRegistryPort:
        """获取关联的注册表"""
        ...
    
    def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        tool_call_id: str,
        timeout: Optional[float] = None,
    ) -> ToolCallResult:
        """同步执行工具
        
        Args:
            tool_name: 工具名称
            arguments: 参数字典
            tool_call_id: 工具调用 ID
            timeout: 超时时间（覆盖工具定义）
            
        Returns:
            执行结果
        """
        ...
    
    async def execute_async(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        tool_call_id: str,
        timeout: Optional[float] = None,
    ) -> ToolCallResult:
        """异步执行工具"""
        ...
    
    def execute_batch(
        self,
        calls: List[Dict[str, Any]],  # [{"tool_name": ..., "arguments": ..., "tool_call_id": ...}]
        *,
        parallel: bool = True,
    ) -> List[ToolCallResult]:
        """批量执行工具"""
        ...
    
    def validate_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """验证工具参数
        
        Returns:
            (is_valid, error_message)
        """
        ...


@runtime_checkable
class ToolPolicyPort(Protocol):
    """工具策略接口
    
    负责工具的访问控制和策略管理。
    """
    
    def resolve_tools(
        self,
        requested_tools: Optional[List[str]] = None,
        *,
        policy: Optional[ToolPolicy] = None,
    ) -> tuple[List[ToolSpec], Dict[str, ApprovalMode]]:
        """解析可用工具
        
        Args:
            requested_tools: 请求的工具列表，None 表示所有
            policy: 策略配置，None 使用默认
            
        Returns:
            (工具规格列表, 审批模式字典)
        """
        ...
    
    def resolve_review_tools(
        self,
        tool_names: List[str],
        *,
        auto_approve: bool = False,
    ) -> tuple[List[Dict[str, Any]], List[str]]:
        """按审查请求解析工具 schema 与免确认名单。

        对应审查流水线的实际调用形态：输入前端请求的工具名列表与是否
        自动批准，返回 (工具 schema 列表, 免确认工具名单)。

        Args:
            tool_names: 请求启用的工具名
            auto_approve: 是否自动批准全部请求工具

        Returns:
            (schemas, auto_approve_list)
        """
        ...

    def is_tool_allowed(
        self,
        tool_name: str,
        *,
        policy: Optional[ToolPolicy] = None,
    ) -> bool:
        """检查工具是否允许使用"""
        ...
    
    def get_approval_mode(
        self,
        tool_name: str,
        *,
        policy: Optional[ToolPolicy] = None,
    ) -> ApprovalMode:
        """获取工具的审批模式"""
        ...
    
    def create_restricted_policy(
        self,
        allowed_tools: List[str],
    ) -> ToolPolicy:
        """创建受限策略（仅允许指定工具）"""
        ...
