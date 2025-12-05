"""统一的上下文级别定义。"""

from __future__ import annotations

from typing import Literal


ContextLevel = Literal["diff_only", "function", "file_context", "full_file"]
"""统一的上下文级别枚举：
- diff_only: 仅包含差异部分
- function: 包含函数级上下文
- file_context: 包含文件级上下文
- full_file: 包含完整文件
"""


RULE_TO_UNIFIED_CONTEXT_MAP = {
    "local": "diff_only",
    "function": "function",
    "file": "file_context"
}
"""规则层上下文级别到统一上下文级别的映射。"""


UNIFIED_TO_RULE_CONTEXT_MAP = {
    "diff_only": "local",
    "function": "function",
    "file_context": "file",
    "full_file": "file"
}
"""统一上下文级别到规则层上下文级别的映射。"""


_CONTEXT_ORDER = ["diff_only", "function", "file_context", "full_file"]
"""上下文级别优先级顺序，用于比较不同上下文级别的优先级。"""


def ctx_rank(level: str | None) -> int:
    """获取上下文级别的优先级排名。
    
    Args:
        level: 上下文级别
        
    Returns:
        int: 优先级排名，值越大表示上下文越丰富
             无效级别返回 -1，与 diff_only(0) 区分
    """
    if level is None:
        return -1  # 无效级别返回 -1，与 diff_only(0) 区分
    try:
        return _CONTEXT_ORDER.index(str(level))
    except ValueError:
        return -1  # 未知级别返回 -1


def is_valid_context_level(level: str | None) -> bool:
    """检查上下文级别是否有效。
    
    Args:
        level: 上下文级别
        
    Returns:
        bool: 是否有效
    """
    return str(level) in _CONTEXT_ORDER


def get_default_context_level() -> ContextLevel:
    """获取默认上下文级别。
    
    Returns:
        ContextLevel: 默认上下文级别
    """
    return "function"


__all__ = [
    "ContextLevel",
    "RULE_TO_UNIFIED_CONTEXT_MAP",
    "UNIFIED_TO_RULE_CONTEXT_MAP",
    "ctx_rank",
    "is_valid_context_level",
    "get_default_context_level"
]
