"""上下文调度器：执行融合计划并生成 ContextBundle。"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from Agent.core.context.diff_provider import DiffContext
from Agent.core.logging.fallback_tracker import record_fallback, read_text_with_fallback


class ContextConfig:
    """可配置开关，避免硬编码。"""

    def __init__(
        self,
        function_window: int = 30,
        file_context_window: int = 20,
        full_file_max_lines: int = 300,
        callers_max_hits: int = 5,
        max_chars_per_field: int = 8000,
        callers_snippet_window: int = 3,
    ) -> None:
        self.function_window = function_window
        self.file_context_window = file_context_window
        self.full_file_max_lines = full_file_max_lines
        self.callers_max_hits = callers_max_hits
        self.max_chars_per_field = max_chars_per_field
        self.callers_snippet_window = callers_snippet_window


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


def _read_file_cached(cache: Dict[str, List[str]], path: str) -> List[str]:
    if path in cache:
        return cache[path]
    p = Path(path)
    if not p.exists():
        cache[path] = []
        return cache[path]
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
        cache[path] = []
        return cache[path]
    cache[path] = text.splitlines()
    return cache[path]


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
        tree = ast.parse("\n".join(lines))
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
        result = subprocess.run(
            ["git", "show", f"{base}:{file_path}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            record_fallback(
                "git_show_failed",
                "git show returned non-zero",
                meta={"base": base, "file_path": file_path, "stderr": result.stderr.strip()},
            )
            return []
        return result.stdout.splitlines()
    except Exception as exc:
        record_fallback(
            "git_show_failed",
            "git show raised exception",
            meta={"base": base, "file_path": file_path, "error": str(exc)},
        )
        return []


def _search_callers(symbol: str, max_hits: int = 5) -> List[Dict[str, str]]:
    """若可用则用 ripgrep 查找调用方；返回文件路径与代码片段。"""
    hits: List[Dict[str, str]] = []
    if not symbol or not symbol.replace("_", "").isalnum():
        return hits
    try:
        result = subprocess.run(
            ["rg", "-n", symbol],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            check=False,
        )
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
    return hits


def _truncate(text: Optional[str], max_chars: int) -> Optional[str]:
    if text is None:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...TRUNCATED..."


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


def build_context_bundle(
    diff_ctx: DiffContext,
    fused_plan: Dict[str, Any],
    config: Optional[ContextConfig] = None,
) -> List[Dict[str, Any]]:
    """根据融合计划组装 ContextBundle（diff + 请求的上下文）。"""

    cfg = config or ContextConfig()
    unit_lookup = _unit_map(diff_ctx)
    plan_items = fused_plan.get("plan", []) if isinstance(fused_plan, dict) else []
    bundle: List[Dict[str, Any]] = []

    file_cache: Dict[str, List[str]] = {}
    prev_file_cache: Dict[Tuple[str, str], List[str]] = {}  # (base, file_path) 的缓存
    allowed_levels = {"diff_only", "function", "file_context", "full_file"}

    for item in plan_items:
        if not isinstance(item, dict):
            continue
        unit_id = item.get("unit_id")
        if not unit_id or str(unit_id) not in unit_lookup:
            continue
        if item.get("skip_review"):
            # LLM 规划明确跳过的单元不进入上下文包
            continue
        unit = unit_lookup[str(unit_id)]
        file_path = unit.get("file_path")
        tags = unit.get("tags", [])
        hunk = unit.get("hunk_range", {}) or {}
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
        diff_text = unit.get("unified_diff_with_lines") or unit.get("unified_diff") or ""

        function_ctx = None
        file_ctx = None
        full_file_ctx = None
        prev_version_ctx = None
        callers_ctx: List[Dict[str, str]] = []
        line_numbers = unit.get("line_numbers") or {}
        location_str = _format_location(file_path, line_numbers, new_start, new_end)
        if location_str:
            diff_text = f"@@ {location_str} @@\n{diff_text}"
        diff_text = _truncate_lines(diff_text, cfg.max_chars_per_field // 40)  # 近似按行截断

        ctx_level = (
            item.get("final_context_level")
            or item.get("llm_context_level")
            or unit.get("rule_context_level")
            or "function"
        )
        if ctx_level not in allowed_levels:
            ctx_level = "diff_only"
        extra_requests = item.get("extra_requests") or item.get("final_extra_requests") or []

        lines = _read_file_cached(file_cache, file_path) if file_path else []

        if ctx_level == "function":
            function_ctx = _extract_function_ast(lines, new_start, new_end, unit.get("language", "")) or _extract_function_by_span(
                lines, new_start, new_end, window=cfg.function_window
            )
        elif ctx_level == "file_context":
            file_ctx = _slice_lines(
                lines, new_start - cfg.file_context_window, new_end + cfg.file_context_window
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
                    key = (base, file_path)
                    if key not in prev_file_cache:
                        prev_file_cache[key] = _git_show_file(base, file_path)
                    prev_lines = prev_file_cache.get(key, [])
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
                    hit_lines = _read_file_cached(file_cache, fp)
                    snippet = _slice_lines(
                        hit_lines,
                        ln - cfg.callers_snippet_window,
                        ln + cfg.callers_snippet_window,
                    )
            callers_ctx_enriched.append(
                {"file_path": hit.get("file_path"), "snippet": snippet}
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
                "file_path": c.get("file_path"),
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


__all__ = ["build_context_bundle"]
