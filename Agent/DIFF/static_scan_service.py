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

# 扫描完成事件 - 用于工具等待扫描完成
_SCAN_COMPLETE_EVENTS: Dict[str, threading.Event] = {}
_SCAN_COMPLETE_EVENTS_LOCK = threading.Lock()


def get_scan_complete_event(session_id: str) -> threading.Event:
    """获取或创建扫描完成事件。
    
    工具调用时使用此事件等待扫描完成。
    """
    with _SCAN_COMPLETE_EVENTS_LOCK:
        if session_id not in _SCAN_COMPLETE_EVENTS:
            _SCAN_COMPLETE_EVENTS[session_id] = threading.Event()
        return _SCAN_COMPLETE_EVENTS[session_id]

async def wait_scan_complete(session_id: str, timeout: float = 60.0) -> bool:
    if not session_id:
        return False
    if is_scan_complete(session_id):
        return True
    event = get_scan_complete_event(session_id)
    try:
        await asyncio.wait_for(asyncio.to_thread(event.wait), timeout=float(timeout))
        return True
    except asyncio.TimeoutError:
        return False


def mark_scan_started(session_id: str) -> None:
    """标记扫描开始（清除完成信号）。"""
    if not session_id:
        return
    event = get_scan_complete_event(session_id)
    event.clear()


def mark_scan_complete(session_id: str) -> None:
    """标记扫描完成（设置完成信号）。"""
    if not session_id:
        return
    event = get_scan_complete_event(session_id)
    event.set()


def is_scan_complete(session_id: str) -> bool:
    """检查扫描是否已完成。"""
    if not session_id:
        return False
    with _SCAN_COMPLETE_EVENTS_LOCK:
        event = _SCAN_COMPLETE_EVENTS.get(session_id)
        if event is None:
            return False
        return event.is_set()


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

    p = p.strip("`\"'")
    p = re.sub(r"^\*\*([^*]+)\*\*$", r"\1", p)
    p = re.sub(r"^\*([^*]+)\*$", r"\1", p)
    p = re.sub(r"^__([^_]+)__$", r"\1", p)
    p = p.strip("`\"' *_")
    if not p:
        return ""
    
    # 处理重命名前缀，使用更精确的正则表达式
    rename_patterns = [
        # 完整的重命名格式：rename from old.py to new.py
        r"^rename from\s+([^\s]+)\s+to\s+[^\s]+",
        # 简化的重命名格式：from old.py 或 to new.py
        r"^from\s+([^\s]+)",
        r"^to\s+([^\s]+)",
        # 带冒号的格式：old: old.py 或 new: new.py
        r"^old:\s+([^\s]+)",
        r"^new:\s+([^\s]+)",
        r"^original:\s+([^\s]+)",
        r"^modified:\s+([^\s]+)"
    ]
    
    for pattern in rename_patterns:
        match = re.match(pattern, p, re.IGNORECASE)
        if match:
            p = match.group(1)
            break

    p = p.strip("`\"' *_")
    
    # 统一使用正斜杠
    p = p.replace("\\", "/")

    m = re.match(r"^(.*?)(?::L?\d+(?:[-~—–]\d+)?)$", p, flags=re.IGNORECASE)
    if m:
        p = m.group(1)
    m = re.match(r"^(.*?)(?:#L?\d+(?:[-~—–]\d+)?)$", p, flags=re.IGNORECASE)
    if m:
        p = m.group(1)

    m = re.match(r"^(.+?)\s*\(\s*L?\d+(?:\s*[-~—–]\s*\d+)?\s*\)\s*$", p, flags=re.IGNORECASE)
    if m:
        p = m.group(1)

    p = p.strip().strip("`\"' *_")

    # 处理 Git 风格的路径前缀
    git_prefixes = ["a/", "b/", "old/", "new/"]
    for prefix in git_prefixes:
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    
    # 处理相对路径前缀
    while p.startswith("./"):
        p = p[2:]
    
    # 处理绝对路径前缀
    if p.startswith("/"):
        p = p[1:]
    
    # 处理 Windows 驱动器号，如 C:/ 或 D:\
    windows_drive_pattern = r"^[A-Za-z]:"
    if re.match(windows_drive_pattern, p):
        # 移除驱动器号，如 C:/ -> /
        p = p[2:]
        # 如果移除驱动器号后还有斜杠，再移除
        if p.startswith("/"):
            p = p[1:]
    
    # 处理重复斜杠
    p = re.sub(r"/+", "/", p)
    
    # 移除末尾斜杠
    if p.endswith("/") and len(p) > 1:
        p = p[:-1]
    
    # 处理 URL 编码的路径
    try:
        import urllib.parse
        p = urllib.parse.unquote(p)
    except Exception:
        pass
    
    return p


def _extract_file_path_from_text(text: str) -> str:
    t = str(text or "")
    m = re.search(
        r"([A-Za-z0-9_\-./\\]+?\.(?:py|js|ts|tsx|jsx|java|go|rb|rs|cpp|c|h|hpp|json|yaml|yml))",
        t,
        flags=re.IGNORECASE,
    )
    if not m:
        return ""
    return _normalize_file_key(m.group(1))


def _resolve_units_for_file(
    fp_norm: str,
    units_by_file: Dict[str, List[Tuple[str, int, int, Dict[str, Any]]]],
    file_key_to_path: Dict[str, str],
) -> Tuple[str, List[Tuple[str, int, int, Dict[str, Any]]]]:
    fp_key = str(fp_norm or "").lower()
    if not fp_key:
        return "", []
    file_units = units_by_file.get(fp_key)
    if file_units:
        return file_key_to_path.get(fp_key, fp_norm), file_units

    fp_parts = [x for x in str(fp_norm).split("/") if x]
    if not fp_parts:
        return fp_norm, []

    best_score = 0
    best_suffix_len = 0
    best_distance = 10**9
    best_path_len = 10**9
    best_key: Optional[str] = None
    best_units: Optional[List[Tuple[str, int, int, Dict[str, Any]]]] = None

    fp_norm_lower = str(fp_norm).lower()
    for cand_key, cand_units in units_by_file.items():
        cand_path = file_key_to_path.get(cand_key, cand_key)
        cand_parts = [x for x in str(cand_path).split("/") if x]
        if not cand_parts:
            continue

        max_len = min(len(fp_parts), len(cand_parts))
        suffix_len = 0
        while suffix_len < max_len and fp_parts[-(suffix_len + 1)].lower() == cand_parts[-(suffix_len + 1)].lower():
            suffix_len += 1
        if suffix_len <= 0:
            continue

        score = suffix_len * 100
        cand_lower = str(cand_path).lower()
        if cand_lower.endswith(fp_norm_lower) or fp_norm_lower.endswith(cand_lower):
            score += 30

        distance = abs(len(cand_parts) - len(fp_parts))
        path_len = len(cand_parts)

        if (
            score > best_score
            or (
                score == best_score
                and (
                    suffix_len > best_suffix_len
                    or (suffix_len == best_suffix_len and distance < best_distance)
                    or (suffix_len == best_suffix_len and distance == best_distance and path_len < best_path_len)
                    or (suffix_len == best_suffix_len and distance == best_distance and path_len == best_path_len and str(cand_path) < str(file_key_to_path.get(best_key or "", best_key or "")))
                )
            )
        ):
            best_score = score
            best_suffix_len = suffix_len
            best_distance = distance
            best_path_len = path_len
            best_key = cand_key
            best_units = cand_units

    if best_key and best_units:
        return file_key_to_path.get(best_key, fp_norm), best_units

    return fp_norm, []


def _issue_line(issue: Dict[str, Any]) -> Optional[int]:
    line = issue.get("line") or issue.get("start_line")
    if line is None:
        return None
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
        logger.debug("Empty text provided to parse_review_report_issues")
        return []

    try:
        if len(text) > 200_000:
            logger.debug(f"Truncating text to 200,000 characters for parsing")
            text = str(text)[:200_000]
    except Exception as e:
        logger.debug(f"Error truncating text: {e}, using original text")
        text = str(text or "")

    def _norm_path(p: str) -> str:
        return _normalize_file_key(str(p or "").strip().strip("`").strip("'").strip())

    def _parse_line_range_text(raw: str) -> Tuple[int, int]:
        s = str(raw or "").strip()
        if not s:
            return 0, 0
        s = s.strip("`").strip("'").strip()
        
        # 移除行号前缀，如 "line", "lines", "行", "行号", "range" 等
        s = re.sub(r"^(?:line|lines|行|行号|range|范围)\s*[:：]?\s*", "", s, flags=re.IGNORECASE)
        
        # 替换各种分隔符为标准连字符
        s = (
            s.replace("—", "-")
            .replace("–", "-")
            .replace("~", "-")
            .replace("到", "-")
            .replace("至", "-")
            .replace("~", "-")
            .replace(" ", "")
            .replace("，", ",")
            .replace(",", "-")  # 处理逗号分隔的范围，如 "123,456" 视为 "123-456"
        )
        
        # 处理特殊情况："123+" 表示从123行开始到文件末尾
        if s.endswith("+"):
            s = s[:-1]
            nums = re.findall(r"\d+", s)
            if nums:
                try:
                    a = int(nums[0])
                    if a > 0:
                        return a, 999999  # 使用一个大数表示文件末尾
                except Exception:
                    pass
        
        # 匹配所有数字序列
        nums = re.findall(r"\d+", s)
        if not nums:
            return 0, 0
        
        try:
            a = int(nums[0])
        except Exception:
            return 0, 0
        
        if a <= 0:
            return 0, 0
        
        # 处理单数字情况，如 "123" 表示单行
        b = a
        if len(nums) > 1:
            try:
                b = int(nums[1])
            except Exception:
                b = a
        
        # 处理无效的结束行号
        if b <= 0:
            b = a
        
        # 确保结束行号大于等于开始行号
        if b < a:
            a, b = b, a
        
        return a, b

    def _try_parse_location_line(s: str) -> Tuple[str, int, int]:
        line = str(s or "").strip().strip("`").strip("'")
        if not line:
            return "", 0, 0
        
        # 移除行内代码（反引号包裹的内容），避免其中的内容被误解析
        # 例如: `# syntax=docker/dockerfile:1` 中的 dockerfile:1 不应被解析为文件路径
        line = re.sub(r'`[^`]+`', '', line)
        
        line = (
            line.replace("\u00a0", " ")
            .replace("\u200b", "")
            .replace("‑", "-")
            .replace("−", "-")
        )
        line = re.sub(r"\s+", " ", line).strip()

        # 尝试匹配多种文件路径和行号格式
        patterns = [
            # 带前缀 + 路径 + 中文描述 + 行号范围，如："文件: .env.example 敏感信息配置示例风险 L1-26 严重性: info"
            r"(?:文件|file|path)\s*[:：]\s*([^\s]+(?:\.[^\s]+)*?)\s+(?:[^\sL\d]+(?:\s+[^\sL\d]+)*)\s+(?:L|l)?(\d+)\s*[-~—–]\s*(?:L|l)?(\d+)",
            # 带前缀 + 路径 + 空格 + 行号范围，如："文件: src/main.py L123-456" 或 "file: path 123-456"
            r"(?:文件|file|path)\s*[:：]\s*([^\s]+(?:\s+[^\sL\d][^\s]*)*?)\s+(?:L|l)?(\d+)\s*[-~—–]\s*(?:L|l)?(\d+)\s*$",
            # 带前缀的完整格式，支持各种分隔符和大小写
            r"(?:文件|file|path)\s*[:：]?\s*(.+?)\s*[\(（\[【\{]?\s*(?:L|l)?\s*(\d+)\s*[-~—–]\s*(?:L|l)?\s*(\d+)\s*[\)）\]】\}]?\s*$",
            # 不带前缀的格式，如：path:123-456 或 path#L123-456
            r"([A-Za-z0-9_./\\-]+)\s*[:#@]\s*(?:L|l)?\s*(\d+)\s*[-~—–]\s*(?:L|l)?\s*(\d+)",
            # 简化的文件路径和行号格式，如："src/config.py L78-90"
            r"([A-Za-z0-9_./\\-]+(?:/[A-Za-z0-9_./\\-]+)*)\s+(?:L|l)?(\d+)\s*[-~—–]\s*(?:L|l)?(\d+)\s*$",
            # 简化格式，如：path (123) 或 path:123
            r"([A-Za-z0-9_./\\-]+)\s*[\(：:]\s*(?:L|l)?\s*(\d+)\s*[\)]?\s*$",
            # 增强的文件路径和行号格式，如："文件: src/main.py (L123-456)"
            r"(?:文件|file|path)\s*[:：]\s*(.+?)\s*[\(（]\s*(?:L|l)\s*(\d+)\s*[-~—–]\s*(?:L|l)?\s*(\d+)\s*[\)）]\s*$",
            # 单文件格式，如：文件: path 或 file: path（无行号）
            r"(?:文件|file|path)\s*[:：]?\s*(.+?)\s*$",
        ]

        # 常见的代码文件扩展名，用于验证解析出的路径是否为有效文件
        valid_extensions = {
            '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h', '.hpp',
            '.go', '.rs', '.rb', '.php', '.cs', '.swift', '.kt', '.scala', '.vue',
            '.css', '.scss', '.sass', '.less', '.html', '.htm', '.xml', '.json',
            '.yaml', '.yml', '.md', '.txt', '.sh', '.bash', '.zsh', '.ps1',
            '.sql', '.env', '.conf', '.cfg', '.ini', '.toml', '.lock', '.dockerfile'
        }
        
        # 常见的无扩展名文件名
        valid_filenames = {
            'dockerfile', 'makefile', 'jenkinsfile', 'vagrantfile', 'gemfile',
            'rakefile', 'procfile', 'brewfile', 'podfile', 'fastfile',
            'readme', 'license', 'changelog', 'authors', 'contributors',
            'codeowners', 'gitignore', 'dockerignore', 'editorconfig',
            'eslintrc', 'prettierrc', 'babelrc', 'nvmrc', 'npmrc', 'yarnrc'
        }

        def _is_likely_file_path(fp: str) -> bool:
            """检查字符串是否可能是有效的文件路径"""
            if not fp:
                return False
            # 包含目录分隔符的一定是文件路径
            if '/' in fp or '\\' in fp:
                return True
            # 检查是否是常见的无扩展名文件
            lower_fp = fp.lower().lstrip('.')
            if lower_fp in valid_filenames:
                return True
            # 检查是否有常见的文件扩展名
            for ext in valid_extensions:
                if lower_fp.endswith(ext):
                    return True
            # 文件名中有点且点后有字母（可能是扩展名）
            if '.' in fp:
                parts = fp.rsplit('.', 1)
                if len(parts) == 2 and parts[1].isalnum() and len(parts[1]) <= 10:
                    return True
            return False

        for idx, pattern in enumerate(patterns):
            m = re.search(pattern, line, flags=re.IGNORECASE)
            if m:
                groups = m.groups()
                if len(groups) == 1:
                    # 只有文件路径
                    fp = _norm_path(groups[0])
                    # 对于无前缀匹配（最后一个pattern），需要验证路径
                    if idx == len(patterns) - 1 and not _is_likely_file_path(fp):
                        continue
                    return fp, 0, 0
                else:
                    # 有文件路径和行号
                    fp = _norm_path(groups[0])
                    # 对于无 "文件:" 前缀的 pattern（索引 3, 4, 5），需要验证路径有效性
                    # 这些 pattern 可能误匹配 "dockerfile:1" 这类非文件路径
                    if idx in (3, 4, 5) and not _is_likely_file_path(fp):
                        logger.debug(f"Skipping invalid file path: {fp} (pattern {idx})")
                        continue
                    try:
                        a = int(groups[1]) if groups[1] else 0
                        b = int(groups[2]) if len(groups) > 2 and groups[2] else a
                    except Exception as e:
                        logger.debug(f"Error parsing line numbers: {e}, groups: {groups}")
                        return fp, 0, 0
                    if a <= 0:
                        logger.debug(f"Invalid start line: {a}, returning fp only")
                        return fp, 0, 0
                    if b <= 0:
                        b = a
                    if b < a:
                        a, b = b, a
                    logger.debug(f"Parsed location: {fp}, lines {a}-{b}")
                    return fp, a, b

        return "", 0, 0

    def _try_parse_severity_line(s: str) -> Optional[str]:
        # 预处理：移除 Markdown 加粗格式 **...** 和 __...__
        clean_s = re.sub(r'\*\*([^*]+)\*\*', r'\1', s)
        clean_s = re.sub(r'__([^_]+)__', r'\1', clean_s)
        clean_s = re.sub(r'\*([^*]+)\*', r'\1', clean_s)
        clean_s = clean_s.strip()
        
        # 支持更多的严重性表示方式
        m = re.search(
            r"(?:严重性|severity|级别|严重程度)\s*[:：]?\s*([A-Za-z]+|[\u4e00-\u9fa5]+)",
            clean_s, 
            flags=re.IGNORECASE
        )
        if not m:
            return None
        
        # 处理中文严重性
        sev = str(m.group(1)).lower()
        if sev in ("错误", "严重", "fatal", "critical", "error"):
            return "error"
        if sev in ("警告", "warn", "warning"):
            return "warning"
        if sev in ("信息", "info", "notice", "information"):
            return "info"
        
        return _normalize_suggestion_severity(sev)

    def _container_mode_of_text(raw: str) -> Optional[str]:
        t = str(raw or "").strip()
        if not t:
            return None
        t = t.strip("`").strip("'").strip()
        t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
        t = re.sub(r"__([^_]+)__", r"\1", t)
        t = re.sub(r"\*([^*]+)\*", r"\1", t)
        t = re.sub(r"`([^`]+)`", r"\1", t)
        t = re.sub(r"^(?:[-*+•‣⁃]|\d+[.。)）]|\([1-9]\d*\))\s*", "", t)
        t = re.sub(r"^(?:建议|问题)\s*[:：]\s*", "", t)
        t = re.sub(r"^[【\[\(（<《]\s*", "", t)
        t = re.sub(r"\s*[】\]\)）>》]\s*$", "", t)
        t = t.rstrip(":：").strip()
        t = re.sub(r"\s*[（(][^）)]*[)）]\s*$", "", t).strip()

        if t in {"建议优化的点", "建议优化点", "优化建议", "改进建议"}:
            return "suggestion"
        if t in {"必须修复的点", "必须修复点", "必须修复项", "必须修复问题", "必须修复的问题"}:
            return "problem"
        return None

    def _is_invalid_message_content(msg: str) -> bool:
        """检测消息内容是否无效（分隔线、空占位符等）"""
        if not msg:
            return True
        m = str(msg).strip()
        if not m:
            return True
        # 常见的空占位符
        if m in ["(无)", "无", "none", "N/A", "n/a", "-", "–", "—", "...", "…"]:
            return True
        # Markdown 分隔线：---、***、___
        if re.match(r"^[-*_]{3,}$", m):
            return True
        # 只包含标点符号的消息
        if re.match(r"^[\-*_=~#:.。,，;；!！?？\s]+$", m):
            return True
        return False

    out: List[Dict[str, Any]] = []
    cur_title = ""
    cur_file = ""
    cur_start = 0
    cur_end = 0
    cur_sev = "info"
    mode: Optional[str] = None

    def _try_parse_title_range_line(s: str) -> Tuple[str, int, int]:
        line = str(s or "").strip().strip("`").strip("'")
        if not line:
            return "", 0, 0

        # 匹配行号范围，如：L123-456 或 123-456 或 行123-456
        m = re.search(r"(?:L|l|行|lines?)?\s*(\d+)\s*[-~—–]\s*(\d+)", line)
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
            title = line[: m.start()].strip().strip(":：-—–= ").strip()
            return title, a, b

        # 匹配单行号，如：L123 或 123 或 行123
        m = re.search(r"(?:L|l|行|line)\s*(\d+)", line)
        if m:
            try:
                a = int(m.group(1))
            except Exception:
                return "", 0, 0
            if a <= 0:
                return "", 0, 0
            title = line[: m.start()].strip().strip(":：-—–= ").strip()
            return title, a, a

        return "", 0, 0

    # 预处理文本，处理可能的格式问题
    text = text.replace("\r\n", "\n").replace("\t", "    ")
    text = re.sub(
        r"((?:文件|file|path)\s*[:：][^\n]*?(?:L|l)\s*\d+\s*[-~—–]\s*(?:L|l)?\s*\d+)\s+(?=(?:问题|建议)\s*[:：])",
        r"\1\n",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(问题\s*[:：][^\n]*?)\s+(?=建议\s*[:：])",
        r"\1\n",
        text,
        flags=re.IGNORECASE,
    )
    lines = text.split("\n")
    
    logger.debug(f"Starting to parse review report with {len(lines)} lines")
    
    for line_num, raw in enumerate(lines, 1):
        try:
            line = str(raw or "").strip()
            if not line:
                continue

            # 处理标题行，支持不同级别的标题
            if re.match(r"^#{1,6}\s+", line):
                heading = re.sub(r"^#{1,6}\s+", "", line).strip()
                fp, a, b = "", 0, 0
                if (
                    re.search(r"(?:文件|file|path)\s*[:：]", heading, flags=re.IGNORECASE)
                    or re.search(r"\.[A-Za-z0-9]{1,6}(?:\s|$)", heading)
                ):
                    fp, a, b = _try_parse_location_line(heading)
                if fp:
                    # 标题中包含文件信息，更新当前上下文
                    logger.debug(f"Found file info in heading at line {line_num}: {fp}, lines {a}-{b}")
                    cur_file = fp
                    cur_title = heading.split('(')[0].strip() if '(' in heading else heading
                    mode = None
                    cur_start = a if a > 0 else 0
                    cur_end = b if b > 0 else 0
                    cur_sev = "info"
                    continue
                else:
                    # 预处理标题：移除 markdown 格式
                    clean_heading = re.sub(r'\*\*([^*]+)\*\*', r'\1', heading)
                    clean_heading = re.sub(r'\*([^*]+)\*', r'\1', clean_heading)
                    clean_heading = clean_heading.strip()

                    # 首先检查是否是严重性标题行，如 "### 严重性: error" 或 "### **严重性:** warning"
                    sev_from_heading = _try_parse_severity_line(clean_heading)
                    if sev_from_heading:
                        logger.debug(f"Found severity in heading at line {line_num}: {sev_from_heading}")
                        cur_sev = sev_from_heading
                        continue

                    inferred_container_mode = _container_mode_of_text(clean_heading)
                    if inferred_container_mode:
                        mode = inferred_container_mode
                        continue
                    
                    # 检查是否是模式标题（问题/建议），支持多种格式变体
                    problem_pattern = re.match(
                        r"^(?:问题|problems?|issues?|缺陷|bugs?|错误|errors?)"
                        r"(?:\s*(?:描述|说明|列表|分析))?\s*(?:\([^)]*\))?\s*$",
                        clean_heading, flags=re.IGNORECASE
                    )
                    suggestion_pattern = re.match(
                        r"^(?:建议|recommendations?|suggestions?|fixes?|changes?|优化|改进|解决方案?|修复)"
                        r"(?:\s*(?:描述|说明|列表|方案|措施))?\s*(?:\([^)]*\))?\s*$",
                        clean_heading, flags=re.IGNORECASE
                    )
                    if problem_pattern or suggestion_pattern:
                        # 这是一个模式标题，更新mode
                        if problem_pattern:
                            logger.debug(f"Switched to problem mode at line {line_num} via heading")
                            mode = "problem"
                        else:
                            logger.debug(f"Switched to suggestion mode at line {line_num} via heading")
                            mode = "suggestion"
                        continue
                    
                    # 只有在二级标题且不包含文件路径时，才重置文件上下文
                    # 这样可以保留三级及以下标题（如"### 问题"、"### 建议"）的文件上下文
                    if re.match(r"^##\s+", line):
                        logger.debug(f"Found section heading at line {line_num}: {heading}")
                        cur_title = heading
                        mode = None
                        cur_file = ""
                        cur_start = 0
                        cur_end = 0
                        cur_sev = "info"
                    else:
                        # 三级及以下标题，保留文件上下文
                        logger.debug(f"Found subsection heading at line {line_num}: {heading}")
                        
                        # 如果当前有文件上下文，尝试从标题中解析行号范围
                        # 例如: "问题标题 L123-456" 或 "变量未初始化问题 L100-120"
                        if cur_file:
                            title_parsed, a, b = _try_parse_title_range_line(heading)
                            if a > 0:
                                cur_title = title_parsed if title_parsed else heading
                                cur_start = a
                                cur_end = b if b > 0 else a
                                logger.debug(f"Parsed line range from subsection heading: {cur_start}-{cur_end}, title: {cur_title}")
                            else:
                                cur_title = heading
                        else:
                            cur_title = heading
                        # 保留当前mode，不要重置
                    continue

            # 尝试解析位置信息
            fp, a, b = "", 0, 0
            if (
                re.search(r"(?:文件|file|path)\s*[:：]", line, flags=re.IGNORECASE)
                or re.search(r"\.[A-Za-z0-9]{1,6}(?:\s|$)", line)
            ):
                fp, a, b = _try_parse_location_line(line)
            if fp:
                logger.debug(f"Found location info at line {line_num}: {fp}, lines {a}-{b}")
                # 更新当前文件上下文
                cur_file = fp
                if a > 0:
                    cur_start, cur_end = a, b
                # 重置mode，等待后续的模式切换指令
                mode = None
                continue

            # 解析严重性
            sev = _try_parse_severity_line(line)
            if sev:
                logger.debug(f"Updated severity at line {line_num}: {sev}")
                cur_sev = sev
                continue

            # 解析模式：问题或建议，支持有#前缀和没有#前缀的情况
            # 检查是否是模式标题行，如："问题:" 或 "建议:" 或 "**问题**" 等
            # 需要兼容多种 LLM 输出格式变体
            logger.debug(f"Line {line_num}: Checking mode switch for line: '{line}'")
            
            # 预处理：移除 markdown 格式标记
            clean_line = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)  # 移除 **...**
            clean_line = re.sub(r'\*([^*]+)\*', r'\1', clean_line)  # 移除 *...*
            clean_line = re.sub(r'__([^_]+)__', r'\1', clean_line)  # 移除 __...__
            clean_line = re.sub(r'`([^`]+)`', r'\1', clean_line)  # 移除 `...`
            clean_line = clean_line.strip()

            inferred_container_mode = _container_mode_of_text(clean_line)
            if inferred_container_mode:
                mode = inferred_container_mode
                continue

            inline_mode_item_match = re.match(
                r"^(?:[-*+•‣⁃]|\d+[.。)）]|\([1-9]\d*\))?\s*"
                r"(?P<kw>问题|problems?|issues?|缺陷|bugs?|错误|errors?|"
                r"建议|recommendations?|suggestions?|fixes?|changes?|优化|改进|解决方案?|修复)"
                r"(?:\s*(?:描述|说明|列表|分析|方案|措施))?\s*[:：]\s*(?P<rest>.+?)\s*$",
                clean_line,
                flags=re.IGNORECASE,
            )
            if inline_mode_item_match:
                kw = str(inline_mode_item_match.group("kw") or "").lower()
                rest = str(inline_mode_item_match.group("rest") or "").strip()
                if kw in {"问题", "problem", "problems", "issue", "issues", "缺陷", "bug", "bugs", "错误", "error", "errors"}:
                    mode = "problem"
                else:
                    mode = "suggestion"

                if cur_file and rest:
                    msg = rest
                    item_start_line = cur_start
                    item_end_line = cur_end if cur_end > 0 else cur_start

                    line_match = re.search(
                        r"^(?:行|line)\s*(\d+)(?:[-~—–]\s*(\d+))?\s*[:：]\s*",
                        msg,
                        re.IGNORECASE,
                    )
                    if not line_match:
                        line_match = re.search(
                            r"^(?:L|l)\s*(\d+)(?:[-~—–]\s*(\d+))?\s*[:：]?\s*",
                            msg,
                        )
                    if not line_match:
                        line_match = re.search(
                            r"^[\[\(]\s*(\d+)(?:[-~—–]\s*(\d+))?\s*[\]\)]\s*[:：]?\s*",
                            msg,
                        )

                    if line_match:
                        try:
                            item_start_line = int(line_match.group(1))
                            item_end_line = int(line_match.group(2)) if line_match.group(2) else item_start_line
                            if item_end_line < item_start_line:
                                item_start_line, item_end_line = item_end_line, item_start_line
                            msg = msg[line_match.end():].strip()
                        except Exception:
                            pass

                    msg = str(msg or "").strip()
                    inferred_container_mode = _container_mode_of_text(msg)
                    if inferred_container_mode:
                        mode = inferred_container_mode
                        continue
                    if msg and not _is_invalid_message_content(msg):
                        prefix = "问题" if mode == "problem" else "建议"
                        inline_item: Dict[str, Any] = {
                            "file": cur_file,
                            "severity": cur_sev,
                            "line": item_start_line,
                            "start_line": item_start_line,
                            "end_line": item_end_line,
                            "message": f"{prefix}: {msg}",
                            "source": "llm",
                        }
                        if cur_title and cur_title != "(无)":
                            inline_item["title"] = cur_title
                        out.append(inline_item)
                        logger.debug(
                            f"Added {mode} item (inline) at line {line_num}: {cur_file}:{item_start_line}-{item_end_line} - {msg[:50]}..."
                        )
                continue
            
            # 增强的模式标题匹配：允许更多格式变体
            # 例如：问题、问题:、问题描述:、问题 (2个)、**问题**、Issues: 等
            # 不匹配：行123: 这是一个问题、变量存在问题 等
            problem_mode_match = re.match(
                r"^(?:[-*+•‣⁃]|\d+[.。)）]|\([1-9]\d*\))?\s*"  # 可选列表标记
                r"(?:问题|problems?|issues?|缺陷|bugs?|错误|errors?)"  # 关键词
                r"(?:\s*(?:描述|说明|列表|分析))?"  # 可选后缀
                r"\s*(?:\([^)]*\))?"  # 可选括号说明（如"(2个)"）
                r"\s*[:：]?\s*$",  # 可选冒号，行尾
                clean_line, flags=re.IGNORECASE
            )
            suggestion_mode_match = re.match(
                r"^(?:[-*+•‣⁃]|\d+[.。)）]|\([1-9]\d*\))?\s*"  # 可选列表标记
                r"(?:建议|recommendations?|suggestions?|fixes?|changes?|优化|改进|解决方案?|修复)"  # 关键词
                r"(?:\s*(?:描述|说明|列表|方案|措施))?"  # 可选后缀
                r"\s*(?:\([^)]*\))?"  # 可选括号说明
                r"\s*[:：]?\s*$",  # 可选冒号，行尾
                clean_line, flags=re.IGNORECASE
            )
            
            if problem_mode_match:
                logger.debug(f"Switched to problem mode at line {line_num}")
                mode = "problem"
                continue
            if suggestion_mode_match:
                logger.debug(f"Switched to suggestion mode at line {line_num}")
                mode = "suggestion"
                continue
            
            logger.debug(f"Line {line_num}: No mode switch found")
            
            # 如果已经有文件信息，尝试解析行号范围
            if cur_file:
                # 处理类似 "L123-456" 或 "行号:123-456" 的行
                if re.match(
                    r"^(?:L|l|行|line)\s*\d+(?:\s*[-~—–]\s*\d+)?\s*[:：]\s*\S+",
                    line,
                    flags=re.IGNORECASE,
                ):
                    pass
                elif re.match(r"^(?:L|l|行|行号|lines?|range)\s*", line, flags=re.IGNORECASE):
                    a2, b2 = _parse_line_range_text(line)
                    if a2 > 0:
                        logger.debug(f"Updated line range at line {line_num}: {a2}-{b2}")
                        cur_start, cur_end = a2, b2
                    continue

                # 只有当不是列表项时，才处理标题行中的行号范围
                # 这样列表项会被传递到后面的列表项解析逻辑中
                if not re.match(r"^(?:[-*+•‣⁃]|\d+[.。)）]|\([1-9]\d*\))\s+", line):
                    if re.match(
                        r"^(?:L|l|行|line)\s*\d+(?:\s*[-~—–]\s*\d+)?\s*[:：]\s*\S+",
                        line,
                        flags=re.IGNORECASE,
                    ):
                        pass
                    else:
                        title2, a2, b2 = _try_parse_title_range_line(line)
                        if a2 > 0:
                            logger.debug(f"Found title with line range at line {line_num}: {title2}, {a2}-{b2}")
                            cur_start, cur_end = a2, b2
                            if title2:
                                cur_title = title2
                            cur_sev = "info"
                            continue

                if mode in ("problem", "suggestion") and not re.match(
                    r"^(?:[-*+•‣⁃]|\d+[.。)）]|\([1-9]\d*\))\s+",
                    line,
                ):
                    msg = line
                    item_start_line = cur_start
                    item_end_line = cur_end if cur_end > 0 else cur_start

                    line_match = re.search(
                        r"^(?:行|line)\s*(\d+)(?:[-~—–]\s*(\d+))?\s*[:：]\s*",
                        msg,
                        re.IGNORECASE,
                    )
                    if not line_match:
                        line_match = re.search(
                            r"^(?:L|l)\s*(\d+)(?:[-~—–]\s*(\d+))?\s*[:：]?\s*",
                            msg,
                        )
                    if not line_match:
                        line_match = re.search(
                            r"^[\[\(]\s*(\d+)(?:[-~—–]\s*(\d+))?\s*[\]\)]\s*[:：]?\s*",
                            msg,
                        )

                    if line_match:
                        try:
                            item_start_line = int(line_match.group(1))
                            item_end_line = int(line_match.group(2)) if line_match.group(2) else item_start_line
                            if item_end_line < item_start_line:
                                item_start_line, item_end_line = item_end_line, item_start_line
                            msg = msg[line_match.end():].strip()
                        except Exception:
                            pass

                    msg = str(msg or "").strip()
                    if not msg or _is_invalid_message_content(msg):
                        continue
                    inferred_container_mode = _container_mode_of_text(msg)
                    if inferred_container_mode:
                        mode = inferred_container_mode
                        continue

                    prefix = "问题" if mode == "problem" else "建议"
                    non_bullet_item: Dict[str, Any] = {
                        "file": cur_file,
                        "severity": cur_sev,
                        "line": item_start_line,
                        "start_line": item_start_line,
                        "end_line": item_end_line,
                        "message": f"{prefix}: {msg}",
                        "source": "llm",
                    }
                    if cur_title and cur_title != "(无)":
                        non_bullet_item["title"] = cur_title
                    out.append(non_bullet_item)
                    logger.debug(
                        f"Added {mode} item (non-bullet) at line {line_num}: {cur_file}:{item_start_line}-{item_end_line} - {msg[:50]}..."
                    )
                    continue
            
            # 检查是否是有#前缀的模式标题，如："### 问题" 或 "#### 建议"
            # 注意：这个逻辑已经在标题处理部分实现了，这里不需要重复处理

            # 解析列表项，支持各种列表标记
            m_bullet = re.match(r"^(?:[-*+•‣⁃]|\d+[.。)）]|\([1-9]\d*\))\s+(.*)$", line)
            if not m_bullet:
                continue

            # 确保有必要的上下文信息
            if not cur_file:
                logger.debug(f"Skipping list item at line {line_num}: no file context")
                continue
            
            # 提取列表项内容
            bullet_content = str(m_bullet.group(1) or "").strip()
            if not bullet_content or _is_invalid_message_content(bullet_content):
                logger.debug(f"Skipping empty list item at line {line_num}")
                continue
            
            inferred_container_mode = _container_mode_of_text(bullet_content)
            if inferred_container_mode:
                mode = inferred_container_mode
                logger.debug(f"Line {line_num}: Container heading detected, switched mode={mode}")
                continue
            
            # 智能推断 mode：如果没有明确的 mode，尝试从列表项内容推断
            effective_mode = mode
            if mode not in ("problem", "suggestion"):
                # 检查内容是否像建议（包含建议性动词或短语）
                suggestion_indicators = re.search(
                    r"(?:建议|应该|可以|需要|考虑|推荐|使用|添加|修改|更改|替换|改为|改成|优化|重构|提取|封装|抽象|统一|规范)",
                    bullet_content
                )
                problem_indicators = re.search(
                    r"(?:错误|问题|缺陷|漏洞|风险|警告|未|没有|缺少|遗漏|可能|导致|存在|不一致|不正确|不安全)",
                    bullet_content
                )
                
                if suggestion_indicators and not problem_indicators:
                    effective_mode = "suggestion"
                    logger.debug(f"Line {line_num}: Inferred mode=suggestion from content")
                elif problem_indicators:
                    effective_mode = "problem"
                    logger.debug(f"Line {line_num}: Inferred mode=problem from content")
                else:
                    # 如果有行号上下文，默认作为问题处理（保守策略）
                    if cur_start > 0:
                        effective_mode = "problem"
                        logger.debug(f"Line {line_num}: Default mode=problem (has line context)")
                    else:
                        logger.debug(f"Skipping list item at line {line_num}: cannot infer mode")
                        continue
            
            # 尝试从列表项内容中提取行号，支持多种格式
            # 如："行123: 变量未初始化" 或 "L123-456: 问题描述" 或 "[123] 内容"
            item_start_line = cur_start
            item_end_line = cur_end if cur_end > 0 else cur_start
            msg = bullet_content
            
            # 格式1: "行123:" 或 "line 123:"
            line_match = re.search(r"^(?:行|line)\s*(\d+)(?:[-~—–]\s*(\d+))?\s*[:：]\s*", bullet_content, re.IGNORECASE)
            # 格式2: "L123-456:" 或 "L123:"
            if not line_match:
                line_match = re.search(r"^(?:L|l)\s*(\d+)(?:[-~—–]\s*(\d+))?\s*[:：]?\s*", bullet_content)
            # 格式3: "[123]" 或 "(123)"
            if not line_match:
                line_match = re.search(r"^[\[\(]\s*(\d+)(?:[-~—–]\s*(\d+))?\s*[\]\)]\s*[:：]?\s*", bullet_content)
            
            if line_match:
                # 从列表项中提取行号
                try:
                    item_start_line = int(line_match.group(1))
                    item_end_line = int(line_match.group(2)) if line_match.group(2) else item_start_line
                    if item_end_line < item_start_line:
                        item_start_line, item_end_line = item_end_line, item_start_line
                    logger.debug(f"Line {line_num}: Extracted line range from item: {item_start_line}-{item_end_line}")
                    # 提取消息内容，去除行号前缀
                    msg = bullet_content[line_match.end():].strip()
                except Exception as e:
                    logger.debug(f"Line {line_num}: Error parsing line numbers from item: {e}")
            elif cur_start <= 0:
                # 如果没有提取到行号，且当前上下文没有行号
                # 仍然收集该项，使用0作为行号，在映射阶段通过兜底策略处理
                logger.debug(f"Line {line_num}: No line number found, collecting with line=0")
                item_start_line = 0
                item_end_line = 0

            if not msg or _is_invalid_message_content(msg):
                logger.debug(f"Line {line_num}: No message content or invalid content after removing line numbers, skipping item")
                continue
            
            inferred_container_mode = _container_mode_of_text(msg)
            if inferred_container_mode:
                mode = inferred_container_mode
                logger.debug(f"Line {line_num}: Container heading detected after stripping line prefix, switched mode={mode}")
                continue

            prefix = "问题" if effective_mode == "problem" else "建议"
            bullet_item: Dict[str, Any] = {
                "file": cur_file,
                "severity": cur_sev,
                "line": item_start_line,
                "start_line": item_start_line,
                "end_line": item_end_line,
                "message": f"{prefix}: {msg}",
                "source": "llm",
            }
            if cur_title and cur_title != "(无)":
                bullet_item["title"] = cur_title
            out.append(bullet_item)
            logger.debug(f"Added {effective_mode} item at line {line_num}: {cur_file}:{item_start_line}-{item_end_line} - {msg[:50]}...")
        except Exception as e:
            logger.error(f"Error parsing line {line_num}: {e}")
            logger.error(f"Line content: {raw}")
            # 继续处理下一行，不中断整个解析过程
            continue
    
    logger.debug(f"Finished parsing review report, found {len(out)} issues/suggestions")
    return out


def parse_review_report_blocks(text: str) -> List[Dict[str, Any]]:
    blocks: Dict[Tuple[str, str, int, int, str], Dict[str, Any]] = {}
    items = parse_review_report_issues(text)

    for it in items:
        fp = _normalize_file_key(it.get("file") or it.get("file_path") or "")
        if not fp:
            continue
        title = str(it.get("title") or "").strip()
        try:
            start_i = int(it.get("start_line") or it.get("line") or 0)
        except Exception:
            start_i = 0
        try:
            end_i = int(it.get("end_line") or start_i)
        except Exception:
            end_i = start_i
        if end_i < start_i:
            start_i, end_i = end_i, start_i
        sev = _normalize_suggestion_severity(it.get("severity") or "info")

        key = (fp, title, start_i, end_i, sev)
        blk = blocks.get(key)
        if not blk:
            blk = {
                "file": fp,
                "title": title,
                "start_line": start_i,
                "end_line": end_i,
                "severity": sev,
                "problems": [],
                "suggestions": [],
                "source": "llm",
            }
            blocks[key] = blk

        msg = str(it.get("message") or "").strip()
        if msg.lower().startswith("问题:") or msg.startswith("问题："):
            blk["problems"].append(msg.split(":", 1)[-1].split("：", 1)[-1].strip())
        elif msg.lower().startswith("建议:") or msg.startswith("建议："):
            blk["suggestions"].append(msg.split(":", 1)[-1].split("：", 1)[-1].strip())
        else:
            blk["problems"].append(msg)

    out = list(blocks.values())
    out.sort(key=lambda x: (str(x.get("file") or ""), int(x.get("start_line") or 0), str(x.get("title") or "")))
    return out


def build_linked_unit_llm_suggestions(
    units: List[Dict[str, Any]],
    suggestions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    units_by_file: Dict[str, List[Tuple[str, int, int, Dict[str, Any]]]] = {}
    file_key_to_path: Dict[str, str] = {}
    
    logger.debug(f"Starting to build linked unit LLM suggestions with {len(units or [])} units and {len(suggestions or [])} suggestions")
    
    # 预处理units，按文件路径分组，并存储完整的unit信息
    for u in units or []:
        try:
            unit_id = u.get("unit_id") or u.get("id")
            if not unit_id:
                continue
            fp_norm = _normalize_file_key(u.get("file_path") or "")
            if not fp_norm:
                continue
            fp_key = fp_norm.lower()
            if fp_key not in file_key_to_path:
                file_key_to_path[fp_key] = fp_norm
            hr = u.get("hunk_range") or {}
            
            # 处理new_start和new_lines，增强容错性
            try:
                new_start = int(hr.get("new_start") or hr.get("start") or 0)
            except Exception:
                new_start = 0
            
            try:
                new_lines = int(hr.get("new_lines") or hr.get("lines") or 0)
            except Exception:
                new_lines = 0
            
            if new_start <= 0:
                # 尝试从old_start获取信息，作为 fallback
                try:
                    new_start = int(hr.get("old_start") or 0)
                except Exception:
                    continue
            
            if new_start <= 0:
                continue
            
            # 计算结束行号
            new_end = new_start + max(new_lines, 1) - 1
            units_by_file.setdefault(fp_key, []).append((str(unit_id), new_start, new_end, u))
            logger.debug(f"Added unit {unit_id} for file {fp_norm}, lines {new_start}-{new_end}")
        except Exception as e:
            logger.error(f"Error processing unit: {e}")
            continue

    # 按行号排序，确保处理顺序正确
    for fp, ranges in units_by_file.items():
        ranges.sort(key=lambda x: x[1])
        logger.debug(f"Sorted {len(ranges)} units for file {fp}")

    unit_suggestions: Dict[str, List[Dict[str, Any]]] = {}
    mapped_count = 0
    unmapped_count = 0
    unmapped_suggestions: List[Dict[str, Any]] = []  # 收集未映射的建议

    for suggestion_num, it in enumerate(suggestions or [], 1):
        try:
            # 获取并标准化文件路径
            raw_fp = it.get("file") or it.get("file_path") or ""
            fp_norm = _normalize_file_key(raw_fp)
            if not fp_norm:
                fp_norm = _extract_file_path_from_text(it.get("message") or "")
            if not fp_norm:
                logger.debug(f"Suggestion {suggestion_num}: No file path, unmapped")
                unmapped_count += 1
                unmapped_suggestions.append({**it, "unmapped_reason": "no_file_path"})
                continue
            resolved_fp, file_units = _resolve_units_for_file(fp_norm, units_by_file, file_key_to_path)

            # 获取行号范围
            start = _issue_line(it) or it.get("start_line")
            try:
                start_i = int(start) if start is not None else 0
            except Exception:
                start_i = 0
                
            end = it.get("end_line") or it.get("end") or start_i
            try:
                end_i = int(end) if end is not None else start_i
            except Exception:
                end_i = start_i
            
            # 确保开始行号小于等于结束行号
            if end_i < start_i:
                start_i, end_i = end_i, start_i
            
            # 处理无效的行号
            if start_i <= 0:
                # 尝试从消息中提取行号
                try:
                    msg = str(it.get("message") or "")
                    line_match = re.search(r"(?:行|line)\s*(\d+)", msg, flags=re.IGNORECASE)
                    if line_match:
                        start_i = int(line_match.group(1))
                        end_i = start_i
                except Exception:
                    pass
            
            # 标记是否没有有效行号（用于后续兜底处理）
            no_valid_line = (start_i <= 0)
            
            # 查找匹配的unit
            matched_any = False
            matched_units = []
            
            if not file_units:
                logger.debug(f"Suggestion {suggestion_num}: No file match for {fp_norm}, unmapped")
                unmapped_count += 1
                unmapped_suggestions.append({**it, "unmapped_reason": "no_file_match", "attempted_file": fp_norm})
                continue
            
            # 计算匹配分数，找到最佳匹配
            for unit_id, u_start, u_end, unit_info in file_units:
                # 计算匹配分数
                score = 0
                
                # 如果没有有效行号，给予基础分数，让后续兜底策略能匹配
                if no_valid_line:
                    score = 1  # 基础分数，用于文件匹配
                else:
                    # 计算重叠范围
                    overlap_start = max(start_i, u_start)
                    overlap_end = min(end_i, u_end)
                    overlap_length = max(0, overlap_end - overlap_start + 1)
                    
                    # 基础重叠分数
                    if overlap_length > 0:
                        score += overlap_length * 10
                    
                    # 完全包含分数
                    if start_i >= u_start and end_i <= u_end:
                        score += 50
                    
                    # 行号接近分数，扩大接近范围到50行
                    # 这样即使行号稍微超出unit范围，也能获得匹配分数
                    distance = min(abs(start_i - u_start), abs(start_i - u_end), abs(end_i - u_start), abs(end_i - u_end))
                    if distance <= 50:
                        score += max(1, (50 - distance))  # 确保有正分数
                
                # 记录匹配信息
                matched_units.append((score, unit_id, u_start, u_end))
            
            # 按分数排序，选择最佳匹配
            matched_units.sort(key=lambda x: x[0], reverse=True)
            
            # 处理匹配结果
            for score, unit_id, u_start, u_end in matched_units:
                # 只处理有分数的匹配
                if score <= 0:
                    continue
                
                # 计算最终的重叠范围
                if no_valid_line:
                    # 没有有效行号，使用 unit 的行号
                    overlap_start = u_start
                    overlap_end = u_end
                    logger.debug(f"Suggestion {suggestion_num}: No valid line, using unit line numbers {u_start}-{u_end}")
                else:
                    overlap_start = max(start_i, u_start)
                    overlap_end = min(end_i, u_end)
                    
                    # 如果没有实际重叠，但分数较高（行号接近），则使用建议的行号
                    if overlap_start > overlap_end:
                        # 行号接近的情况，使用建议的行号
                        logger.debug(f"Suggestion {suggestion_num}: No exact overlap, using suggested line numbers {start_i}-{end_i}")
                        overlap_start = start_i
                        overlap_end = end_i
                
                # 创建建议副本并更新行号信息
                it_copy = dict(it)
                if resolved_fp and resolved_fp != fp_norm:
                    it_copy.setdefault("origin_file", fp_norm)
                    it_copy["file"] = resolved_fp
                it_copy["origin_start_line"] = start_i
                it_copy["origin_end_line"] = end_i
                it_copy["start_line"] = overlap_start
                it_copy["end_line"] = overlap_end
                it_copy["line"] = overlap_start
                
                # 存储到对应的unit
                unit_suggestions.setdefault(unit_id, []).append(it_copy)
                mapped_count += 1
                matched_any = True
                
                logger.debug(f"Suggestion {suggestion_num}: Mapped to unit {unit_id} with score {score}, lines {overlap_start}-{overlap_end}")
                
                # 只使用最佳匹配
                break
            
            # 兜底策略：如果有文件匹配但没有找到行号匹配，映射到该文件的第一个 unit
            if not matched_any and file_units:
                first_unit = file_units[0]
                unit_id, u_start, u_end, unit_info = first_unit
                
                it_copy = dict(it)
                if resolved_fp and resolved_fp != fp_norm:
                    it_copy.setdefault("origin_file", fp_norm)
                    it_copy["file"] = resolved_fp
                it_copy["origin_start_line"] = start_i
                it_copy["origin_end_line"] = end_i
                it_copy["start_line"] = start_i if start_i > 0 else u_start
                it_copy["end_line"] = end_i if end_i > 0 else u_end
                it_copy["line"] = it_copy["start_line"]
                it_copy["fallback_mapped"] = True  # 标记为兜底映射
                
                unit_suggestions.setdefault(unit_id, []).append(it_copy)
                mapped_count += 1
                matched_any = True
                logger.debug(f"Suggestion {suggestion_num}: Fallback mapped to first unit {unit_id} of file")
        
        except Exception as e:
            logger.error(f"Error processing suggestion {suggestion_num}: {e}")
            unmapped_count += 1
            unmapped_suggestions.append({**it, "unmapped_reason": "exception", "error": str(e)})
            continue
        
        if not matched_any:
            logger.debug(f"Suggestion {suggestion_num}: No matching unit found, unmapped")
            unmapped_count += 1
            unmapped_suggestions.append({**it, "unmapped_reason": "no_unit_match", "file": fp_norm, "line": start_i})
            continue

    def _sort_key(x: Dict[str, Any]) -> Tuple[int, int, str]:
        sev = _severity_rank(str(x.get("severity") or ""))
        ln = _issue_line(x) or x.get("start_line") or 0
        try:
            ln_i = int(ln)
        except Exception:
            ln_i = 0
        msg = str(x.get("message") or "")
        return (sev, ln_i, msg)

    # 排序建议项
    for unit_id, items in unit_suggestions.items():
        items.sort(key=_sort_key)
        logger.debug(f"Sorted {len(items)} suggestions for unit {unit_id}")

    logger.debug(f"Finished building linked unit LLM suggestions: {mapped_count} mapped, {unmapped_count} unmapped")
    
    return {
        "unit_llm_suggestions": unit_suggestions,
        "llm_suggestions_total": len(suggestions or []),
        "llm_mapped_count": mapped_count,
        "llm_unmapped_count": unmapped_count,
        "llm_unmapped_suggestions": unmapped_suggestions,  # 未映射的建议列表
    }


def _build_linked_unit_issues(
    units: List[Dict[str, Any]],
    issues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    units_by_file: Dict[str, List[Tuple[str, int, int, Dict[str, Any]]]] = {}
    file_key_to_path: Dict[str, str] = {}
    
    # 预处理units，按文件路径分组，并存储完整的unit信息
    for u in units or []:
        unit_id = u.get("unit_id") or u.get("id")
        if not unit_id:
            continue
        fp_norm = _normalize_file_key(u.get("file_path") or "")
        if not fp_norm:
            continue
        fp_key = fp_norm.lower()
        if fp_key not in file_key_to_path:
            file_key_to_path[fp_key] = fp_norm
        hr = u.get("hunk_range") or {}
        
        # 处理new_start和new_lines，增强容错性
        try:
            new_start = int(hr.get("new_start") or hr.get("start") or 0)
        except Exception:
            new_start = 0
        
        try:
            new_lines = int(hr.get("new_lines") or hr.get("lines") or 0)
        except Exception:
            new_lines = 0
        
        if new_start <= 0:
            # 尝试从old_start获取信息，作为 fallback
            try:
                new_start = int(hr.get("old_start") or 0)
            except Exception:
                continue
            
        if new_start <= 0:
            continue
            
        # 计算结束行号
        new_end = new_start + max(new_lines, 1) - 1
        units_by_file.setdefault(fp_key, []).append((str(unit_id), new_start, new_end, u))

    # 按行号排序，确保处理顺序正确
    for ranges in units_by_file.values():
        ranges.sort(key=lambda x: x[1])

    unit_issues: Dict[str, List[Dict[str, Any]]] = {}
    mapped_count = 0
    unmapped_count = 0
    
    for it in issues or []:
        # 获取并标准化文件路径
        raw_fp = it.get("file") or it.get("file_path") or ""
        fp_norm = _normalize_file_key(raw_fp)
        if not fp_norm:
            fp_norm = _extract_file_path_from_text(it.get("message") or "")
        if not fp_norm:
            unmapped_count += 1
            continue
        
        # 获取行号，增强容错性
        line = _issue_line(it)
        if not line:
            # 尝试从其他字段获取行号
            try:
                line = int(it.get("line_number") or it.get("position") or 0)
            except Exception:
                unmapped_count += 1
                continue
        
        if line <= 0:
            unmapped_count += 1
            continue
        
        # 查找匹配的unit
        matched = False
        matched_units = []
        
        resolved_fp, file_units = _resolve_units_for_file(fp_norm, units_by_file, file_key_to_path)
        if not file_units:
            unmapped_count += 1
            continue
        
        # 计算匹配分数，找到最佳匹配
        for unit_id, u_start, u_end, unit_info in file_units:
            # 计算匹配分数
            score = 0
            
            # 精确匹配分数
            if u_start <= line <= u_end:
                score += 100
                
                # 完全包含在unit的前半部分，分数更高
                unit_mid = u_start + (u_end - u_start) // 2
                if line <= unit_mid:
                    score += 20
            
            # 行号接近分数
            elif abs(line - u_start) <= 3:
                score += (3 - abs(line - u_start)) * 10
            elif abs(line - u_end) <= 3:
                score += (3 - abs(line - u_end)) * 10
            
            # 记录匹配信息
            matched_units.append((score, unit_id))
        
        # 按分数排序，选择最佳匹配
        matched_units.sort(key=lambda x: x[0], reverse=True)
        
        # 处理匹配结果
        for score, unit_id in matched_units:
            # 只处理有分数的匹配
            if score <= 0:
                continue
            
            # 存储到对应的unit
            it_copy = dict(it)
            if resolved_fp and resolved_fp != fp_norm:
                it_copy.setdefault("origin_file", fp_norm)
                it_copy["file"] = resolved_fp
            unit_issues.setdefault(unit_id, []).append(it_copy)
            mapped_count += 1
            matched = True
            
            # 只使用最佳匹配
            break
        
        if not matched:
            unmapped_count += 1

    def _sort_key(x: Dict[str, Any]) -> Tuple[int, int, int, str]:
        sev = _severity_rank(str(x.get("severity") or ""))
        ln = _issue_line(x) or 0
        try:
            col = int(x.get("column") or x.get("col") or 0)
        except Exception:
            col = 0
        rule = str(x.get("rule_id") or x.get("rule") or x.get("code") or "")
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
    
    # 尝试从会话数据中获取static_scan_linked
    if not data:
        from Agent.core.api.session import SessionAPI
        session_data = SessionAPI.get_session(session_id)
        if session_data:
            if "static_scan_linked" in session_data and session_data["static_scan_linked"]:
                # 从会话数据中获取static_scan_linked
                data = session_data["static_scan_linked"]
                # 缓存到内存中
                with _STATIC_SCAN_LINKED_CACHE_LOCK:
                    _STATIC_SCAN_LINKED_CACHE[session_id] = data
            else:
                # 对于没有static_scan_linked数据的历史会话，尝试重新生成
                logger.debug(f"Session {session_id} has no static_scan_linked data, trying to regenerate")
                
                # 获取会话的diff_units和审查报告
                diff_units = session_data.get("diff_units", [])
                messages = session_data.get("messages", [])
                
                # 查找最后一个助手消息，包含审查报告
                review_report = ""
                for msg in reversed(messages):
                    if msg.get("role") == "assistant" and msg.get("content"):
                        review_report = msg["content"]
                        break
                
                if review_report and diff_units:
                    # 解析审查报告，生成LLM建议
                    llm_suggestions = parse_review_report_issues(review_report)
                    if llm_suggestions:
                        # 重新构建映射
                        linked_issues = _build_linked_unit_issues(units=diff_units, issues=[])
                        linked_suggestions = build_linked_unit_llm_suggestions(units=diff_units, suggestions=llm_suggestions)
                        
                        # 合并结果
                        data = {
                            "session_id": session_id,
                            "generated_at": time.time(),
                            "diff_units": diff_units,
                            **linked_issues,
                            **linked_suggestions
                        }
                        
                        # 缓存结果
                        with _STATIC_SCAN_LINKED_CACHE_LOCK:
                            _STATIC_SCAN_LINKED_CACHE[session_id] = data
                        
                        logger.debug(f"Successfully regenerated static_scan_linked data for session {session_id}")
                
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
    commit_sha: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], float]:
    """在线程中同步执行单个文件的扫描。
    
    Args:
        file_path: 文件路径
        content: 文件内容（可选）
        scanners: 扫描器列表
        project_root: 项目根目录
        commit_sha: 如果指定，从此 commit 读取文件内容（用于历史提交模式）
        
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
            
            # 如果指定了 commit_sha，优先从 Git 历史读取
            if commit_sha:
                try:
                    import subprocess
                    result = subprocess.run(
                        ["git", "show", f"{commit_sha}:{file_path}"],
                        cwd=project_root,
                        capture_output=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        # 尝试多种编码
                        try:
                            content = result.stdout.decode("utf-8")
                        except UnicodeDecodeError:
                            try:
                                content = result.stdout.decode("gbk")
                            except UnicodeDecodeError:
                                content = result.stdout.decode("utf-8", errors="replace")
                        logger.debug(f"Read file {file_path} from git commit {commit_sha[:7]}")
                    else:
                        logger.debug(f"Failed to read {file_path} from git commit {commit_sha[:7]}: {result.stderr.decode('utf-8', errors='replace')}")
                except Exception as e:
                    logger.debug(f"Git read failed for {file_path}: {e}")
            
            # 如果从 Git 读取失败，尝试从文件系统读取
            if content is None:
                try:
                    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except Exception as e:
                    logger.debug(f"Failed to read file {full_path}: {e}")
                    content = None
        
        issues, stats = executor.execute(file_path, content)
        file_issues = issues
        
    except Exception as e:
            logger.warning(f"Scanner execution failed for {Path(file_path).name}: {e}")
    
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
    commit_sha: Optional[str] = None,
) -> StaticScanResult:
    """执行静态分析旁路扫描。
    
    Args:
        files: 需要扫描的文件列表（已去重）
        units: 审查单元列表，用于获取 tags 等元信息
        callback: 事件回调函数，用于向前端推送进度
        project_root: 项目根目录
        session_id: 会话 ID
        commit_sha: 如果指定，从此 commit 读取文件内容（用于历史提交模式）
        
    Returns:
        StaticScanResult: 扫描结果
    """
    result = StaticScanResult()
    start_time = time.perf_counter()
    
    # 标记扫描开始，工具调用时使用此信号等待
    if session_id:
        mark_scan_started(session_id)
    
    if not files:
        logger.debug("No files to scan")
        if session_id:
            mark_scan_complete(session_id)  # 无文件也需标记完成
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
                commit_sha,  # 历史提交模式时从 Git 读取
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
    
    # 标记扫描完成，通知等待中的工具
    if session_id:
        mark_scan_complete(session_id)
    
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
