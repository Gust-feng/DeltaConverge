"""静态扫描执行接口定义

定义"发起旁路静态扫描"的抽象接口。

与 ``kernel.ports.stores.ScanServicePort`` 的区别：
- ``ScanServicePort`` 负责扫描**结果/状态**的查询（快照、是否完成）；
- ``ScanRunnerPort`` 负责扫描的**执行**（挑选待扫文件、跑扫描并回调进度）。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

ScanEventCallback = Callable[[Dict[str, Any]], None]


@runtime_checkable
class ScanRunnerPort(Protocol):
    """静态扫描执行接口。"""

    def get_files_to_scan(self, diff_context: Any) -> List[str]:
        """从 Diff 上下文中提取去重后的待扫描文件列表。"""
        ...

    async def run_scan(
        self,
        *,
        files: List[str],
        units: List[Dict[str, Any]],
        callback: Optional[ScanEventCallback] = None,
        project_root: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Any:
        """执行静态扫描。

        Args:
            files: 待扫描文件列表（已去重）
            units: 审查单元列表，用于携带 tags 等元信息
            callback: 进度事件回调
            project_root: 项目根目录
            session_id: 会话 ID

        Returns:
            扫描结果对象（由实现方定义，调用方仅透传/忽略）。
        """
        ...


__all__ = ["ScanRunnerPort", "ScanEventCallback"]
