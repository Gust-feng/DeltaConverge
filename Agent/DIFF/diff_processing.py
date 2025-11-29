"""Diff 处理模块：处理 diff 解析、hunk 分析、上下文提取等。"""

from __future__ import annotations

import re
from typing import List, Tuple, Set, Optional
from unidiff import PatchSet


def extract_unified_diff_view(hunk) -> str:
    """生成类似 git diff 的统一视图，更易于理解变更。"""
    lines = []
    for line in hunk:
        content = line.value.rstrip("\n")
        if line.line_type == "+":
            lines.append(f"+{content}") #优化空格，减少tokens消耗
        elif line.line_type == "-":
            lines.append(f"-{content}")
        elif line.line_type == " ":
            lines.append(f" {content}")
    return "\n".join(lines)


def extract_unified_diff_view_with_lines(hunk) -> str:
    """生成带行号的 diff 视图，便于 LLM 精确引用位置。"""
    lines = []
    for line in hunk:
        content = line.value.rstrip("\n")
        if line.line_type == "+":
            ln = line.target_line_no
            prefix = f"+{ln}" if ln is not None else f"+"
        elif line.line_type == "-":
            ln = line.source_line_no
            prefix = f"-{ln}" if ln is not None else f"-"
        else:
            ln = line.target_line_no if line.target_line_no is not None else line.source_line_no
            prefix = f" {ln}" if ln is not None else f" "
        if ln is not None:
            lines.append(f"{prefix}: {content}")
        else:
            lines.append(f"{prefix} {content}")
    return "\n".join(lines)


def extract_before_after_from_hunk(hunk) -> Tuple[str, str]:
    """从 hunk 中提取变更前后的片段。"""

    before_lines: List[str] = []
    after_lines: List[str] = []
    for line in hunk:
        content = line.value.rstrip("\n")
        if line.line_type in ("-", " "):
            before_lines.append(content)
        if line.line_type in ("+", " "):
            after_lines.append(content)
    return "\n".join(before_lines), "\n".join(after_lines)


def _collect_line_numbers(hunk) -> Tuple[List[int], List[int]]:
    """收集 hunk 中真实变更行号（新/旧文件）。"""

    new_lines: List[int] = []
    old_lines: List[int] = []
    for line in hunk:
        if line.line_type == "+" and getattr(line, "target_line_no", None) is not None:
            new_lines.append(int(line.target_line_no))
        elif line.line_type == "-" and getattr(line, "source_line_no", None) is not None:
            old_lines.append(int(line.source_line_no))
    return sorted(set(new_lines)), sorted(set(old_lines))


def _compact_line_spans(lines: List[int]) -> str:
    """将行号列表压缩为 L10-12,L20 形式，便于展示。"""

    if not lines:
        return ""
    spans: List[Tuple[int, int]] = []
    start = prev = lines[0]
    for num in lines[1:]:
        if num == prev + 1:
            prev = num
            continue
        spans.append((start, prev))
        start = prev = num
    spans.append((start, prev))

    parts: List[str] = []
    for a, b in spans:
        if a == b:
            parts.append(f"L{a}")
        else:
            parts.append(f"L{a}-{b}")
    return ",".join(parts)


def extract_context(
    full_lines: List[str],
    new_start: int,
    new_end: int,
    before: int = 20,
    after: int = 20,
) -> Tuple[str, int, int]:
    """从新文件行中提取周围上下文。"""

    if not full_lines:
        ctx_start = new_start if new_start > 0 else 0
        ctx_end = new_end if new_end > 0 else ctx_start
        return "", ctx_start, ctx_end

    start_idx = max(1, new_start if new_start > 0 else 1)
    end_idx = max(start_idx, new_end if new_end > 0 else start_idx)
    ctx_start = max(1, start_idx - before)
    ctx_end = min(len(full_lines), end_idx + after)
    context_lines = full_lines[ctx_start - 1 : ctx_end]
    return "\n".join(context_lines), ctx_start, ctx_end


def extract_changed_symbols(hunk) -> Set[str]:
    """提取变更中涉及的符号（函数名、变量名等）。"""
    symbols = set()
    
    for line in hunk:
        if line.line_type not in ("+", "-"):
            continue
        
        content = line.value.strip()
        # 提取函数调用: func_name(
        func_calls = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(', content)
        symbols.update(func_calls)
        
        # 提取赋值: var_name =
        assignments = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*=', content)
        symbols.update(assignments)
        
        # 提取属性访问: obj.attr
        attributes = re.findall(r'\.([a-zA-Z_][a-zA-Z0-9_]*)', content)
        symbols.update(attributes)
    
    return symbols
