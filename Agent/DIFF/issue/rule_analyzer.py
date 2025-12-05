"""规则分析器：从冲突记录中提取通用规则模式。

基于语义特征（语言、标签、变更规模）而非文件路径来分析冲突，
生成可应用规则和参考提示。
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from Agent.DIFF.issue.conflict_tracker import (
    ConflictTracker,
    ConflictType,
    RuleConflict,
    get_conflict_tracker,
)


@dataclass
class ApplicableRule:
    """可应用的通用规则。
    
    满足严格条件的规则，开发者确认后可一键应用到全局配置。
    """
    rule_id: str                      # 唯一标识
    language: str                     # 编程语言
    required_tags: List[str]          # 必需的标签组合
    suggested_context_level: str      # 建议的上下文级别
    confidence: float                 # 置信度
    sample_count: int                 # 样本数量
    consistency: float                # 一致性比例
    unique_files: int                 # 不同文件数
    conflict_type: str                # 原始冲突类型
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return asdict(self)
    
    def to_config(self) -> Dict[str, Any]:
        """转换为规则配置格式。"""
        return {
            "required_tags": self.required_tags,
            "context_level": self.suggested_context_level,
            "base_confidence": self.confidence,
            "notes": f"learned:{'+'.join(sorted(self.required_tags))}",
            "source": "conflict_learning",
            "rule_id": self.rule_id,
            "learned_at": datetime.now().isoformat(),
            "sample_count": self.sample_count,
            "consistency": self.consistency,
        }


@dataclass
class ReferenceHint:
    """参考提示（不可直接应用）。
    
    不满足自动应用条件的冲突模式，仅供开发者参考。
    """
    language: str                     # 编程语言
    tags: List[str]                   # 相关标签
    suggested_context_level: str      # 建议的上下文级别
    sample_count: int                 # 样本数量
    consistency: float                # 一致性比例
    reason: str                       # 不能自动应用的原因
    conflict_type: str                # 原始冲突类型
    unique_files: int = 0             # 不同文件数
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return asdict(self)


@dataclass(frozen=True)
class SemanticFeatureKey:
    """语义特征键，用于分组。
    
    基于语言、标签签名和冲突类型进行分组，
    不依赖文件路径，确保跨项目通用性。
    """
    language: str
    tags_signature: str  # 排序后的标签字符串，如 "api_endpoint|function_change"
    conflict_type: str
    
    @classmethod
    def from_conflict(cls, conflict: RuleConflict) -> "SemanticFeatureKey":
        """从冲突记录创建语义特征键。"""
        sorted_tags = sorted(conflict.tags)
        return cls(
            language=conflict.language,
            tags_signature="|".join(sorted_tags),
            conflict_type=conflict.conflict_type.value,
        )


class RuleAnalyzer:
    """规则分析器：从冲突中提取通用规则模式。"""
    
    # 可应用规则的严格条件
    MIN_OCCURRENCES = 5          # 最少出现次数
    MIN_CONSISTENCY = 0.9        # 最低一致性 (90%)
    MIN_COMMON_TAGS = 2          # 最少通用标签数
    MIN_UNIQUE_FILES = 2         # 最少不同文件数
    TAG_PRESENCE_THRESHOLD = 0.8 # 标签出现阈值 (80%)
    
    def __init__(self, tracker: Optional[ConflictTracker] = None):
        """初始化分析器。
        
        Args:
            tracker: 冲突追踪器实例，默认使用全局单例
        """
        self.tracker = tracker or get_conflict_tracker()
    
    def group_by_semantic_features(
        self, 
        conflicts: List[RuleConflict]
    ) -> Dict[SemanticFeatureKey, List[RuleConflict]]:
        """按语义特征分组冲突。
        
        基于语言、标签和冲突类型进行分组，不依赖文件路径。
        
        Args:
            conflicts: 冲突记录列表
            
        Returns:
            按语义特征键分组的冲突字典
        """
        groups: Dict[SemanticFeatureKey, List[RuleConflict]] = defaultdict(list)
        
        for conflict in conflicts:
            key = SemanticFeatureKey.from_conflict(conflict)
            groups[key].append(conflict)
        
        return dict(groups)
    
    def extract_common_tags(
        self, 
        conflicts: List[RuleConflict]
    ) -> List[str]:
        """提取出现在 80%+ 冲突中的通用标签。
        
        Args:
            conflicts: 冲突记录列表
            
        Returns:
            通用标签列表
        """
        if not conflicts:
            return []
        
        # 统计每个标签的出现次数
        tag_counts: Counter = Counter()
        for conflict in conflicts:
            # 使用 set 避免同一冲突中重复标签的重复计数
            for tag in set(conflict.tags):
                tag_counts[tag] += 1
        
        # 筛选出现在 80%+ 冲突中的标签
        threshold = len(conflicts) * self.TAG_PRESENCE_THRESHOLD
        common_tags = [
            tag for tag, count in tag_counts.items()
            if count >= threshold
        ]
        
        return sorted(common_tags)
    
    def calculate_consistency(
        self, 
        conflicts: List[RuleConflict]
    ) -> Tuple[float, Optional[str]]:
        """计算 LLM 决策一致性。
        
        Args:
            conflicts: 冲突记录列表
            
        Returns:
            (一致性比例, 最常见决策)
        """
        if not conflicts:
            return 0.0, None
        
        # 统计 LLM 决策
        decisions = [c.llm_context_level for c in conflicts if c.llm_context_level]
        
        if not decisions:
            return 0.0, None
        
        decision_counts = Counter(decisions)
        most_common_decision, most_common_count = decision_counts.most_common(1)[0]
        
        consistency = most_common_count / len(decisions)
        
        return consistency, most_common_decision
    
    def _generate_rule_id(
        self, 
        language: str, 
        tags: List[str], 
        conflict_type: str
    ) -> str:
        """生成规则唯一标识。"""
        content = f"{language}:{'+'.join(sorted(tags))}:{conflict_type}"
        hash_suffix = hashlib.md5(content.encode()).hexdigest()[:8]
        return f"rule_{language}_{hash_suffix}"
    
    def _get_failure_reason(
        self,
        sample_count: int,
        consistency: float,
        common_tags_count: int,
        unique_files: int,
    ) -> str:
        """获取不满足条件的原因。"""
        reasons = []
        
        if sample_count < self.MIN_OCCURRENCES:
            reasons.append(f"样本不足 ({sample_count} < {self.MIN_OCCURRENCES})")
        
        if consistency < self.MIN_CONSISTENCY:
            reasons.append(f"一致性不足 ({consistency:.0%} < {self.MIN_CONSISTENCY:.0%})")
        
        if common_tags_count < self.MIN_COMMON_TAGS:
            reasons.append(f"通用标签不足 ({common_tags_count} < {self.MIN_COMMON_TAGS})")
        
        if unique_files < self.MIN_UNIQUE_FILES:
            reasons.append(f"文件覆盖不足 ({unique_files} < {self.MIN_UNIQUE_FILES})")
        
        return "; ".join(reasons) if reasons else "未知原因"
    
    def evaluate_applicability(
        self, 
        conflicts: List[RuleConflict]
    ) -> Union[ApplicableRule, ReferenceHint]:
        """评估冲突组是否可生成可应用规则。
        
        Args:
            conflicts: 同一语义特征组的冲突列表
            
        Returns:
            ApplicableRule 或 ReferenceHint
        """
        if not conflicts:
            return ReferenceHint(
                language="unknown",
                tags=[],
                suggested_context_level="",
                sample_count=0,
                consistency=0.0,
                reason="无冲突记录",
                conflict_type="",
            )
        
        # 提取基本信息
        sample = conflicts[0]
        language = sample.language
        conflict_type = sample.conflict_type.value
        
        # 计算指标
        sample_count = len(conflicts)
        consistency, most_common_decision = self.calculate_consistency(conflicts)
        common_tags = self.extract_common_tags(conflicts)
        unique_files = len(set(c.file_path for c in conflicts))
        
        # 检查所有条件
        meets_occurrences = sample_count >= self.MIN_OCCURRENCES
        meets_consistency = consistency >= self.MIN_CONSISTENCY
        meets_tags = len(common_tags) >= self.MIN_COMMON_TAGS
        meets_files = unique_files >= self.MIN_UNIQUE_FILES
        
        all_conditions_met = (
            meets_occurrences and 
            meets_consistency and 
            meets_tags and 
            meets_files and
            most_common_decision is not None
        )
        
        if all_conditions_met:
            # 生成可应用规则
            rule_id = self._generate_rule_id(language, common_tags, conflict_type)
            
            # 计算置信度（基于一致性和样本数）
            confidence = min(0.95, consistency * (1 + min(sample_count - 5, 10) * 0.01))
            
            return ApplicableRule(
                rule_id=rule_id,
                language=language,
                required_tags=common_tags,
                suggested_context_level=most_common_decision,
                confidence=round(confidence, 2),
                sample_count=sample_count,
                consistency=round(consistency, 2),
                unique_files=unique_files,
                conflict_type=conflict_type,
            )
        else:
            # 生成参考提示
            reason = self._get_failure_reason(
                sample_count, consistency, len(common_tags), unique_files
            )
            
            # 使用所有标签（不仅是通用标签）
            all_tags = list(set(tag for c in conflicts for tag in c.tags))
            
            return ReferenceHint(
                language=language,
                tags=sorted(all_tags)[:5],  # 最多显示 5 个标签
                suggested_context_level=most_common_decision or "unknown",
                sample_count=sample_count,
                consistency=round(consistency, 2),
                reason=reason,
                conflict_type=conflict_type,
                unique_files=unique_files,
            )
    
    def analyze_all(
        self, 
        conflicts: Optional[List[RuleConflict]] = None
    ) -> Tuple[List[ApplicableRule], List[ReferenceHint]]:
        """分析所有冲突，返回可应用规则和参考提示。
        
        Args:
            conflicts: 冲突列表，默认从 tracker 加载
            
        Returns:
            (可应用规则列表, 参考提示列表)
        """
        if conflicts is None:
            conflicts = self.tracker._load_all_conflicts()
        
        if not conflicts:
            return [], []
        
        # 按语义特征分组
        groups = self.group_by_semantic_features(conflicts)
        
        applicable_rules: List[ApplicableRule] = []
        reference_hints: List[ReferenceHint] = []
        
        for key, group_conflicts in groups.items():
            result = self.evaluate_applicability(group_conflicts)
            
            if isinstance(result, ApplicableRule):
                applicable_rules.append(result)
            else:
                reference_hints.append(result)
        
        # 按样本数排序
        applicable_rules.sort(key=lambda r: r.sample_count, reverse=True)
        reference_hints.sort(key=lambda h: h.sample_count, reverse=True)
        
        return applicable_rules, reference_hints


# 全局单例
_analyzer: Optional[RuleAnalyzer] = None


def get_rule_analyzer() -> RuleAnalyzer:
    """获取全局规则分析器实例。"""
    global _analyzer
    if _analyzer is None:
        _analyzer = RuleAnalyzer()
    return _analyzer


__all__ = [
    "RuleAnalyzer",
    "ApplicableRule",
    "ReferenceHint",
    "SemanticFeatureKey",
    "get_rule_analyzer",
]
