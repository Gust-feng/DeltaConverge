"""Legacy 工具系统适配器

包装旧内核的工具运行时和注册表，实现新的 ToolPort 接口。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from kernel.ports.llm import ToolSpec
from kernel.ports.tool import (
    ApprovalMode,
    ToolCallResult,
    ToolCategory,
    ToolDefinition,
    ToolPolicy,
    ToolPolicyPort,
    ToolRegistryPort,
    ToolRuntimePort,
)

logger = logging.getLogger(__name__)


class LegacyToolRegistry(ToolRegistryPort):
    """包装旧工具注册表的适配器"""
    
    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._initialized = False
    
    def _ensure_initialized(self) -> None:
        """延迟初始化旧工具"""
        if self._initialized:
            return
        
        try:
            from Agent.tool.registry import get_tool_functions
            
            # 获取旧工具函数
            legacy_tools = get_tool_functions()
            
            for name, func in legacy_tools.items():
                # 从函数文档字符串提取描述
                description = func.__doc__ or f"Tool: {name}"
                
                # 创建工具定义
                self._tools[name] = ToolDefinition(
                    name=name,
                    description=description.split("\n")[0] if description else name,
                    parameters={"type": "object", "properties": {}},  # 简化
                    category=ToolCategory.CUSTOM,
                    handler=func,
                )
            
            self._initialized = True
        except Exception as e:
            logger.warning(f"Failed to initialize legacy tools: {e}")
            self._initialized = True
    
    def register(
        self,
        tool: ToolDefinition,
        *,
        overwrite: bool = False,
    ) -> None:
        """注册工具"""
        if tool.name in self._tools and not overwrite:
            raise ValueError(f"Tool {tool.name} already registered")
        
        self._tools[tool.name] = tool
    
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
        """注册函数为工具"""
        tool = ToolDefinition(
            name=name,
            description=description or handler.__doc__ or name,
            parameters=parameters or {"type": "object", "properties": {}},
            category=category,
            approval_mode=approval_mode,
            handler=handler,
        )
        self.register(tool)
        return tool
    
    def get(self, name: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        self._ensure_initialized()
        return self._tools.get(name)
    
    def list_tools(
        self,
        *,
        category: Optional[ToolCategory] = None,
        enabled_only: bool = False,
    ) -> List[ToolDefinition]:
        """列出工具"""
        self._ensure_initialized()
        tools = list(self._tools.values())
        
        if category:
            tools = [t for t in tools if t.category == category]
        
        return tools
    
    def get_tool_specs(
        self,
        names: Optional[List[str]] = None,
    ) -> List[ToolSpec]:
        """获取 LLM 工具规格列表"""
        self._ensure_initialized()
        
        if names:
            tools = [self._tools[n] for n in names if n in self._tools]
        else:
            tools = list(self._tools.values())
        
        return [t.to_tool_spec() for t in tools]
    
    def has_tool(self, name: str) -> bool:
        """检查工具是否存在"""
        self._ensure_initialized()
        return name in self._tools
    
    def unregister(self, name: str) -> bool:
        """注销工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False


class LegacyToolRuntime(ToolRuntimePort):
    """包装旧工具运行时的适配器"""
    
    def __init__(self, registry: Optional[ToolRegistryPort] = None) -> None:
        self._registry = registry or LegacyToolRegistry()
    
    @property
    def registry(self) -> ToolRegistryPort:
        return self._registry
    
    def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        tool_call_id: str,
        timeout: Optional[float] = None,
    ) -> ToolCallResult:
        """同步执行工具"""
        import time
        
        start_time = time.time()
        
        try:
            # 获取工具定义
            tool = self._registry.get(tool_name)
            if not tool:
                return ToolCallResult(
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    success=False,
                    error=f"Tool {tool_name} not found",
                )
            
            # 验证参数
            is_valid, error = self.validate_arguments(tool_name, arguments)
            if not is_valid:
                return ToolCallResult(
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    success=False,
                    error=error,
                )
            
            # 执行工具
            if tool.handler:
                result = tool.handler(**arguments)
            else:
                # 使用旧 runtime
                from Agent.core.tools.runtime import ToolRuntime
                
                runtime = ToolRuntime()
                result = runtime.run(tool_name, arguments)
            
            execution_time = (time.time() - start_time) * 1000
            
            return ToolCallResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                success=True,
                result=result,
                execution_time_ms=execution_time,
            )
        
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            return ToolCallResult(
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                success=False,
                error=str(e),
                execution_time_ms=execution_time,
            )
    
    async def execute_async(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        tool_call_id: str,
        timeout: Optional[float] = None,
    ) -> ToolCallResult:
        """异步执行工具"""
        # 简化实现：使用同步方法
        return self.execute(tool_name, arguments, tool_call_id=tool_call_id, timeout=timeout)
    
    def execute_batch(
        self,
        calls: List[Dict[str, Any]],
        *,
        parallel: bool = True,
    ) -> List[ToolCallResult]:
        """批量执行工具"""
        results = []
        for call in calls:
            result = self.execute(
                tool_name=call["tool_name"],
                arguments=call["arguments"],
                tool_call_id=call["tool_call_id"],
            )
            results.append(result)
        return results
    
    def validate_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Tuple[bool, Optional[str]]:
        """验证工具参数"""
        tool = self._registry.get(tool_name)
        if not tool:
            return (False, f"Tool {tool_name} not found")
        
        # 简化验证：检查参数是否为字典
        if not isinstance(arguments, dict):
            return (False, "Arguments must be a dictionary")
        
        return (True, None)


class LegacyToolPolicy(ToolPolicyPort):
    """包装旧工具策略的适配器"""
    
    def __init__(self, registry: Optional[ToolRegistryPort] = None) -> None:
        self._registry = registry or LegacyToolRegistry()

    def resolve_review_tools(
        self,
        tool_names: List[str],
        *,
        auto_approve: bool = False,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """按审查请求解析工具 schema 与免确认名单（复用旧 tool_policy）。"""
        from Agent.core.services.tool_policy import resolve_tools

        resolved = resolve_tools(list(tool_names or []), auto_approve)
        return (resolved.get("schemas") or [], resolved.get("auto_approve") or [])

    def resolve_tools(
        self,
        requested_tools: Optional[List[str]] = None,
        *,
        policy: Optional[ToolPolicy] = None,
    ) -> Tuple[List[ToolSpec], Dict[str, ApprovalMode]]:
        """解析可用工具"""
        policy = policy or ToolPolicy()
        
        # 获取所有工具
        all_tools = self._registry.list_tools()
        
        # 过滤工具
        available_tools = []
        for tool in all_tools:
            # 检查是否在请求列表中
            if requested_tools and tool.name not in requested_tools:
                continue
            
            # 检查是否允许
            if not self.is_tool_allowed(tool.name, policy=policy):
                continue
            
            available_tools.append(tool)
        
        # 构建 ToolSpec 和审批模式
        tool_specs = [t.to_tool_spec() for t in available_tools]
        approval_modes = {
            t.name: self.get_approval_mode(t.name, policy=policy)
            for t in available_tools
        }
        
        return (tool_specs, approval_modes)
    
    def is_tool_allowed(
        self,
        tool_name: str,
        *,
        policy: Optional[ToolPolicy] = None,
    ) -> bool:
        """检查工具是否允许使用"""
        policy = policy or ToolPolicy()
        
        # 检查禁用列表
        if tool_name in policy.disabled_tools:
            return False
        
        # 检查启用列表
        if policy.enabled_tools is not None:
            return tool_name in policy.enabled_tools
        
        return True
    
    def get_approval_mode(
        self,
        tool_name: str,
        *,
        policy: Optional[ToolPolicy] = None,
    ) -> ApprovalMode:
        """获取工具的审批模式"""
        policy = policy or ToolPolicy()
        
        # 检查覆盖
        if tool_name in policy.approval_overrides:
            return policy.approval_overrides[tool_name]
        
        # 使用工具定义的模式
        tool = self._registry.get(tool_name)
        if tool:
            return tool.approval_mode
        
        # 使用默认模式
        return policy.default_approval
    
    def create_restricted_policy(
        self,
        allowed_tools: List[str],
    ) -> ToolPolicy:
        """创建受限策略（仅允许指定工具）"""
        return ToolPolicy(
            enabled_tools=allowed_tools,
            disabled_tools=[],
            default_approval=ApprovalMode.AUTO,
        )
