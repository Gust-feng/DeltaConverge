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
from typing import Any, Dict, List, Optional


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
    review_index_max_chars: int = 18_000
    intent_max_chars: int = 6_000
    context_bundle_max_items: int = 10
    context_bundle_max_chars: int = 45_000
    context_field_max_chars: int = 1_800
    caller_max_chars: int = 500
    tags_max_count: int = 6


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
            self._validate_updates(updates, current)
            self._deep_update(current, updates)
            self._validate_merged_config(current)
            self._config = KernelConfig.from_dict(current)
            
            if persist:
                self._save_config()
            
            return self.get_config()

    @staticmethod
    def _validate_updates(updates: Dict[str, Any], current: Dict[str, Any]) -> None:
        """校验更新 payload 的结构、字段合法性与基础类型。"""
        if not isinstance(updates, dict):
            raise ValueError("updates 必须是对象")

        for section, value in updates.items():
            if section not in current:
                raise ValueError(f"未知配置分组: {section}")
            if not isinstance(value, dict):
                raise ValueError(f"配置分组 {section} 必须是对象")
            for field, field_value in value.items():
                if field not in current[section]:
                    raise ValueError(f"未知配置项: {section}.{field}")
                default_value = current[section][field]
                expected_type = type(default_value)
                if expected_type is bool:
                    if not isinstance(field_value, bool):
                        raise ValueError(f"{section}.{field} 必须是布尔值")
                    continue
                if expected_type is int:
                    if not isinstance(field_value, int) or isinstance(field_value, bool):
                        raise ValueError(f"{section}.{field} 必须是整数")
                    continue
                if expected_type is float:
                    if not isinstance(field_value, (int, float)) or isinstance(field_value, bool):
                        raise ValueError(f"{section}.{field} 必须是数值")
                    continue
                if not isinstance(field_value, expected_type):
                    raise ValueError(f"{section}.{field} 类型不正确")

    @staticmethod
    def _validate_merged_config(data: Dict[str, Any]) -> None:
        """校验合并后的配置取值范围。"""
        llm = data["llm"]
        context = data["context"]
        review = data["review"]
        fusion = data["fusion_thresholds"]

        positive_int_fields = (
            ("llm.call_timeout", llm["call_timeout"]),
            ("llm.planner_timeout", llm["planner_timeout"]),
            ("llm.planner_first_token_timeout", llm["planner_first_token_timeout"]),
            ("llm.planner_first_token_timeout_thinking", llm["planner_first_token_timeout_thinking"]),
            ("context.max_context_chars", context["max_context_chars"]),
            ("context.full_file_max_lines", context["full_file_max_lines"]),
            ("context.callers_max_hits", context["callers_max_hits"]),
            ("review.max_units_per_batch", review["max_units_per_batch"]),
            ("review.stream_chunk_sample_rate", review["stream_chunk_sample_rate"]),
            ("review.review_index_max_chars", review["review_index_max_chars"]),
            ("review.intent_max_chars", review["intent_max_chars"]),
            ("review.context_bundle_max_items", review["context_bundle_max_items"]),
            ("review.context_bundle_max_chars", review["context_bundle_max_chars"]),
            ("review.context_field_max_chars", review["context_field_max_chars"]),
            ("review.caller_max_chars", review["caller_max_chars"]),
            ("review.tags_max_count", review["tags_max_count"]),
        )
        for field_name, value in positive_int_fields:
            if int(value) <= 0:
                raise ValueError(f"{field_name} 必须大于 0")

        non_negative_fields = (
            ("llm.max_retries", llm["max_retries"]),
            ("context.file_cache_ttl", context["file_cache_ttl"]),
            ("review.intent_cache_ttl_days", review["intent_cache_ttl_days"]),
        )
        for field_name, value in non_negative_fields:
            if int(value) < 0:
                raise ValueError(f"{field_name} 不能小于 0")

        if float(llm["retry_delay"]) < 0:
            raise ValueError("llm.retry_delay 不能小于 0")

        high = float(fusion["high"])
        medium = float(fusion["medium"])
        low = float(fusion["low"])
        for field_name, value in (
            ("fusion_thresholds.high", high),
            ("fusion_thresholds.medium", medium),
            ("fusion_thresholds.low", low),
        ):
            if value < 0 or value > 1:
                raise ValueError(f"{field_name} 必须在 [0,1] 区间")
        if not (high >= medium >= low):
            raise ValueError("fusion_thresholds 必须满足 high >= medium >= low")
    
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

    @staticmethod
    def get_config_doctor() -> Dict[str, Any]:
        """输出配置诊断信息（默认值、持久化值、当前生效值与差异）。"""
        manager = get_config_manager()
        default_config = KernelConfig().to_dict()
        effective_config = manager.get_config().to_dict()

        persisted_raw: Dict[str, Any] | None = None
        persisted_path = str(manager._config_path)
        persisted_exists = manager._config_path.exists()
        if persisted_exists:
            try:
                with open(manager._config_path, "r", encoding="utf-8") as f:
                    parsed = json.load(f)
                if isinstance(parsed, dict):
                    persisted_raw = parsed
            except Exception:
                persisted_raw = None

        changed_fields: List[Dict[str, Any]] = []

        def _walk(path: str, default_val: Any, effective_val: Any, persisted_val: Any, has_persisted: bool) -> None:
            if isinstance(default_val, dict) and isinstance(effective_val, dict):
                keys = sorted(set(default_val.keys()) | set(effective_val.keys()))
                for key in keys:
                    child_path = f"{path}.{key}" if path else str(key)
                    child_default = default_val.get(key)
                    child_effective = effective_val.get(key)
                    child_persisted = persisted_val.get(key) if isinstance(persisted_val, dict) else None
                    child_has_persisted = isinstance(persisted_val, dict) and (key in persisted_val)
                    _walk(child_path, child_default, child_effective, child_persisted, child_has_persisted)
                return
            if default_val != effective_val:
                changed_fields.append(
                    {
                        "path": path,
                        "default": default_val,
                        "effective": effective_val,
                        "source": "persisted" if has_persisted else "runtime_or_fallback",
                        "persisted": persisted_val if has_persisted else None,
                    }
                )

        _walk("", default_config, effective_config, persisted_raw or {}, persisted_exists and isinstance(persisted_raw, dict))

        return {
            "config_path": persisted_path,
            "persisted_exists": persisted_exists,
            "defaults": default_config,
            "persisted": persisted_raw,
            "effective": effective_config,
            "changed_fields": changed_fields,
            "summary": {
                "changed_count": len(changed_fields),
                "using_default_only": len(changed_fields) == 0,
            },
        }


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


# ============================================================================
# Review Prompt Construction Limits
# ============================================================================

def get_review_prompt_limits() -> Dict[str, int]:
    """获取审查提示词构建的内部限制。
    
    Returns:
        Dict: 包含 review_index、intent、context_bundle 等字符数/数量限制
    """
    try:
        review = get_config_manager().get_config().review
        return {
            "review_index_max_chars": max(1, int(review.review_index_max_chars)),
            "intent_max_chars": max(1, int(review.intent_max_chars)),
            "context_bundle_max_items": max(1, int(review.context_bundle_max_items)),
            "context_bundle_max_chars": max(1, int(review.context_bundle_max_chars)),
            "context_field_max_chars": max(1, int(review.context_field_max_chars)),
            "caller_max_chars": max(1, int(review.caller_max_chars)),
            "tags_max_count": max(1, int(review.tags_max_count)),
        }
    except Exception:
        return {
            "review_index_max_chars": 18_000,
            "intent_max_chars": 6_000,
            "context_bundle_max_items": 10,
            "context_bundle_max_chars": 45_000,
            "context_field_max_chars": 1_800,
            "caller_max_chars": 500,
            "tags_max_count": 6,
        }


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
    "get_review_prompt_limits",
]
