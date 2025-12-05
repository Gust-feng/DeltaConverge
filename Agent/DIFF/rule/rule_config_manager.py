"""规则配置管理器：管理学习到的规则。

负责存储、加载和管理从冲突分析中学习到的规则。
学习到的规则存储在单独的 JSON 文件中，与默认规则配置分离。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from Agent.DIFF.issue.rule_analyzer import ApplicableRule


class RuleConfigManager:
    """规则配置管理器：管理学习到的规则。"""
    
    # 学习规则存储文件路径
    LEARNED_RULES_FILE = Path(__file__).parent / "learned_rules.json"
    
    def __init__(self, rules_file: Optional[Path] = None):
        """初始化管理器。
        
        Args:
            rules_file: 规则文件路径，默认使用 LEARNED_RULES_FILE
        """
        self.rules_file = rules_file or self.LEARNED_RULES_FILE
        self._cache: Optional[Dict[str, Any]] = None
    
    def _load_rules(self) -> Dict[str, Any]:
        """加载学习到的规则。"""
        if self._cache is not None:
            return self._cache
        
        if not self.rules_file.exists():
            self._cache = {
                "version": "1.0",
                "rules": {},
                "updated_at": datetime.now().isoformat(),
            }
            return self._cache
        
        try:
            with open(self.rules_file, "r", encoding="utf-8") as f:
                self._cache = json.load(f)
                return self._cache
        except (json.JSONDecodeError, IOError):
            self._cache = {
                "version": "1.0",
                "rules": {},
                "updated_at": datetime.now().isoformat(),
            }
            return self._cache
    
    def _save_rules(self, data: Dict[str, Any]) -> None:
        """保存规则到文件。"""
        data["updated_at"] = datetime.now().isoformat()
        
        # 确保目录存在
        self.rules_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self.rules_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        self._cache = data
    
    def add_tag_rule(
        self, 
        language: str, 
        rule: ApplicableRule
    ) -> Dict[str, Any]:
        """添加基于标签的规则到配置。
        
        Args:
            language: 编程语言
            rule: 可应用规则
            
        Returns:
            添加的规则配置
        """
        data = self._load_rules()
        
        if language not in data["rules"]:
            data["rules"][language] = []
        
        # 检查是否已存在相同 rule_id
        existing_ids = {r.get("rule_id") for r in data["rules"][language]}
        if rule.rule_id in existing_ids:
            # 更新现有规则
            for i, r in enumerate(data["rules"][language]):
                if r.get("rule_id") == rule.rule_id:
                    data["rules"][language][i] = rule.to_config()
                    break
        else:
            # 添加新规则
            data["rules"][language].append(rule.to_config())
        
        self._save_rules(data)
        
        return rule.to_config()
    
    def get_learned_rules(self) -> Dict[str, List[Dict]]:
        """获取所有学习到的规则。
        
        Returns:
            按语言分组的规则字典
        """
        data = self._load_rules()
        return data.get("rules", {})
    
    def get_rules_by_language(self, language: str) -> List[Dict]:
        """获取指定语言的学习规则。
        
        Args:
            language: 编程语言
            
        Returns:
            规则列表
        """
        rules = self.get_learned_rules()
        return rules.get(language, [])
    
    def get_rule_by_id(self, rule_id: str) -> Optional[Dict]:
        """根据 ID 获取规则。
        
        Args:
            rule_id: 规则 ID
            
        Returns:
            规则配置，如果不存在返回 None
        """
        rules = self.get_learned_rules()
        for lang_rules in rules.values():
            for rule in lang_rules:
                if rule.get("rule_id") == rule_id:
                    return rule
        return None
    
    def remove_learned_rule(self, rule_id: str) -> bool:
        """移除学习到的规则。
        
        Args:
            rule_id: 规则 ID
            
        Returns:
            是否成功移除
        """
        data = self._load_rules()
        
        for language, rules in data["rules"].items():
            for i, rule in enumerate(rules):
                if rule.get("rule_id") == rule_id:
                    del data["rules"][language][i]
                    self._save_rules(data)
                    return True
        
        return False
    
    def clear_all_rules(self) -> int:
        """清除所有学习到的规则。
        
        Returns:
            清除的规则数量
        """
        data = self._load_rules()
        
        count = sum(len(rules) for rules in data["rules"].values())
        
        data["rules"] = {}
        self._save_rules(data)
        
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """获取规则统计信息。
        
        Returns:
            统计信息字典
        """
        data = self._load_rules()
        rules = data.get("rules", {})
        
        total = sum(len(r) for r in rules.values())
        by_language = {lang: len(r) for lang, r in rules.items()}
        
        return {
            "total_rules": total,
            "by_language": by_language,
            "updated_at": data.get("updated_at"),
        }
    
    def invalidate_cache(self) -> None:
        """使缓存失效，下次访问时重新加载。"""
        self._cache = None


# 全局单例
_manager: Optional[RuleConfigManager] = None


def get_rule_config_manager() -> RuleConfigManager:
    """获取全局规则配置管理器实例。"""
    global _manager
    if _manager is None:
        _manager = RuleConfigManager()
    return _manager


__all__ = [
    "RuleConfigManager",
    "get_rule_config_manager",
]
