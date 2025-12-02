"""健康检查与系统指标模块。

提供服务健康状态检测和运行时指标统计功能。
这些API主要用于运维监控和问题排查。
"""

from __future__ import annotations

import os
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from Agent.core.api.factory import LLMFactory


@dataclass
class ProviderStatus:
    """单个LLM提供商状态。"""
    name: str
    label: str
    available: bool
    error: Optional[str] = None


@dataclass
class HealthStatus:
    """系统健康状态。"""
    status: str  # "healthy", "degraded", "unhealthy"
    timestamp: str
    providers: List[ProviderStatus]
    disk_space_ok: bool
    log_dir_writable: bool
    cache_dir_writable: bool
    available_provider_count: int
    total_provider_count: int


@dataclass  
class SystemMetrics:
    """系统运行指标。"""
    total_reviews: int = 0
    successful_reviews: int = 0
    failed_reviews: int = 0
    total_tokens_used: int = 0
    tokens_by_provider: Dict[str, int] = field(default_factory=dict)
    avg_review_duration_ms: float = 0.0
    cache_hit_rate: float = 0.0
    fallback_count: int = 0
    uptime_seconds: float = 0.0


class MetricsCollector:
    """指标收集器（单例）。
    
    收集系统运行时的各类指标。
    注意：这是一个轻量级的内存指标收集器，重启后数据会丢失。
    生产环境应考虑集成专业的监控系统（如Prometheus）。
    """
    
    _instance: Optional["MetricsCollector"] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "MetricsCollector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        
        self._metrics_lock = threading.RLock()
        self._start_time = time.time()
        
        # 审查统计
        self._total_reviews = 0
        self._successful_reviews = 0
        self._failed_reviews = 0
        
        # Token统计
        self._total_tokens = 0
        self._tokens_by_provider: Dict[str, int] = {}
        
        # 耗时统计
        self._review_durations: List[float] = []  # 最近100次审查耗时
        self._max_duration_samples = 100
        
        # 缓存命中统计
        self._cache_hits = 0
        self._cache_misses = 0
        
        # 回退统计
        self._fallback_count = 0
        
        self._initialized = True
    
    def record_review_start(self) -> float:
        """记录审查开始，返回开始时间戳。"""
        return time.time()
    
    def record_review_end(
        self,
        start_time: float,
        success: bool,
        provider: str,
        tokens_used: int = 0,
    ) -> None:
        """记录审查结束。"""
        with self._metrics_lock:
            self._total_reviews += 1
            
            if success:
                self._successful_reviews += 1
            else:
                self._failed_reviews += 1
            
            # 记录耗时
            duration_ms = (time.time() - start_time) * 1000
            self._review_durations.append(duration_ms)
            if len(self._review_durations) > self._max_duration_samples:
                self._review_durations.pop(0)
            
            # 记录Token
            self._total_tokens += tokens_used
            self._tokens_by_provider[provider] = (
                self._tokens_by_provider.get(provider, 0) + tokens_used
            )
    
    def record_cache_hit(self) -> None:
        """记录缓存命中。"""
        with self._metrics_lock:
            self._cache_hits += 1
    
    def record_cache_miss(self) -> None:
        """记录缓存未命中。"""
        with self._metrics_lock:
            self._cache_misses += 1
    
    def record_fallback(self) -> None:
        """记录一次回退。"""
        with self._metrics_lock:
            self._fallback_count += 1
    
    def get_metrics(self) -> SystemMetrics:
        """获取当前指标快照。"""
        with self._metrics_lock:
            # 计算平均耗时
            avg_duration = 0.0
            if self._review_durations:
                avg_duration = sum(self._review_durations) / len(self._review_durations)
            
            # 计算缓存命中率
            total_cache_ops = self._cache_hits + self._cache_misses
            cache_hit_rate = 0.0
            if total_cache_ops > 0:
                cache_hit_rate = self._cache_hits / total_cache_ops
            
            return SystemMetrics(
                total_reviews=self._total_reviews,
                successful_reviews=self._successful_reviews,
                failed_reviews=self._failed_reviews,
                total_tokens_used=self._total_tokens,
                tokens_by_provider=dict(self._tokens_by_provider),
                avg_review_duration_ms=avg_duration,
                cache_hit_rate=cache_hit_rate,
                fallback_count=self._fallback_count,
                uptime_seconds=time.time() - self._start_time,
            )
    
    def reset(self) -> None:
        """重置所有指标（主要用于测试）。"""
        with self._metrics_lock:
            self._total_reviews = 0
            self._successful_reviews = 0
            self._failed_reviews = 0
            self._total_tokens = 0
            self._tokens_by_provider.clear()
            self._review_durations.clear()
            self._cache_hits = 0
            self._cache_misses = 0
            self._fallback_count = 0
            self._start_time = time.time()


# 全局指标收集器
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """获取指标收集器单例。"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


class HealthChecker:
    """健康检查器。"""
    
    def __init__(self) -> None:
        # 关键目录
        self._log_dir = Path("log")
        self._cache_dir = Path(__file__).parent / ".." / "DIFF" / "rule" / "data"
        self._cache_dir = self._cache_dir.resolve()
    
    def check_disk_space(self, min_free_mb: int = 100) -> bool:
        """检查磁盘空间是否充足。"""
        try:
            import shutil
            total, used, free = shutil.disk_usage(".")
            free_mb = free // (1024 * 1024)
            return free_mb >= min_free_mb
        except Exception:
            return True  # 无法检测时假设正常
    
    def check_dir_writable(self, path: Path) -> bool:
        """检查目录是否可写。"""
        try:
            path.mkdir(parents=True, exist_ok=True)
            test_file = path / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            return True
        except Exception:
            return False
    
    def check_providers(self) -> List[ProviderStatus]:
        """检查所有LLM提供商状态。"""
        statuses: List[ProviderStatus] = []
        
        for name, config in LLMFactory.PROVIDERS.items():
            api_key = os.getenv(config.api_key_env)
            available = bool(api_key)
            error = None if available else f"缺少环境变量 {config.api_key_env}"
            
            statuses.append(ProviderStatus(
                name=name,
                label=config.label,
                available=available,
                error=error,
            ))
        
        return statuses
    
    def get_health_status(self) -> HealthStatus:
        """获取完整的健康状态。"""
        providers = self.check_providers()
        available_count = sum(1 for p in providers if p.available)
        
        disk_ok = self.check_disk_space()
        log_writable = self.check_dir_writable(self._log_dir)
        cache_writable = self.check_dir_writable(self._cache_dir)
        
        # 判断总体状态
        if available_count == 0:
            status = "unhealthy"
        elif not disk_ok or not log_writable:
            status = "degraded"
        elif available_count < len(providers) // 2:
            status = "degraded"
        else:
            status = "healthy"
        
        return HealthStatus(
            status=status,
            timestamp=datetime.now().isoformat(),
            providers=providers,
            disk_space_ok=disk_ok,
            log_dir_writable=log_writable,
            cache_dir_writable=cache_writable,
            available_provider_count=available_count,
            total_provider_count=len(providers),
        )


# 全局健康检查器
_health_checker: Optional[HealthChecker] = None


def get_health_checker() -> HealthChecker:
    """获取健康检查器单例。"""
    global _health_checker
    if _health_checker is None:
        _health_checker = HealthChecker()
    return _health_checker


class HealthAPI:
    """健康检查与指标API（静态方法接口）。"""
    
    @staticmethod
    def health_check() -> Dict[str, Any]:
        """执行服务健康检查。
        
        Returns:
            Dict: {
                "status": "healthy" | "degraded" | "unhealthy",
                "timestamp": str,
                "providers": List[{"name", "label", "available", "error"}],
                "disk_space_ok": bool,
                "log_dir_writable": bool,
                "cache_dir_writable": bool,
                "available_provider_count": int,
                "total_provider_count": int
            }
        """
        status = get_health_checker().get_health_status()
        return {
            "status": status.status,
            "timestamp": status.timestamp,
            "providers": [
                {
                    "name": p.name,
                    "label": p.label,
                    "available": p.available,
                    "error": p.error,
                }
                for p in status.providers
            ],
            "disk_space_ok": status.disk_space_ok,
            "log_dir_writable": status.log_dir_writable,
            "cache_dir_writable": status.cache_dir_writable,
            "available_provider_count": status.available_provider_count,
            "total_provider_count": status.total_provider_count,
        }
    
    @staticmethod
    def get_metrics() -> Dict[str, Any]:
        """获取系统运行指标。
        
        Returns:
            Dict: {
                "total_reviews": int,
                "successful_reviews": int,
                "failed_reviews": int,
                "total_tokens_used": int,
                "tokens_by_provider": Dict[str, int],
                "avg_review_duration_ms": float,
                "cache_hit_rate": float,
                "fallback_count": int,
                "uptime_seconds": float
            }
        """
        metrics = get_metrics_collector().get_metrics()
        return {
            "total_reviews": metrics.total_reviews,
            "successful_reviews": metrics.successful_reviews,
            "failed_reviews": metrics.failed_reviews,
            "total_tokens_used": metrics.total_tokens_used,
            "tokens_by_provider": metrics.tokens_by_provider,
            "avg_review_duration_ms": metrics.avg_review_duration_ms,
            "cache_hit_rate": metrics.cache_hit_rate,
            "fallback_count": metrics.fallback_count,
            "uptime_seconds": metrics.uptime_seconds,
        }
    
    @staticmethod
    def get_provider_status() -> List[Dict[str, Any]]:
        """获取所有LLM提供商的状态。
        
        Returns:
            List[Dict]: 每个提供商的状态信息
        """
        statuses = get_health_checker().check_providers()
        return [
            {
                "name": s.name,
                "label": s.label,
                "available": s.available,
                "error": s.error,
            }
            for s in statuses
        ]
    
    @staticmethod
    def is_healthy() -> bool:
        """快速健康检查（仅返回布尔值）。"""
        status = get_health_checker().get_health_status()
        return status.status == "healthy"
    
    @staticmethod
    def reset_metrics() -> Dict[str, str]:
        """重置所有运行指标（主要用于测试）。
        
        Returns:
            Dict: {"status": "ok", "message": str}
        """
        get_metrics_collector().reset()
        return {
            "status": "ok",
            "message": "Metrics reset successfully",
        }


__all__ = [
    "HealthAPI",
    "HealthChecker",
    "HealthStatus",
    "MetricsCollector",
    "SystemMetrics",
    "ProviderStatus",
    "get_health_checker",
    "get_metrics_collector",
]
