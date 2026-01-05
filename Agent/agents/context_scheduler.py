"""上下文调度器：执行融合计划并生成 ContextBundle。"""

from __future__ import annotations

import ast
import hashlib
import logging
import re
import subprocess
import threading
from collections import OrderedDict
from pathlib import Path
import time
from typing import Any, Dict, List, Tuple, Optional, TypeVar, Generic

from Agent.core.context.diff_provider import DiffContext
from Agent.core.context.runtime_context import get_project_root
from Agent.core.logging.fallback_tracker import record_fallback, read_text_with_fallback
from Agent.core.api.config import get_context_limits
from Agent.DIFF.git_operations import run_git

logger = logging.getLogger(__name__)


# ============================================================
# LRU 缓存实现
# ============================================================

K = TypeVar('K')
V = TypeVar('V')


class LRUCache(Generic[K, V]):
    """简单的 LRU 缓存实现，限制最大条目数。
    
    当缓存满时，自动移除最久未使用的条目。
    """
    
    def __init__(self, max_size: int = 100) -> None:
        self._max_size = max(1, max_size)
        self._cache: OrderedDict[K, V] = OrderedDict()
        self._lock = threading.RLock()
    
    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """获取缓存值，并将其标记为最近使用。
        
        Args:
            key: 缓存键
            default: 键不存在时返回的默认值
            
        Returns:
            缓存值或默认值
        """
        with self._lock:
            if key not in self._cache:
                return default
            # 移动到末尾（最近使用）
            self._cache.move_to_end(key)
            return self._cache[key]
    
    def set(self, key: K, value: V) -> None:
        """设置缓存值，超出大小限制时移除最旧条目。"""
        with self._lock:
            # 如果键已存在，更新值并移动到末尾
            if key in self._cache:
                if self._cache[key] != value:
                    self._cache[key] = value
                self._cache.move_to_end(key)
                return

            # 新增键，检查容量
            if len(self._cache) >= self._max_size:
                self._cache.popitem(last=False)
            self._cache[key] = value
    
    def __contains__(self, key: K) -> bool:
        with self._lock:
            return key in self._cache
    
    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)
    
    def clear(self) -> None:
        """清除所有缓存。"""
        with self._lock:
            self._cache.clear()
    
    def stats(self) -> Dict[str, Any]:
        """返回缓存统计信息。"""
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "utilization": len(self._cache) / self._max_size if self._max_size > 0 else 0,
            }


# ============================================================
# 缓存配置
# ============================================================

# 缓存大小限制（可根据内存情况调整）
_FILE_CACHE_MAX_SIZE = 100
_PREV_FILE_CACHE_MAX_SIZE = 50
_AST_CACHE_MAX_SIZE = 50
_RG_CACHE_MAX_SIZE = 100


class ContextConfig:
    """可配置开关，避免硬编码。
    
    当参数为 None 时，从 ConfigAPI 读取配置值作为默认值。
    """

    def __init__(
        self,
        function_window: int = 30,
        file_context_window: int = 20,
        full_file_max_lines: Optional[int] = None,
        callers_max_hits: Optional[int] = None,
        max_chars_per_field: Optional[int] = None,
        callers_snippet_window: int = 3,
    ) -> None:
        # 从 ConfigAPI 获取配置限制
        limits = get_context_limits()
        
        self.function_window = function_window
        self.file_context_window = file_context_window
        self.full_file_max_lines = full_file_max_lines if full_file_max_lines is not None else limits.get("full_file_max_lines", 150)
        self.callers_max_hits = callers_max_hits if callers_max_hits is not None else limits.get("callers_max_hits", 3)
        # 降低单字段最大字符数，避免上下文过大
        self.max_chars_per_field = max_chars_per_field if max_chars_per_field is not None else min(limits.get("max_context_chars", 8000), 5000)
        self.callers_snippet_window = callers_snippet_window


# ============================================================
# 跨调用的文件读取缓存（使用 LRU 策略）
# ============================================================

_FILE_CACHE: LRUCache[str, List[str]] = LRUCache(max_size=_FILE_CACHE_MAX_SIZE)
"""文件内容缓存，键为文件路径，值为文件内容的行列表。"""

_PREV_FILE_CACHE: LRUCache[Tuple[str, str], List[str]] = LRUCache(max_size=_PREV_FILE_CACHE_MAX_SIZE)
"""历史版本文件内容缓存，键为 (base, file_path) 元组，值为文件内容的行列表。"""

_AST_CACHE: LRUCache[str, ast.AST] = LRUCache(max_size=_AST_CACHE_MAX_SIZE)
"""AST 缓存，键为文件内容 hash，值为解析后的 AST。"""

_RG_CACHE: LRUCache[Tuple[str, str, int], List[Dict[str, str]]] = LRUCache(max_size=_RG_CACHE_MAX_SIZE)
"""ripgrep 搜索缓存。"""

_EMPTY_RESULT_LIST: List[str] = []
"""空结果常量，避免重复创建列表对象。"""


def _compute_content_hash(lines: List[str]) -> str:
    """计算文件内容的 hash 值，用于 AST 缓存键。
    
    注意：对空列表 []，hash 值将是空字符串的 sha256 结果 (e3b0c442...)。
    这在当前使用场景下是预期的行为（空文件具有明确的唯一 hash），且已被 AST 缓存正确处理。
    
    使用 SHA-256 替代 MD5，提供更强的抗碰撞能力。
    虽然当前场景不涉及安全认证，但使用更现代的哈希算法是最佳实践。
    """
    content = "\n".join(lines)
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()


def clear_file_caches() -> None:
    """清除所有文件缓存。"""
    _FILE_CACHE.clear()
    _PREV_FILE_CACHE.clear()
    _AST_CACHE.clear()
    _RG_CACHE.clear()
    logger.debug("All file caches cleared")


def get_cache_stats() -> Dict[str, Any]:
    """获取所有缓存的统计信息。"""
    return {
        "file_cache": _FILE_CACHE.stats(),
        "prev_file_cache": _PREV_FILE_CACHE.stats(),
        "ast_cache": _AST_CACHE.stats(),
        "rg_cache": _RG_CACHE.stats(),
    }


def _unit_map(diff_ctx: DiffContext) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    for u in diff_ctx.units:
        uid = u.get("unit_id") or u.get("id")
        if uid:
            mapping[str(uid)] = u
    return mapping


def _span_from_unit(unit: Dict[str, Any], key: str) -> Tuple[int, int]:
    """根据 hunk_range 返回新旧区间的 (start, end)，确保区间始终有效。"""
    hunk = unit.get("hunk_range", {}) or {}
    
    # 确定使用的字段名
    if key == "after":
        start_key = "new_start"
        lines_key = "new_lines"
    else:
        start_key = "old_start"
        lines_key = "old_lines"
    
    # 解析起始位置，确保为正整数
    try:
        start = int(hunk.get(start_key) or 1)
        start = max(1, start)  # 确保起始位置至少为1
    except (ValueError, TypeError):
        start = 1
    
    # 解析长度，确保为正整数
    try:
        length = int(hunk.get(lines_key) or 0)
        length = max(1, length)  # 确保长度至少为1
    except (ValueError, TypeError):
        length = 1
    
    # 计算结束位置，确保区间有效
    end = start + length - 1
    
    return start, end


def _read_file_cached(path: str) -> List[str]:
    """读取文件内容，使用 LRU 缓存。
    
    Args:
        path: 文件路径
        
    Returns:
        List[str]: 文件内容的行列表
    """
    root_str = get_project_root() or ""
    cache_key = f"{root_str}::{path}"
    
    # 尝试从缓存获取
    cached = _FILE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    
    p = Path(path)
    if not p.exists():
        if root_str and not p.is_absolute():
            try:
                root_path = Path(root_str).resolve()
                candidate = (root_path / p).resolve()
                candidate.relative_to(root_path)
                if candidate.exists():
                    p = candidate
            except Exception:
                pass
    
    if not p.exists():
        _FILE_CACHE.set(cache_key, _EMPTY_RESULT_LIST)
        return _EMPTY_RESULT_LIST
    
    try:
        text = read_text_with_fallback(
            p, tracker_key="context_read_fallback", reason="context_cache_decode"
        )
    except Exception as exc:
        record_fallback(
            "context_read_failed",
            "读取上下文文件失败，返回空结果",
            meta={"path": path, "error": str(exc)},
        )
        _FILE_CACHE.set(cache_key, _EMPTY_RESULT_LIST)
        return _EMPTY_RESULT_LIST
    
    lines = text.splitlines()
    _FILE_CACHE.set(cache_key, lines)
    return lines


def _slice_lines(lines: List[str], start: int, end: int) -> str:
    if not lines:
        return ""
    s = max(1, start)
    e = max(s, end)
    return "\n".join(lines[s - 1 : e])


def _extract_function_by_span(lines: List[str], start: int, end: int, window: int = 30) -> str:
    """启发式：在跨度周围取较大窗口作为函数级上下文兜底。"""
    if not lines:
        return ""
    s = max(1, start - window)
    e = min(len(lines), end + window)
    return _slice_lines(lines, s, e)


def _extract_function_ast(lines: List[str], start: int, end: int, language: str) -> Optional[str]:
    """Python 专用：选择覆盖该跨度的最小函数。"""
    if language != "python" or not lines:
        return None
    try:
        # 使用内容 hash 作为缓存键（避免 id() 的内存地址重用问题）
        cache_key = _compute_content_hash(lines)
        tree = _AST_CACHE.get(cache_key)
        if tree is None:
            tree = ast.parse("\n".join(lines))
            _AST_CACHE.set(cache_key, tree)
    except SyntaxError:
        return None
    best = None
    best_size = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not hasattr(node, "lineno"):
                continue
            node_start = node.lineno
            node_end = getattr(node, "end_lineno", node_start)
            if node_start <= start <= node_end or node_start <= end <= node_end:
                size = node_end - node_start
                if best_size is None or size < best_size:
                    best_size = size
                    best = (node_start, node_end)
    if best:
        return _slice_lines(lines, best[0], best[1])
    return None


def _git_show_file(base: str, file_path: str) -> List[str]:
    def _safe_ref(ref: str) -> bool:
        return bool(ref) and ref[0] != "/" and ref.count("..") == 0 and all(
            ch.isalnum() or ch in {"-", "_", "."} for ch in ref
        )

    def _safe_path(path: str) -> bool:
        return bool(path) and not Path(path).is_absolute() and ".." not in path and "\n" not in path and "\r" not in path

    # 基线分支与路径做轻量白名单检查，避免命令注入/路径穿越。
    if not _safe_ref(base) or not _safe_path(file_path):
        record_fallback(
            "git_show_rejected",
            "skip git show due to unsafe ref/path",
            meta={"base": base, "file_path": file_path},
        )
        return []
    try:
        cwd = get_project_root()
        output = run_git("show", f"{base}:{file_path}", cwd=cwd)
        return output.splitlines()
    except Exception as exc:
        record_fallback(
            "git_show_failed",
            "git show raised exception",
            meta={"base": base, "file_path": file_path, "error": str(exc)},
        )
        return []



# 符号验证正则：验证符号为合法标识符格式（允许点号和$，支持 module.func 及 JS 风格）
# 限制长度为 256 字符 (1 + 255)
_SYMBOL_PATTERN = re.compile(r'^[a-zA-Z_$.][a-zA-Z0-9_$.]{0,255}$')


def _search_callers(symbol: str, max_hits: int = 5) -> List[Dict[str, str]]:
    """若可用则用 ripgrep 查找调用方；返回文件路径与代码片段。
    
    安全措施：
    - 使用严格的正则表达式验证符号格式，防止命令注入
    - 使用 shell=False（subprocess.run 默认值）确保参数不会被 shell 解释
    """
    hits: List[Dict[str, str]] = []
    
    # 安全验证：符号必须符合 Python 标识符格式（防止命令注入）
    if not symbol or not _SYMBOL_PATTERN.match(symbol):
        return hits

    root = get_project_root() or ""
    # 简化缓存键：max_hits 已经是 int 类型，无需额外转换
    cache_key = (root, symbol, max_hits)
    cached = _RG_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)

    t0 = time.perf_counter()
    try:
        cwd = root or None
        # 限制单行长度防止极长行导致的内存问题
        max_cols = 1000
        result = subprocess.run(
            ["rg", "-n", "--fixed-strings", "--max-count", str(max_hits), "--max-columns", str(max_cols), symbol],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            check=False,
        )
        # 检查输出大小，防止意外的超大输出
        if len(result.stdout) > 1 * 1024 * 1024:  # 1MB limit
            logger.warning(f"ripgrep output too large for symbol {symbol}, truncated")
            return hits
            
        if result.returncode not in (0, 1):  # 返回码 1 表示无匹配
            return hits
        for line in result.stdout.splitlines()[:max_hits]:
            parts = line.split(":", 2)
            if len(parts) < 3:
                continue
            fp, ln, snippet = parts[0], parts[1], parts[2]
            hits.append({"file_path": fp, "snippet": f"{ln}: {snippet}"})
    except FileNotFoundError:
        pass

    _RG_CACHE.set(cache_key, list(hits))
    elapsed = time.perf_counter() - t0
    if elapsed >= 1.0:
        logger.info("context rg slow symbol=%s hits=%d elapsed=%.3fs", symbol, len(hits), elapsed)
    return hits


# 单字段最大字符数限制（尊重决策 agent，仅在超限时截断）
MAX_FIELD_CHARS = 30000

def _truncate(text: Optional[str], max_chars: int) -> Optional[str]:
    """截断文本，超过限制时附加 markdown 提示。"""
    if text is None:
        return None
    # 使用配置的限制和全局限制中较小的值
    effective_limit = min(max_chars, MAX_FIELD_CHARS)
    if len(text) <= effective_limit:
        return text
    truncated_chars = len(text) - effective_limit
    return text[:effective_limit] + f"\n\n> **⚠️ 上下文已截断**：原始内容 {len(text)} 字符，已截断 {truncated_chars} 字符。可能导致上下文超出预算，如需更多信息，请使用工具查看源文件。"


def _format_location(
    file_path: Optional[str],
    line_numbers: Dict[str, Any],
    default_start: int,
    default_end: int,
) -> Optional[str]:
    """优先使用精确行号，退化到 hunk 范围。"""

    new_compact = (line_numbers or {}).get("new_compact")
    old_compact = (line_numbers or {}).get("old_compact")
    if file_path and new_compact:
        return f"{file_path}:{new_compact}"
    if file_path and old_compact:
        return f"{file_path}:(removed) {old_compact}"
    if file_path:
        return f"{file_path}:{default_start}-{default_end}"
    if new_compact:
        return new_compact
    if old_compact:
        return f"(removed) {old_compact}"
    return None


def _truncate_lines(text: Optional[str], max_lines: int) -> Optional[str]:
    """按行数截断，保留首尾标记，降低上下文体积。"""

    if text is None:
        return None
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    keep = max_lines // 2
    head = lines[:keep]
    tail = lines[-keep:] if keep else []
    return "\n".join([*head, "...TRUNCATED...", *tail])


def _merge_adjacent_plan_items(
    plan_items: List[Dict[str, Any]],
    unit_lookup: Dict[str, Dict[str, Any]],
    merge_gap: int = 100
) -> List[Dict[str, Any]]:
    """合并同文件相邻的 plan items，减少上下文冗余。
    
    优化策略：
    1. 同一文件内所有 items 默认尝试合并
    2. 使用更大的合并阈值（100行）
    3. 对于样式文件（CSS/SCSS等），整个文件合并为一个
    
    Args:
        plan_items: 原始 plan 列表
        unit_lookup: unit_id -> unit 映射
        merge_gap: 合并阈值，行号间隔 <= 此值的 hunks 会被合并
        
    Returns:
        合并后的 plan 列表，每个 item 可能包含多个 unit_ids
    """
    if not plan_items:
        return []
    
    # 样式文件扩展名，这些文件整个文件合并为一个
    style_extensions = {".css", ".scss", ".sass", ".less", ".styl"}
    
    # 按文件分组
    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for item in plan_items:
        if not isinstance(item, dict):
            continue
        unit_id = item.get("unit_id")
        if not unit_id or str(unit_id) not in unit_lookup:
            continue
        if item.get("skip_review"):
            continue
        unit = unit_lookup[str(unit_id)]
        fp = unit.get("file_path") or ""
        by_file.setdefault(fp, []).append(item)
    
    merged_items: List[Dict[str, Any]] = []
    
    for fp, items in by_file.items():
        if len(items) <= 1:
            # 单个 item 无需合并
            merged_items.extend(items)
            continue
        
        # 检查是否是样式文件，样式文件整个文件合并为一个
        is_style_file = any(fp.lower().endswith(ext) for ext in style_extensions)
        if is_style_file:
            # 样式文件：整个文件的所有 items 合并为一个
            merged_items.append(_create_merged_item(items, unit_lookup))
            continue
        
        # 非样式文件：按行号排序后合并相邻的
        def get_start_line(item: Dict[str, Any]) -> int:
            uid = item.get("unit_id")
            unit = unit_lookup.get(str(uid), {})
            hunk = unit.get("hunk_range", {}) or {}
            return int(hunk.get("new_start", 0) or 0)
        
        sorted_items = sorted(items, key=get_start_line)
        
        # 合并相邻的 items
        current_group: List[Dict[str, Any]] = [sorted_items[0]]
        current_end = get_start_line(sorted_items[0])
        uid0 = sorted_items[0].get("unit_id")
        unit0 = unit_lookup.get(str(uid0), {})
        hunk0 = unit0.get("hunk_range", {}) or {}
        current_end += int(hunk0.get("new_lines", 1) or 1)
        
        for item in sorted_items[1:]:
            start = get_start_line(item)
            if start - current_end <= merge_gap:
                # 相邻，合并
                current_group.append(item)
                uid = item.get("unit_id")
                unit = unit_lookup.get(str(uid), {})
                hunk = unit.get("hunk_range", {}) or {}
                current_end = max(current_end, start + int(hunk.get("new_lines", 1) or 1))
            else:
                # 不相邻，保存当前组并开始新组
                merged_items.append(_create_merged_item(current_group, unit_lookup))
                current_group = [item]
                uid = item.get("unit_id")
                unit = unit_lookup.get(str(uid), {})
                hunk = unit.get("hunk_range", {}) or {}
                current_end = start + int(hunk.get("new_lines", 1) or 1)
        
        # 保存最后一组
        if current_group:
            merged_items.append(_create_merged_item(current_group, unit_lookup))
    
    return merged_items


def _create_merged_item(
    items: List[Dict[str, Any]],
    unit_lookup: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """从多个 items 创建合并后的 item。"""
    if len(items) == 1:
        return items[0]
    
    # 合并后的 item：使用第一个 unit_id，但记录所有 unit_ids
    first = items[0]
    merged = dict(first)
    merged["_merged_unit_ids"] = [item.get("unit_id") for item in items]
    merged["_merged_count"] = len(items)
    
    # 计算合并后的行号范围（用于生成统一上下文）
    all_starts = []
    all_ends = []
    for item in items:
        uid = item.get("unit_id")
        unit = unit_lookup.get(str(uid), {})
        hunk = unit.get("hunk_range", {}) or {}
        start = int(hunk.get("new_start", 0) or 0)
        lines = int(hunk.get("new_lines", 1) or 1)
        if start > 0:
            all_starts.append(start)
            all_ends.append(start + lines - 1)
    
    if all_starts and all_ends:
        merged["_merged_span"] = (min(all_starts), max(all_ends))
    
    # 使用最高的上下文级别
    level_rank = {"diff_only": 0, "function": 1, "file_context": 2, "full_file": 3}
    best_level = "diff_only"
    for item in items:
        level = item.get("final_context_level") or item.get("llm_context_level") or "function"
        if level_rank.get(level, 0) > level_rank.get(best_level, 0):
            best_level = level
    merged["final_context_level"] = best_level
    
    return merged

def build_context_bundle(
    diff_ctx: DiffContext,
    fused_plan: Dict[str, Any],
    config: Optional[ContextConfig] = None,
) -> List[Dict[str, Any]]:
    """根据融合计划组装 ContextBundle（diff + 请求的上下文）。"""

    cfg = config or ContextConfig()
    unit_lookup = _unit_map(diff_ctx)
    plan_items = fused_plan.get("plan", []) if isinstance(fused_plan, dict) else []
    
    # 合并同文件相邻的 hunks，减少上下文冗余
    merged_plan_items = _merge_adjacent_plan_items(plan_items, unit_lookup, merge_gap=30)
    
    bundle: List[Dict[str, Any]] = []

    allowed_levels = {"diff_only", "function", "file_context", "full_file"}

    for item in merged_plan_items:
        if not isinstance(item, dict):
            continue
        unit_id = item.get("unit_id")
        if not unit_id or str(unit_id) not in unit_lookup:
            continue
        # skip_review 已在合并阶段过滤
        unit = unit_lookup[str(unit_id)]
        file_path = unit.get("file_path")
        tags = unit.get("tags", [])
        hunk = unit.get("hunk_range", {}) or {}
        
        # 如果是合并后的 item，使用合并后的 span
        merged_span = item.get("_merged_span")
        if merged_span:
            new_start, new_end = merged_span
        else:
            new_start, new_end = _span_from_unit(unit, "after")
        old_start, old_end = _span_from_unit(unit, "before")
        # 若旧文件范围无效，则按窗口回退（作为最后的安全检查）
        if old_end < old_start:
            record_fallback(
                "missing_old_hunk_range",
                "old hunk range invalid, fallback to window",
                meta={
                    "file_path": file_path, 
                    "unit_id": unit_id,
                    "old_start": old_start,
                    "old_end": old_end,
                    "hunk": hunk
                },
            )
            old_start = max(1, new_start - cfg.function_window)
            old_end = new_end + cfg.function_window

        # diff 片段：始终包含（带行号优先），并附加位置提示行，便于审查端快速聚焦
        # 如果是合并后的 item，合并所有子 hunks 的 diff
        merged_unit_ids = item.get("_merged_unit_ids")
        if merged_unit_ids:
            diff_parts = []
            for mid in merged_unit_ids:
                sub_unit = unit_lookup.get(str(mid), {})
                sub_diff = sub_unit.get("unified_diff_with_lines") or sub_unit.get("unified_diff") or ""
                if sub_diff:
                    sub_ln = sub_unit.get("line_numbers") or {}
                    sub_hunk = sub_unit.get("hunk_range", {}) or {}
                    sub_start = int(sub_hunk.get("new_start", 0) or 0)
                    sub_end = sub_start + int(sub_hunk.get("new_lines", 1) or 1) - 1
                    sub_loc = _format_location(file_path, sub_ln, sub_start, sub_end)
                    if sub_loc:
                        diff_parts.append(f"@@ {sub_loc} @@\n{sub_diff}")
                    else:
                        diff_parts.append(sub_diff)
            diff_text = "\n\n".join(diff_parts)
        else:
            diff_text = unit.get("unified_diff_with_lines") or unit.get("unified_diff") or ""
            line_numbers = unit.get("line_numbers") or {}
            location_str = _format_location(file_path, line_numbers, new_start, new_end)
            if location_str:
                diff_text = f"@@ {location_str} @@\n{diff_text}"
        
        diff_text = _truncate_lines(diff_text, cfg.max_chars_per_field // 40)  # 近似按行截断

        function_ctx = None
        file_ctx = None
        full_file_ctx = None
        prev_version_ctx = None
        callers_ctx: List[Dict[str, str]] = []

        ctx_level = (
            item.get("final_context_level")
            or item.get("llm_context_level")
            or unit.get("rule_context_level")
            or "function"
        )
        if ctx_level not in allowed_levels:
            record_fallback(
                "invalid_context_level",
                f"invalid context level: {ctx_level}, fallback to diff_only",
                meta={
                    "unit_id": unit_id,
                    "file_path": file_path,
                    "original_ctx_level": ctx_level
                },
            )
            ctx_level = "diff_only"
        
        extra_requests = item.get("extra_requests") or item.get("final_extra_requests") or []

        lines = _read_file_cached(file_path) if file_path else []

        if ctx_level == "function":
            function_ctx = _extract_function_ast(lines, new_start, new_end, unit.get("language", "")) or _extract_function_by_span(
                lines, new_start, new_end, window=cfg.function_window
            )
        elif ctx_level == "file_context":
            file_ctx = _slice_lines(
                lines,
                new_start - cfg.file_context_window,
                new_end + cfg.file_context_window
            )
        elif ctx_level == "full_file":
            if lines:
                if len(lines) > cfg.full_file_max_lines:
                    head = "\n".join(lines[:50])
                    mid_start = max(1, new_start - cfg.file_context_window)
                    mid_end = min(len(lines), new_end + cfg.file_context_window)
                    mid = _slice_lines(lines, mid_start, mid_end)
                    tail = "\n".join(lines[-30:])
                    full_file_ctx = "\n".join(
                        [head, "...TRUNCATED...", mid, "...TRUNCATED...", tail]
                    )
                else:
                    full_file_ctx = "\n".join(lines)

        for req in extra_requests:
            if not isinstance(req, dict):
                continue
            rtype = req.get("type")
            if rtype == "previous_version":
                base = diff_ctx.base_branch
                if base and file_path:
                    root_str = get_project_root() or ""
                    key = (f"{root_str}::{base}", file_path)
                    prev_lines = _PREV_FILE_CACHE.get(key)
                    if prev_lines is None:
                        prev_lines = _git_show_file(base, file_path)
                        _PREV_FILE_CACHE.set(key, prev_lines)
                    prev_version_ctx = _slice_lines(prev_lines, old_start, old_end)
            elif rtype == "callers":
                symbol = req.get("symbol")
                if symbol:
                    callers_ctx = _search_callers(symbol, max_hits=cfg.callers_max_hits)
            elif rtype == "search":
                keyword = req.get("keyword") or req.get("text")
                if keyword:
                    callers_ctx = _search_callers(keyword, max_hits=cfg.callers_max_hits)

        # 补充调用方代码片段上下文（行号 ± window）
        callers_ctx_enriched: List[Dict[str, str]] = []
        for hit in callers_ctx:
            fp = hit.get("file_path")
            snippet = hit.get("snippet") or ""
            if fp and ":" in snippet:
                try:
                    ln = int(snippet.split(":", 1)[0])
                except Exception:
                    ln = None
                if ln:
                    hit_lines = _read_file_cached(fp)
                    snippet = _slice_lines(
                        hit_lines,
                        ln - cfg.callers_snippet_window,
                        ln + cfg.callers_snippet_window,
                    )
            callers_ctx_enriched.append(
                {"file_path": hit.get("file_path") or "", "snippet": snippet}
            )
        callers_ctx = callers_ctx_enriched

        # 统一截断，避免单个字段过大
        diff_text = _truncate(diff_text, cfg.max_chars_per_field)
        function_ctx = _truncate(function_ctx, cfg.max_chars_per_field)
        file_ctx = _truncate(file_ctx, cfg.max_chars_per_field)
        full_file_ctx = _truncate(full_file_ctx, cfg.max_chars_per_field)
        prev_version_ctx = _truncate(prev_version_ctx, cfg.max_chars_per_field)
        # 去掉空上下文，避免占位噪音
        if function_ctx == "":
            function_ctx = None
        if file_ctx == "":
            file_ctx = None
        if full_file_ctx == "":
            full_file_ctx = None
        if prev_version_ctx == "":
            prev_version_ctx = None
        callers_ctx = [
            {
                "file_path": c.get("file_path") or "",
                "snippet": (_truncate(c.get("snippet"), cfg.max_chars_per_field) or ""),
            }
            for c in callers_ctx
        ]
        # 去重调用方片段
        seen_callers = set()
        dedup_callers: List[Dict[str, str]] = []
        for c in callers_ctx:
            key = (c.get("file_path"), c.get("snippet"))
            if key in seen_callers:
                continue
            seen_callers.add(key)
            dedup_callers.append(c)
        callers_ctx = dedup_callers

        bundle.append(
            {
                "unit_id": unit_id,
                "meta": {
                    "file_path": file_path,
                    "tags": tags,
                    "hunk_range": hunk,
                    "line_numbers": line_numbers or None,
                    "location": location_str,
                },
                "final_context_level": ctx_level,
                "extra_requests": extra_requests,
                "diff": diff_text,
                "function_context": function_ctx,
                "file_context": file_ctx,
                "full_file": full_file_ctx,
                "previous_version": prev_version_ctx,
                "callers": callers_ctx,
            }
        )

    return bundle


__all__ = ["build_context_bundle", "clear_file_caches", "get_cache_stats", "LRUCache"]
