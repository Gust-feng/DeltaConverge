"""CLI 辅助工具函数"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """加载配置文件
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置字典
    """
    config = {}
    
    # 从默认位置加载配置
    default_config = Path.home() / ".deltaconverge" / "config.json"
    if default_config.exists():
        try:
            with open(default_config, 'r', encoding='utf-8') as f:
                config.update(json.load(f))
        except Exception:
            pass
    
    # 从指定路径加载配置
    if config_path and Path(config_path).exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config.update(json.load(f))
        except Exception:
            pass
    
    # 从环境变量加载配置
    env_config = {
        'api_key': os.getenv('ANTHROPIC_API_KEY'),
        'model': os.getenv('DELTA_CONVERGE_MODEL', 'claude-3-opus-20240229'),
        'base_url': os.getenv('DELTA_CONVERGE_BASE_URL'),
    }
    # 只添加非 None 的值
    env_config = {k: v for k, v in env_config.items() if v is not None}
    config.update(env_config)
    
    return config


def format_output(result: str, output_format: str = 'text') -> str:
    """格式化输出结果
    
    Args:
        result: 审查结果
        output_format: 输出格式 (text, json, markdown)
        
    Returns:
        格式化后的结果
    """
    if output_format == 'json':
        return json.dumps({'result': result}, ensure_ascii=False, indent=2)
    elif output_format == 'markdown':
        return f"# 代码审查结果\n\n{result}"
    else:  # text
        return result


def validate_model(model: str) -> bool:
    """验证模型是否有效
    
    Args:
        model: 模型名称
        
    Returns:
        是否有效
    """
    valid_models = [
        'claude-3-opus-20240229',
        'claude-3-sonnet-20240229',
        'claude-3-haiku-20240307',
        'claude-2.1',
        'claude-2.0',
    ]
    return model in valid_models


def get_default_model() -> str:
    """获取默认模型
    
    Returns:
        默认模型名称
    """
    return os.getenv('DELTA_CONVERGE_MODEL', 'claude-3-sonnet-20240229')
