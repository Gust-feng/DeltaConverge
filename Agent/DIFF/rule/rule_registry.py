"""Rule handler registry and factory for managing language-specific rule handlers."""

from __future__ import annotations

from typing import Dict, Optional, Type

from Agent.DIFF.rule.rule_base import RuleHandler

# 规则处理器注册表
_rule_handlers: Dict[str, Type[RuleHandler]] = {}


def register_rule_handler(language: str, handler_cls: Type[RuleHandler]) -> None:
    """注册语言特定的规则处理器。
    
    Args:
        language: 编程语言名称（如 "python", "typescript"）
        handler_cls: 规则处理器类，必须继承自 RuleHandler
    """
    if not issubclass(handler_cls, RuleHandler):
        raise TypeError(f"Handler class must inherit from RuleHandler, got {handler_cls}")
    
    _rule_handlers[language.lower()] = handler_cls


def get_rule_handler(language: str) -> Optional[RuleHandler]:
    """获取指定语言的规则处理器实例。
    
    Args:
        language: 编程语言名称（如 "python", "typescript"）
        
    Returns:
        规则处理器实例，如果没有找到则返回 None
    """
    handler_cls = _rule_handlers.get(language.lower())
    if handler_cls:
        return handler_cls()
    return None


def get_all_rule_handlers() -> Dict[str, Type[RuleHandler]]:
    """获取所有注册的规则处理器。
    
    Returns:
        所有注册的规则处理器映射
    """
    return _rule_handlers.copy()


def initialize_handlers() -> None:
    """初始化所有规则处理器，自动注册内置的语言处理器。"""
    # 自动导入并注册内置的语言处理器
    try:
        from Agent.DIFF.rule.rule_lang_python import PythonRuleHandler
        register_rule_handler("python", PythonRuleHandler)
    except ImportError:
        print("[警告] 无法导入 Python 规则处理器")
    
    try:
        from Agent.DIFF.rule.rule_lang_typescript import TypeScriptRuleHandler
        register_rule_handler("typescript", TypeScriptRuleHandler)
    except ImportError:
        print("[警告] 无法导入 TypeScript 规则处理器")
    
    try:
        from Agent.DIFF.rule.rule_lang_java import JavaRuleHandler
        register_rule_handler("java", JavaRuleHandler)
    except ImportError:
        print("[警告] 无法导入 Java 规则处理器")
    
    try:
        from Agent.DIFF.rule.rule_lang_go import GoRuleHandler
        register_rule_handler("go", GoRuleHandler)
    except ImportError:
        print("[警告] 无法导入 Go 规则处理器")
    
    try:
        from Agent.DIFF.rule.rule_lang_ruby import RubyRuleHandler
        register_rule_handler("ruby", RubyRuleHandler)
    except ImportError:
        print("[警告] 无法导入 Ruby 规则处理器")

# 初始化规则处理器
initialize_handlers()
