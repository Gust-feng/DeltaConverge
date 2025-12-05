"""规则冲突追踪器：记录规则层与 LLM 决策之间的冲突。

冲突类型：
1. rule_high_llm_expand: 规则高置信度建议较小上下文，LLM 要求更多上下文
2. rule_high_llm_skip: 规则高置信度认为需要审查，LLM 建议跳过
3. rule_low_llm_consistent: 规则低置信度，LLM 给出明确决策（可提取新规则）
4. context_level_mismatch: 上下文级别不匹配（非高置信度情况）

存储路径：Agent/DIFF/issue/conflicts/

自成长机制功能：
- 冲突检测与记录
- 冲突汇总统计
- 模式提取与规则建议生成
- 冲突清理（按时间/数量）
- 趋势分析
- 规则建议导出
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from Agent.DIFF.rule.rule_config import ConfigDefaults


class ConflictType(Enum):
    """冲突类型枚举。"""
    RULE_HIGH_LLM_EXPAND = "rule_high_llm_expand"      # 规则高置信度，LLM 要求更多上下文
    RULE_HIGH_LLM_SKIP = "rule_high_llm_skip"          # 规则高置信度，LLM 建议跳过
    RULE_LOW_LLM_CONSISTENT = "rule_low_llm_consistent"  # 规则低置信度，LLM 明确决策
    CONTEXT_LEVEL_MISMATCH = "context_level_mismatch"  # 上下文级别不匹配


@dataclass
class RuleConflict:
    """规则冲突记录。"""
    conflict_type: ConflictType
    unit_id: str
    file_path: str
    language: str
    tags: List[str]
    metrics: Dict[str, Any]
    
    # 规则决策
    rule_context_level: str
    rule_confidence: float
    rule_notes: str
    rule_extra_requests: List[Dict[str, Any]] = field(default_factory=list)
    
    # LLM 决策
    llm_context_level: Optional[str] = None
    llm_skip_review: bool = False
    llm_reason: Optional[str] = None
    llm_extra_requests: List[Dict[str, Any]] = field(default_factory=list)
    
    # 最终决策
    final_context_level: Optional[str] = None
    
    # 元数据
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    diff_snippet: Optional[str] = None  # 可选，用于后续分析
    symbol_info: Optional[Dict[str, Any]] = None  # 符号信息
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        data = asdict(self)
        data["conflict_type"] = self.conflict_type.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleConflict":
        """从字典创建实例。"""
        data = data.copy()
        data["conflict_type"] = ConflictType(data["conflict_type"])
        return cls(**data)


# 上下文级别优先级（用于比较）
_CONTEXT_LEVEL_RANK = {
    "diff_only": 0,
    "local": 0,
    "function": 1,
    "file_context": 2,
    "file": 2,
    "full_file": 3,
}


def _get_context_rank(level: Optional[str]) -> int:
    """获取上下文级别的优先级排名。"""
    if not level:
        return -1
    return _CONTEXT_LEVEL_RANK.get(level, -1)


class ConflictTracker:
    """规则冲突追踪器。"""
    
    def __init__(self, base_dir: Optional[str] = None):
        """初始化追踪器。
        
        Args:
            base_dir: 基础目录，默认为 Agent/DIFF/issue
        """
        if base_dir is None:
            # 默认路径：Agent/DIFF/issue
            base_dir = str(Path(__file__).parent)
        
        self.base_dir = Path(base_dir)
        self.conflicts_dir = self.base_dir / "conflicts"
        self.patterns_dir = self.base_dir / "patterns"
        
        # 确保目录存在
        self.conflicts_dir.mkdir(parents=True, exist_ok=True)
        self.patterns_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存中的冲突缓存（当前会话）
        self._session_conflicts: List[RuleConflict] = []
    
    def detect_conflict(
        self,
        unit: Dict[str, Any],
        llm_decision: Dict[str, Any],
    ) -> Optional[RuleConflict]:
        """检测规则与 LLM 决策之间的冲突。
        
        Args:
            unit: 变更单元（包含规则决策）
            llm_decision: LLM 决策
            
        Returns:
            如果检测到冲突，返回 RuleConflict；否则返回 None
        """
        rule_confidence = float(unit.get("rule_confidence") or 0.0)
        rule_level = unit.get("rule_context_level") or "function"
        llm_level = llm_decision.get("llm_context_level")
        llm_skip = bool(llm_decision.get("skip_review", False))
        
        conflict_type: Optional[ConflictType] = None
        
        # 场景 1: 规则高置信度，LLM 要求更多上下文
        if rule_confidence >= ConfigDefaults.CONFIDENCE_HIGH:
            rule_rank = _get_context_rank(rule_level)
            llm_rank = _get_context_rank(llm_level)
            
            if llm_rank > rule_rank and llm_rank >= 0:
                conflict_type = ConflictType.RULE_HIGH_LLM_EXPAND
            
            # 场景 2: 规则高置信度，LLM 建议跳过（但规则认为需要审查）
            elif llm_skip and rule_level not in ("diff_only", "local"):
                conflict_type = ConflictType.RULE_HIGH_LLM_SKIP
        
        # 场景 3: 规则低置信度，LLM 给出明确决策
        elif rule_confidence < ConfigDefaults.CONFIDENCE_LOW:
            if llm_level and _get_context_rank(llm_level) >= 0:
                conflict_type = ConflictType.RULE_LOW_LLM_CONSISTENT
        
        # 场景 4: 中等置信度，上下文级别不匹配
        else:
            rule_rank = _get_context_rank(rule_level)
            llm_rank = _get_context_rank(llm_level)
            
            # 差异超过 1 级才记录
            if llm_rank >= 0 and abs(llm_rank - rule_rank) > 1:
                conflict_type = ConflictType.CONTEXT_LEVEL_MISMATCH
        
        if conflict_type is None:
            return None
        
        # 创建冲突记录
        conflict = RuleConflict(
            conflict_type=conflict_type,
            unit_id=str(unit.get("unit_id") or unit.get("id") or ""),
            file_path=unit.get("file_path", ""),
            language=unit.get("language", "unknown"),
            tags=unit.get("tags", []),
            metrics=unit.get("metrics", {}),
            rule_context_level=rule_level,
            rule_confidence=rule_confidence,
            rule_notes=unit.get("rule_notes") or "",
            rule_extra_requests=unit.get("rule_extra_requests") or [],
            llm_context_level=llm_level,
            llm_skip_review=llm_skip,
            llm_reason=llm_decision.get("reason"),
            llm_extra_requests=llm_decision.get("extra_requests") or [],
            final_context_level=llm_decision.get("final_context_level"),
            symbol_info=unit.get("symbol"),
        )
        
        return conflict
    
    def record(self, conflict: RuleConflict) -> str:
        """记录冲突到文件。
        
        Args:
            conflict: 冲突记录
            
        Returns:
            保存的文件路径
        """
        # 添加到会话缓存
        self._session_conflicts.append(conflict)
        
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}_{conflict.conflict_type.value}.json"
        filepath = self.conflicts_dir / filename
        
        # 保存到文件
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(conflict.to_dict(), f, ensure_ascii=False, indent=2)
        
        return str(filepath)
    
    def detect_and_record(
        self,
        unit: Dict[str, Any],
        llm_decision: Dict[str, Any],
    ) -> Optional[str]:
        """检测并记录冲突。
        
        Args:
            unit: 变更单元
            llm_decision: LLM 决策
            
        Returns:
            如果记录了冲突，返回文件路径；否则返回 None
        """
        conflict = self.detect_conflict(unit, llm_decision)
        if conflict:
            return self.record(conflict)
        return None
    
    def get_session_conflicts(self) -> List[RuleConflict]:
        """获取当前会话的所有冲突。"""
        return list(self._session_conflicts)
    
    def clear_session(self) -> None:
        """清空当前会话的冲突缓存。"""
        self._session_conflicts.clear()
    
    def get_summary(self) -> Dict[str, Any]:
        """获取冲突汇总统计。
        
        Returns:
            汇总统计字典
        """
        # 读取所有冲突文件
        conflicts: List[RuleConflict] = []
        for filepath in self.conflicts_dir.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    conflicts.append(RuleConflict.from_dict(data))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        # 统计
        by_type: Dict[str, int] = {}
        by_language: Dict[str, int] = {}
        by_rule_notes: Dict[str, int] = {}
        
        for conflict in conflicts:
            # 按类型统计
            type_key = conflict.conflict_type.value
            by_type[type_key] = by_type.get(type_key, 0) + 1
            
            # 按语言统计
            lang = conflict.language
            by_language[lang] = by_language.get(lang, 0) + 1
            
            # 按规则备注统计（提取规则类型）
            notes = conflict.rule_notes
            if notes:
                # 提取主要规则标识（如 "py:decorator:django_view" -> "py:decorator"）
                parts = notes.split(":")
                if len(parts) >= 2:
                    rule_key = ":".join(parts[:2])
                else:
                    rule_key = notes
                by_rule_notes[rule_key] = by_rule_notes.get(rule_key, 0) + 1
        
        return {
            "total_conflicts": len(conflicts),
            "by_type": by_type,
            "by_language": by_language,
            "by_rule_notes": by_rule_notes,
            "session_conflicts": len(self._session_conflicts),
        }
    
    def export_patterns(self) -> List[Dict[str, Any]]:
        """导出可提取的新规则模式。
        
        分析 RULE_LOW_LLM_CONSISTENT 类型的冲突，
        找出 LLM 多次给出相同决策的模式。
        
        Returns:
            可提取的规则模式列表
        """
        # 读取所有 RULE_LOW_LLM_CONSISTENT 类型的冲突
        conflicts: List[RuleConflict] = []
        for filepath in self.conflicts_dir.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    conflict = RuleConflict.from_dict(data)
                    if conflict.conflict_type == ConflictType.RULE_LOW_LLM_CONSISTENT:
                        conflicts.append(conflict)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        
        # 按文件路径模式和语言分组
        patterns: Dict[str, List[RuleConflict]] = {}
        for conflict in conflicts:
            # 提取文件路径模式（如 "models.py", "views.py" 等）
            file_path = conflict.file_path
            filename = os.path.basename(file_path)
            
            # 构建模式键
            pattern_key = f"{conflict.language}:{filename}:{conflict.llm_context_level}"
            
            if pattern_key not in patterns:
                patterns[pattern_key] = []
            patterns[pattern_key].append(conflict)
        
        # 筛选出现次数 >= 3 的模式
        suggested_rules: List[Dict[str, Any]] = []
        for pattern_key, pattern_conflicts in patterns.items():
            if len(pattern_conflicts) >= 3:
                # 提取共同特征
                sample = pattern_conflicts[0]
                common_tags = set(sample.tags)
                for c in pattern_conflicts[1:]:
                    common_tags &= set(c.tags)
                
                suggested_rules.append({
                    "pattern_key": pattern_key,
                    "language": sample.language,
                    "file_pattern": os.path.basename(sample.file_path),
                    "suggested_context_level": sample.llm_context_level,
                    "occurrence_count": len(pattern_conflicts),
                    "common_tags": list(common_tags),
                    "sample_files": [c.file_path for c in pattern_conflicts[:5]],
                })
        
        return suggested_rules
    
    def _load_all_conflicts(self) -> List[RuleConflict]:
        """加载所有冲突记录。
        
        Returns:
            冲突记录列表
        """
        conflicts: List[RuleConflict] = []
        for filepath in self.conflicts_dir.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    conflicts.append(RuleConflict.from_dict(data))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return conflicts
    
    def cleanup_old_conflicts(
        self,
        max_age_days: int = 30,
        max_count: Optional[int] = None,
    ) -> int:
        """清理旧的冲突记录。
        
        Args:
            max_age_days: 最大保留天数，超过此天数的记录将被删除
            max_count: 最大保留数量，超过此数量时删除最旧的记录
            
        Returns:
            删除的记录数量
        """
        deleted_count = 0
        cutoff_date = datetime.now() - timedelta(days=max_age_days)
        
        # 收集所有文件及其时间戳
        files_with_time: List[Tuple[Path, datetime]] = []
        for filepath in self.conflicts_dir.glob("*.json"):
            try:
                # 从文件名提取时间戳
                filename = filepath.stem
                timestamp_str = "_".join(filename.split("_")[:3])
                file_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S_%f")
                files_with_time.append((filepath, file_time))
            except (ValueError, IndexError):
                # 无法解析时间戳，使用文件修改时间
                mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
                files_with_time.append((filepath, mtime))
        
        # 按时间排序（最旧的在前）
        files_with_time.sort(key=lambda x: x[1])
        
        # 按时间删除
        for filepath, file_time in files_with_time:
            if file_time < cutoff_date:
                try:
                    filepath.unlink()
                    deleted_count += 1
                except OSError:
                    pass
        
        # 按数量删除（如果指定了 max_count）
        if max_count is not None:
            remaining_files = list(self.conflicts_dir.glob("*.json"))
            if len(remaining_files) > max_count:
                # 重新排序剩余文件
                remaining_with_time: List[Tuple[Path, datetime]] = []
                for filepath in remaining_files:
                    try:
                        filename = filepath.stem
                        timestamp_str = "_".join(filename.split("_")[:3])
                        file_time = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S_%f")
                        remaining_with_time.append((filepath, file_time))
                    except (ValueError, IndexError):
                        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
                        remaining_with_time.append((filepath, mtime))
                
                remaining_with_time.sort(key=lambda x: x[1])
                
                # 删除超出数量的最旧文件
                to_delete = len(remaining_with_time) - max_count
                for filepath, _ in remaining_with_time[:to_delete]:
                    try:
                        filepath.unlink()
                        deleted_count += 1
                    except OSError:
                        pass
        
        return deleted_count
    
    def get_trend_analysis(self, days: int = 7) -> Dict[str, Any]:
        """获取冲突趋势分析。
        
        Args:
            days: 分析的天数范围
            
        Returns:
            趋势分析结果
        """
        conflicts = self._load_all_conflicts()
        cutoff_date = datetime.now() - timedelta(days=days)
        
        # 按日期分组统计
        daily_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        recent_conflicts: List[RuleConflict] = []
        
        for conflict in conflicts:
            try:
                conflict_time = datetime.fromisoformat(conflict.timestamp)
                if conflict_time >= cutoff_date:
                    recent_conflicts.append(conflict)
                    date_key = conflict_time.strftime("%Y-%m-%d")
                    daily_counts[date_key][conflict.conflict_type.value] += 1
                    daily_counts[date_key]["total"] += 1
            except (ValueError, TypeError):
                continue
        
        # 计算趋势
        dates = sorted(daily_counts.keys())
        trend_data = []
        for date in dates:
            trend_data.append({
                "date": date,
                "total": daily_counts[date]["total"],
                "by_type": dict(daily_counts[date]),
            })
        
        # 计算平均值和变化率
        total_counts = [d["total"] for d in trend_data]
        avg_daily = sum(total_counts) / len(total_counts) if total_counts else 0
        
        # 计算最近一天与平均值的变化
        change_rate = 0.0
        if len(total_counts) >= 2 and avg_daily > 0:
            latest = total_counts[-1]
            change_rate = (latest - avg_daily) / avg_daily * 100
        
        return {
            "period_days": days,
            "total_conflicts": len(recent_conflicts),
            "average_daily": round(avg_daily, 2),
            "change_rate_percent": round(change_rate, 2),
            "daily_trend": trend_data,
            "most_common_type": self._get_most_common(
                [c.conflict_type.value for c in recent_conflicts]
            ),
            "most_affected_language": self._get_most_common(
                [c.language for c in recent_conflicts]
            ),
        }
    
    def _get_most_common(self, items: List[str]) -> Optional[str]:
        """获取列表中出现最多的元素。"""
        if not items:
            return None
        counts: Dict[str, int] = {}
        for item in items:
            counts[item] = counts.get(item, 0) + 1
        return max(counts, key=lambda k: counts[k])
    
    def generate_rule_suggestions(self) -> List[Dict[str, Any]]:
        """生成规则优化建议。
        
        基于冲突分析，生成具体的规则配置建议。
        
        Returns:
            规则建议列表
        """
        conflicts = self._load_all_conflicts()
        suggestions: List[Dict[str, Any]] = []
        
        # 分析 RULE_HIGH_LLM_EXPAND 类型：规则可能低估了复杂度
        expand_conflicts = [
            c for c in conflicts 
            if c.conflict_type == ConflictType.RULE_HIGH_LLM_EXPAND
        ]
        if expand_conflicts:
            # 按规则备注分组
            by_notes: Dict[str, List[RuleConflict]] = defaultdict(list)
            for c in expand_conflicts:
                if c.rule_notes:
                    by_notes[c.rule_notes].append(c)
            
            for notes, group in by_notes.items():
                if len(group) >= 2:
                    # 计算 LLM 建议的平均上下文级别
                    llm_levels = [c.llm_context_level for c in group if c.llm_context_level]
                    if llm_levels:
                        most_common_level = self._get_most_common(llm_levels)
                        suggestions.append({
                            "type": "upgrade_context_level",
                            "rule_notes": notes,
                            "current_behavior": "规则建议较小上下文",
                            "suggested_change": f"考虑将上下文级别提升到 {most_common_level}",
                            "occurrence_count": len(group),
                            "confidence": min(0.9, 0.5 + len(group) * 0.1),
                            "sample_files": [c.file_path for c in group[:3]],
                        })
        
        # 分析 RULE_HIGH_LLM_SKIP 类型：规则可能高估了风险
        skip_conflicts = [
            c for c in conflicts 
            if c.conflict_type == ConflictType.RULE_HIGH_LLM_SKIP
        ]
        if skip_conflicts:
            by_notes: Dict[str, List[RuleConflict]] = defaultdict(list)
            for c in skip_conflicts:
                if c.rule_notes:
                    by_notes[c.rule_notes].append(c)
            
            for notes, group in by_notes.items():
                if len(group) >= 3:
                    # 分析共同标签
                    common_tags = set(group[0].tags)
                    for c in group[1:]:
                        common_tags &= set(c.tags)
                    
                    suggestions.append({
                        "type": "add_noise_detection",
                        "rule_notes": notes,
                        "current_behavior": "规则认为需要审查",
                        "suggested_change": "考虑添加噪音标签识别，减少误报",
                        "common_tags": list(common_tags),
                        "occurrence_count": len(group),
                        "confidence": min(0.85, 0.4 + len(group) * 0.1),
                        "sample_files": [c.file_path for c in group[:3]],
                    })
        
        # 分析 RULE_LOW_LLM_CONSISTENT 类型：可以提取新规则
        consistent_conflicts = [
            c for c in conflicts 
            if c.conflict_type == ConflictType.RULE_LOW_LLM_CONSISTENT
        ]
        if consistent_conflicts:
            # 按语言和文件模式分组
            by_pattern: Dict[str, List[RuleConflict]] = defaultdict(list)
            for c in consistent_conflicts:
                filename = os.path.basename(c.file_path)
                pattern_key = f"{c.language}:{filename}"
                by_pattern[pattern_key].append(c)
            
            for pattern_key, group in by_pattern.items():
                if len(group) >= 3:
                    # 检查 LLM 决策是否一致
                    llm_levels = [c.llm_context_level for c in group if c.llm_context_level]
                    if llm_levels:
                        most_common = self._get_most_common(llm_levels)
                        consistency = llm_levels.count(most_common) / len(llm_levels)
                        
                        if consistency >= 0.7:
                            lang, filename = pattern_key.split(":", 1)
                            suggestions.append({
                                "type": "new_rule",
                                "language": lang,
                                "file_pattern": filename,
                                "suggested_context_level": most_common,
                                "suggested_confidence": 0.75,
                                "occurrence_count": len(group),
                                "consistency": round(consistency, 2),
                                "sample_files": [c.file_path for c in group[:3]],
                            })
        
        # 按置信度排序
        suggestions.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        return suggestions
    
    def export_report(self, output_path: Optional[str] = None) -> str:
        """导出完整的分析报告。
        
        Args:
            output_path: 输出文件路径，默认为 patterns/report_{timestamp}.json
            
        Returns:
            报告文件路径
        """
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = str(self.patterns_dir / f"report_{timestamp}.json")
        
        report = {
            "generated_at": datetime.now().isoformat(),
            "summary": self.get_summary(),
            "trend_analysis": self.get_trend_analysis(days=7),
            "patterns": self.export_patterns(),
            "rule_suggestions": self.generate_rule_suggestions(),
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        return output_path
    
    def get_conflicts_by_type(
        self, 
        conflict_type: ConflictType,
        limit: Optional[int] = None,
    ) -> List[RuleConflict]:
        """按类型获取冲突记录。
        
        Args:
            conflict_type: 冲突类型
            limit: 返回数量限制
            
        Returns:
            冲突记录列表
        """
        conflicts = self._load_all_conflicts()
        filtered = [c for c in conflicts if c.conflict_type == conflict_type]
        
        # 按时间倒序排序
        filtered.sort(key=lambda c: c.timestamp, reverse=True)
        
        if limit:
            return filtered[:limit]
        return filtered
    
    def get_high_priority_conflicts(self, limit: int = 10) -> List[RuleConflict]:
        """获取高优先级冲突（需要优先处理的）。
        
        优先级规则：
        1. RULE_HIGH_LLM_SKIP - 规则高置信度但 LLM 建议跳过（可能误报）
        2. RULE_HIGH_LLM_EXPAND - 规则可能低估复杂度
        3. RULE_LOW_LLM_CONSISTENT - 可提取新规则
        
        Args:
            limit: 返回数量限制
            
        Returns:
            高优先级冲突列表
        """
        conflicts = self._load_all_conflicts()
        
        # 按优先级分组
        priority_order = [
            ConflictType.RULE_HIGH_LLM_SKIP,
            ConflictType.RULE_HIGH_LLM_EXPAND,
            ConflictType.RULE_LOW_LLM_CONSISTENT,
            ConflictType.CONTEXT_LEVEL_MISMATCH,
        ]
        
        result: List[RuleConflict] = []
        for conflict_type in priority_order:
            type_conflicts = [c for c in conflicts if c.conflict_type == conflict_type]
            type_conflicts.sort(key=lambda c: c.timestamp, reverse=True)
            result.extend(type_conflicts)
            if len(result) >= limit:
                break
        
        return result[:limit]


# 全局单例
_tracker: Optional[ConflictTracker] = None


def get_conflict_tracker() -> ConflictTracker:
    """获取全局冲突追踪器实例。"""
    global _tracker
    if _tracker is None:
        _tracker = ConflictTracker()
    return _tracker


def record_conflict(
    unit: Dict[str, Any],
    llm_decision: Dict[str, Any],
) -> Optional[str]:
    """便捷函数：检测并记录冲突。
    
    Args:
        unit: 变更单元
        llm_decision: LLM 决策
        
    Returns:
        如果记录了冲突，返回文件路径；否则返回 None
    """
    tracker = get_conflict_tracker()
    return tracker.detect_and_record(unit, llm_decision)
