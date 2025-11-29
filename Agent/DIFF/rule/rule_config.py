"""规则配置：基础规则 + 按语言覆盖的路径/关键词提示。

目前使用内置配置（可后续替换为 YAML/JSON 读取），保持输出契约不变：
- 仅影响 rule_context_level / rule_confidence / rule_notes（可选 extra_requests 提示）。
- 未匹配到语言规则时回退到基础规则/默认逻辑。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from typing import Any, Dict, List


class ConfigDefaults:
    """配置默认值的集中管理。"""
    # 基础配置默认值
    LARGE_CHANGE_LINES = 80
    MODERATE_CHANGE_LINES = 20
    NOISE_TAGS = ["only_imports", "only_comments", "only_logging"]
    DOC_TAGS = ["doc_file"]
    
    # 安全关键词
    SECURITY_KEYWORDS = [
        "auth",
        "token",
        "jwt",
        "oauth",
        "sso",
        "security",
        "crypto",
        "password",
        "secret",
        "csrf",
        "xss",
        "sql",
    ]
    
    # 配置关键词
    CONFIG_KEYWORDS = [
        "config",
        "setting",
        "settings",
        ".env",
        "environment",
        "yaml",
        "yml",
        "ini",
        "toml",
        "conf",
    ]


# 简化的内置默认配置，可按需扩展/改为外部文件。
DEFAULT_RULE_CONFIG: Dict[str, Any] = {
    "base": {
        "large_change_lines": ConfigDefaults.LARGE_CHANGE_LINES,
        "moderate_change_lines": ConfigDefaults.MODERATE_CHANGE_LINES,
        "noise_tags": ConfigDefaults.NOISE_TAGS,
        "doc_tags": ConfigDefaults.DOC_TAGS,
        "security_keywords": ConfigDefaults.SECURITY_KEYWORDS,
        "config_keywords": ConfigDefaults.CONFIG_KEYWORDS,
    },
    "languages": {
        "python": {
            "path_rules": [
                {
                    "match": ["migrations/"],
                    "context_level": "file",
                    "base_confidence": 0.9,
                    "notes": "py_migration",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.1
                    }
                },
                {
                    "match": ["settings.py", "config.py"],
                    "context_level": "file",
                    "base_confidence": 0.88,
                    "notes": "py_config",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.1,
                        "rule_specificity": 0.1
                    }
                },
                {
                    "match": [
                        "urls.py",
                        "views.py",
                        "serializers.py",
                        "permissions.py",
                        "middleware.py",
                        "tasks.py",
                    ],
                    "context_level": "function",
                    "base_confidence": 0.86,
                    "notes": "py_web_entry",
                    "extra_requests": [{"type": "previous_version"}],
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
            ],
            "symbol_rules": [
                {
                    "type": "function",
                    "name_patterns": ["test", "spec", "unit"],
                    "context_level": "function",
                    "base_confidence": 0.7,
                    "notes": "py_test_function",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
                {
                    "type": "class",
                    "name_patterns": ["controller", "service", "manager"],
                    "context_level": "file",
                    "base_confidence": 0.8,
                    "notes": "py_class_component",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
            ],
            "metric_rules": [
                {
                    "min_lines": 50,
                    "context_level": "file",
                    "base_confidence": 0.82,
                    "notes": "py_large_change",
                    "confidence_adjusters": {
                        "file_size": 0.1,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
                {
                    "min_lines": 6,
                    "max_lines": 49,
                    "context_level": "function",
                    "base_confidence": 0.76,
                    "notes": "py_medium_change",
                    "confidence_adjusters": {
                        "file_size": 0.05,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
                {
                    "max_lines": 5,
                    "context_level": "local",
                    "base_confidence": 0.68,
                    "notes": "py_small_change",
                    "confidence_adjusters": {
                        "file_size": -0.1,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
            ],
            "keywords": [
                "celery",
                "pydantic",
                "fastapi",
                "flask",
                "django",
                "sqlalchemy",
            ],
        },
        "typescript": {
            "path_rules": [
                {
                    "match": ["pages/api/", "app/api/", "api/", "server/"],
                    "context_level": "function",
                    "base_confidence": 0.9,
                    "notes": "ts_api_route",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.1,
                        "rule_specificity": 0.05
                    }
                },
                {
                    "match": ["middleware.ts", "next.config", "prisma/schema.prisma"],
                    "context_level": "file",
                    "base_confidence": 0.9,
                    "notes": "ts_config_schema",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.1,
                        "rule_specificity": 0.1
                    }
                },
                {
                    "match": ["lib/db", "services/", "server/"],
                    "context_level": "function",
                    "base_confidence": 0.87,
                    "notes": "ts_backend_logic",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
            ],
            "symbol_rules": [
                {
                    "type": "function",
                    "name_patterns": ["test", "spec", "it"],
                    "context_level": "function",
                    "base_confidence": 0.7,
                    "notes": "ts_test_function",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
                {
                    "type": "function",
                    "name_patterns": ["use", "hook"],
                    "context_level": "function",
                    "base_confidence": 0.68,
                    "notes": "ts_hook_function",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
            ],
            "metric_rules": [
                {
                    "min_lines": 60,
                    "context_level": "file",
                    "base_confidence": 0.77,
                    "notes": "ts_large_change",
                    "confidence_adjusters": {
                        "file_size": 0.1,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
                {
                    "min_lines": 6,
                    "max_lines": 59,
                    "context_level": "function",
                    "base_confidence": 0.72,
                    "notes": "ts_medium_change",
                    "confidence_adjusters": {
                        "file_size": 0.05,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
                {
                    "max_lines": 5,
                    "context_level": "local",
                    "base_confidence": 0.70,
                    "notes": "ts_small_change",
                    "confidence_adjusters": {
                        "file_size": -0.1,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
            ],
            "keywords": ["router", "handler", "prisma", "trpc", "graphql"],
        },
        "go": {
            "path_rules": [
                {
                    "match": ["pkg/api", "pkg/server", "cmd/", "router", "middleware"],
                    "context_level": "function",
                    "base_confidence": 0.88,
                    "notes": "go_server_path",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
                {
                    "match": ["config/", ".yaml", ".yml"],
                    "context_level": "file",
                    "base_confidence": 0.9,
                    "notes": "go_config",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.1,
                        "rule_specificity": 0.1
                    }
                },
                {
                    "match": ["auth", "datasource", "plugins"],
                    "context_level": "function",
                    "base_confidence": 0.86,
                    "notes": "go_security_or_plugin",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.1,
                        "rule_specificity": 0.05
                    }
                },
            ],
            "symbol_rules": [
                {
                    "type": "function",
                    "name_patterns": ["test", "Test"],
                    "context_level": "function",
                    "base_confidence": 0.75,
                    "notes": "go_test_function",
                    "notes": "go_test_function",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
                {
                    "type": "function",
                    "name_patterns": ["main", "init"],
                    "context_level": "file",
                    "base_confidence": 0.85,
                    "notes": "go_main_function",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.1
                    }
                },
            ],
            "metric_rules": [
                {
                    "min_lines": 70,
                    "context_level": "file",
                    "base_confidence": 0.84,
                    "notes": "go_large_change",
                    "confidence_adjusters": {
                        "file_size": 0.1,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
                {
                    "min_lines": 6,
                    "max_lines": 69,
                    "context_level": "function",
                    "base_confidence": 0.76,
                    "notes": "go_medium_change",
                    "confidence_adjusters": {
                        "file_size": 0.05,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
                {
                    "max_lines": 5,
                    "context_level": "local",
                    "base_confidence": 0.68,
                    "notes": "go_small_change",
                    "confidence_adjusters": {
                        "file_size": -0.1,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
            ],
            "keywords": ["http.", "gin", "echo", "mux", "sql.", "context.Context"],
        },
        "java": {
            "path_rules": [
                {
                    "match": [
                        "controller",
                        "resource",
                        "filter",
                        "interceptor",
                        "servlet",
                        "realm",
                    ],
                    "context_level": "function",
                    "base_confidence": 0.9,
                    "notes": "java_http_entry",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
                {
                    "match": ["service", "auth", "token"],
                    "context_level": "function",
                    "base_confidence": 0.87,
                    "notes": "java_service_auth",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.1,
                        "rule_specificity": 0.05
                    }
                },
                {
                    "match": ["application.yml", "application.yaml", "application.properties", "pom.xml"],
                    "context_level": "file",
                    "base_confidence": 0.92,
                    "notes": "java_config_build",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.1
                    }
                },
            ],
            "symbol_rules": [
                {
                    "type": "class",
                    "name_patterns": ["test", "Test"],
                    "context_level": "function",
                    "base_confidence": 0.75,
                    "notes": "java_test_class",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
                {
                    "type": "method",
                    "name_patterns": ["get", "post", "put", "delete"],
                    "context_level": "function",
                    "base_confidence": 0.76,
                    "notes": "java_rest_method",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
            ],
            "metric_rules": [
                {
                    "min_lines": 90,
                    "context_level": "file",
                    "base_confidence": 0.83,
                    "notes": "java_large_change",
                    "confidence_adjusters": {
                        "file_size": 0.1,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
                {
                    "min_lines": 6,
                    "max_lines": 89,
                    "context_level": "function",
                    "base_confidence": 0.75,
                    "notes": "java_medium_change",
                    "confidence_adjusters": {
                        "file_size": 0.05,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
                {
                    "max_lines": 5,
                    "context_level": "local",
                    "base_confidence": 0.70,
                    "notes": "java_small_change",
                    "confidence_adjusters": {
                        "file_size": -0.1,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
            ],
            "keywords": ["@rolesallowed", "@preauthorize", "@postauthorize", "@path", "@post"],
        },
        "ruby": {
            "path_rules": [
                {
                    "match": ["app/controllers/", "config/routes.rb", "middleware"],
                    "context_level": "function",
                    "base_confidence": 0.88,
                    "notes": "rb_web_route",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
                {
                    "match": ["app/jobs/", "app/services/", "lib/"],
                    "context_level": "function",
                    "base_confidence": 0.86,
                    "notes": "rb_service_job",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
                {
                    "match": ["config/", "Gemfile", "plugin.rb"],
                    "context_level": "file",
                    "base_confidence": 0.9,
                    "notes": "rb_config_dependency",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.1
                    }
                },
            ],
            "symbol_rules": [
                {
                    "type": "class",
                    "name_patterns": ["test", "spec"],
                    "context_level": "function",
                    "base_confidence": 0.75,
                    "notes": "rb_test_class",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
                {
                    "type": "method",
                    "name_patterns": ["create", "update", "destroy"],
                    "context_level": "function",
                    "base_confidence": 0.76,
                    "notes": "rb_crud_method",
                    "confidence_adjusters": {
                        "file_size": 0.0,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.05
                    }
                },
            ],
            "metric_rules": [
                {
                    "min_lines": 80,
                    "context_level": "file",
                    "base_confidence": 0.82,
                    "notes": "rb_large_change",
                    "confidence_adjusters": {
                        "file_size": 0.1,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
                {
                    "min_lines": 6,
                    "max_lines": 79,
                    "context_level": "function",
                    "base_confidence": 0.75,
                    "notes": "rb_medium_change",
                    "confidence_adjusters": {
                        "file_size": 0.05,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
                {
                    "max_lines": 5,
                    "context_level": "local",
                    "base_confidence": 0.70,
                    "notes": "rb_small_change",
                    "confidence_adjusters": {
                        "file_size": -0.1,
                        "change_type": 0.0,
                        "security_sensitive": 0.0,
                        "rule_specificity": 0.0
                    }
                },
            ],
            "keywords": ["active_record", "sidekiq", "redis", "devise", "omniauth"],
        },
    },
}


_CONFIG_CACHE: Dict[str, Any] | None = None


def _validate_config(config: Dict[str, Any]) -> None:
    """验证配置的有效性。
    
    Args:
        config: 配置字典
        
    Raises:
        ValueError: 如果配置无效
    """
    # 验证基础配置
    if "base" not in config:
        raise ValueError("配置缺少 'base' 部分")
    
    base_config = config["base"]
    required_base_fields = ["large_change_lines", "moderate_change_lines", "noise_tags", "doc_tags"]
    for field in required_base_fields:
        if field not in base_config:
            raise ValueError(f"基础配置缺少 '{field}' 字段")
    
    # 验证语言配置
    if "languages" not in config:
        raise ValueError("配置缺少 'languages' 部分")
    
    languages = config["languages"]
    if not isinstance(languages, dict):
        raise ValueError("'languages' 必须是字典类型")


def load_config_from_file(config_path: str) -> Dict[str, Any]:
    """从外部文件加载规则配置。
    
    支持JSON和YAML格式的配置文件。
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        加载的配置字典
        
    Raises:
        FileNotFoundError: 如果配置文件不存在
        ValueError: 如果配置文件格式无效
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    
    with open(config_path, "r", encoding="utf-8") as f:
        if config_path.endswith(".json"):
            config = json.load(f)
        elif config_path.endswith((".yaml", ".yml")):
            if not YAML_AVAILABLE:
                raise ValueError("YAML配置文件需要PyYAML库支持")
            config = yaml.safe_load(f)
        else:
            raise ValueError(f"不支持的配置文件格式: {config_path}")
    
    # 验证配置
    _validate_config(config)
    
    return config


def merge_configs(base_config: Dict[str, Any], override_config: Dict[str, Any]) -> Dict[str, Any]:
    """合并两个配置字典。
    
    Args:
        base_config: 基础配置
        override_config: 覆盖配置
        
    Returns:
        合并后的配置字典
    """
    merged = base_config.copy()
    
    for key, value in override_config.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = merge_configs(merged[key], value)
        else:
            merged[key] = value
    
    return merged


def get_rule_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """返回规则配置（支持外部文件加载）。
    
    Args:
        config_path: 可选的外部配置文件路径
        
    Returns:
        规则配置字典
    """
    global _CONFIG_CACHE
    
    # 如果已经加载过配置，直接返回缓存
    if _CONFIG_CACHE is not None and config_path is None:
        return _CONFIG_CACHE
    
    # 加载基础配置
    config = DEFAULT_RULE_CONFIG.copy()
    
    # 如果提供了外部配置文件，加载并合并
    if config_path:
        try:
            external_config = load_config_from_file(config_path)
            config = merge_configs(config, external_config)
        except Exception as e:
            print(f"加载外部配置文件失败，使用默认配置: {e}")
    
    # 缓存配置
    if config_path is None:
        _CONFIG_CACHE = config
    
    return config


def reset_config_cache() -> None:
    """重置配置缓存。"""
    global _CONFIG_CACHE
    _CONFIG_CACHE = None


def get_config_defaults() -> ConfigDefaults:
    """获取配置默认值。
    
    Returns:
        ConfigDefaults: 配置默认值对象
    """
    return ConfigDefaults()


__all__ = [
    "get_rule_config",
    "DEFAULT_RULE_CONFIG",
    "ConfigDefaults",
    "reset_config_cache",
    "get_config_defaults"
]
