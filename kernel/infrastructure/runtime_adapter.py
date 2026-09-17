"""Legacy 运行时上下文适配器

包装旧内核的 ``Agent.core.context.runtime_context``、
``Agent.DIFF.rule.context_decision`` 与 ``Agent.agents.context_scheduler``，
实现新的 RuntimeContextPort 接口。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from kernel.ports.runtime import RuleEventCallback, RuntimeContextPort

logger = logging.getLogger(__name__)


class LegacyRuntimeContextAdapter(RuntimeContextPort):
    """包装旧全局运行时状态的适配器。"""

    def set_project_root(self, path: Optional[str]) -> None:
        from Agent.core.context.runtime_context import set_project_root

        set_project_root(path)

    def get_project_root(self) -> Optional[str]:
        from Agent.core.context.runtime_context import get_project_root

        return get_project_root()

    def set_session_id(self, session_id: Optional[str]) -> None:
        from Agent.core.context.runtime_context import set_session_id

        set_session_id(session_id)

    def get_session_id(self) -> Optional[str]:
        from Agent.core.context.runtime_context import get_session_id

        return get_session_id()

    def set_diff_units(self, units: List[Dict[str, Any]]) -> None:
        from Agent.core.context.runtime_context import set_diff_units

        set_diff_units(units)

    def get_diff_units(self) -> List[Dict[str, Any]]:
        from Agent.core.context.runtime_context import get_diff_units

        return get_diff_units()

    def set_rule_event_callback(self, callback: Optional[RuleEventCallback]) -> None:
        from Agent.DIFF.rule.context_decision import set_rule_event_callback

        set_rule_event_callback(callback)

    def clear_file_caches(self, project_root: Optional[str] = None) -> None:
        from Agent.agents.context_scheduler import clear_file_caches

        try:
            clear_file_caches(project_root)
        except Exception:
            # 缓存清理失败不影响审查结果，但可能导致后续内存占用偏高
            logger.warning(
                "清理项目文件缓存失败 (project_root=%s)",
                project_root,
                exc_info=True,
            )

    def reset(self) -> None:
        """重置全部运行时状态，单项失败不阻断其余清理。"""
        try:
            self.set_project_root(None)
            self.set_session_id(None)
            self.set_diff_units([])
            self.set_rule_event_callback(None)
        except Exception:
            logger.warning("重置全局运行时上下文失败", exc_info=True)


__all__ = ["LegacyRuntimeContextAdapter"]
