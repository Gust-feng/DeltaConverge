"""运行时上下文接口定义

定义内核对"进程级/请求级全局运行时状态"的抽象访问接口。

背景：旧工具层（``Agent.core.context.runtime_context`` 与
``Agent.DIFF.rule.context_decision``）依赖 ContextVar 形式的全局状态与全局事件回调。
新内核不应直接触碰这些全局量，因此通过本端口收口，
既保留兼容性，也让 application 层可被替换 / 可测试。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

RuleEventCallback = Callable[[Dict[str, Any]], None]


@runtime_checkable
class RuntimeContextPort(Protocol):
    """运行时全局上下文访问接口。"""

    def set_project_root(self, path: Optional[str]) -> None:
        """设置当前项目根目录。"""
        ...

    def get_project_root(self) -> Optional[str]:
        """获取当前项目根目录。"""
        ...

    def set_session_id(self, session_id: Optional[str]) -> None:
        """设置当前会话 ID。"""
        ...

    def get_session_id(self) -> Optional[str]:
        """获取当前会话 ID。"""
        ...

    def set_diff_units(self, units: List[Dict[str, Any]]) -> None:
        """设置当前 diff 单元列表。"""
        ...

    def get_diff_units(self) -> List[Dict[str, Any]]:
        """获取当前 diff 单元列表。"""
        ...

    def set_rule_event_callback(self, callback: Optional[RuleEventCallback]) -> None:
        """注册（或以 None 注销）规则层事件回调。"""
        ...

    def clear_file_caches(self, project_root: Optional[str] = None) -> None:
        """清理上下文文件缓存。

        Args:
            project_root: 指定项目时仅清理该项目作用域，None 表示全部清理。
        """
        ...

    def reset(self) -> None:
        """重置全部运行时状态（项目根、会话、diff 单元、规则回调）。

        用于一次审查结束后的资源清理，防止全局状态泄漏到下一次运行。
        """
        ...


__all__ = ["RuntimeContextPort", "RuleEventCallback"]
