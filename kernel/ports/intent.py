"""意图与缓存访问接口定义

application 层的意图服务只依赖这里的抽象，具体实现由 infrastructure 提供，
避免 kernel/application 反向依赖旧 Agent API。
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class IntentPort(Protocol):
    """项目意图缓存的读取、写入与流式分析入口。"""

    def get_intent_cache(self, project_root: str) -> Dict[str, Any]:
        """按项目根目录读取意图缓存；未命中时返回 found=False。"""

    def update_intent_cache(self, project_root: str, content: str) -> Dict[str, Any]:
        """写入项目意图缓存。"""

    def run_intent_analysis_sse(
        self,
        project_root: str,
        *,
        force_refresh: bool = False,
        model: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """流式分析项目意图，产出原始事件字典。"""


@runtime_checkable
class CachePort(Protocol):
    """意图缓存的列表、统计与清理入口。"""

    def get_cache_stats(self) -> Dict[str, Any]:
        """返回缓存统计信息。"""

    def list_intent_caches(self) -> List[Dict[str, Any]]:
        """列出全部意图缓存条目。"""

    def get_intent_cache(self, name: str) -> Optional[Dict[str, Any]]:
        """按文件名或项目名读取单条缓存。"""

    def clear_intent_cache(self, target: Optional[str] = None) -> Dict[str, Any]:
        """清理指定或全部意图缓存。"""


__all__ = ["CachePort", "IntentPort"]
