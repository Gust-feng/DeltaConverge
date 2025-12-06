"""Java 规则：按路径/关键词给出上下文建议。

优化内容（Requirements 6.1, 6.2, 6.8）：
- 添加注解模式识别（@Annotation）
- 优化 Spring/JPA 相关规则
- 添加 language_specificity_bonus 加成
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from Agent.DIFF.rule.rule_base import (
    RuleHandler, 
    RuleSuggestion,
    _detect_patterns,
    _patterns_to_notes,
)

Unit = Dict[str, Any]

# Java 注解模式定义
JAVA_ANNOTATION_PATTERNS: Dict[str, Dict[str, Any]] = {
    # Spring Core 注解
    "spring_component": {
        "patterns": [r"@Component\b", r"@Service\b", r"@Repository\b", r"@Controller\b", 
                     r"@RestController\b", r"@Configuration\b", r"@Bean\b"],
        "risk": "high",
        "context_level": "file",
        "notes": "java:annotation:spring_component",
        "framework": "spring",
    },
    "spring_injection": {
        "patterns": [r"@Autowired\b", r"@Inject\b", r"@Resource\b", r"@Value\b", 
                     r"@Qualifier\b", r"@Primary\b"],
        "risk": "medium",
        "context_level": "function",
        "notes": "java:annotation:spring_injection",
        "framework": "spring",
    },
    "spring_web": {
        "patterns": [r"@RequestMapping\b", r"@GetMapping\b", r"@PostMapping\b", 
                     r"@PutMapping\b", r"@DeleteMapping\b", r"@PatchMapping\b",
                     r"@RequestBody\b", r"@ResponseBody\b", r"@PathVariable\b",
                     r"@RequestParam\b", r"@RequestHeader\b"],
        "risk": "high",
        "context_level": "function",
        "notes": "java:annotation:spring_web",
        "framework": "spring",
    },
    "spring_security": {
        "patterns": [r"@PreAuthorize\b", r"@PostAuthorize\b", r"@Secured\b", 
                     r"@RolesAllowed\b", r"@EnableWebSecurity\b", r"@EnableGlobalMethodSecurity\b"],
        "risk": "critical",
        "context_level": "function",
        "notes": "java:annotation:spring_security",
        "framework": "spring-security",
    },
    "spring_transaction": {
        "patterns": [r"@Transactional\b", r"@EnableTransactionManagement\b"],
        "risk": "high",
        "context_level": "function",
        "notes": "java:annotation:spring_transaction",
        "framework": "spring",
    },
    "spring_async": {
        "patterns": [r"@Async\b", r"@EnableAsync\b", r"@Scheduled\b", r"@EnableScheduling\b"],
        "risk": "high",
        "context_level": "function",
        "notes": "java:annotation:spring_async",
        "framework": "spring",
    },
    # JPA/Hibernate 注解
    "jpa_entity": {
        "patterns": [r"@Entity\b", r"@Table\b", r"@MappedSuperclass\b", r"@Embeddable\b"],
        "risk": "high",
        "context_level": "file",
        "notes": "java:annotation:jpa_entity",
        "framework": "jpa",
    },
    "jpa_mapping": {
        "patterns": [r"@Column\b", r"@Id\b", r"@GeneratedValue\b", r"@OneToMany\b", 
                     r"@ManyToOne\b", r"@OneToOne\b", r"@ManyToMany\b", r"@JoinColumn\b",
                     r"@JoinTable\b", r"@Embedded\b", r"@EmbeddedId\b"],
        "risk": "high",
        "context_level": "function",
        "notes": "java:annotation:jpa_mapping",
        "framework": "jpa",
    },
    "jpa_query": {
        "patterns": [r"@Query\b", r"@NamedQuery\b", r"@NamedNativeQuery\b", r"@Modifying\b"],
        "risk": "high",
        "context_level": "function",
        "notes": "java:annotation:jpa_query",
        "framework": "jpa",
    },
    # Lombok 注解
    "lombok": {
        "patterns": [r"@Data\b", r"@Getter\b", r"@Setter\b", r"@Builder\b", 
                     r"@NoArgsConstructor\b", r"@AllArgsConstructor\b", r"@RequiredArgsConstructor\b",
                     r"@ToString\b", r"@EqualsAndHashCode\b", r"@Slf4j\b", r"@Log\b"],
        "risk": "medium",
        "context_level": "file",
        "notes": "java:annotation:lombok",
        "framework": "lombok",
    },
    # Validation 注解
    "validation": {
        "patterns": [r"@Valid\b", r"@NotNull\b", r"@NotEmpty\b", r"@NotBlank\b", 
                     r"@Size\b", r"@Min\b", r"@Max\b", r"@Pattern\b", r"@Email\b"],
        "risk": "medium",
        "context_level": "function",
        "notes": "java:annotation:validation",
        "framework": "validation",
    },
    # Test 注解
    "junit": {
        "patterns": [r"@Test\b", r"@BeforeEach\b", r"@AfterEach\b", r"@BeforeAll\b", 
                     r"@AfterAll\b", r"@Disabled\b", r"@DisplayName\b", r"@ParameterizedTest\b"],
        "risk": "low",
        "context_level": "function",
        "notes": "java:annotation:junit",
        "framework": "junit",
    },
    "mockito": {
        "patterns": [r"@Mock\b", r"@InjectMocks\b", r"@Spy\b", r"@Captor\b", 
                     r"@MockBean\b", r"@SpyBean\b"],
        "risk": "low",
        "context_level": "function",
        "notes": "java:annotation:mockito",
        "framework": "mockito",
    },
    # Jackson 注解
    "jackson": {
        "patterns": [r"@JsonProperty\b", r"@JsonIgnore\b", r"@JsonInclude\b", 
                     r"@JsonFormat\b", r"@JsonSerialize\b", r"@JsonDeserialize\b"],
        "risk": "medium",
        "context_level": "function",
        "notes": "java:annotation:jackson",
        "framework": "jackson",
    },
}

# Java 框架特定路径规则
JAVA_FRAMEWORK_PATH_RULES: List[Dict[str, Any]] = [
    # Spring Boot 项目结构
    {
        "match": ["controller/", "controllers/", "rest/", "api/"],
        "context_level": "function",
        "base_confidence": 0.88,
        "notes": "java:spring:controller",
        "framework": "spring",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["service/", "services/"],
        "context_level": "function",
        "base_confidence": 0.85,
        "notes": "java:spring:service",
        "framework": "spring",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["repository/", "repositories/", "dao/"],
        "context_level": "function",
        "base_confidence": 0.88,
        "notes": "java:spring:repository",
        "framework": "spring",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["entity/", "entities/", "model/", "models/", "domain/"],
        "context_level": "file",
        "base_confidence": 0.88,
        "notes": "java:jpa:entity",
        "framework": "jpa",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["dto/", "dtos/", "vo/", "request/", "response/"],
        "context_level": "file",
        "base_confidence": 0.82,
        "notes": "java:dto",
        "framework": "java",
        "confidence_adjusters": {"rule_specificity": 0.05, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["config/", "configuration/", "configs/"],
        "context_level": "file",
        "base_confidence": 0.88,
        "notes": "java:spring:config",
        "framework": "spring",
        "extra_requests": [{"type": "search_config_usage"}],
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["security/", "auth/", "authentication/", "authorization/"],
        "context_level": "file",
        "base_confidence": 0.92,
        "notes": "java:spring:security",
        "framework": "spring-security",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1, "security_sensitive": 0.1},
    },
    {
        "match": ["mapper/", "mappers/", "converter/", "converters/"],
        "context_level": "function",
        "base_confidence": 0.82,
        "notes": "java:mapper",
        "framework": "java",
        "confidence_adjusters": {"rule_specificity": 0.05, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["exception/", "exceptions/", "handler/", "handlers/"],
        "context_level": "function",
        "base_confidence": 0.85,
        "notes": "java:exception",
        "framework": "java",
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
    {
        "match": ["util/", "utils/", "helper/", "helpers/"],
        "context_level": "function",
        "base_confidence": 0.75,
        "notes": "java:util",
        "framework": "java",
        "confidence_adjusters": {"rule_specificity": 0.05, "language_specificity_bonus": 0.1},
    },
    # 测试文件
    {
        "match": ["test/", "tests/", "Test.java", "Tests.java", "IT.java"],
        "context_level": "function",
        "base_confidence": 0.75,
        "notes": "java:test",
        "framework": "junit",
        "confidence_adjusters": {"rule_specificity": 0.05, "language_specificity_bonus": 0.1},
    },
    # 资源文件（Requirements 8.3: 配置文件变更添加 search_config_usage 建议）
    {
        "match": ["application.properties", "application.yml", "application.yaml"],
        "context_level": "file",
        "base_confidence": 0.9,
        "notes": "java:spring:config_file",
        "framework": "spring",
        "extra_requests": [{"type": "search_config_usage"}],
        "confidence_adjusters": {"rule_specificity": 0.1, "language_specificity_bonus": 0.1},
    },
]

# 默认的 language_specificity_bonus
DEFAULT_LANGUAGE_SPECIFICITY_BONUS = 0.1


class JavaRuleHandler(RuleHandler):
    """Java 语言规则处理器
    
    优化内容：
    - 注解模式识别（@Annotation）
    - Spring/JPA 框架规则
    - language_specificity_bonus 加成
    """
    
    def __init__(self):
        super().__init__(language="java")
        self._annotation_patterns = JAVA_ANNOTATION_PATTERNS
        self._framework_path_rules = JAVA_FRAMEWORK_PATH_RULES
    
    def _detect_annotations(self, content: str) -> List[Dict[str, Any]]:
        """检测代码中的注解模式
        
        Args:
            content: 代码内容（diff 内容或源代码）
            
        Returns:
            匹配的注解模式列表
        """
        matched_annotations: List[Dict[str, Any]] = []
        
        for annotation_name, annotation_config in self._annotation_patterns.items():
            patterns = annotation_config.get("patterns", [])
            matched_patterns: List[str] = []
            
            for pattern in patterns:
                if re.search(pattern, content):
                    matched_patterns.append(pattern)
            
            if matched_patterns:
                matched_annotations.append({
                    "annotation_name": annotation_name,
                    "risk": annotation_config.get("risk", "medium"),
                    "context_level": annotation_config.get("context_level", "function"),
                    "notes": annotation_config.get("notes", f"java:annotation:{annotation_name}"),
                    "framework": annotation_config.get("framework", "java"),
                    "matched_patterns": matched_patterns,
                })
        
        # 按风险等级排序
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        matched_annotations.sort(key=lambda x: risk_order.get(x.get("risk", "medium"), 2))
        
        return matched_annotations
    
    def _get_annotation_suggestion(self, annotations: List[Dict[str, Any]], unit: Unit) -> Optional[RuleSuggestion]:
        """根据注解模式生成建议
        
        Args:
            annotations: 匹配的注解列表
            unit: 变更单元
            
        Returns:
            RuleSuggestion 或 None
        """
        if not annotations:
            return None
        
        # 使用风险最高的注解
        highest_risk_annotation = annotations[0]
        
        # 构建规则用于置信度计算
        rule = {
            "base_confidence": 0.85,  # 注解匹配给予较高基础置信度
            "confidence_adjusters": {
                "rule_specificity": 0.1,
                "language_specificity_bonus": DEFAULT_LANGUAGE_SPECIFICITY_BONUS,
            },
            "risk_level": highest_risk_annotation.get("risk", "medium"),
        }
        
        confidence = self._calculate_confidence(rule, unit)
        
        # 构建 notes
        annotation_names = [a.get("annotation_name", "") for a in annotations]
        notes = f"java:annotation:{','.join(annotation_names)}"
        
        # 添加框架信息
        frameworks = set(a.get("framework", "") for a in annotations if a.get("framework"))
        if frameworks:
            notes += f";frameworks:{','.join(frameworks)}"
        
        return RuleSuggestion(
            context_level=highest_risk_annotation.get("context_level", "function"),
            confidence=confidence,
            notes=notes,
        )
    
    def _match_framework_path_rules(self, file_path: str, unit: Unit) -> Optional[RuleSuggestion]:
        """匹配框架特定的路径规则
        
        Args:
            file_path: 文件路径
            unit: 变更单元
            
        Returns:
            RuleSuggestion 或 None
        """
        return self._match_path_rules(file_path, self._framework_path_rules, unit)
    
    def _apply_language_specificity_bonus(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """应用语言特定加成
        
        Args:
            rule: 原始规则
            
        Returns:
            添加了语言特定加成的规则
        """
        enhanced_rule = rule.copy()
        adjusters = enhanced_rule.get("confidence_adjusters", {}).copy()
        
        # 添加语言特定加成
        if "language_specificity_bonus" not in adjusters:
            adjusters["language_specificity_bonus"] = DEFAULT_LANGUAGE_SPECIFICITY_BONUS
        
        enhanced_rule["confidence_adjusters"] = adjusters
        return enhanced_rule
    
    def match(self, unit: Unit) -> Optional[RuleSuggestion]:
        file_path = str(unit.get("file_path", "")).lower()
        original_file_path = str(unit.get("file_path", ""))  # Keep original for scanner
        metrics = unit.get("metrics", {}) or {}
        total_changed = self._total_changed(metrics)
        tags = set(unit.get("tags", []) or [])
        symbol = unit.get("symbol") or {}
        sym_name = symbol.get("name", "").lower() if isinstance(symbol, dict) else ""
        
        # 获取 diff 内容用于注解检测
        diff_content = unit.get("diff_content", "") or unit.get("content", "") or ""
        
        # 执行扫描器获取问题列表（Requirements 1.2, 3.4, 3.5）
        scanner_issues = self._scan_file(original_file_path, diff_content) if original_file_path else []
        
        # 1. 检测注解模式（Requirements 6.8）
        if diff_content:
            annotations = self._detect_annotations(diff_content)
            if annotations:
                annotation_suggestion = self._get_annotation_suggestion(annotations, unit)
                if annotation_suggestion:
                    # 应用扫描器结果到建议（Requirements 3.5）
                    return self._apply_scanner_results(annotation_suggestion, scanner_issues)
        
        # 2. 匹配框架特定路径规则（Spring/JPA）
        framework_match = self._match_framework_path_rules(file_path, unit)
        if framework_match:
            return self._apply_scanner_results(framework_match, scanner_issues)
        
        # 3. 从配置加载路径规则
        path_rules = self._get_language_config("path_rules", [])
        # 应用语言特定加成
        enhanced_path_rules = [self._apply_language_specificity_bonus(r) for r in path_rules]
        path_match = self._match_path_rules(file_path, enhanced_path_rules, unit)
        if path_match:
            return self._apply_scanner_results(path_match, scanner_issues)

        # 4. 从配置加载符号规则
        sym_rules = self._get_language_config("symbol_rules", [])
        if symbol:
            # 应用语言特定加成
            enhanced_sym_rules = [self._apply_language_specificity_bonus(r) for r in sym_rules]
            sym_match = self._match_symbol_rules(symbol, enhanced_sym_rules, unit)
            if sym_match:
                return self._apply_scanner_results(sym_match, scanner_issues)

        # 5. 从配置加载度量规则
        metric_rules = self._get_language_config("metric_rules", [])
        # 应用语言特定加成
        enhanced_metric_rules = [self._apply_language_specificity_bonus(r) for r in metric_rules]
        metric_match = self._match_metric_rules(metrics, enhanced_metric_rules, unit)
        if metric_match:
            return self._apply_scanner_results(metric_match, scanner_issues)

        # 6. 从配置加载关键词
        keywords = self._get_language_config("keywords", [])
        # 添加基础安全关键词
        keywords.extend(self._get_base_config("security_keywords", []))
        haystack = self._build_haystack(file_path, sym_name, tags)
        # 转换关键词为小写以匹配
        lowercase_keywords = [kw.lower() for kw in keywords]
        keyword_match = self._match_keywords(haystack, lowercase_keywords, unit, confidence=0.83, note_prefix="lang_java:kw:")
        if keyword_match:
            return self._apply_scanner_results(keyword_match, scanner_issues)

        # 7. 检测变更模式
        if diff_content:
            patterns = _detect_patterns(diff_content, file_path)
            if patterns:
                highest_risk_pattern = patterns[0]
                pattern_notes = _patterns_to_notes(patterns)
                
                rule = {
                    "base_confidence": 0.5,
                    "confidence_adjusters": {
                        "rule_specificity": 0.05,
                    },
                    "risk_level": highest_risk_pattern.get("risk", "medium"),
                }
                
                pattern_suggestion = RuleSuggestion(
                    context_level=highest_risk_pattern.get("context_level", "function"),
                    confidence=self._calculate_confidence(rule, unit),
                    notes=f"java:{pattern_notes}",
                )
                return self._apply_scanner_results(pattern_suggestion, scanner_issues)

        # 8. 默认返回：如果没有匹配到任何规则，返回低置信度的默认建议
        # 使用 "function" 而非 "unknown"，确保每个变更单元都有明确的审查策略
        # confidence 在 0.3-0.45 范围内（Requirements 7.1, 7.2）
        default_suggestion = RuleSuggestion(
            context_level="function",
            confidence=self._calculate_confidence({
                "base_confidence": 0.35,
                "confidence_adjusters": {
                    "file_size": 0.0,
                    "change_type": 0.0,
                    "security_sensitive": 0.0,
                    "rule_specificity": 0.0
                }
            }, unit),
            notes="java:default_fallback",
        )
        return self._apply_scanner_results(default_suggestion, scanner_issues)


__all__ = ["JavaRuleHandler", "JAVA_ANNOTATION_PATTERNS", "JAVA_FRAMEWORK_PATH_RULES"]
