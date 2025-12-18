"""内核配置管理模块。

提供运行时配置的获取、更新、重置功能。
配置分为两层：
1. 默认配置（硬编码）
2. 运行时配置（可通过API动态调整，可选持久化）
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class FusionThresholds:
    """融合层置信度阈值配置。"""
    high: float = 0.8       # 高置信度：规则层优先
    medium: float = 0.5     # 中置信度：加权融合
    low: float = 0.3        # 低置信度：LLM优先


@dataclass
class LLMConfig:
    """LLM调用相关配置。"""
    call_timeout: int = 300             # LLM调用超时（秒）
    planner_timeout: int = 120           # 规划阶段超时（秒）
    planner_first_token_timeout: int = 20  # 规划阶段首个增量输出超时（秒）
    planner_first_token_timeout_thinking: int = 120  # 思考模型首个增量输出超时（秒）
    max_retries: int = 3                # 最大重试次数
    retry_delay: float = 1.0            # 重试间隔（秒）


@dataclass
class ContextConfig:
    """上下文管理配置。"""
    max_context_chars: int = 50000      # 单字段最大字符数
    full_file_max_lines: int = 1000     # 全文件模式最大行数
    callers_max_hits: int = 10          # 调用方搜索最大命中数
    file_cache_ttl: int = 300           # 文件缓存TTL（秒）


@dataclass
class ReviewConfig:
    """审查流程配置。"""
    max_units_per_batch: int = 50       # 单次审查最大单元数
    enable_intent_cache: bool = True    # 是否启用意图分析缓存
    intent_cache_ttl_days: int = 30     # 意图缓存过期天数
    stream_chunk_sample_rate: int = 20  # 流式日志采样率


@dataclass
class KernelConfig:
    """内核完整配置。"""
    llm: LLMConfig = field(default_factory=LLMConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    review: ReviewConfig = field(default_factory=ReviewConfig)
    fusion_thresholds: FusionThresholds = field(default_factory=FusionThresholds)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式。"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KernelConfig":
        """从字典创建配置对象。"""
        return cls(
            llm=LLMConfig(**data.get("llm", {})),
            context=ContextConfig(**data.get("context", {})),
            review=ReviewConfig(**data.get("review", {})),
            fusion_thresholds=FusionThresholds(**data.get("fusion_thresholds", {})),
        )


class ConfigManager:
    """配置管理器（单例）。
    
    提供线程安全的配置访问和修改能力。
    """
    
    _instance: Optional["ConfigManager"] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "ConfigManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        
        self._config_lock = threading.RLock()
        self._config = KernelConfig()
        self._config_path = Path(__file__).parent / "kernel_config.json"
        self._load_config()
        self._initialized = True
    
    def _load_config(self) -> None:
        """从文件加载配置（如果存在）。"""
        if self._config_path.exists():
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._config = KernelConfig.from_dict(data)
            except Exception:
                # 加载失败时使用默认配置
                self._config = KernelConfig()
    
    def _save_config(self) -> None:
        """保存配置到文件。"""
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # 保存失败不影响运行
    
    def get_config(self) -> KernelConfig:
        """获取当前配置的副本。"""
        with self._config_lock:
            return KernelConfig.from_dict(self._config.to_dict())
    
    def update_config(self, updates: Dict[str, Any], persist: bool = True) -> KernelConfig:
        """更新配置（部分更新）。
        
        Args:
            updates: 要更新的配置项，支持嵌套路径如 {"llm": {"call_timeout": 180}}
            persist: 是否持久化到文件
            
        Returns:
            更新后的完整配置
        """
        with self._config_lock:
            current = self._config.to_dict()
            self._deep_update(current, updates)
            self._config = KernelConfig.from_dict(current)
            
            if persist:
                self._save_config()
            
            return self.get_config()
    
    def reset_config(self, persist: bool = True) -> KernelConfig:
        """重置为默认配置。
        
        Args:
            persist: 是否持久化（删除配置文件）
            
        Returns:
            重置后的默认配置
        """
        with self._config_lock:
            self._config = KernelConfig()
            
            if persist and self._config_path.exists():
                try:
                    self._config_path.unlink()
                except Exception:
                    pass
            
            return self.get_config()
    
    @staticmethod
    def _deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """递归更新嵌套字典。"""
        for key, value in updates.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigManager._deep_update(base[key], value)
            else:
                base[key] = value


# 全局配置管理器实例
_config_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """获取配置管理器单例。"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager


class ConfigAPI:
    """配置管理API（静态方法接口）。"""
    
    @staticmethod
    def get_config() -> Dict[str, Any]:
        """获取当前内核配置。
        
        Returns:
            Dict: 完整配置字典，包含 llm、context、review、fusion_thresholds 四个部分
        """
        return get_config_manager().get_config().to_dict()
    
    @staticmethod
    def update_config(updates: Dict[str, Any], persist: bool = True) -> Dict[str, Any]:
        """更新配置（支持部分更新）。
        
        Args:
            updates: 要更新的配置项
            persist: 是否持久化
            
        Returns:
            Dict: 更新后的完整配置
            
        Example:
            >>> ConfigAPI.update_config({"llm": {"call_timeout": 180}})
        """
        return get_config_manager().update_config(updates, persist).to_dict()
    
    @staticmethod
    def reset_config(persist: bool = True) -> Dict[str, Any]:
        """重置为默认配置。
        
        Args:
            persist: 是否删除持久化文件
            
        Returns:
            Dict: 默认配置
        """
        return get_config_manager().reset_config(persist).to_dict()
    
    @staticmethod
    def get_llm_config() -> Dict[str, Any]:
        """获取LLM相关配置。"""
        return asdict(get_config_manager().get_config().llm)
    
    @staticmethod
    def get_context_config() -> Dict[str, Any]:
        """获取上下文相关配置。"""
        return asdict(get_config_manager().get_config().context)
    
    @staticmethod
    def get_review_config() -> Dict[str, Any]:
        """获取审查流程配置。"""
        return asdict(get_config_manager().get_config().review)
    
    @staticmethod
    def get_fusion_thresholds() -> Dict[str, float]:
        """获取融合层阈值配置。"""
        return asdict(get_config_manager().get_config().fusion_thresholds)


# ============================================================================
# Configuration Helper Functions
# ============================================================================

def get_llm_call_timeout(default: float = 300.0) -> float:
    """获取LLM调用超时配置，带fallback。
    
    Args:
        default: 默认超时值（秒）
        
    Returns:
        float: LLM调用超时时间（秒）
    """
    try:
        config = get_config_manager().get_config()
        return float(config.llm.call_timeout)
    except Exception:
        return default


def get_planner_timeout(default: float = 120.0) -> float:
    """获取规划器超时配置，带fallback。
    
    Args:
        default: 默认超时值（秒）
        
    Returns:
        float: 规划器超时时间（秒）
    """
    try:
        config = get_config_manager().get_config()
        return float(config.llm.planner_timeout)
    except Exception:
        return default


def get_planner_first_token_timeout(default: float = 20.0) -> float:
    """获取规划器首 token 超时配置（非思考模型），带fallback。"""

    try:
        config = get_config_manager().get_config()
        return float(config.llm.planner_first_token_timeout)
    except Exception:
        return default


def get_planner_first_token_timeout_thinking(default: float = 120.0) -> float:
    """获取规划器首 token 超时配置（思考模型），带fallback。"""

    try:
        config = get_config_manager().get_config()
        return float(config.llm.planner_first_token_timeout_thinking)
    except Exception:
        return default


def get_retry_config(default_retries: int = 3, default_delay: float = 1.0) -> tuple[int, float]:
    """获取重试配置，带fallback。
    
    Args:
        default_retries: 默认最大重试次数
        default_delay: 默认重试延迟（秒）
        
    Returns:
        Tuple[int, float]: (最大重试次数, 重试延迟秒数)
    """
    try:
        config = get_config_manager().get_config()
        return (int(config.llm.max_retries), float(config.llm.retry_delay))
    except Exception:
        return (default_retries, default_delay)


def get_context_limits() -> dict[str, int]:
    """获取上下文限制配置。
    
    Returns:
        Dict[str, int]: 包含 max_context_chars, full_file_max_lines, 
                        callers_max_hits, file_cache_ttl 的字典
    """
    try:
        config = get_config_manager().get_config()
        return {
            "max_context_chars": config.context.max_context_chars,
            "full_file_max_lines": config.context.full_file_max_lines,
            "callers_max_hits": config.context.callers_max_hits,
            "file_cache_ttl": config.context.file_cache_ttl,
        }
    except Exception:
        return {
            "max_context_chars": 50000,
            "full_file_max_lines": 1000,
            "callers_max_hits": 10,
            "file_cache_ttl": 300,
        }


# ============================================================================
# Review Configuration Helper Functions
# ============================================================================

def get_review_settings() -> dict[str, Any]:
    """获取审查流程配置。
    
    Returns:
        Dict: 包含 max_units_per_batch, enable_intent_cache, 
              intent_cache_ttl_days, stream_chunk_sample_rate 的字典
    """
    try:
        config = get_config_manager().get_config()
        return {
            "max_units_per_batch": config.review.max_units_per_batch,
            "enable_intent_cache": config.review.enable_intent_cache,
            "intent_cache_ttl_days": config.review.intent_cache_ttl_days,
            "stream_chunk_sample_rate": config.review.stream_chunk_sample_rate,
        }
    except Exception:
        return {
            "max_units_per_batch": 50,
            "enable_intent_cache": True,
            "intent_cache_ttl_days": 30,
            "stream_chunk_sample_rate": 20,
        }


def get_intent_cache_enabled(default: bool = True) -> bool:
    """获取意图缓存是否启用配置，带fallback。
    
    Args:
        default: 默认值
        
    Returns:
        bool: 是否启用意图缓存
    """
    try:
        config = get_config_manager().get_config()
        return bool(config.review.enable_intent_cache)
    except Exception:
        return default


def get_intent_cache_ttl_days(default: int = 30) -> int:
    """获取意图缓存过期天数配置，带fallback。
    
    Args:
        default: 默认过期天数
        
    Returns:
        int: 意图缓存过期天数
    """
    try:
        config = get_config_manager().get_config()
        return int(config.review.intent_cache_ttl_days)
    except Exception:
        return default


def get_stream_chunk_sample_rate(default: int = 20) -> int:
    """获取流式日志采样率配置，带fallback。
    
    Args:
        default: 默认采样率
        
    Returns:
        int: 流式日志采样率
    """
    try:
        config = get_config_manager().get_config()
        return max(1, int(config.review.stream_chunk_sample_rate))
    except Exception:
        return default


def get_max_units_per_batch(default: int = 50) -> int:
    """获取单次审查最大单元数配置，带fallback。
    
    Args:
        default: 默认最大单元数
        
    Returns:
        int: 单次审查最大单元数
    """
    try:
        config = get_config_manager().get_config()
        return max(1, int(config.review.max_units_per_batch))
    except Exception:
        return default


__all__ = [
    "KernelConfig",
    "LLMConfig",
    "ContextConfig",
    "ReviewConfig",
    "FusionThresholds",
    "ConfigAPI",
    "ConfigManager",
    "get_config_manager",
    # Configuration helper functions
    "get_llm_call_timeout",
    "get_planner_timeout",
    "get_planner_first_token_timeout",
    "get_planner_first_token_timeout_thinking",
    "get_retry_config",
    "get_context_limits",
    # Review configuration helper functions
    "get_review_settings",
    "get_intent_cache_enabled",
    "get_intent_cache_ttl_days",
    "get_stream_chunk_sample_rate",
    "get_max_units_per_batch",
]
