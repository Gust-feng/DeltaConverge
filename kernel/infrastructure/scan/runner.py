"""Legacy 静态扫描执行适配器

包装旧内核的 ``Agent.DIFF.static_scan_service``，实现新的 ScanRunnerPort 接口。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from kernel.ports.scan import ScanEventCallback, ScanRunnerPort

logger = logging.getLogger(__name__)


class LegacyScanRunner(ScanRunnerPort):
    """包装旧静态扫描服务的适配器。"""

    def get_files_to_scan(self, diff_context: Any) -> List[str]:
        """从 Diff 上下文中提取去重后的待扫描文件列表。"""
        from Agent.DIFF.static_scan_service import get_unique_files_from_diff_context

        return get_unique_files_from_diff_context(diff_context)

    async def run_scan(
        self,
        *,
        files: List[str],
        units: List[Dict[str, Any]],
        callback: Optional[ScanEventCallback] = None,
        project_root: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Any:
        """执行静态扫描。"""
        from Agent.DIFF.static_scan_service import run_static_scan

        return await run_static_scan(
            files=files,
            units=units,
            callback=callback,
            project_root=project_root,
            session_id=session_id,
        )


__all__ = ["LegacyScanRunner"]
