"""Stage 层共享的文本处理工具。

本模块是 ``_truncate_prompt_text`` 的**唯一实现**。
历史上 ``kernel/application/stages/fusion_stage.py`` 与
``Agent/core/review_kernel.py`` 各自维护了一份完全相同的副本，
已在内核收口阶段合并到此处，避免两侧行为漂移。
"""

from __future__ import annotations

__all__ = ["truncate_prompt_text"]


def truncate_prompt_text(text: str | None, max_chars: int, *, label: str) -> str | None:
    """按字符数截断提示词文本，并在尾部标注省略信息。

    Args:
        text: 待截断文本；``None`` 或空串原样返回。
        max_chars: 允许保留的最大字符数。
        label: 出现在截断提示中的字段名，便于定位是哪一段被裁掉。

    Returns:
        未超限时返回原文本；超限时返回截断后的文本 + 省略字符数说明。
    """
    if not text:
        return text
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[已截断 {label}，省略 {omitted} 字符。]"


# 兼容旧内部调用名（fusion_stage / review_kernel 曾使用下划线前缀私有名）
_truncate_prompt_text = truncate_prompt_text
