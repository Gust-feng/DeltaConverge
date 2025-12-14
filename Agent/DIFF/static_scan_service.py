"""静态分析旁路扫描服务。

这个模块提供独立于主审查链路的静态分析扫描功能。
扫描器作为可选旁路服务运行，不阻塞主链路的 Planner/Fusion/Review 流程。

核心设计原则：
- 主链路永远不依赖扫描器
- 扫描器按文件去重执行（而非按 Unit 重复扫描）
- 通过事件回调向前端汇报进度
- 扫描结果可供后续归一化 Agent 或前端展示使用
"""

from __future__ import annotations

import asyncio
import re
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from pathlib import Path
import threading

from Agent.core.logging import get_logger
from Agent.DIFF.file_utils import guess_language
from Agent.DIFF.rule.scanner_registry import ScannerRegistry
from Agent.DIFF.rule.scanner_performance import ScannerExecutor, AvailabilityCache

logger = get_logger(__name__)

# 类型别名
StreamCallback = Callable[[Dict[str, Any]], None]

# 全局线程池，用于执行阻塞的扫描操作
_scan_executor: Optional[ThreadPoolExecutor] = None

_STATIC_SCAN_ISSUES_CACHE: Dict[str, Dict[str, Any]] = {}
_STATIC_SCAN_ISSUES_CACHE_LOCK = threading.Lock()
_MAX_CACHED_ISSUES_PER_SESSION = 20000

_STATIC_SCAN_LINKED_CACHE: Dict[str, Dict[str, Any]] = {}
_STATIC_SCAN_LINKED_CACHE_LOCK = threading.Lock()


def _get_scan_executor() -> ThreadPoolExecutor:
    """获取或创建扫描线程池。"""
    global _scan_executor
    if _scan_executor is None:
        # 使用较少的线程数，避免资源竞争
        _scan_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="static_scan_")
    return _scan_executor


def _normalize_issue(issue: Any, file_path: str) -> Dict[str, Any]:
    if hasattr(issue, 'to_dict'):
        issue_dict = issue.to_dict()
    elif isinstance(issue, dict):
        issue_dict = dict(issue)
    else:
        try:
            from dataclasses import asdict
            issue_dict = asdict(issue)
        except (TypeError, ImportError):
            issue_dict = {"message": str(issue)}
    issue_dict["file"] = file_path
    return issue_dict


def _normalize_file_key(path: str) -> str:
    p = str(path or "").strip()
    if not p:
        return ""
    if p.startswith("rename from "):
        p = p[len("rename from "):]
    elif p.startswith("rename to "):
        p = p[len("rename to "):]
    p = p.replace("\\", "/")
    if p.startswith("a/"):
        p = p[2:]
    elif p.startswith("b/"):
        p = p[2:]
    if p.startswith("./"):
        p = p[2:]
    if p.startswith("/"):
        p = p[1:]
    return p


def _issue_line(issue: Dict[str, Any]) -> Optional[int]:
    line = issue.get("line") or issue.get("start_line")
    try:
        n = int(line)
    except Exception:
        return None
    if n <= 0:
        return None
    return n


def _severity_rank(sev: str) -> int:
    s = str(sev or "").lower()
    if s == "error":
        return 0
    if s == "warning":
        return 1
    if s == "info":
        return 2
    return 3


def _normalize_suggestion_severity(sev: str) -> str:
    s = str(sev or "").strip().lower()
    if s in ("error", "fatal", "critical"):
        return "error"
    if s in ("warning", "warn"):
        return "warning"
    if s in ("info", "information", "notice"):
        return "info"
    return "info"


def parse_review_report_issues(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []

    try:
        if len(text) > 200_000:
            text = str(text)[:200_000]
    except Exception:
        text = str(text or "")

    def _norm_path(p: str) -> str:
        return _normalize_file_key(str(p or "").strip().strip("`").strip())

    def _parse_line_range_text(raw: str) -> Tuple[int, int]:
        s = str(raw or "").strip()
        if not s:
            return 0, 0
        s = s.strip("`").strip()
        s = (
            s.replace("—", "-")
            .replace("–", "-")
            .replace("~", "-")
            .replace("到", "-")
            .replace("至", "-")
        )
        nums = re.findall(r"\d+", s)
        if not nums:
            return 0, 0
        try:
            a = int(nums[0])
        except Exception:
            return 0, 0
        if a <= 0:
            return 0, 0
        b = a
        if len(nums) > 1:
            try:
                b = int(nums[1])
            except Exception:
                b = a
        if b <= 0:
            b = a
        if b < a:
            a, b = b, a
        return a, b

    def _try_parse_location_line(s: str) -> Tuple[str, int, int]:
        line = str(s or "").strip().strip("`")
        if not line:
            return "", 0, 0

        m = re.search(
            r"(?:文件|file|path)\s*[:：]\s*(.+?)\s*[\(（\[【]?\s*(?:L|l)\s*(\d+)\s*[-~—–]\s*(\d+)\s*[\)）\]】]?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m:
            fp = _norm_path(m.group(1))
            try:
                a = int(m.group(2))
                b = int(m.group(3))
            except Exception:
                return fp, 0, 0
            if b < a:
                a, b = b, a
            return fp, a, b

        m = re.search(
            r"(?:文件|file|path)\s*[:：]\s*(.+?)\s*[\(（\[【]?\s*(\d+)\s*[-~—–]\s*(\d+)\s*[\)）\]】]?\s*$",
            line,
            flags=re.IGNORECASE,
        )
        if m:
            fp = _norm_path(m.group(1))
            try:
                a = int(m.group(2))
                b = int(m.group(3))
            except Exception:
                return fp, 0, 0
            if b < a:
                a, b = b, a
            return fp, a, b

        m = re.search(r"(?:文件|file|path)\s*[:：]\s*(.+?)\s*$", line, flags=re.IGNORECASE)
        if m:
            return _norm_path(m.group(1)), 0, 0

        m = re.search(r"([A-Za-z0-9_./\\-]+)\s*[:#@]\s*L?\s*(\d+)\s*[-~—–]\s*(\d+)", line)
        if m:
            fp = _norm_path(m.group(1))
            try:
                a = int(m.group(2))
                b = int(m.group(3))
            except Exception:
                return fp, 0, 0
            if b < a:
                a, b = b, a
            return fp, a, b

        return "", 0, 0

    def _try_parse_severity_line(s: str) -> Optional[str]:
        m = re.search(r"(?:严重性|severity|级别)\s*[:：]\s*([A-Za-z]+)", s, flags=re.IGNORECASE)
        if not m:
            return None
        return _normalize_suggestion_severity(m.group(1))

    out: List[Dict[str, Any]] = []
    cur_title = ""
    cur_file = ""
    cur_start = 0
    cur_end = 0
    cur_sev = "info"
    mode: Optional[str] = None

    def _try_parse_title_range_line(s: str) -> Tuple[str, int, int]:
        line = str(s or "").strip().strip("`")
        if not line:
            return "", 0, 0

        m = re.search(r"\b[Ll]\s*(\d+)\s*[-~—–]\s*(\d+)\b", line)
        if m:
            try:
                a = int(m.group(1))
                b = int(m.group(2))
            except Exception:
                return "", 0, 0
            if a <= 0:
                return "", 0, 0
            if b <= 0:
                b = a
            if b < a:
                a, b = b, a
            title = line[: m.start()].strip().strip(":：-—–").strip()
            return title, a, b

        m = re.search(r"\b[Ll]\s*(\d+)\b", line)
        if m:
            try:
                a = int(m.group(1))
            except Exception:
                return "", 0, 0
            if a <= 0:
                return "", 0, 0
            title = line[: m.start()].strip().strip(":：-—–").strip()
            return title, a, a

        return "", 0, 0

    lines = str(text).replace("\r\n", "\n").split("\n")
    for raw in lines:
        line = str(raw or "").strip()
        if not line:
            continue

        if re.match(r"^#{2,4}\s+", line):
            heading = re.sub(r"^#{2,4}\s+", "", line).strip()
            fp, a, b = _try_parse_location_line(heading)
            if fp:
                cur_file = fp
                cur_title = ""
                mode = None
                cur_start = a if a > 0 else 0
                cur_end = b if b > 0 else 0
                cur_sev = "info"
                continue

            cur_title = heading
            mode = None
            cur_file = ""
            cur_start = 0
            cur_end = 0
            cur_sev = "info"
            continue

        fp, a, b = _try_parse_location_line(line)
        if fp:
            cur_file = fp
            if a > 0:
                cur_start, cur_end = a, b
            continue

        if cur_file:
            if not re.match(r"^(?:[-*+]|\d+\.)\s+", line):
                title2, a2, b2 = _try_parse_title_range_line(line)
                if a2 > 0:
                    cur_start, cur_end = a2, b2
                    if title2:
                        cur_title = title2
                    mode = None
                    cur_sev = "info"
                    continue

        if cur_file and (
            re.match(r"^[Ll]\s*\d+", line)
            or re.match(r"^(?:行号|行|lines?|range)\s*[:：]", line, flags=re.IGNORECASE)
        ):
            a2, b2 = _parse_line_range_text(line)
            if a2 > 0:
                cur_start, cur_end = a2, b2
            continue

        sev = _try_parse_severity_line(line)
        if sev:
            cur_sev = sev
            continue

        if re.match(r"^(?:问题|problem)\s*[:：]?\s*$", line, flags=re.IGNORECASE):
            mode = "problem"
            continue
        if re.match(
            r"^(?:建议|recommendations?|suggestions?|fix|changes?)\s*[:：]?\s*$",
            line,
            flags=re.IGNORECASE,
        ):
            mode = "suggestion"
            continue

        m_bullet = re.match(r"^(?:[-*+]|\d+\.)\s+(.+)$", line)
        if not m_bullet:
            continue

        if not cur_file or cur_start <= 0:
            continue
        if mode not in ("problem", "suggestion"):
            continue

        msg = str(m_bullet.group(1) or "").strip()
        if not msg or msg == "(无)":
            continue

        prefix = "问题" if mode == "problem" else "建议"
        item: Dict[str, Any] = {
            "file": cur_file,
            "severity": cur_sev,
            "line": cur_start,
            "start_line": cur_start,
            "end_line": cur_end if cur_end > 0 else cur_start,
            "message": f"{prefix}: {msg}",
            "source": "llm",
        }
        if cur_title and cur_title != "(无)":
            item["title"] = cur_title
        out.append(item)

    return out


def build_linked_unit_llm_suggestions(
    units: List[Dict[str, Any]],
    suggestions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    units_by_file: Dict[str, List[Tuple[str, int, int]]] = {}
    for u in units or []:
        unit_id = u.get("unit_id") or u.get("id")
        if not unit_id:
            continue
        fp = _normalize_file_key(u.get("file_path") or "")
        if not fp:
            continue
        hr = u.get("hunk_range") or {}
        try:
            new_start = int(hr.get("new_start") or 0)
        except Exception:
            new_start = 0
        try:
            new_lines = int(hr.get("new_lines") or 0)
        except Exception:
            new_lines = 0
        if new_start <= 0:
            continue
        new_end = new_start + max(new_lines, 1) - 1
        units_by_file.setdefault(fp, []).append((str(unit_id), new_start, new_end))

    for ranges in units_by_file.values():
        ranges.sort(key=lambda x: x[1])

    unit_suggestions: Dict[str, List[Dict[str, Any]]] = {}
    mapped_count = 0
    unmapped_count = 0

    for it in suggestions or []:
        fp = _normalize_file_key(it.get("file") or it.get("file_path") or "")
        if not fp:
            unmapped_count += 1
            continue

        start = _issue_line(it) or it.get("start_line")
        try:
            start_i = int(start) if start is not None else 0
        except Exception:
            start_i = 0
        if start_i <= 0:
            unmapped_count += 1
            continue

        end = it.get("end_line") or it.get("end") or start_i
        try:
            end_i = int(end) if end is not None else start_i
        except Exception:
            end_i = start_i
        if end_i < start_i:
            start_i, end_i = end_i, start_i

        matched_any = False
        for unit_id, u_start, u_end in units_by_file.get(fp, []):
            overlap_start = max(start_i, u_start)
            overlap_end = min(end_i, u_end)
            if overlap_start <= overlap_end:
                matched_any = True
                it_copy = dict(it)
                it_copy["origin_start_line"] = start_i
                it_copy["origin_end_line"] = end_i
                it_copy["start_line"] = overlap_start
                it_copy["end_line"] = overlap_end
                it_copy["line"] = overlap_start
                unit_suggestions.setdefault(unit_id, []).append(it_copy)
                mapped_count += 1

        if not matched_any:
            unmapped_count += 1
            continue

    def _sort_key(x: Dict[str, Any]) -> Tuple[int, int, str]:
        sev = _severity_rank(x.get("severity"))
        ln = _issue_line(x) or x.get("start_line") or 0
        try:
            ln_i = int(ln)
        except Exception:
            ln_i = 0
        msg = str(x.get("message") or "")
        return (sev, ln_i, msg)

    for unit_id, items in unit_suggestions.items():
        items.sort(key=_sort_key)

    return {
        "unit_llm_suggestions": unit_suggestions,
        "llm_suggestions_total": len(suggestions or []),
        "llm_mapped_count": mapped_count,
        "llm_unmapped_count": unmapped_count,
    }


def _build_linked_unit_issues(
    units: List[Dict[str, Any]],
    issues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    units_by_file: Dict[str, List[Tuple[str, int, int]]] = {}
    for u in units or []:
        unit_id = u.get("unit_id") or u.get("id")
        if not unit_id:
            continue
        fp = _normalize_file_key(u.get("file_path") or "")
        if not fp:
            continue
        hr = u.get("hunk_range") or {}
        try:
            new_start = int(hr.get("new_start") or 0)
        except Exception:
            new_start = 0
        try:
            new_lines = int(hr.get("new_lines") or 0)
        except Exception:
            new_lines = 0
        if new_start <= 0:
            continue
        new_end = new_start + max(new_lines, 1) - 1
        units_by_file.setdefault(fp, []).append((str(unit_id), new_start, new_end))

    for ranges in units_by_file.values():
        ranges.sort(key=lambda x: x[1])

    unit_issues: Dict[str, List[Dict[str, Any]]] = {}
    mapped_count = 0
    unmapped_count = 0
    for it in issues or []:
        fp = _normalize_file_key(it.get("file") or it.get("file_path") or "")
        if not fp:
            unmapped_count += 1
            continue
        line = _issue_line(it)
        if not line:
            unmapped_count += 1
            continue
        matched = False
        for unit_id, start, end in units_by_file.get(fp, []):
            if start <= line <= end:
                unit_issues.setdefault(unit_id, []).append(it)
                mapped_count += 1
                matched = True
                break
        if not matched:
            unmapped_count += 1

    def _sort_key(x: Dict[str, Any]) -> Tuple[int, int, int, str]:
        sev = _severity_rank(x.get("severity"))
        ln = _issue_line(x) or 0
        try:
            col = int(x.get("column") or 0)
        except Exception:
            col = 0
        rule = str(x.get("rule_id") or x.get("rule") or "")
        return (sev, ln, col, rule)

    for unit_id, items in unit_issues.items():
        items.sort(key=_sort_key)

    return {
        "unit_issues": unit_issues,
        "mapped_count": mapped_count,
        "unmapped_count": unmapped_count,
    }


def get_static_scan_linked(session_id: str) -> Dict[str, Any]:
    with _STATIC_SCAN_LINKED_CACHE_LOCK:
        data = _STATIC_SCAN_LINKED_CACHE.get(session_id)
    if not data:
        raise KeyError("static_scan_linked_not_found")
    return data


def _issue_sort_key(x: Dict[str, Any]) -> Tuple[int, str, int, int, str]:
    severity_order = {"error": 0, "warning": 1, "info": 2}
    sev = str(x.get("severity", "")).lower()
    f = str(x.get("file", ""))
    line = x.get("line") or x.get("start_line") or 0
    col = x.get("column") or 0
    try:
        line_i = int(line)
    except Exception:
        line_i = 0
    try:
        col_i = int(col)
    except Exception:
        col_i = 0
    rule = str(x.get("rule_id") or x.get("rule") or "")
    return (severity_order.get(sev, 3), f, line_i, col_i, rule)


def get_static_scan_issues_page(
    session_id: str,
    severity: str = "error",
    offset: int = 0,
    limit: int = 50,
) -> Dict[str, Any]:
    sev = str(severity or "error").lower()
    if sev not in ("error", "warning", "info"):
        sev = "error"
    off = int(offset or 0)
    lim = int(limit or 50)
    if off < 0:
        off = 0
    if lim <= 0:
        lim = 50
    if lim > 200:
        lim = 200

    with _STATIC_SCAN_ISSUES_CACHE_LOCK:
        data = _STATIC_SCAN_ISSUES_CACHE.get(session_id)
        if not data:
            raise KeyError("static_scan_issues_not_found")
        issues_by_sev = data.get("issues_by_severity") or {}
        issues = issues_by_sev.get(sev) or []

    total = len(issues)
    page = issues[off:off + lim]
    return {
        "session_id": session_id,
        "severity": sev,
        "offset": off,
        "limit": lim,
        "total": total,
        "has_more": (off + lim) < total,
        "issues": page,
    }


def _execute_file_scan_sync(
    file_path: str,
    content: Optional[str],
    scanners: List[Any],
    project_root: Optional[str],
) -> Tuple[List[Dict[str, Any]], float]:
    """在线程中同步执行单个文件的扫描。
    
    Args:
        file_path: 文件路径
        content: 文件内容（可选）
        scanners: 扫描器列表
        project_root: 项目根目录
        
    Returns:
        (issues, duration_ms) 元组
    """
    file_start = time.perf_counter()
    file_issues: List[Dict[str, Any]] = []
    
    try:
        # 注意：这里不传 event_callback，因为线程中的回调需要特殊处理
        # 事件会在外层异步函数中发送
        executor = ScannerExecutor(
            scanners=scanners,
            mode="sequential",
            event_callback=None,  # 线程中不直接回调
        )
        
        # 读取文件内容
        if content is None:
            full_path = file_path
            if project_root and not Path(file_path).is_absolute():
                full_path = str(Path(project_root) / file_path)
            
            try:
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception as e:
                logger.debug(f"Failed to read file {full_path}: {e}")
                content = None
        
        issues, stats = executor.execute(file_path, content)
        file_issues = issues
        
    except Exception as e:
        logger.warning(f"Scanner execution failed for {file_path}: {e}")
    
    duration_ms = (time.perf_counter() - file_start) * 1000
    return file_issues, duration_ms


class StaticScanResult:
    """静态扫描结果的结构化表示。"""
    
    def __init__(self):
        self.files_scanned: int = 0
        self.files_total: int = 0
        self.total_issues: int = 0
        self.error_count: int = 0
        self.warning_count: int = 0
        self.info_count: int = 0
        self.duration_ms: float = 0.0
        self.issues_by_file: Dict[str, List[Dict[str, Any]]] = {}
        self.scanners_used: List[str] = []
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式。"""
        return {
            "files_scanned": self.files_scanned,
            "files_total": self.files_total,
            "total_issues": self.total_issues,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "duration_ms": self.duration_ms,
            "scanners_used": self.scanners_used,
        }


def _detect_language(file_path: str) -> Optional[str]:
    """根据文件扩展名检测语言。"""
    lang = guess_language(file_path)
    if lang == "unknown":
        return None
    return lang


def _get_risk_score(file_path: str, tags: Set[str]) -> int:
    """计算文件的风险分数，用于排序。
    
    分数越高，优先级越高。
    """
    score = 0
    lower_path = file_path.lower()
    
    # 安全敏感路径
    security_keywords = ["auth", "security", "crypto", "password", "token", "jwt", "oauth"]
    for kw in security_keywords:
        if kw in lower_path:
            score += 100
            break
    
    # 配置文件
    config_keywords = ["config", "setting", "env", ".yaml", ".yml", ".json", ".toml"]
    for kw in config_keywords:
        if kw in lower_path:
            score += 50
            break
    
    # 基于 tags 的加权
    if "security_sensitive" in tags:
        score += 80
    if "config_file" in tags:
        score += 40
    if "routing_file" in tags:
        score += 30
    
    return score


async def run_static_scan(
    files: List[str],
    units: List[Dict[str, Any]],
    callback: Optional[StreamCallback] = None,
    project_root: Optional[str] = None,
    session_id: Optional[str] = None,
) -> StaticScanResult:
    """执行静态分析旁路扫描。
    
    Args:
        files: 需要扫描的文件列表（已去重）
        units: 审查单元列表，用于获取 tags 等元信息
        callback: 事件回调函数，用于向前端推送进度
        project_root: 项目根目录
        
    Returns:
        StaticScanResult: 扫描结果
    """
    result = StaticScanResult()
    start_time = time.perf_counter()
    
    if not files:
        logger.debug("No files to scan")
        return result

    # 构建文件到 tags 的映射
    file_tags: Dict[str, Set[str]] = {}
    for unit in units:
        fp = unit.get("file_path", "")
        if fp:
            tags = set(unit.get("tags", []) or [])
            if fp in file_tags:
                file_tags[fp].update(tags)
            else:
                file_tags[fp] = tags
    
    # 按风险分数排序文件
    sorted_files = sorted(
        files,
        key=lambda f: _get_risk_score(f, file_tags.get(f, set())),
        reverse=True
    )
    
    available_files_total = 0
    files_by_lang_probe: Dict[str, List[str]] = {}
    skipped_doc = 0
    skipped_unknown_lang = 0
    for fp in sorted_files:
        guessed_lang = guess_language(fp)
        if guessed_lang == "text":
            skipped_doc += 1
            continue
        if guessed_lang == "unknown":
            skipped_unknown_lang += 1
            continue
        if guessed_lang not in files_by_lang_probe:
            files_by_lang_probe[guessed_lang] = []
        files_by_lang_probe[guessed_lang].append(fp)

    skipped_no_scanner = 0
    skipped_scanner_error = 0

    for lang, lang_files in files_by_lang_probe.items():
        try:
            scanners = ScannerRegistry.get_available_scanners(lang)
            if scanners:
                available_files_total += len(lang_files)
                for s in scanners:
                    if s.name not in result.scanners_used:
                        result.scanners_used.append(s.name)
            else:
                skipped_no_scanner += len(lang_files)
        except Exception:
            skipped_scanner_error += len(lang_files)

    result.files_total = available_files_total
    
    # 发送扫描开始事件
    if callback:
        try:
            callback({
                "type": "static_scan_start",
                "files_total": result.files_total,
                "files_all": len(sorted_files),
                "files_skipped": max(0, len(sorted_files) - result.files_total),
                "files_skipped_doc": skipped_doc,
                "files_skipped_unknown_lang": skipped_unknown_lang,
                "files_skipped_no_scanner": skipped_no_scanner,
                "files_skipped_scanner_error": skipped_scanner_error,
                "timestamp": time.time(),
            })
        except Exception as e:
            logger.warning(f"Failed to emit static_scan_start event: {e}")
    
    # 按语言分组文件
    files_by_lang: Dict[str, List[str]] = files_by_lang_probe
    
    # 对每种语言获取可用的扫描器
    scanners_by_lang: Dict[str, List[Any]] = {}
    for lang in files_by_lang:
        try:
            scanners = ScannerRegistry.get_available_scanners(lang)
            if scanners:
                scanners_by_lang[lang] = scanners
                for s in scanners:
                    if s.name not in result.scanners_used:
                        result.scanners_used.append(s.name)
        except Exception as e:
            logger.debug(f"Failed to get scanners for {lang}: {e}")
    
    # 执行扫描 - 使用线程池避免阻塞事件循环
    for lang, lang_files in files_by_lang.items():
        scanners = scanners_by_lang.get(lang, [])
        if not scanners:
            continue
        
        for file_path in lang_files:
            # 发送文件扫描开始事件
            if callback:
                try:
                    callback({
                        "type": "static_scan_file_start",
                        "file": file_path,
                        "language": lang,
                        "timestamp": time.time(),
                    })
                except Exception:
                    pass
            
            # 在线程池中执行阻塞的扫描操作，不阻塞事件循环
            # 这样主链路（Planner/Fusion/Review）可以并行运行
            file_issues, file_duration = await asyncio.to_thread(
                _execute_file_scan_sync,
                file_path,
                None,  # content 由线程内部读取
                scanners,
                project_root,
            )
            
            # 统计问题
            for issue in file_issues:
                severity = str(issue.get("severity", "")).lower()
                if severity == "error":
                    result.error_count += 1
                elif severity == "warning":
                    result.warning_count += 1
                else:
                    result.info_count += 1
            
            result.total_issues += len(file_issues)
            result.files_scanned += 1
            
            if file_issues:
                result.issues_by_file[file_path] = file_issues
            
            # 发送文件扫描完成事件
            if callback:
                try:
                    callback({
                        "type": "static_scan_file_done",
                        "file": file_path,
                        "language": lang,
                        "issues_count": len(file_issues),
                        "duration_ms": file_duration,
                        "progress": result.files_scanned / (result.files_total or 1),
                        "timestamp": time.time(),
                    })
                except Exception:
                    pass
    
    result.duration_ms = (time.perf_counter() - start_time) * 1000

    critical_issues: List[Dict[str, Any]] = []
    try:
        all_issues: List[Dict[str, Any]] = []
        for file_path, issues in result.issues_by_file.items():
            for issue in issues:
                all_issues.append(_normalize_issue(issue, file_path))

        all_issues.sort(key=_issue_sort_key)

        issues_by_severity: Dict[str, List[Dict[str, Any]]] = {
            "error": [],
            "warning": [],
            "info": [],
        }
        for it in all_issues:
            sev = str(it.get("severity", "info")).lower()
            if sev == "error":
                issues_by_severity["error"].append(it)
            elif sev == "warning":
                issues_by_severity["warning"].append(it)
            else:
                issues_by_severity["info"].append(it)

        if session_id:
            with _STATIC_SCAN_ISSUES_CACHE_LOCK:
                _STATIC_SCAN_ISSUES_CACHE[session_id] = {
                    "issues": all_issues[:_MAX_CACHED_ISSUES_PER_SESSION],
                    "issues_by_severity": {
                        "error": issues_by_severity["error"][:_MAX_CACHED_ISSUES_PER_SESSION],
                        "warning": issues_by_severity["warning"][:_MAX_CACHED_ISSUES_PER_SESSION],
                        "info": issues_by_severity["info"][:_MAX_CACHED_ISSUES_PER_SESSION],
                    },
                    "scanners_used": list(result.scanners_used),
                    "files_total": int(result.files_total or 0),
                    "files_scanned": int(result.files_scanned or 0),
                    "duration_ms": float(result.duration_ms or 0.0),
                    "timestamp": time.time(),
                }

            linked = _build_linked_unit_issues(units=units, issues=all_issues)

            diff_units: List[Dict[str, Any]] = []
            for u in units or []:
                uid = u.get("unit_id") or u.get("id")
                if not uid:
                    continue
                diff_units.append({
                    "unit_id": str(uid),
                    "file_path": _normalize_file_key(u.get("file_path") or ""),
                    "change_type": u.get("change_type") or u.get("patch_type"),
                    "hunk_range": u.get("hunk_range") or {},
                    "unified_diff": u.get("unified_diff") or "",
                    "unified_diff_with_lines": u.get("unified_diff_with_lines"),
                    "tags": u.get("tags") or [],
                    "rule_context_level": u.get("rule_context_level"),
                    "rule_confidence": u.get("rule_confidence"),
                })
            with _STATIC_SCAN_LINKED_CACHE_LOCK:
                _STATIC_SCAN_LINKED_CACHE[session_id] = {
                    "session_id": session_id,
                    "generated_at": time.time(),
                    "diff_units": diff_units,
                    **linked,
                }
        critical_issues = issues_by_severity["error"][:50]
    except Exception as e:
        logger.warning(f"Failed to build/cache static scan results: {e}")

    # 发送扫描完成事件
    if callback:
        try:
            callback({
                "type": "static_scan_complete",
                "files_scanned": result.files_scanned,
                "files_total": result.files_total,
                "files_all": len(sorted_files),
                "files_skipped": max(0, len(sorted_files) - result.files_total),
                "files_skipped_doc": skipped_doc,
                "files_skipped_unknown_lang": skipped_unknown_lang,
                "files_skipped_no_scanner": skipped_no_scanner,
                "files_skipped_scanner_error": skipped_scanner_error,
                "total_issues": result.total_issues,
                "error_count": result.error_count,
                "warning_count": result.warning_count,
                "info_count": result.info_count,
                "duration_ms": result.duration_ms,
                "scanners_used": result.scanners_used,
                "issues": critical_issues,
                "timestamp": time.time(),
            })
        except Exception as e:
            logger.warning(f"Failed to emit static_scan_complete event: {e}")
    
    logger.info(
        f"Static scan completed: {result.files_scanned}/{result.files_total} files "
        f"(skipped={max(0, len(sorted_files) - result.files_total)}, "
        f"doc={skipped_doc}, unknown_lang={skipped_unknown_lang}, no_scanner={skipped_no_scanner}, "
        f"scanner_error={skipped_scanner_error}), "
        f"{result.total_issues} issues ({result.error_count} errors, "
        f"{result.warning_count} warnings) in {result.duration_ms:.2f}ms"
    )
    
    return result


def get_unique_files_from_diff_context(diff_ctx: Any) -> List[str]:
    """从 DiffContext 中提取唯一的文件列表。
    
    Args:
        diff_ctx: DiffContext 对象
        
    Returns:
        去重后的文件路径列表
    """
    files: Set[str] = set()
    
    # 从 files 属性获取
    if hasattr(diff_ctx, "files") and diff_ctx.files:
        files.update(diff_ctx.files)
    
    # 从 units 属性获取
    if hasattr(diff_ctx, "units") and diff_ctx.units:
        for unit in diff_ctx.units:
            fp = unit.get("file_path", "")
            if fp:
                files.add(fp)
    
    return list(files)
