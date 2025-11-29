"""Rule handler base classes and shared helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple, Union

from Agent.DIFF.rule.rule_config import get_rule_config


@dataclass
class RuleSuggestion:
    context_level: str  # local | function | file | unknown
    confidence: float
    notes: str
    extra_requests: list[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if not payload.get("extra_requests"):
            payload.pop("extra_requests", None)
        return payload


class RuleHandler:
    """Base class for language-specific rule handlers."""
    
    def __init__(self, language: Optional[str] = None):
        """Initialize rule handler with language-specific configuration.
        
        Args:
            language: The language for this handler (e.g., "python", "typescript")
        """
        self.language = language
        self.config = get_rule_config()
        self.language_config = self.config.get("languages", {}).get(language, {}) if language else {}
    
    def _get_base_config(self, key: str, default: Any = None) -> Any:
        """Get base configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        return self.config.get("base", {}).get(key, default)
    
    def _get_language_config(self, key: str, default: Any = None) -> Any:
        """Get language-specific configuration value.
        
        Args:
            key: Configuration key
            default: Default value if key not found
            
        Returns:
            Configuration value or default
        """
        return self.language_config.get(key, default)

    def _total_changed(self, metrics: Dict[str, Any]) -> int:
        """Calculate total changed lines from metrics."""
        added = int(metrics.get("added_lines", 0) or 0)
        removed = int(metrics.get("removed_lines", 0) or 0)
        return added + removed

    def _match_path_rules(self, file_path: str, path_rules: List[Dict[str, Any]], unit: Dict[str, Any]) -> Optional[RuleSuggestion]:
        """Match file path against a list of path rules from configuration.
        
        Args:
            file_path: The file path to match
            path_rules: List of path rule dictionaries from configuration
            unit: The unit dictionary containing file information
            
        Returns:
            RuleSuggestion if matched, None otherwise
        """
        import os
        
        # 按照base_confidence降序排列规则，确保高优先级规则先被匹配
        sorted_rules = sorted(path_rules, key=lambda x: x.get("base_confidence", x.get("confidence", 0.0)), reverse=True)
        
        for rule in sorted_rules:
            patterns = rule.get("match", [])
            if not patterns:
                continue
            
            # 标准化文件路径，确保路径分隔符一致
            normalized_file_path = os.path.normpath(file_path).lower()
            
            for pattern in patterns:
                if not pattern:
                    continue
                
                # 标准化模式，确保路径分隔符一致
                normalized_pattern = os.path.normpath(pattern).lower()
                
                # 检查精确匹配
                if normalized_file_path == normalized_pattern:
                    # Calculate final confidence
                    confidence = self._calculate_confidence(rule, unit)
                    
                    return RuleSuggestion(
                        context_level=rule.get("context_level", "function"),
                        confidence=confidence,
                        notes=rule.get("notes", "lang:path_rule"),
                        extra_requests=rule.get("extra_requests", [])
                    )
                
                # 检查目录前缀匹配（确保是完整目录）
                if normalized_file_path.startswith(normalized_pattern + os.sep):
                    # Calculate final confidence
                    confidence = self._calculate_confidence(rule, unit)
                    
                    return RuleSuggestion(
                        context_level=rule.get("context_level", "function"),
                        confidence=confidence,
                        notes=rule.get("notes", "lang:path_rule"),
                        extra_requests=rule.get("extra_requests", [])
                    )
                
                # 检查文件名匹配（确保是完整文件名）
                if os.path.basename(normalized_file_path) == normalized_pattern:
                    # Calculate final confidence
                    confidence = self._calculate_confidence(rule, unit)
                    
                    return RuleSuggestion(
                        context_level=rule.get("context_level", "function"),
                        confidence=confidence,
                        notes=rule.get("notes", "lang:path_rule"),
                        extra_requests=rule.get("extra_requests", [])
                    )
                
                # 检查路径中包含完整目录（使用路径分隔符包围）
                if os.sep + normalized_pattern + os.sep in normalized_file_path:
                    # Calculate final confidence
                    confidence = self._calculate_confidence(rule, unit)
                    
                    return RuleSuggestion(
                        context_level=rule.get("context_level", "function"),
                        confidence=confidence,
                        notes=rule.get("notes", "lang:path_rule"),
                        extra_requests=rule.get("extra_requests", [])
                    )
        return None

    def _match_keywords(self, haystack: str, keywords: List[str], unit: Dict[str, Any], context_level: str = "function", confidence: float = 0.82, note_prefix: str = "lang:kw:") -> Optional[RuleSuggestion]:
        """Match keywords against a haystack string.
        
        Args:
            haystack: The string to search in
            keywords: List of keywords to match
            unit: The unit dictionary containing file information
            context_level: Default context level if matched
            confidence: Default confidence if matched
            note_prefix: Prefix for notes if matched
            
        Returns:
            RuleSuggestion if matched, None otherwise
        """
        import re
        
        for kw in keywords:
            if not kw:
                continue
            
            # 使用词边界检查，确保匹配的是完整单词
            # 添加前后词边界，避免部分匹配（如"test"匹配"testing"）
            pattern = re.compile(r'\b' + re.escape(kw) + r'\b', re.IGNORECASE)
            if pattern.search(haystack):
                # Create a temporary rule for keyword matching
                keyword_rule = {
                    "base_confidence": confidence,
                    "confidence_adjusters": {
                        "security_sensitive": 0.1 if kw in self._get_base_config("security_keywords", []) else 0.0
                    }
                }
                # Calculate final confidence
                final_confidence = self._calculate_confidence(keyword_rule, unit)
                
                return RuleSuggestion(
                    context_level=context_level,
                    confidence=final_confidence,
                    notes=f"{note_prefix}{kw}",
                )
        return None

    def _build_haystack(self, file_path: str, sym_name: str, tags: set) -> str:
        """Build a haystack string for keyword matching.
        
        Args:
            file_path: The file path
            sym_name: The symbol name
            tags: Set of tags
            
        Returns:
            Combined haystack string
        """
        return " ".join([file_path, sym_name, " ".join(tags)])
    
    def _match_symbol_rules(self, symbol: Dict[str, Any], sym_rules: List[Dict[str, Any]], unit: Dict[str, Any]) -> Optional[RuleSuggestion]:
        """Match symbol against a list of symbol rules.
        
        Args:
            symbol: The symbol dictionary to match
            sym_rules: List of symbol rule dictionaries
            unit: The unit dictionary containing file information
            
        Returns:
            RuleSuggestion if matched, None otherwise
        """
        # 增强symbol处理，支持多种结构
        processed_symbol = symbol.copy()
        
        # 如果symbol包含functions或classes列表，提取第一个作为主要符号
        if "functions" in processed_symbol and processed_symbol["functions"]:
            func = processed_symbol["functions"][0]
            processed_symbol.update({
                "kind": "function",
                "name": func.get("name", ""),
                "start_line": func.get("start_line", 0),
                "end_line": func.get("end_line", 0)
            })
        elif "classes" in processed_symbol and processed_symbol["classes"]:
            cls = processed_symbol["classes"][0]
            processed_symbol.update({
                "kind": "class",
                "name": cls.get("name", ""),
                "start_line": cls.get("start_line", 0),
                "end_line": cls.get("end_line", 0)
            })
        
        # 按照base_confidence降序排列规则，确保高优先级规则先被匹配
        sorted_rules = sorted(sym_rules, key=lambda x: x.get("base_confidence", x.get("confidence", 0.0)), reverse=True)
        
        for rule in sorted_rules:
            sym_type = rule.get("type")
            sym_name_patterns = rule.get("name_patterns", [])
            
            # Check symbol type match
            if sym_type and processed_symbol.get("kind") != sym_type:
                continue
            
            # Check symbol name match
            sym_name = processed_symbol.get("name", "").lower()
            if sym_name_patterns and not any(pattern in sym_name for pattern in sym_name_patterns):
                continue
            
            # Calculate final confidence
            confidence = self._calculate_confidence(rule, unit)
            
            # All conditions matched
            return RuleSuggestion(
                context_level=rule.get("context_level", "function"),
                confidence=confidence,
                notes=rule.get("notes", "lang:sym_rule"),
                extra_requests=rule.get("extra_requests", [])
            )
        return None
    
    def _calculate_confidence(self, rule: Dict[str, Any], unit: Dict[str, Any]) -> float:
        """Calculate final confidence based on base confidence and dynamic adjusters.
        
        Args:
            rule: The rule dictionary containing base_confidence and confidence_adjusters
            unit: The unit dictionary containing file information
            
        Returns:
            Final confidence value between 0.0 and 1.0, following the confidence intervals:
            - 0.8 ~ 1.0: High confidence (HIGH)
            - 0.5 ~ 0.8: Medium confidence (MEDIUM)
            - 0.0 ~ 0.5: Low confidence (LOW)
        """
        # Get base confidence from rule, default to 0.4 if not found (low confidence)
        base_confidence = rule.get("base_confidence", rule.get("confidence", 0.4))
        
        # Get confidence adjusters from rule, default to empty dict
        adjusters = rule.get("confidence_adjusters", {})
        
        # Calculate adjustment factors
        adjustment = 0.0
        
        # 1. File size adjustment
        file_size_factor = adjusters.get("file_size", 0.0)
        if file_size_factor != 0.0:
            metrics = unit.get("metrics", {})
            total_changed = self._total_changed(metrics)
            # Small files get negative adjustment, large files get positive adjustment
            # 优化：使用更精细的文件大小调整逻辑
            if total_changed < 5:
                adjustment += file_size_factor * -0.15  # 极小文件，更大的负调整
            elif total_changed < 20:
                adjustment += file_size_factor * -0.05  # 小文件，较小的负调整
            elif total_changed > 150:
                adjustment += file_size_factor * 0.15  # 极大文件，更大的正调整
            elif total_changed > 80:
                adjustment += file_size_factor * 0.08  # 大文件，较小的正调整
        
        # 2. Change type adjustment
        change_type_factor = adjusters.get("change_type", 0.0)
        if change_type_factor != 0.0:
            change_type = unit.get("change_type", "modify")
            # 优化：根据变更类型的风险程度调整
            if change_type == "delete":
                adjustment += change_type_factor * 0.12  # 删除操作，更高的置信度
            elif change_type == "add":
                adjustment += change_type_factor * 0.08  # 添加操作，中等置信度
            elif change_type == "rename":
                adjustment += change_type_factor * 0.05  # 重命名操作，较低置信度
        
        # 3. Security sensitive adjustment
        security_factor = adjusters.get("security_sensitive", 0.0)
        if security_factor != 0.0:
            file_path = unit.get("file_path", "").lower()
            tags = set(unit.get("tags", []) or [])
            security_keywords = self._get_base_config("security_keywords", [])
            # 优化：综合考虑路径和标签
            is_security_sensitive = "security_sensitive" in tags or any(kw in file_path for kw in security_keywords)
            if is_security_sensitive:
                adjustment += security_factor * 0.15  # 安全敏感，更高的置信度调整
        
        # 4. Rule specificity adjustment
        specificity_factor = adjusters.get("rule_specificity", 0.0)
        if specificity_factor != 0.0:
            # 优化：根据规则的匹配条件数量调整特异性
            rule_specificity = 0
            if "match" in rule and rule["match"]:
                rule_specificity += 1
            if "type" in rule:
                rule_specificity += 1
            if "name_patterns" in rule and rule["name_patterns"]:
                rule_specificity += 1
            if "min_lines" in rule or "max_lines" in rule:
                rule_specificity += 1
            if "min_hunks" in rule or "max_hunks" in rule:
                rule_specificity += 1
            
            # 规则条件越多，特异性越高，置信度调整越大
            adjustment += specificity_factor * (rule_specificity * 0.02)  # 每个条件增加0.02的置信度
        
        # Calculate final confidence
        final_confidence = base_confidence + adjustment
        
        # Ensure confidence is between 0.0 and 1.0
        final_confidence = max(0.0, min(1.0, final_confidence))
        
        return final_confidence
    
    def _match_metric_rules(self, metrics: Dict[str, Any], metric_rules: List[Dict[str, Any]], unit: Dict[str, Any]) -> Optional[RuleSuggestion]:
        """Match metrics against a list of metric rules.
        
        Args:
            metrics: The metrics dictionary to match
            metric_rules: List of metric rule dictionaries
            unit: The unit dictionary containing file information
            
        Returns:
            RuleSuggestion if matched, None otherwise
        """
        total_changed = self._total_changed(metrics)
        
        # 按照base_confidence降序排列规则，确保高优先级规则先被匹配
        sorted_rules = sorted(metric_rules, key=lambda x: x.get("base_confidence", x.get("confidence", 0.0)), reverse=True)
        
        for rule in sorted_rules:
            min_lines = rule.get("min_lines")
            max_lines = rule.get("max_lines")
            min_hunks = rule.get("min_hunks")
            max_hunks = rule.get("max_hunks")
            
            # Check line count conditions
            if min_lines is not None and total_changed < min_lines:
                continue
            if max_lines is not None and total_changed > max_lines:
                continue
            
            # Check hunk count conditions
            hunk_count = metrics.get("hunk_count", 1)
            if min_hunks is not None and hunk_count < min_hunks:
                continue
            if max_hunks is not None and hunk_count > max_hunks:
                continue
            
            # Calculate final confidence
            confidence = self._calculate_confidence(rule, unit)
            
            # All conditions matched
            return RuleSuggestion(
                context_level=rule.get("context_level", "function"),
                confidence=confidence,
                notes=rule.get("notes", "lang:metric_rule"),
                extra_requests=rule.get("extra_requests", [])
            )
        return None

    def match(self, unit: Dict[str, Any]) -> Optional[RuleSuggestion]:  # pragma: no cover - interface
        """Match unit against all applicable rules.
        
        Args:
            unit: The unit dictionary to match
            
        Returns:
            RuleSuggestion if matched, None otherwise
        """
        raise NotImplementedError


__all__ = ["RuleSuggestion", "RuleHandler"]
