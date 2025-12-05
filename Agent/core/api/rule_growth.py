"""规则自成长API模块。

提供规则冲突追踪、趋势分析、规则建议生成等功能的对外接口。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from Agent.DIFF.issue.conflict_tracker import (
    ConflictTracker,
    ConflictType,
    get_conflict_tracker,
)


class RuleGrowthAPI:
    """规则自成长API（静态方法接口）。
    
    提供以下功能：
    - 冲突汇总统计
    - 趋势分析
    - 规则建议生成
    - 模式提取
    - 冲突清理
    - 报告导出
    """
    
    @staticmethod
    def get_summary() -> Dict[str, Any]:
        """获取冲突汇总统计。
        
        Returns:
            Dict: {
                "total_conflicts": int,
                "by_type": Dict[str, int],
                "by_language": Dict[str, int],
                "by_rule_notes": Dict[str, int],
                "session_conflicts": int,
                "error": str | None
            }
        """
        try:
            tracker = get_conflict_tracker()
            summary = tracker.get_summary()
            return {
                **summary,
                "error": None,
            }
        except Exception as e:
            return {
                "total_conflicts": 0,
                "by_type": {},
                "by_language": {},
                "by_rule_notes": {},
                "session_conflicts": 0,
                "error": str(e),
            }
    
    @staticmethod
    def get_trend_analysis(days: int = 7) -> Dict[str, Any]:
        """获取冲突趋势分析。
        
        Args:
            days: 分析的天数范围，默认7天
            
        Returns:
            Dict: {
                "period_days": int,
                "total_conflicts": int,
                "average_daily": float,
                "change_rate_percent": float,
                "daily_trend": List[Dict],
                "most_common_type": str | None,
                "most_affected_language": str | None,
                "error": str | None
            }
        """
        try:
            tracker = get_conflict_tracker()
            trend = tracker.get_trend_analysis(days=days)
            return {
                **trend,
                "error": None,
            }
        except Exception as e:
            return {
                "period_days": days,
                "total_conflicts": 0,
                "average_daily": 0.0,
                "change_rate_percent": 0.0,
                "daily_trend": [],
                "most_common_type": None,
                "most_affected_language": None,
                "error": str(e),
            }

    
    @staticmethod
    def get_rule_suggestions() -> Dict[str, Any]:
        """生成规则优化建议。
        
        基于冲突分析，生成具体的规则配置建议。
        
        Returns:
            Dict: {
                "suggestions": List[{
                    "type": str,  # "upgrade_context_level" | "add_noise_detection" | "new_rule"
                    "rule_notes": str | None,
                    "language": str | None,
                    "file_pattern": str | None,
                    "current_behavior": str | None,
                    "suggested_change": str | None,
                    "suggested_context_level": str | None,
                    "suggested_confidence": float | None,
                    "occurrence_count": int,
                    "confidence": float,
                    "sample_files": List[str]
                }],
                "total_count": int,
                "error": str | None
            }
        """
        try:
            tracker = get_conflict_tracker()
            suggestions = tracker.generate_rule_suggestions()
            return {
                "suggestions": suggestions,
                "total_count": len(suggestions),
                "error": None,
            }
        except Exception as e:
            return {
                "suggestions": [],
                "total_count": 0,
                "error": str(e),
            }
    
    @staticmethod
    def get_extractable_patterns() -> Dict[str, Any]:
        """获取可提取的新规则模式。
        
        分析低置信度冲突中 LLM 多次给出相同决策的模式。
        
        Returns:
            Dict: {
                "patterns": List[{
                    "pattern_key": str,
                    "language": str,
                    "file_pattern": str,
                    "suggested_context_level": str,
                    "occurrence_count": int,
                    "common_tags": List[str],
                    "sample_files": List[str]
                }],
                "total_count": int,
                "error": str | None
            }
        """
        try:
            tracker = get_conflict_tracker()
            patterns = tracker.export_patterns()
            return {
                "patterns": patterns,
                "total_count": len(patterns),
                "error": None,
            }
        except Exception as e:
            return {
                "patterns": [],
                "total_count": 0,
                "error": str(e),
            }
    
    @staticmethod
    def get_high_priority_conflicts(limit: int = 10) -> Dict[str, Any]:
        """获取高优先级冲突列表。
        
        按优先级排序：
        1. RULE_HIGH_LLM_SKIP - 规则高置信度但 LLM 建议跳过
        2. RULE_HIGH_LLM_EXPAND - 规则可能低估复杂度
        3. RULE_LOW_LLM_CONSISTENT - 可提取新规则
        
        Args:
            limit: 返回数量限制，默认10
            
        Returns:
            Dict: {
                "conflicts": List[{
                    "conflict_type": str,
                    "unit_id": str,
                    "file_path": str,
                    "language": str,
                    "rule_context_level": str,
                    "rule_confidence": float,
                    "rule_notes": str,
                    "llm_context_level": str | None,
                    "llm_reason": str | None,
                    "timestamp": str
                }],
                "total_count": int,
                "error": str | None
            }
        """
        try:
            tracker = get_conflict_tracker()
            conflicts = tracker.get_high_priority_conflicts(limit=limit)
            
            conflicts_data = []
            for c in conflicts:
                conflicts_data.append({
                    "conflict_type": c.conflict_type.value,
                    "unit_id": c.unit_id,
                    "file_path": c.file_path,
                    "language": c.language,
                    "rule_context_level": c.rule_context_level,
                    "rule_confidence": c.rule_confidence,
                    "rule_notes": c.rule_notes,
                    "llm_context_level": c.llm_context_level,
                    "llm_reason": c.llm_reason,
                    "timestamp": c.timestamp,
                })
            
            return {
                "conflicts": conflicts_data,
                "total_count": len(conflicts_data),
                "error": None,
            }
        except Exception as e:
            return {
                "conflicts": [],
                "total_count": 0,
                "error": str(e),
            }
    
    @staticmethod
    def get_conflicts_by_type(
        conflict_type: str,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """按类型获取冲突记录。
        
        Args:
            conflict_type: 冲突类型，可选值：
                - "rule_high_llm_expand"
                - "rule_high_llm_skip"
                - "rule_low_llm_consistent"
                - "context_level_mismatch"
            limit: 返回数量限制，None 表示不限制
            
        Returns:
            Dict: {
                "conflicts": List[Dict],
                "total_count": int,
                "error": str | None
            }
        """
        try:
            tracker = get_conflict_tracker()
            ct = ConflictType(conflict_type)
            conflicts = tracker.get_conflicts_by_type(ct, limit=limit)
            
            conflicts_data = []
            for c in conflicts:
                conflicts_data.append({
                    "conflict_type": c.conflict_type.value,
                    "unit_id": c.unit_id,
                    "file_path": c.file_path,
                    "language": c.language,
                    "tags": c.tags,
                    "rule_context_level": c.rule_context_level,
                    "rule_confidence": c.rule_confidence,
                    "rule_notes": c.rule_notes,
                    "llm_context_level": c.llm_context_level,
                    "llm_skip_review": c.llm_skip_review,
                    "llm_reason": c.llm_reason,
                    "final_context_level": c.final_context_level,
                    "timestamp": c.timestamp,
                })
            
            return {
                "conflicts": conflicts_data,
                "total_count": len(conflicts_data),
                "error": None,
            }
        except ValueError as e:
            return {
                "conflicts": [],
                "total_count": 0,
                "error": f"Invalid conflict_type: {conflict_type}. Valid values: rule_high_llm_expand, rule_high_llm_skip, rule_low_llm_consistent, context_level_mismatch",
            }
        except Exception as e:
            return {
                "conflicts": [],
                "total_count": 0,
                "error": str(e),
            }

    
    @staticmethod
    def cleanup_old_conflicts(
        max_age_days: int = 30,
        max_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """清理旧的冲突记录。
        
        Args:
            max_age_days: 最大保留天数，超过此天数的记录将被删除
            max_count: 最大保留数量，超过此数量时删除最旧的记录
            
        Returns:
            Dict: {
                "deleted_count": int,
                "remaining_count": int,
                "error": str | None
            }
        """
        try:
            tracker = get_conflict_tracker()
            deleted = tracker.cleanup_old_conflicts(
                max_age_days=max_age_days,
                max_count=max_count,
            )
            
            # 获取剩余数量
            summary = tracker.get_summary()
            remaining = summary.get("total_conflicts", 0)
            
            return {
                "deleted_count": deleted,
                "remaining_count": remaining,
                "error": None,
            }
        except Exception as e:
            return {
                "deleted_count": 0,
                "remaining_count": 0,
                "error": str(e),
            }
    
    @staticmethod
    def export_report(output_path: Optional[str] = None) -> Dict[str, Any]:
        """导出完整的分析报告。
        
        Args:
            output_path: 输出文件路径，默认为 patterns/report_{timestamp}.json
            
        Returns:
            Dict: {
                "report_path": str,
                "report": Dict | None,  # 如果成功，包含完整报告内容
                "error": str | None
            }
        """
        try:
            tracker = get_conflict_tracker()
            report_path = tracker.export_report(output_path=output_path)
            
            # 读取报告内容
            import json
            with open(report_path, "r", encoding="utf-8") as f:
                report = json.load(f)
            
            return {
                "report_path": report_path,
                "report": report,
                "error": None,
            }
        except Exception as e:
            return {
                "report_path": "",
                "report": None,
                "error": str(e),
            }
    
    @staticmethod
    def get_conflict_types() -> Dict[str, Any]:
        """获取所有冲突类型及其说明。
        
        Returns:
            Dict: {
                "types": List[{
                    "value": str,
                    "name": str,
                    "description": str,
                    "optimization_hint": str
                }],
                "error": str | None
            }
        """
        types = [
            {
                "value": "rule_high_llm_expand",
                "name": "规则高置信度，LLM 要求更多上下文",
                "description": "规则高置信度建议较小上下文，但 LLM 认为需要更多上下文",
                "optimization_hint": "规则可能低估了变更的复杂度，考虑调整规则的上下文级别",
            },
            {
                "value": "rule_high_llm_skip",
                "name": "规则高置信度，LLM 建议跳过",
                "description": "规则高置信度认为需要审查，但 LLM 建议跳过",
                "optimization_hint": "规则可能高估了变更的风险，考虑添加噪音标签识别",
            },
            {
                "value": "rule_low_llm_consistent",
                "name": "规则低置信度，LLM 明确决策",
                "description": "规则低置信度无法确定，但 LLM 多次给出相同决策",
                "optimization_hint": "可以提取新规则，提高规则覆盖率",
            },
            {
                "value": "context_level_mismatch",
                "name": "上下文级别不匹配",
                "description": "中等置信度，上下文级别差异超过 1 级",
                "optimization_hint": "规则的置信度计算可能需要调整",
            },
        ]
        
        return {
            "types": types,
            "error": None,
        }
    
    @staticmethod
    def clear_session_conflicts() -> Dict[str, Any]:
        """清空当前会话的冲突缓存。
        
        Returns:
            Dict: {
                "cleared": bool,
                "error": str | None
            }
        """
        try:
            tracker = get_conflict_tracker()
            tracker.clear_session()
            return {
                "cleared": True,
                "error": None,
            }
        except Exception as e:
            return {
                "cleared": False,
                "error": str(e),
            }
    
    @staticmethod
    def get_session_conflicts() -> Dict[str, Any]:
        """获取当前会话的冲突记录。
        
        Returns:
            Dict: {
                "conflicts": List[Dict],
                "total_count": int,
                "error": str | None
            }
        """
        try:
            tracker = get_conflict_tracker()
            conflicts = tracker.get_session_conflicts()
            
            conflicts_data = []
            for c in conflicts:
                conflicts_data.append({
                    "conflict_type": c.conflict_type.value,
                    "unit_id": c.unit_id,
                    "file_path": c.file_path,
                    "language": c.language,
                    "rule_context_level": c.rule_context_level,
                    "rule_confidence": c.rule_confidence,
                    "llm_context_level": c.llm_context_level,
                    "timestamp": c.timestamp,
                })
            
            return {
                "conflicts": conflicts_data,
                "total_count": len(conflicts_data),
                "error": None,
            }
        except Exception as e:
            return {
                "conflicts": [],
                "total_count": 0,
                "error": str(e),
            }


__all__ = [
    "RuleGrowthAPI",
]
