"""扫描器性能优化模块。

本模块提供扫描器性能诊断、可用性缓存和执行策略管理功能。

Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3
"""

from __future__ import annotations

import logging
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from Agent.DIFF.rule.scanner_base import BaseScanner, ScannerIssue

logger = logging.getLogger(__name__)


# =============================================================================
# 性能统计数据结构
# =============================================================================

@dataclass
class ScannerPerformanceStats:
    """单个扫描器的性能统计。
    
    Attributes:
        scanner_name: 扫描器名称
        available: 是否可用
        availability_check_ms: 可用性检查耗时（毫秒）
        scan_duration_ms: 扫描耗时（毫秒），如果未执行则为 None
        issues_count: 发现的问题数量
        error: 错误信息，如果执行成功则为 None
        
    Requirements: 1.1, 1.2, 1.3
    """
    scanner_name: str
    available: bool = False
    availability_check_ms: float = 0.0
    scan_duration_ms: Optional[float] = None
    issues_count: int = 0
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式。"""
        return {
            "scanner_name": self.scanner_name,
            "available": self.available,
            "availability_check_ms": round(self.availability_check_ms, 2),
            "scan_duration_ms": round(self.scan_duration_ms, 2) if self.scan_duration_ms else None,
            "issues_count": self.issues_count,
            "error": self.error,
        }


@dataclass
class ScanExecutionStats:
    """扫描执行的整体统计。
    
    Attributes:
        total_duration_ms: 总耗时（毫秒）
        scanner_stats: 各扫描器的性能统计列表
        mode: 执行模式（sequential | parallel）
        scanners_executed: 成功执行的扫描器数量
        scanners_skipped: 跳过的扫描器数量
        scanners_failed: 失败的扫描器数量
        total_issues: 发现的问题总数
        
    Requirements: 1.4
    """
    total_duration_ms: float = 0.0
    scanner_stats: List[ScannerPerformanceStats] = field(default_factory=list)
    mode: str = "sequential"
    scanners_executed: int = 0
    scanners_skipped: int = 0
    scanners_failed: int = 0
    total_issues: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式。"""
        return {
            "total_duration_ms": round(self.total_duration_ms, 2),
            "mode": self.mode,
            "scanners_executed": self.scanners_executed,
            "scanners_skipped": self.scanners_skipped,
            "scanners_failed": self.scanners_failed,
            "total_issues": self.total_issues,
            "scanner_stats": [s.to_dict() for s in self.scanner_stats],
        }


# =============================================================================
# 性能日志记录器
# =============================================================================

class PerformanceLogger:
    """扫描器性能日志记录器。
    
    提供高精度计时和汇总日志功能，用于诊断扫描器性能瓶颈。
    
    Requirements: 1.1, 1.2, 1.3, 1.4
    """
    
    def __init__(self, logger_instance: Optional[logging.Logger] = None):
        """初始化性能日志记录器。
        
        Args:
            logger_instance: 日志记录器实例，如果为 None 则使用模块级 logger
        """
        self._logger = logger_instance or logger
        self._timings: Dict[str, float] = {}
        self._start_times: Dict[str, float] = {}
        self._lock = Lock()
    
    def start_timing(self, name: str) -> None:
        """开始计时。
        
        Args:
            name: 计时项名称
            
        Requirements: 1.1, 1.2, 1.3
        """
        with self._lock:
            self._start_times[name] = time.perf_counter()
    
    def end_timing(self, name: str) -> float:
        """结束计时并返回耗时。
        
        Args:
            name: 计时项名称
            
        Returns:
            耗时（毫秒），如果未找到开始时间则返回 0.0
            
        Requirements: 1.1, 1.2, 1.3
        """
        end_time = time.perf_counter()
        with self._lock:
            start_time = self._start_times.pop(name, None)
            if start_time is None:
                self._logger.warning(f"No start time found for timing '{name}'")
                return 0.0
            
            duration_ms = (end_time - start_time) * 1000
            self._timings[name] = duration_ms
            return duration_ms
    
    def get_timing(self, name: str) -> Optional[float]:
        """获取已记录的耗时。
        
        Args:
            name: 计时项名称
            
        Returns:
            耗时（毫秒），如果未找到则返回 None
        """
        with self._lock:
            return self._timings.get(name)
    
    def get_all_timings(self) -> Dict[str, float]:
        """获取所有已记录的耗时。
        
        Returns:
            计时项名称到耗时（毫秒）的映射
        """
        with self._lock:
            return dict(self._timings)
    
    def log_summary(self, stats: Optional[ScanExecutionStats] = None) -> Dict[str, Any]:
        """输出汇总日志并返回统计数据。
        
        Args:
            stats: 扫描执行统计，如果提供则使用该统计数据
            
        Returns:
            汇总统计数据字典
            
        Requirements: 1.4
        """
        with self._lock:
            timings = dict(self._timings)
        
        summary: Dict[str, Any] = {
            "timings": {k: round(v, 2) for k, v in timings.items()},
        }
        
        if stats:
            summary.update(stats.to_dict())
        
        # 计算各阶段耗时分布
        total = timings.get("total_scan", 0.0)
        if total > 0:
            distribution = {}
            for name, duration in timings.items():
                if name != "total_scan":
                    distribution[name] = round(duration / total * 100, 1)
            summary["distribution_percent"] = distribution
        
        # 输出日志
        self._logger.info(
            f"Scanner performance summary: "
            f"total={summary.get('total_duration_ms', timings.get('total_scan', 0)):.2f}ms, "
            f"executed={summary.get('scanners_executed', 'N/A')}, "
            f"skipped={summary.get('scanners_skipped', 'N/A')}, "
            f"failed={summary.get('scanners_failed', 'N/A')}, "
            f"issues={summary.get('total_issues', 'N/A')}"
        )
        
        # 输出详细的扫描器耗时
        if stats and stats.scanner_stats:
            for scanner_stat in stats.scanner_stats:
                if scanner_stat.scan_duration_ms is not None:
                    self._logger.debug(
                        f"  Scanner '{scanner_stat.scanner_name}': "
                        f"avail_check={scanner_stat.availability_check_ms:.2f}ms, "
                        f"scan={scanner_stat.scan_duration_ms:.2f}ms, "
                        f"issues={scanner_stat.issues_count}"
                    )
                elif scanner_stat.error:
                    self._logger.debug(
                        f"  Scanner '{scanner_stat.scanner_name}': "
                        f"error={scanner_stat.error}"
                    )
        
        return summary
    
    def reset(self) -> None:
        """重置所有计时数据。"""
        with self._lock:
            self._timings.clear()
            self._start_times.clear()


# =============================================================================
# 可用性缓存
# =============================================================================

class AvailabilityCache:
    """扫描器可用性缓存。
    
    缓存 shutil.which() 的结果，避免重复的系统调用开销。
    使用类级别缓存，在进程生命周期内有效。
    
    Requirements: 2.1, 2.2, 2.3
    """
    
    _cache: Dict[str, Tuple[bool, Optional[str]]] = {}
    _lock = Lock()
    
    @classmethod
    def check(
        cls, 
        command: str, 
        refresh: bool = False
    ) -> Tuple[bool, Optional[str]]:
        """检查命令可用性。
        
        Args:
            command: 要检查的命令名称
            refresh: 是否强制刷新缓存
            
        Returns:
            元组 (is_available, command_path)
            - is_available: 命令是否可用
            - command_path: 命令的完整路径，如果不可用则为 None
            
        Requirements: 2.1, 2.2, 2.3
        """
        if not command:
            return False, None
        
        with cls._lock:
            # 检查缓存
            if not refresh and command in cls._cache:
                return cls._cache[command]
            
            # 执行实际检查
            path = shutil.which(command)
            result = (path is not None, path)
            
            # 存入缓存
            cls._cache[command] = result
            
            return result
    
    @classmethod
    def clear(cls) -> None:
        """清除所有缓存。
        
        Requirements: 2.3
        """
        with cls._lock:
            cls._cache.clear()
    
    @classmethod
    def get_cache_stats(cls) -> Dict[str, Any]:
        """获取缓存统计信息。
        
        Returns:
            缓存统计字典
        """
        with cls._lock:
            available_count = sum(1 for v in cls._cache.values() if v[0])
            return {
                "total_cached": len(cls._cache),
                "available": available_count,
                "unavailable": len(cls._cache) - available_count,
                "commands": list(cls._cache.keys()),
            }


# =============================================================================
# 扫描器执行器
# =============================================================================

class ScannerExecutor:
    """扫描器执行器。
    
    统一管理扫描器的执行策略，支持串行和并行执行模式。
    支持事件回调，用于向前端推送扫描进度。
    
    Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 5.1, 5.2, 5.3
    """
    
    def __init__(
        self,
        scanners: List["BaseScanner"],
        mode: str = "sequential",
        max_workers: int = 4,
        global_timeout: Optional[float] = None,
        enable_performance_log: bool = True,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        """初始化扫描器执行器。
        
        Args:
            scanners: 扫描器实例列表
            mode: 执行模式，可选值: "sequential" | "parallel" | "disabled"
            max_workers: 并行模式最大工作线程数
            global_timeout: 全局超时时间（秒），None 表示不限制
            enable_performance_log: 是否启用性能日志
            event_callback: 事件回调函数，用于推送扫描进度到前端
            
        Requirements: 4.1, 4.2, 4.3, 4.4
        """
        self._scanners = scanners
        self._mode = mode
        self._max_workers = max_workers
        self._global_timeout = global_timeout
        self._enable_performance_log = enable_performance_log
        self._perf_logger = PerformanceLogger() if enable_performance_log else None
        self._event_callback = event_callback
    
    def _emit_event(self, event: Dict[str, Any]) -> None:
        """发送事件到回调函数。
        
        Args:
            event: 事件字典
        """
        if self._event_callback:
            try:
                self._event_callback(event)
            except Exception as e:
                logger.debug(f"Event callback error: {e}")
    
    def execute(
        self,
        file_path: str,
        content: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], ScanExecutionStats]:
        """执行扫描。
        
        Args:
            file_path: 要扫描的文件路径
            content: 文件内容，如果为 None 则从文件读取
            
        Returns:
            元组 (issues, stats)
            - issues: 问题列表
            - stats: 执行统计
            
        Requirements: 3.1, 3.2, 3.3, 3.4, 4.1, 4.3, 4.4
        """
        stats = ScanExecutionStats(mode=self._mode)
        
        # disabled 模式直接返回
        if self._mode == "disabled":
            logger.debug("Scanner execution disabled by configuration")
            return [], stats
        
        if not self._scanners:
            logger.debug("No scanners available")
            return [], stats
        
        # 开始总计时
        if self._perf_logger:
            self._perf_logger.start_timing("total_scan")
        
        start_time = time.perf_counter()
        
        try:
            if self._mode == "parallel":
                issues = self._execute_parallel(file_path, content, stats)
            else:
                issues = self._execute_sequential(file_path, content, stats)
        finally:
            # 结束总计时
            total_ms = (time.perf_counter() - start_time) * 1000
            stats.total_duration_ms = total_ms
            
            if self._perf_logger:
                self._perf_logger.end_timing("total_scan")
                self._perf_logger.log_summary(stats)
        
        return issues, stats
    
    def _check_scanner_availability(
        self, 
        scanner: "BaseScanner"
    ) -> Tuple[bool, float]:
        """检查扫描器可用性并记录耗时。
        
        Args:
            scanner: 扫描器实例
            
        Returns:
            元组 (is_available, check_duration_ms)
            
        Requirements: 1.2, 2.1, 2.2
        """
        start = time.perf_counter()
        
        # 使用缓存检查可用性
        command = getattr(scanner, 'command', '')
        available, _ = AvailabilityCache.check(command)
        
        duration_ms = (time.perf_counter() - start) * 1000
        return available, duration_ms
    
    def _execute_single_scanner(
        self,
        scanner: "BaseScanner",
        file_path: str,
        content: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], ScannerPerformanceStats]:
        """执行单个扫描器。
        
        Args:
            scanner: 扫描器实例
            file_path: 文件路径
            content: 文件内容
            
        Returns:
            元组 (issues, stats)
            
        Requirements: 1.3, 3.3
        """
        scanner_name = getattr(scanner, 'name', 'unknown')
        stats = ScannerPerformanceStats(scanner_name=scanner_name)
        issues: List[Dict[str, Any]] = []
        
        # 检查是否启用
        if not getattr(scanner, 'enabled', True):
            stats.error = "disabled"
            return issues, stats
        
        # 检查可用性
        available, avail_check_ms = self._check_scanner_availability(scanner)
        stats.availability_check_ms = avail_check_ms
        stats.available = available
        
        if not available:
            stats.error = f"command not found: {getattr(scanner, 'command', 'unknown')}"
            return issues, stats
        
        # 发送扫描开始事件
        self._emit_event({
            "type": "scanner_progress",
            "status": "start",
            "scanner": scanner_name,
            "file": file_path,
            "timestamp": time.time()
        })
        
        # 执行扫描
        scan_start = time.perf_counter()
        try:
            scan_issues = scanner.scan(file_path, content)
            stats.scan_duration_ms = (time.perf_counter() - scan_start) * 1000
            
            # 转换为字典格式
            for issue in scan_issues:
                issue_dict = issue.to_dict()
                issue_dict["scanner"] = scanner_name
                issues.append(issue_dict)
            
            stats.issues_count = len(issues)
            
            # 发送扫描完成事件
            error_count = sum(1 for i in issues if i.get("severity") == "error")
            self._emit_event({
                "type": "scanner_progress",
                "status": "complete",
                "scanner": scanner_name,
                "duration_ms": stats.scan_duration_ms,
                "issue_count": stats.issues_count,
                "error_count": error_count
            })
            
        except Exception as e:
            stats.scan_duration_ms = (time.perf_counter() - scan_start) * 1000
            stats.error = str(e)
            logger.warning(f"Scanner {scanner_name} failed: {e}")
            
            # 发送扫描错误事件
            self._emit_event({
                "type": "scanner_progress",
                "status": "error",
                "scanner": scanner_name,
                "error": str(e)
            })
        
        return issues, stats
    
    def _execute_sequential(
        self,
        file_path: str,
        content: Optional[str],
        stats: ScanExecutionStats,
    ) -> List[Dict[str, Any]]:
        """串行执行所有扫描器。
        
        Args:
            file_path: 文件路径
            content: 文件内容
            stats: 执行统计对象（会被修改）
            
        Returns:
            问题列表
            
        Requirements: 4.4
        """
        all_issues: List[Dict[str, Any]] = []
        
        for scanner in self._scanners:
            scanner_name = getattr(scanner, 'name', 'unknown')
            
            if self._perf_logger:
                self._perf_logger.start_timing(f"scanner_{scanner_name}")
            
            issues, scanner_stats = self._execute_single_scanner(
                scanner, file_path, content
            )
            
            if self._perf_logger:
                self._perf_logger.end_timing(f"scanner_{scanner_name}")
            
            stats.scanner_stats.append(scanner_stats)
            
            if scanner_stats.error:
                if scanner_stats.error == "disabled":
                    stats.scanners_skipped += 1
                elif "not found" in scanner_stats.error:
                    stats.scanners_skipped += 1
                else:
                    stats.scanners_failed += 1
            else:
                stats.scanners_executed += 1
                all_issues.extend(issues)
        
        stats.total_issues = len(all_issues)
        return all_issues
    
    def _execute_parallel(
        self,
        file_path: str,
        content: Optional[str],
        stats: ScanExecutionStats,
    ) -> List[Dict[str, Any]]:
        """并行执行所有扫描器。
        
        Args:
            file_path: 文件路径
            content: 文件内容
            stats: 执行统计对象（会被修改）
            
        Returns:
            问题列表
            
        Requirements: 3.1, 3.2, 3.3, 3.4, 5.2, 5.3
        """
        all_issues: List[Dict[str, Any]] = []
        futures_map: Dict[Any, str] = {}
        
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            # 提交所有扫描任务
            for scanner in self._scanners:
                scanner_name = getattr(scanner, 'name', 'unknown')
                future = executor.submit(
                    self._execute_single_scanner,
                    scanner, file_path, content
                )
                futures_map[future] = scanner_name
            
            # 收集结果
            try:
                completed_futures = as_completed(
                    futures_map.keys(),
                    timeout=self._global_timeout
                )
                
                for future in completed_futures:
                    scanner_name = futures_map[future]
                    try:
                        issues, scanner_stats = future.result()
                        stats.scanner_stats.append(scanner_stats)
                        
                        if scanner_stats.error:
                            if scanner_stats.error == "disabled":
                                stats.scanners_skipped += 1
                            elif "not found" in scanner_stats.error:
                                stats.scanners_skipped += 1
                            else:
                                stats.scanners_failed += 1
                        else:
                            stats.scanners_executed += 1
                            all_issues.extend(issues)
                            
                    except Exception as e:
                        logger.warning(f"Scanner {scanner_name} raised exception: {e}")
                        stats.scanners_failed += 1
                        stats.scanner_stats.append(
                            ScannerPerformanceStats(
                                scanner_name=scanner_name,
                                error=str(e)
                            )
                        )
                        
            except FuturesTimeoutError:
                # 全局超时，取消未完成的任务
                logger.warning(
                    f"Global timeout ({self._global_timeout}s) reached, "
                    f"cancelling remaining scanners"
                )
                for future in futures_map:
                    if not future.done():
                        future.cancel()
                        scanner_name = futures_map[future]
                        stats.scanners_failed += 1
                        stats.scanner_stats.append(
                            ScannerPerformanceStats(
                                scanner_name=scanner_name,
                                error="global timeout"
                            )
                        )
        
        stats.total_issues = len(all_issues)
        return all_issues


# =============================================================================
# 配置加载辅助函数
# =============================================================================

def get_scanner_execution_config() -> Dict[str, Any]:
    """获取扫描器执行配置。
    
    Returns:
        配置字典，包含 mode、max_workers、global_timeout、enable_performance_log
        
    Requirements: 4.1, 4.2, 4.3, 4.4
    """
    default_config = {
        "mode": "sequential",
        "max_workers": 4,
        "global_timeout": 60.0,
        "enable_performance_log": True,
    }
    
    try:
        from Agent.DIFF.rule.rule_config import get_rule_config
        config = get_rule_config()
        scanner_config = config.get("scanner_execution", {})
        
        # 合并配置
        for key in default_config:
            if key in scanner_config:
                default_config[key] = scanner_config[key]
                
    except ImportError:
        logger.debug("rule_config not available, using default scanner execution config")
    except Exception as e:
        logger.warning(f"Error loading scanner execution config: {e}")
    
    return default_config
