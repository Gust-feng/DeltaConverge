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
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from pathlib import Path

from Agent.core.logging import get_logger
from Agent.DIFF.rule.scanner_registry import ScannerRegistry
from Agent.DIFF.rule.scanner_performance import ScannerExecutor, AvailabilityCache

logger = get_logger(__name__)

# 类型别名
StreamCallback = Callable[[Dict[str, Any]], None]

# 全局线程池，用于执行阻塞的扫描操作
_scan_executor: Optional[ThreadPoolExecutor] = None


def _get_scan_executor() -> ThreadPoolExecutor:
    """获取或创建扫描线程池。"""
    global _scan_executor
    if _scan_executor is None:
        # 使用较少的线程数，避免资源竞争
        _scan_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="static_scan_")
    return _scan_executor


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
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".java": "java",
        ".go": "go",
        ".rb": "ruby",
        ".php": "php",
        ".rs": "rust",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
    }
    ext = Path(file_path).suffix.lower()
    return ext_map.get(ext)


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
    
    result.files_total = len(sorted_files)
    
    # 发送扫描开始事件
    if callback:
        try:
            callback({
                "type": "static_scan_start",
                "files_total": result.files_total,
                "timestamp": time.time(),
            })
        except Exception as e:
            logger.warning(f"Failed to emit static_scan_start event: {e}")
    
    # 按语言分组文件
    files_by_lang: Dict[str, List[str]] = {}
    for fp in sorted_files:
        lang = _detect_language(fp)
        if lang:
            if lang not in files_by_lang:
                files_by_lang[lang] = []
            files_by_lang[lang].append(fp)
    
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
                        "progress": result.files_scanned / result.files_total,
                        "timestamp": time.time(),
                    })
                except Exception:
                    pass
    
    result.duration_ms = (time.perf_counter() - start_time) * 1000
    
    # 发送扫描完成事件
    if callback:
        try:
            callback({
                "type": "static_scan_complete",
                "files_scanned": result.files_scanned,
                "files_total": result.files_total,
                "total_issues": result.total_issues,
                "error_count": result.error_count,
                "warning_count": result.warning_count,
                "info_count": result.info_count,
                "duration_ms": result.duration_ms,
                "scanners_used": result.scanners_used,
                "timestamp": time.time(),
            })
        except Exception as e:
            logger.warning(f"Failed to emit static_scan_complete event: {e}")
    
    logger.info(
        f"Static scan completed: {result.files_scanned}/{result.files_total} files, "
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
