"""Rule handler base classes and shared helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING

from Agent.DIFF.rule.rule_config import get_rule_config

if TYPE_CHECKING:
    from Agent.DIFF.rule.scanner_base import BaseScanner, ScannerIssue

logger = logging.getLogger(__name__)


# =============================================================================
# 内部辅助结构（不暴露给外部）
# =============================================================================

@dataclass
class _ConfidenceFactors:
    """置信度计算因子（内部使用，不暴露）
    
    用于计算匹配确定性（match_certainty），表示规则对变更单元匹配的确定程度。
    
    Attributes:
        rule_specificity: 规则特异性，匹配条件数量（0-5）
        pattern_precision: 模式精度，精确匹配(1.0) / 部分匹配(0.5) / 无匹配(0.0)
        context_availability: 上下文可用性，符号信息完整度（0.0-1.0）
        language_bonus: 语言特定加成，是否匹配语言特定规则（0.0-0.1）
    """
    
    rule_specificity: int = 0
    pattern_precision: float = 0.0
    context_availability: float = 0.0
    language_bonus: float = 0.0
    
    def to_match_certainty(self) -> float:
        """计算匹配确定性（内部值）
        
        计算公式：
        - 基础置信度: 0.3
        - 特异性得分: min(rule_specificity * 0.06, 0.3)
        - 精度得分: pattern_precision * 0.3
        - 上下文得分: context_availability * 0.2
        - 语言加成: language_bonus
        
        Returns:
            匹配确定性值，范围 0.0-1.0
        """
        base = 0.3  # 基础置信度
        specificity_score = min(self.rule_specificity * 0.06, 0.3)
        precision_score = self.pattern_precision * 0.3
        context_score = self.context_availability * 0.2
        lang_score = self.language_bonus
        
        return min(1.0, base + specificity_score + precision_score + context_score + lang_score)


@dataclass
class _RiskFactors:
    """风险计算因子（内部使用，不暴露）
    
    用于计算风险等级（risk_level），表示变更需要审查的重要程度。
    
    Attributes:
        change_scope: 变更范围，变更行数
        security_sensitive: 安全敏感，是否涉及安全相关代码
        change_type: 变更类型，add/modify/delete
        pattern_risk: 模式风险，变更模式的固有风险（low/medium/high）
        symbol_risk: 符号风险，公共API/构造函数等（low/medium/high）
    """
    
    change_scope: int = 0
    security_sensitive: bool = False
    change_type: str = "modify"
    pattern_risk: str = "medium"  # low/medium/high
    symbol_risk: str = "low"  # low/medium/high
    
    def to_risk_level(self) -> str:
        """计算风险等级（内部值）
        
        计算规则：
        - 安全敏感直接返回 high 或 critical
        - 基于各因子计算风险分数，映射到风险等级
        
        Returns:
            风险等级: "low" | "medium" | "high" | "critical"
        """
        # 安全敏感直接返回 high 或 critical
        if self.security_sensitive:
            return "critical" if self.change_scope > 50 else "high"
        
        # 基于各因子计算风险分数
        score = 0
        
        # 变更范围
        if self.change_scope > 100:
            score += 3
        elif self.change_scope > 50:
            score += 2
        elif self.change_scope > 20:
            score += 1
        
        # 变更类型
        if self.change_type == "delete":
            score += 2
        elif self.change_type == "modify":
            score += 1
        
        # 模式风险
        pattern_scores = {"low": 0, "medium": 1, "high": 2}
        score += pattern_scores.get(self.pattern_risk, 1)
        
        # 符号风险
        symbol_scores = {"low": 0, "medium": 1, "high": 2}
        score += symbol_scores.get(self.symbol_risk, 0)
        
        # 映射到风险等级
        if score >= 6:
            return "critical"
        elif score >= 4:
            return "high"
        elif score >= 2:
            return "medium"
        else:
            return "low"


@dataclass
class _SymbolAnalysisResult:
    """符号分析结果（内部使用，不暴露）
    
    用于存储符号级分析的结果，包括是否为公共 API、构造函数等信息。
    
    Attributes:
        is_public_api: 是否为公共 API（public 方法、导出函数）
        is_constructor: 是否为构造函数或初始化方法
        is_class: 是否为类定义
        is_interface: 是否为接口或抽象类定义
        is_data_model: 是否为数据模型/Schema 定义
        is_config_file: 是否为配置文件变更
        is_exported_constant: 是否为导出的常量
        spans_multiple_functions: 变更是否跨越多个函数
        function_count: 涉及的函数数量
        class_count: 涉及的类数量
        has_symbol_info: 是否有符号信息
        symbol_kind: 符号类型（function/class/method/interface/unknown）
        symbol_name: 符号名称
        visibility: 可见性（public/private/protected/unknown）
        suggested_context_level: 建议的上下文级别
        notes: 分析备注列表
    """
    
    is_public_api: bool = False
    is_constructor: bool = False
    is_class: bool = False
    is_interface: bool = False
    is_data_model: bool = False
    is_config_file: bool = False
    is_exported_constant: bool = False
    spans_multiple_functions: bool = False
    function_count: int = 0
    class_count: int = 0
    has_symbol_info: bool = False
    symbol_kind: str = "unknown"
    symbol_name: str = ""
    visibility: str = "unknown"
    suggested_context_level: str = "function"
    notes: List[str] = field(default_factory=list)
    
    def get_symbol_risk(self) -> str:
        """根据符号分析结果计算符号风险等级
        
        Returns:
            符号风险等级: "low" | "medium" | "high"
        """
        # 公共 API 或构造函数为高风险
        if self.is_public_api or self.is_constructor:
            return "high"
        
        # 类定义为高风险
        if self.is_class:
            return "high"
        
        # 接口/抽象类定义为高风险
        if self.is_interface:
            return "high"
        
        # 数据模型/Schema 定义为高风险
        if self.is_data_model:
            return "high"
        
        # 配置文件变更为中等风险
        if self.is_config_file:
            return "medium"
        
        # 导出常量为中等风险
        if self.is_exported_constant:
            return "medium"
        
        # 跨越多个函数为中等风险
        if self.spans_multiple_functions:
            return "medium"
        
        # 有符号信息但不是特殊情况为低风险
        if self.has_symbol_info:
            return "low"
        
        # 无符号信息使用保守默认值（中等风险）
        return "medium"
    
    def get_dependency_hints(self) -> List[Dict[str, Any]]:
        """根据符号分析结果获取跨文件依赖提示
        
        根据 Requirements 8.1-8.4 生成相应的 extra_requests 建议：
        - 导出函数/类/常量变更 → search_callers (Requirements 8.1)
        - 接口/抽象类定义变更 → search_implementations (Requirements 8.2)
        - 配置文件变更 → search_config_usage (Requirements 8.3)
        - 数据模型/Schema 变更 → search_model_usage (Requirements 8.4)
        
        Returns:
            依赖提示列表，每个元素为 {"type": "search_xxx"} 格式
        """
        hints: List[Dict[str, Any]] = []
        
        # Requirements 8.1: 导出函数/类/常量变更 → search_callers
        if self.is_public_api:
            hints.append({"type": "search_callers"})
        
        # Requirements 8.1: 导出常量变更 → search_callers
        if self.is_exported_constant:
            if not any(h.get("type") == "search_callers" for h in hints):
                hints.append({"type": "search_callers"})
        
        # Requirements 8.2: 接口/抽象类定义变更 → search_implementations
        if self.is_interface:
            hints.append({"type": "search_implementations"})
        
        # Requirements 8.3: 配置文件变更 → search_config_usage
        if self.is_config_file:
            hints.append({"type": "search_config_usage"})
        
        # Requirements 8.4: 数据模型/Schema 变更 → search_model_usage
        if self.is_data_model:
            hints.append({"type": "search_model_usage"})
        
        # 构造函数变更建议检查类的其他方法
        if self.is_constructor:
            hints.append({"type": "search_class_methods"})
        
        # 类定义变更建议搜索调用方
        if self.is_class and not self.is_interface and not self.is_data_model:
            if not any(h.get("type") == "search_callers" for h in hints):
                hints.append({"type": "search_callers"})
        
        return hints


def _analyze_symbols(unit: Dict[str, Any]) -> _SymbolAnalysisResult:
    """分析变更单元的符号信息
    
    分析符号信息判断是否为公共 API、构造函数、接口、数据模型等，
    判断变更是否跨越多个函数，返回符号分析结果。
    
    Args:
        unit: 变更单元字典，包含 symbol、metrics、file_path、tags 等信息
        
    Returns:
        _SymbolAnalysisResult 实例，包含符号分析结果
        
    Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 8.1, 8.2, 8.3, 8.4
    """
    result = _SymbolAnalysisResult()
    
    # 安全获取 symbol，处理 None 和非字典类型
    symbol_raw = unit.get("symbol")
    if symbol_raw is None:
        symbol = {}
        result.notes.append("symbol_is_none")
    elif isinstance(symbol_raw, dict):
        symbol = symbol_raw
    else:
        # 非预期类型，记录并使用空字典
        symbol = {}
        result.notes.append(f"symbol_unexpected_type:{type(symbol_raw).__name__}")
    
    file_path = unit.get("file_path", "").lower()
    tags = set(unit.get("tags", []) or [])
    
    # 检测配置文件变更（Requirements 8.3）
    config_path_patterns = [
        "config/", "configs/", "settings/", ".env",
        "application.properties", "application.yml", "application.yaml",
        "pom.xml", "package.json", "tsconfig", "webpack.config",
        "vite.config", "next.config", "jest.config", "babel.config",
        "Gemfile", "requirements.txt", "pyproject.toml", "setup.py",
        ".eslintrc", ".prettierrc", "docker-compose", "dockerfile",
    ]
    config_file_extensions = [".yaml", ".yml", ".json", ".toml", ".ini", ".conf", ".cfg"]
    
    is_config_by_path = any(pattern in file_path for pattern in config_path_patterns)
    is_config_by_ext = any(file_path.endswith(ext) for ext in config_file_extensions)
    is_config_by_tag = "config_file" in tags
    
    if is_config_by_path or is_config_by_ext or is_config_by_tag:
        result.is_config_file = True
        result.notes.append("config_file")
        result.suggested_context_level = "file"
    
    # 检查是否有符号信息
    if not symbol:
        result.has_symbol_info = False
        result.notes.append("symbol_info_missing")
        result.suggested_context_level = "function"  # 保守默认值
        return result
    
    result.has_symbol_info = True
    
    # 提取函数和类列表
    functions = symbol.get("functions", [])
    classes = symbol.get("classes", [])
    interfaces = symbol.get("interfaces", [])  # TypeScript/Java 接口
    
    result.function_count = len(functions)
    result.class_count = len(classes)
    
    # 判断是否跨越多个函数（Requirements 5.2）
    if result.function_count > 1:
        result.spans_multiple_functions = True
        result.suggested_context_level = "file"
        result.notes.append("spans_multiple_functions")
    elif result.function_count == 1:
        result.suggested_context_level = "function"
    elif result.class_count > 0 or interfaces:
        result.suggested_context_level = "file"
    else:
        result.suggested_context_level = "function"
    
    # 分析主要符号
    main_symbol = None
    if interfaces:
        # 优先处理接口（Requirements 8.2）
        main_symbol = interfaces[0]
        result.symbol_kind = "interface"
        result.is_interface = True
        result.suggested_context_level = "file"
        result.notes.append("interface_definition")
    elif functions:
        main_symbol = functions[0]
        result.symbol_kind = "function"
    elif classes:
        main_symbol = classes[0]
        result.symbol_kind = "class"
        result.is_class = True
    elif symbol.get("kind"):
        result.symbol_kind = symbol.get("kind", "unknown")
        main_symbol = symbol
    elif symbol.get("name"):
        main_symbol = symbol
        result.symbol_kind = "unknown"
    
    if main_symbol:
        result.symbol_name = main_symbol.get("name", "")
        
        # 判断可见性
        name = result.symbol_name.lower()
        
        # Python 风格：以 _ 开头为私有，以 __ 开头为强私有
        if name.startswith("__") and not name.endswith("__"):
            result.visibility = "private"
        elif name.startswith("_"):
            result.visibility = "protected"
        else:
            result.visibility = "public"
        
        # 判断是否为公共 API（Requirements 5.4, 8.1）
        # 公共 API：不以 _ 开头的函数/方法
        if result.visibility == "public" and result.symbol_kind in ("function", "method"):
            result.is_public_api = True
            result.notes.append("public_api")
        
        # 判断是否为导出的常量（Requirements 8.1）
        # 常量通常是全大写的变量名，或者符号类型为 constant
        original_name = result.symbol_name
        if result.symbol_kind in ("constant", "variable"):
            # 全大写变量名（如 MAX_SIZE, API_KEY）
            if original_name.isupper() and len(original_name) > 1:
                result.is_exported_constant = True
                result.notes.append("exported_constant")
            # 大写开头带下划线的常量（如 Config_Value）
            elif original_name and original_name[0].isupper() and "_" in original_name:
                result.is_exported_constant = True
                result.notes.append("exported_constant")
        # 公共类也视为导出的符号（Requirements 8.1）
        if result.visibility == "public" and result.is_class:
            result.is_public_api = True
            if "public_api" not in result.notes:
                result.notes.append("public_api")
        
        # 判断是否为构造函数（Requirements 5.3）
        constructor_names = {
            "__init__",      # Python
            "constructor",   # JavaScript/TypeScript
            "init",          # Swift/Objective-C
            "new",           # Ruby
            "initialize",    # Ruby
            "__new__",       # Python
            "__construct",   # PHP
        }
        if name in constructor_names:
            result.is_constructor = True
            result.suggested_context_level = "file"  # 构造函数建议检查整个文件
            result.notes.append("constructor")
        
        # 检查是否为类定义
        if result.symbol_kind == "class":
            result.is_class = True
            result.suggested_context_level = "file"
            result.notes.append("class_definition")
        
        # 检查是否为接口/抽象类（Requirements 8.2）
        # 通过符号类型或名称模式判断
        if result.symbol_kind == "interface":
            result.is_interface = True
            result.notes.append("interface_definition")
        elif main_symbol.get("is_abstract") or main_symbol.get("abstract"):
            result.is_interface = True
            result.notes.append("abstract_class")
        elif _is_interface_name(result.symbol_name):
            result.is_interface = True
            result.notes.append("interface_pattern")
        
        # 检查是否为数据模型/Schema（Requirements 8.4）
        if _is_data_model(result.symbol_name, file_path, main_symbol):
            result.is_data_model = True
            result.suggested_context_level = "file"
            result.notes.append("data_model")
    
    # 如果有多个类，也建议 file 级别上下文
    if result.class_count > 1:
        result.suggested_context_level = "file"
        result.notes.append("multiple_classes")
    
    return result


def _is_interface_name(name: str) -> bool:
    """判断名称是否符合接口命名模式
    
    Args:
        name: 符号名称
        
    Returns:
        是否为接口命名模式
    """
    name_lower = name.lower()
    
    # 排除过于简单的名称（如 "interface", "base", "abc"）
    if len(name) < 4:
        return False
    
    # 排除私有名称（以 _ 开头的名称不应被识别为接口）
    if name.startswith("_"):
        return False
    
    # 常见接口命名模式
    # Java/TypeScript: IXxx, XxxInterface
    # Python: XxxABC, XxxProtocol, AbstractXxx
    interface_patterns = [
        name.startswith("I") and len(name) > 1 and name[1].isupper(),  # IUserService
        name_lower.endswith("interface") and len(name) > len("interface"),  # UserInterface
        name_lower.endswith("protocol") and len(name) > len("protocol"),   # UserProtocol (Swift/Python)
        name_lower.startswith("abstract") and len(name) > len("abstract"),  # AbstractUser
        name_lower.endswith("abc") and len(name) > len("abc"),         # UserABC (Python)
        name_lower.endswith("base") and len(name) > len("base"),        # UserBase
    ]
    
    return any(interface_patterns)


def _is_data_model(name: str, file_path: str, symbol: Dict[str, Any]) -> bool:
    """判断是否为数据模型/Schema 定义
    
    Args:
        name: 符号名称
        file_path: 文件路径
        symbol: 符号信息字典
        
    Returns:
        是否为数据模型
    """
    name_lower = name.lower()
    
    # 通过文件路径判断
    model_path_patterns = [
        "models/", "model/", "schemas/", "schema/",
        "entities/", "entity/", "dto/", "types/",
        "prisma/schema", "migrations/", "migrate/",
    ]
    if any(pattern in file_path for pattern in model_path_patterns):
        return True
    
    # 通过名称模式判断（需要是类，不是普通函数）
    # 只有当符号是类时才检查名称模式
    symbol_kind = symbol.get("kind", "")
    is_class_like = symbol_kind in ("class", "interface") or symbol.get("classes")
    
    if is_class_like:
        model_name_patterns = [
            name_lower.endswith("model"),      # UserModel
            name_lower.endswith("schema"),     # UserSchema
            name_lower.endswith("entity"),     # UserEntity
            name_lower.endswith("dto"),        # UserDTO
            name_lower.endswith("type"),       # UserType
            name_lower.endswith("record"),     # UserRecord
            name_lower.endswith("table"),      # UserTable
        ]
        if any(model_name_patterns):
            return True
    
    # 通过符号属性判断（如 ORM 装饰器）
    decorators = symbol.get("decorators", [])
    if isinstance(decorators, list):
        model_decorators = ["@entity", "@model", "@table", "@dataclass", "@schema"]
        for dec in decorators:
            dec_lower = str(dec).lower()
            if any(md in dec_lower for md in model_decorators):
                return True
    
    return False


def _compute_final_confidence(match_certainty: float, risk_level: str) -> float:
    """将匹配确定性和风险等级映射为最终的 confidence 值
    
    这是核心的语义优化：
    - 原来的 confidence 混合了"匹配确定性"和"风险等级"
    - 优化后内部分开计算，最终映射回单一的 confidence 值
    - 保持接口不变，但语义更清晰
    
    映射规则：
    - 高风险变更即使匹配确定性低，也应该有较高的 confidence（确保被审查）
    - 低风险变更即使匹配确定性高，confidence 也不应过高（避免过度审查）
    
    Args:
        match_certainty: 匹配确定性，范围 0.0-1.0
        risk_level: 风险等级，"low" | "medium" | "high" | "critical"
        
    Returns:
        最终置信度值，范围 0.0-1.0，保留 2 位小数
    """
    risk_weight = {"critical": 0.30, "high": 0.20, "medium": 0.10, "low": 0.0}
    risk_bonus = risk_weight.get(risk_level, 0.10)
    
    # 最终置信度 = 匹配确定性 * 0.6 + 风险加成 + 基础偏移
    final = match_certainty * 0.6 + risk_bonus + 0.15
    
    return round(max(0.0, min(1.0, final)), 2)


# =============================================================================
# 变更模式定义
# =============================================================================

CHANGE_PATTERNS: Dict[str, Dict[str, Any]] = {
    "import_only": {
        "description": "仅导入语句变更",
        "risk": "low",
        "context_level": "local",
        "indicators": [
            "import ", "from ", "require(", "require ", 
            "include ", "#include", "using ", "use "
        ],
    },
    "signature_change": {
        "description": "函数签名变更",
        "risk": "high",
        "context_level": "file",
        "indicators": [
            "def ", "function ", "func ", "fn ",
            "public ", "private ", "protected ",
            "async ", "static ", "-> ", ": "
        ],
        "extra_requests": [{"type": "search_callers"}],
    },
    "error_handling": {
        "description": "异常处理变更",
        "risk": "medium",
        "context_level": "function",
        "indicators": [
            "try:", "try {", "catch ", "catch(",
            "except ", "except:", "finally:", "finally {",
            "throw ", "raise ", "Error(", "Exception("
        ],
    },
    "config_change": {
        "description": "配置值变更",
        "risk": "medium",
        "context_level": "file",
        "indicators": [
            "config", "setting", "env", "ENV",
            "const ", "final ", "readonly ",
            "CONSTANT", "CONFIG", "SETTING"
        ],
        "extra_requests": [{"type": "search_config_usage"}],
    },
    "data_access": {
        "description": "数据库操作变更",
        "risk": "high",
        "context_level": "function",
        "indicators": [
            "SELECT ", "INSERT ", "UPDATE ", "DELETE ",
            "select(", "insert(", "update(", "delete(",
            ".query(", ".execute(", ".find(", ".save(",
            "cursor.", "connection.", "session.",
            "db.", "database.", "sql"
        ],
    },
    "logging_only": {
        "description": "仅日志语句变更",
        "risk": "low",
        "context_level": "local",
        "indicators": [
            "log.", "logger.", "logging.",
            "console.log", "print(", "println",
            "debug(", "info(", "warn(", "error("
        ],
    },
    "comment_only": {
        "description": "仅注释变更",
        "risk": "low",
        "context_level": "local",
        "indicators": [
            "# ", "// ", "/* ", "* ", "*/",
            '"""', "'''", "<!--", "-->"
        ],
    },
    "test_code": {
        "description": "测试代码变更",
        "risk": "low",
        "context_level": "function",
        "indicators": [
            "test_", "_test", "Test", "spec.",
            "describe(", "it(", "expect(", "assert",
            "@pytest", "@Test", "unittest"
        ],
    },
    "security_sensitive": {
        "description": "安全敏感变更",
        "risk": "critical",
        "context_level": "file",
        "indicators": [
            "password", "secret", "token", "key",
            "auth", "credential", "encrypt", "decrypt",
            "hash", "salt", "jwt", "oauth"
        ],
    },
}


def _detect_patterns(content: str, file_path: str = "") -> List[Dict[str, Any]]:
    """检测变更内容中的模式
    
    分析变更内容识别匹配的模式，返回匹配的模式列表。
    
    Args:
        content: 变更内容（diff 内容或代码片段）
        file_path: 文件路径，用于辅助判断
        
    Returns:
        匹配的模式列表，每个元素包含:
        - pattern_name: 模式名称
        - description: 模式描述
        - risk: 风险等级
        - context_level: 建议的上下文级别
        - matched_indicators: 匹配到的指示符列表
        - extra_requests: 额外请求（如有）
    """
    matched_patterns: List[Dict[str, Any]] = []
    content_lower = content.lower()
    file_path_lower = file_path.lower()
    
    for pattern_name, pattern_config in CHANGE_PATTERNS.items():
        indicators = pattern_config.get("indicators", [])
        matched_indicators: List[str] = []
        
        for indicator in indicators:
            indicator_lower = indicator.lower()
            # 检查内容中是否包含指示符
            if indicator_lower in content_lower:
                matched_indicators.append(indicator)
            # 对于某些模式，也检查文件路径
            elif pattern_name in ("test_code", "config_change") and indicator_lower in file_path_lower:
                matched_indicators.append(indicator)
        
        if matched_indicators:
            pattern_result = {
                "pattern_name": pattern_name,
                "description": pattern_config.get("description", ""),
                "risk": pattern_config.get("risk", "medium"),
                "context_level": pattern_config.get("context_level", "function"),
                "matched_indicators": matched_indicators,
            }
            
            # 添加额外请求（如有）
            extra_requests = pattern_config.get("extra_requests")
            if extra_requests:
                pattern_result["extra_requests"] = extra_requests
            
            matched_patterns.append(pattern_result)
    
    # 按风险等级排序（critical > high > medium > low）
    risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    matched_patterns.sort(key=lambda x: risk_order.get(x.get("risk", "medium"), 2))
    
    return matched_patterns


def _get_highest_risk_pattern(patterns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """获取风险等级最高的模式
    
    Args:
        patterns: 模式列表
        
    Returns:
        风险等级最高的模式，如果列表为空则返回 None
    """
    if not patterns:
        return None
    return patterns[0]  # 已按风险等级排序


def _patterns_to_notes(patterns: List[Dict[str, Any]]) -> str:
    """将模式列表转换为 notes 字符串
    
    Args:
        patterns: 模式列表
        
    Returns:
        格式化的 notes 字符串
    """
    if not patterns:
        return ""
    
    pattern_names = [p.get("pattern_name", "") for p in patterns]
    return "patterns:" + ",".join(pattern_names)


# =============================================================================
# 公共数据结构
# =============================================================================

@dataclass
class RuleSuggestion:
    """规则建议结构。
    
    注意：context_level 不再返回 "unknown"，而是使用 "function" 作为默认值。
    这确保每个变更单元都有明确的审查策略（Requirements 7.1, 7.2）。
    """
    context_level: str  # local | function | file（不再返回 unknown）
    confidence: float
    notes: str
    extra_requests: List[Dict[str, Any]] = field(default_factory=list)  # 使用 List 保持向后兼容

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if not payload.get("extra_requests"):
            payload.pop("extra_requests", None)
        return payload


class RuleHandler:
    """Base class for language-specific rule handlers."""
    
    # 全局开关：控制主链路是否调用扫描器（默认关闭，扫描器作为旁路服务）
    _enable_scanner_in_rules: bool = False
    
    @classmethod
    def set_scanner_enabled(cls, enabled: bool) -> None:
        """设置是否在规则层启用扫描器调用。
        
        Args:
            enabled: True 表示在规则层调用扫描器（深度模式），False 表示不调用（标准模式）
        """
        cls._enable_scanner_in_rules = enabled
    
    @classmethod
    def is_scanner_enabled(cls) -> bool:
        """获取当前扫描器是否在规则层启用。"""
        return cls._enable_scanner_in_rules
    
    def __init__(self, language: Optional[str] = None):
        """Initialize rule handler with language-specific configuration.
        
        Args:
            language: The language for this handler (e.g., "python", "typescript")
            
        Requirements: 2.1, 3.3, 3.4
        
        Note: Scanners are NOT initialized here. They are lazily initialized
        when first needed (in _scan_file) to ensure event callbacks are set
        before initialization, allowing progress events to be sent to frontend.
        
        Note: In standard mode, scanners are NOT called from rule handlers.
        They run as a separate bypass service. Only in deep mode (legacy)
        will scanners be called from rule handlers.
        """
        self.language = language
        self.config = get_rule_config()
        self.language_config = self.config.get("languages", {}).get(language, {}) if language else {}
        
        # Lazy initialization: do NOT initialize scanners in constructor (Requirements 2.1)
        self._scanners: List["BaseScanner"] = []
        self._scanners_initialized: bool = False
        
        # 事件回调函数，用于推送扫描进度到前端
        self._event_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    
    def set_event_callback(self, callback: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        """设置事件回调函数。
        
        Args:
            callback: 事件回调函数，接收事件字典作为参数
        """
        self._event_callback = callback
    
    def _ensure_scanners_initialized(self) -> None:
        """Ensure scanners are initialized (lazy initialization).
        
        This method implements lazy initialization pattern to ensure scanners
        are only initialized when actually needed, and after event callbacks
        are set up. This allows progress events to be sent to the frontend.
        
        Requirements: 2.2, 3.1
        """
        if self._scanners_initialized:
            return
        
        if self.language:
            self._init_scanners(self.language)
        self._scanners_initialized = True
    
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
                
                # 检查文件扩展名匹配（如 .yml, .yaml, .json）
                if normalized_pattern.startswith(".") and normalized_file_path.endswith(normalized_pattern):
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
        
        使用符号分析结果来确定 context_level 和 confidence。
        
        - 根据符号边界确定 context_level（Requirements 5.1, 5.2）
        - 公共 API 和构造函数变更提升 confidence（Requirements 5.3, 5.4）
        - 缺少符号信息时使用保守默认值并在 notes 中标注（Requirements 5.5）
        
        Args:
            symbol: The symbol dictionary to match
            sym_rules: List of symbol rule dictionaries
            unit: The unit dictionary containing file information
            
        Returns:
            RuleSuggestion if matched, None otherwise
        """
        # 使用新的符号分析方法
        symbol_analysis = _analyze_symbols(unit)
        
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
            
            # 根据符号分析结果确定 context_level（Requirements 5.1, 5.2）
            context_level = symbol_analysis.suggested_context_level
            # 如果规则指定了更高级别的上下文，使用规则的设置
            rule_context = rule.get("context_level", "function")
            context_priority = {"local": 0, "function": 1, "file": 2}
            if context_priority.get(rule_context, 1) > context_priority.get(context_level, 1):
                context_level = rule_context
            
            # 构建增强的规则用于置信度计算
            enhanced_rule = rule.copy()
            
            # 公共 API 和构造函数变更提升 confidence（Requirements 5.3, 5.4）
            if symbol_analysis.is_public_api or symbol_analysis.is_constructor:
                # 提升 base_confidence 以确保高置信度
                current_base = enhanced_rule.get("base_confidence", 0.5)
                enhanced_rule["base_confidence"] = max(current_base, 0.75)
                # 设置高符号风险
                enhanced_rule["symbol_risk"] = "high"
            
            # Calculate final confidence
            confidence = self._calculate_confidence(enhanced_rule, unit)
            
            # 构建 notes，包含符号分析信息
            base_notes = rule.get("notes", "lang:sym_rule")
            analysis_notes = ",".join(symbol_analysis.notes) if symbol_analysis.notes else ""
            notes = f"{base_notes}"
            if analysis_notes:
                notes = f"{notes};{analysis_notes}"
            
            # 构建 extra_requests（使用新的依赖提示方法）
            extra_requests = list(rule.get("extra_requests", []))
            
            # 添加基于符号分析的依赖提示（Requirements 8.1, 8.2, 8.4）
            dependency_hints = symbol_analysis.get_dependency_hints()
            for hint in dependency_hints:
                if not any(r.get("type") == hint.get("type") for r in extra_requests):
                    extra_requests.append(hint)
            
            # All conditions matched
            return RuleSuggestion(
                context_level=context_level,
                confidence=confidence,
                notes=notes,
                extra_requests=extra_requests if extra_requests else []
            )
        
        # 如果没有匹配的规则但有符号信息，返回基于符号分析的默认建议
        if symbol_analysis.has_symbol_info:
            # 构建基于符号分析的规则
            symbol_based_rule = {
                "base_confidence": 0.5,
            }
            
            # 公共 API 和构造函数提升置信度
            if symbol_analysis.is_public_api or symbol_analysis.is_constructor:
                symbol_based_rule["base_confidence"] = 0.75
                symbol_based_rule["symbol_risk"] = "high"
            
            confidence = self._calculate_confidence(symbol_based_rule, unit)
            
            # 构建 notes
            analysis_notes = ",".join(symbol_analysis.notes) if symbol_analysis.notes else ""
            notes = f"lang:sym_analysis"
            if analysis_notes:
                notes = f"{notes};{analysis_notes}"
            
            # 构建 extra_requests（使用新的依赖提示方法）
            extra_requests = symbol_analysis.get_dependency_hints()
            
            return RuleSuggestion(
                context_level=symbol_analysis.suggested_context_level,
                confidence=confidence,
                notes=notes,
                extra_requests=extra_requests if extra_requests else []
            )
        
        # 缺少符号信息时使用保守默认值（Requirements 5.5）
        if not symbol_analysis.has_symbol_info:
            # 即使没有符号信息，也要检查是否为配置文件（Requirements 8.3）
            extra_requests = []
            context_level = "function"  # 保守默认值
            notes_parts = ["lang:sym_rule", "symbol_info_missing"]
            
            if symbol_analysis.is_config_file:
                extra_requests.append({"type": "search_config_usage"})
                context_level = "file"
                notes_parts.append("config_file")
            
            return RuleSuggestion(
                context_level=context_level,
                confidence=self._calculate_confidence({"base_confidence": 0.4}, unit),
                notes=";".join(notes_parts),
                extra_requests=extra_requests
            )
        
        return None
    
    def _calculate_confidence(self, rule: Dict[str, Any], unit: Dict[str, Any]) -> float:
        """Calculate final confidence based on base confidence and dynamic adjusters.
        
        使用新的 _ConfidenceFactors 和 _RiskFactors 结构进行计算，
        保持方法签名不变以确保向后兼容。
        
        Args:
            rule: The rule dictionary containing base_confidence and confidence_adjusters
            unit: The unit dictionary containing file information
            
        Returns:
            Final confidence value between 0.0 and 1.0, following the confidence intervals:
            - 0.75 ~ 1.0: High confidence (HIGH) - 精确匹配或高风险
            - 0.5 ~ 0.75: Medium confidence (MEDIUM) - 部分匹配
            - 0.0 ~ 0.5: Low confidence (LOW) - 无匹配或默认
        """
        # 构建置信度因子
        confidence_factors = self._build_confidence_factors(rule, unit)
        
        # 构建风险因子
        risk_factors = self._build_risk_factors(rule, unit)
        
        # 计算匹配确定性和风险等级
        match_certainty = confidence_factors.to_match_certainty()
        risk_level = risk_factors.to_risk_level()
        
        # 使用新的映射函数计算最终置信度
        return _compute_final_confidence(match_certainty, risk_level)
    
    def _build_confidence_factors(self, rule: Dict[str, Any], unit: Dict[str, Any]) -> _ConfidenceFactors:
        """构建置信度计算因子
        
        Args:
            rule: 规则字典
            unit: 变更单元字典
            
        Returns:
            _ConfidenceFactors 实例
        """
        # 1. 计算规则特异性（匹配条件数量）
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
        
        # 2. 计算模式精度
        # 基于 base_confidence 推断精度：高 base_confidence 表示精确匹配
        base_confidence = rule.get("base_confidence", rule.get("confidence", 0.4))
        if base_confidence >= 0.8:
            pattern_precision = 1.0  # 精确匹配
        elif base_confidence >= 0.5:
            pattern_precision = 0.5  # 部分匹配
        else:
            pattern_precision = 0.0  # 无匹配
        
        # 3. 计算上下文可用性（符号信息完整度）
        symbol = unit.get("symbol", {})
        context_availability = 0.0
        if symbol:
            # 检查符号信息的完整度
            if symbol.get("kind") or symbol.get("functions") or symbol.get("classes"):
                context_availability += 0.4
            if symbol.get("name"):
                context_availability += 0.3
            if symbol.get("start_line") and symbol.get("end_line"):
                context_availability += 0.3
        
        # 4. 语言特定加成
        language_bonus = 0.0
        if self.language and self.language_config:
            # 如果有语言特定配置，给予加成
            language_bonus = 0.1
        
        return _ConfidenceFactors(
            rule_specificity=rule_specificity,
            pattern_precision=pattern_precision,
            context_availability=context_availability,
            language_bonus=language_bonus
        )
    
    def _build_risk_factors(self, rule: Dict[str, Any], unit: Dict[str, Any]) -> _RiskFactors:
        """构建风险计算因子
        
        使用 _analyze_symbols() 进行符号分析，获取更准确的符号风险。
        
        Args:
            rule: 规则字典
            unit: 变更单元字典
            
        Returns:
            _RiskFactors 实例
        """
        # 1. 变更范围（变更行数）
        metrics = unit.get("metrics", {})
        change_scope = self._total_changed(metrics)
        
        # 2. 安全敏感检测
        file_path = unit.get("file_path", "").lower()
        tags = set(unit.get("tags", []) or [])
        security_keywords = self._get_base_config("security_keywords", [])
        security_sensitive = "security_sensitive" in tags or any(kw in file_path for kw in security_keywords)
        
        # 3. 变更类型
        change_type = unit.get("change_type", "modify")
        
        # 4. 模式风险（从规则中获取或推断）
        pattern_risk = rule.get("risk_level", "medium")
        if pattern_risk not in ("low", "medium", "high"):
            pattern_risk = "medium"
        
        # 5. 符号风险（使用符号分析结果）
        # 如果规则中已指定 symbol_risk，优先使用
        if "symbol_risk" in rule:
            symbol_risk = rule["symbol_risk"]
        else:
            # 使用符号分析获取风险等级
            symbol_analysis = _analyze_symbols(unit)
            symbol_risk = symbol_analysis.get_symbol_risk()
        
        return _RiskFactors(
            change_scope=change_scope,
            security_sensitive=security_sensitive,
            change_type=change_type,
            pattern_risk=pattern_risk,
            symbol_risk=symbol_risk
        )
    
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

    def _init_scanners(self, language: str) -> None:
        """Initialize scanners for the specified language.
        
        Includes performance logging for initialization time.
        Emits scanner_init events for frontend progress tracking.
        
        Args:
            language: The language to get scanners for
            
        Requirements: 1.1, 1.2, 3.4, 4.2, 4.3
        """
        import time
        start_time = time.perf_counter()
        
        # Emit initialization start event (Requirements 1.1, 4.3)
        if self._event_callback:
            try:
                self._event_callback({
                    "type": "scanner_init",
                    "status": "start",
                    "language": language,
                    "timestamp": time.time()
                })
            except Exception as e:
                logger.warning(f"Failed to emit scanner_init start event: {e}")
        
        try:
            # Check if scanner execution is disabled
            try:
                from Agent.DIFF.rule.rule_config import get_scanner_execution_config
                exec_config = get_scanner_execution_config()
                if exec_config.get("mode") == "disabled":
                    logger.debug(f"Scanner execution disabled, skipping initialization for {language}")
                    self._scanners = []
                    return
            except ImportError:
                pass
            
            from Agent.DIFF.rule.scanner_registry import ScannerRegistry
            self._scanners = ScannerRegistry.get_available_scanners(language)
            
            init_duration_ms = (time.perf_counter() - start_time) * 1000
            
            if self._scanners:
                logger.info(
                    f"Initialized {len(self._scanners)} scanner(s) for '{language}' "
                    f"in {init_duration_ms:.2f}ms: {[s.name for s in self._scanners]}"
                )
            else:
                logger.debug(
                    f"No scanners available for '{language}' (init took {init_duration_ms:.2f}ms)"
                )
            
            # Emit initialization complete event (Requirements 1.2, 4.3)
            if self._event_callback:
                try:
                    self._event_callback({
                        "type": "scanner_init",
                        "status": "complete",
                        "language": language,
                        "duration_ms": init_duration_ms,
                        "scanner_count": len(self._scanners),
                        "scanners": [s.name for s in self._scanners]
                    })
                except Exception as e:
                    logger.warning(f"Failed to emit scanner_init complete event: {e}")
                
        except ImportError:
            init_duration_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                f"Scanner registry not available, skipping initialization "
                f"(took {init_duration_ms:.2f}ms)"
            )
            self._scanners = []
            # Emit initialization complete event even for ImportError (no scanners available)
            if self._event_callback:
                try:
                    self._event_callback({
                        "type": "scanner_init",
                        "status": "complete",
                        "language": language,
                        "duration_ms": init_duration_ms,
                        "scanner_count": 0,
                        "scanners": []
                    })
                except Exception as e:
                    logger.warning(f"Failed to emit scanner_init complete event: {e}")
        except Exception as e:
            init_duration_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                f"Failed to initialize scanners for {language} in {init_duration_ms:.2f}ms: {e}"
            )
            self._scanners = []
            # Emit initialization error event (Requirements 1.2)
            if self._event_callback:
                try:
                    self._event_callback({
                        "type": "scanner_init",
                        "status": "error",
                        "language": language,
                        "error": str(e)
                    })
                except Exception as emit_error:
                    logger.warning(f"Failed to emit scanner_init error event: {emit_error}")
    
    def _scan_file(
        self, 
        file_path: str, 
        content: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Execute all available scanners and return issues.
        
        Uses ScannerExecutor for optimized execution with performance logging,
        availability caching, and configurable execution modes (sequential/parallel).
        
        Error handling strategy (Requirements 6.4):
        - Each scanner runs independently
        - Failures in one scanner don't affect others
        - All errors are logged for debugging
        - Partial results from successful scanners are preserved
        
        Args:
            file_path: Path to the file to scan
            content: Optional file content (if not provided, read from file_path)
            
        Returns:
            List of issue dictionaries from all scanners
            
        Requirements: 1.1, 1.2, 1.3, 1.4, 2.2, 3.5, 6.3, 6.4
        """
        # Lazy initialization: ensure scanners are initialized before use (Requirements 2.2)
        self._ensure_scanners_initialized()
        
        if not self._scanners:
            return []
        
        # Try to use optimized ScannerExecutor
        try:
            from Agent.DIFF.rule.scanner_performance import ScannerExecutor
            from Agent.DIFF.rule.rule_config import get_scanner_execution_config
            
            # Get execution configuration
            exec_config = get_scanner_execution_config()
            
            # Create executor with configuration
            executor = ScannerExecutor(
                scanners=self._scanners,
                mode=exec_config.get("mode", "sequential"),
                max_workers=exec_config.get("max_workers", 4),
                global_timeout=exec_config.get("global_timeout"),
                enable_performance_log=exec_config.get("enable_performance_log", True),
                event_callback=self._event_callback,
            )
            
            # Execute and return results
            issues, stats = executor.execute(file_path, content)
            
            # Log performance summary at debug level
            if stats.total_duration_ms > 0:
                logger.debug(
                    f"Scanner execution completed: {stats.scanners_executed} executed, "
                    f"{stats.scanners_skipped} skipped, {stats.scanners_failed} failed, "
                    f"{stats.total_issues} issues in {stats.total_duration_ms:.2f}ms"
                )
            
            return issues
            
        except ImportError:
            logger.debug("ScannerExecutor not available, using fallback implementation")
        except Exception as e:
            logger.warning(f"ScannerExecutor failed, using fallback: {e}")
        
        # Fallback to original implementation
        return self._scan_file_fallback(file_path, content)
    
    def _scan_file_fallback(
        self, 
        file_path: str, 
        content: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Fallback scanner execution (original implementation).
        
        Used when ScannerExecutor is not available or fails.
        
        Args:
            file_path: Path to the file to scan
            content: Optional file content
            
        Returns:
            List of issue dictionaries from all scanners
        """
        all_issues: List[Dict[str, Any]] = []
        failed_scanners: List[str] = []
        successful_scanners: List[str] = []
        
        if not self._scanners:
            return all_issues
        
        # Get content for cache key computation
        scan_content = content
        if scan_content is None:
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    scan_content = f.read()
            except FileNotFoundError:
                logger.warning(f"File not found for scanning: {Path(file_path).name}")
                return all_issues
            except PermissionError:
                logger.warning(f"Permission denied reading file: {Path(file_path).name}")
                return all_issues
            except Exception as e:
                logger.warning(f"Failed to read file for scanning: {Path(file_path).name}: {e}")
                scan_content = ""
        
        # Import cache lazily to avoid circular imports
        cache = None
        try:
            from Agent.DIFF.rule.scanner_cache import get_scanner_cache
            cache = get_scanner_cache()
        except ImportError:
            logger.debug("Scanner cache not available, scanning without cache")
        except Exception as e:
            logger.debug(f"Failed to initialize scanner cache: {e}")
        
        for scanner in self._scanners:
            scanner_name = getattr(scanner, 'name', 'unknown')
            
            try:
                # Check if scanner is enabled (Requirements 4.2)
                if not scanner.enabled:
                    logger.debug(f"Scanner {scanner_name} is disabled, skipping")
                    continue
                
                # Check if scanner is available (Requirements 4.2)
                if not scanner.is_available():
                    logger.warning(
                        f"Scanner {scanner_name} is not available, skipping. "
                        f"Install {getattr(scanner, 'command', 'unknown')} to enable this scanner."
                    )
                    continue
                
                # Check cache first (Requirements 6.3)
                if cache and scan_content:
                    try:
                        cached_issues = cache.get(file_path, scanner_name, scan_content)
                        if cached_issues is not None:
                            # Cache hit - use cached results
                            for issue_dict in cached_issues:
                                # Ensure scanner name is set
                                issue_dict_copy = dict(issue_dict)
                                issue_dict_copy["scanner"] = scanner_name
                                all_issues.append(issue_dict_copy)
                            logger.debug(
                                f"Using cached results for {scanner_name} on {file_path}: "
                                f"{len(cached_issues)} issue(s)"
                            )
                            successful_scanners.append(scanner_name)
                            continue
                    except Exception as cache_error:
                        # Cache error shouldn't prevent scanning
                        logger.debug(f"Cache lookup failed for {scanner_name}: {cache_error}")
                
                # Cache miss - run scanner
                try:
                    issues = scanner.scan(file_path, content)
                except Exception as scan_error:
                    # Log scan failure and continue with other scanners (Requirements 6.4)
                    logger.warning(
                        f"Scanner {scanner_name} failed during scan of {file_path}: {scan_error}"
                    )
                    failed_scanners.append(scanner_name)
                    continue
                
                # Process scan results
                scanner_issues: List[Dict[str, Any]] = []
                
                for issue in issues:
                    try:
                        issue_dict = issue.to_dict()
                        issue_dict["scanner"] = scanner_name
                        scanner_issues.append(issue_dict)
                        all_issues.append(issue_dict)
                    except Exception as issue_error:
                        logger.debug(
                            f"Failed to process issue from {scanner_name}: {issue_error}"
                        )
                
                # Store results in cache (Requirements 6.3)
                if cache and scan_content:
                    try:
                        # Store without scanner name in cached issues (added on retrieval)
                        cache_issues = [issue.to_dict() for issue in issues]
                        cache.set(file_path, scanner_name, scan_content, cache_issues)
                    except Exception as cache_error:
                        # Cache error shouldn't affect results
                        logger.debug(f"Failed to cache results for {scanner_name}: {cache_error}")
                
                successful_scanners.append(scanner_name)
                
                if issues:
                    logger.debug(
                        f"Scanner {scanner_name} found {len(issues)} issue(s) in {file_path}"
                    )
                    
            except Exception as e:
                # Catch-all for any unexpected errors (Requirements 6.4)
                logger.warning(
                    f"Unexpected error in scanner {scanner_name} for {file_path}: {e}"
                )
                failed_scanners.append(scanner_name)
                # Continue with other scanners - don't let one failure stop the process
                continue
        
        # Log summary if there were failures
        if failed_scanners:
            logger.warning(
                f"Scan completed with failures. Successful: {successful_scanners}, "
                f"Failed: {failed_scanners}. Returning {len(all_issues)} issue(s) from successful scanners."
            )
        
        return all_issues
    
    def _filter_critical_issues(
        self,
        issues: List[Dict[str, Any]],
        changed_lines: Optional[List[int]] = None,
        max_issues: int = 10
    ) -> List[Dict[str, Any]]:
        """过滤 Scanner 结果，只保留严重问题。
        
        过滤策略：
        1. 只保留与变更行相关的问题（如果提供了 changed_lines）
        2. 只保留严重问题类型：
           - 安全漏洞（security, injection, xss, csrf, auth 等）
           - 逻辑错误（undefined, null, type error 等）
           - 语法错误（syntax, parse error 等）
           - 依赖问题（import, module not found 等）
           - 内存问题（memory, leak 等）
        3. 过滤掉格式/风格问题：
           - 行长度（E501）
           - 空白行（W293, W291）
           - 命名规范（C0103）
           - 缺少 docstring（C0116, C0115）
           - 变量命名（N801, N802 等）
        
        Args:
            issues: 原始问题列表
            changed_lines: 变更的行号列表（可选）
            max_issues: 最大返回问题数
            
        Returns:
            过滤后的严重问题列表
        """
        if not issues:
            return []
        
        # 需要过滤掉的规则 ID（格式/风格问题）
        IGNORED_RULES = {
            # flake8 格式问题
            "E501",  # line too long
            "W291", "W292", "W293",  # whitespace
            "E302", "E303", "E305",  # blank lines
            "E101", "E111", "E117",  # indentation
            "W503", "W504",  # line break
            # pylint 格式/命名问题
            "C0103",  # invalid-name
            "C0114", "C0115", "C0116",  # missing-docstring
            "C0301",  # line-too-long
            "C0303",  # trailing-whitespace
            "C0304",  # missing-final-newline
            "C0305",  # trailing-newlines
            "C0321",  # multiple-statements
            "R0903",  # too-few-public-methods
            "R0913",  # too-many-arguments
            "R0914",  # too-many-locals
            "R0915",  # too-many-statements
            "W0311",  # bad-indentation
            "W0612",  # unused-variable (可能是误报)
            # pep8 命名
            "N801", "N802", "N803", "N806", "N812",
        }
        
        # 严重问题关键词（在 message 或 rule_id 中匹配）
        CRITICAL_KEYWORDS = {
            # 安全问题
            "security", "injection", "xss", "csrf", "auth", "password",
            "token", "secret", "credential", "encrypt", "hash", "sql",
            "command", "exec", "eval", "unsafe", "vulnerable",
            # 逻辑错误
            "undefined", "null", "none", "type", "attribute", "index",
            "key", "division", "zero", "overflow", "underflow",
            # 语法错误
            "syntax", "parse", "invalid", "unexpected", "missing",
            # 依赖问题
            "import", "module", "not found", "unresolved", "undefined name",
            # 内存问题
            "memory", "leak", "resource", "close", "release",
            # 未使用的导入（可能是依赖问题）
            "unused import", "imported but unused",
        }
        
        filtered = []
        
        for issue in issues:
            rule_id = issue.get("rule_id", "")
            severity = issue.get("severity", "")
            message = issue.get("message", "").lower()
            line = issue.get("line", 0)
            
            # 1. 过滤掉已知的格式/风格规则
            if rule_id in IGNORED_RULES:
                continue
            
            # 2. 如果提供了变更行，只保留相关问题
            if changed_lines and line not in changed_lines:
                continue
            
            # 3. 只保留 error 级别，或包含严重关键词的问题
            is_error = severity == "error"
            has_critical_keyword = any(kw in message or kw in rule_id.lower() for kw in CRITICAL_KEYWORDS)
            
            if is_error or has_critical_keyword:
                filtered.append(issue)
        
        # 4. 限制返回数量，优先保留 error 级别
        if len(filtered) > max_issues:
            # 按严重程度排序：error > warning > info
            severity_order = {"error": 0, "warning": 1, "info": 2}
            filtered.sort(key=lambda x: severity_order.get(x.get("severity", "info"), 2))
            filtered = filtered[:max_issues]
        
        return filtered
    
    def _build_scanner_extra_request(
        self, 
        issues: List[Dict[str, Any]],
        scanner_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Build extra_requests entry for scanner results.
        
        Args:
            issues: List of issue dictionaries
            scanner_name: Optional scanner name (if all issues from same scanner)
            
        Returns:
            Dictionary in format {"type": "scanner_issues", "issues": [...], ...}
            
        Requirements: 2.3
        """
        error_count = sum(1 for i in issues if i.get("severity") == "error")
        warning_count = sum(1 for i in issues if i.get("severity") == "warning")
        
        result: Dict[str, Any] = {
            "type": "scanner_issues",
            "issues": issues,
            "issue_count": len(issues),
            "error_count": error_count,
            "warning_count": warning_count,
        }
        
        if scanner_name:
            result["scanner"] = scanner_name
        elif issues:
            # Get unique scanner names
            scanners = list(set(i.get("scanner", "unknown") for i in issues))
            if len(scanners) == 1:
                result["scanner"] = scanners[0]
            else:
                result["scanners"] = scanners
        
        return result
    
    def _apply_scanner_results(
        self, 
        suggestion: RuleSuggestion, 
        issues: List[Dict[str, Any]]
    ) -> RuleSuggestion:
        """Apply scanner results to a rule suggestion.
        
        Modifies confidence and context_level based on scanner findings:
        - Error-level issues increase confidence by at least 0.1 (Requirements 5.1)
        - Multiple issues upgrade context_level to "file" (Requirements 5.2)
        - Security issues add "security_sensitive" to notes (Requirements 5.3)
        - No issues leaves values unchanged (Requirements 5.4)
        
        Args:
            suggestion: The base RuleSuggestion to modify
            issues: List of issue dictionaries from scanners
            
        Returns:
            Modified RuleSuggestion with scanner results applied
            
        Requirements: 3.5, 5.1, 5.2, 5.3, 5.4
        """
        if not issues:
            # No issues - return suggestion unchanged (Requirements 5.4)
            return suggestion
        
        # 过滤只保留严重问题，减少噪音
        critical_issues = self._filter_critical_issues(issues)
        
        # 发送问题汇总事件到前端
        if self._event_callback:
            try:
                self._event_callback({
                    "type": "scanner_issues_summary",
                    "total_issues": len(issues),
                    "critical_issues": critical_issues,
                    "filtered_count": len(critical_issues),
                    "original_count": len(issues),
                    "by_severity": {
                        "error": sum(1 for i in critical_issues if i.get("severity") == "error"),
                        "warning": sum(1 for i in critical_issues if i.get("severity") == "warning"),
                        "info": sum(1 for i in critical_issues if i.get("severity") == "info")
                    }
                })
            except Exception:
                pass  # 事件发送失败不影响主流程
        
        # 如果过滤后没有严重问题，只记录统计信息
        if not critical_issues:
            # 仍然记录原始统计，但不传递具体问题
            scanner_extra = {
                "type": "scanner_issues",
                "issues": [],  # 空列表，不传递具体问题
                "issue_count": len(issues),
                "error_count": sum(1 for i in issues if i.get("severity") == "error"),
                "warning_count": sum(1 for i in issues if i.get("severity") == "warning"),
                "filtered_count": 0,  # 过滤后的严重问题数
                "note": "no_critical_issues_after_filter"
            }
        else:
            # 只传递过滤后的严重问题
            scanner_extra = self._build_scanner_extra_request(critical_issues)
            scanner_extra["filtered_count"] = len(critical_issues)
            scanner_extra["original_count"] = len(issues)
        
        # Add to existing extra_requests
        new_extra_requests = list(suggestion.extra_requests) if suggestion.extra_requests else []
        new_extra_requests.append(scanner_extra)
        
        # Calculate confidence adjustment
        new_confidence = suggestion.confidence
        has_error = any(i.get("severity") == "error" for i in issues)
        
        # Requirements 5.1: Error-level issues increase confidence by at least 0.1
        if has_error:
            new_confidence = min(1.0, new_confidence + 0.1)
        
        # Determine context level
        new_context_level = suggestion.context_level
        
        # Requirements 5.2: Multiple issues upgrade context_level to "file"
        if len(issues) > 1 and new_context_level == "function":
            new_context_level = "file"
        
        # Build notes
        new_notes = suggestion.notes
        
        # Requirements 5.3: Security issues add "security_sensitive" to notes
        security_keywords = ["security", "auth", "password", "token", "secret", 
                           "credential", "encrypt", "decrypt", "hash", "salt",
                           "jwt", "oauth", "injection", "xss", "csrf"]
        has_security_issue = any(
            any(kw in i.get("message", "").lower() or kw in i.get("rule_id", "").lower() 
                for kw in security_keywords)
            for i in issues
        )
        
        if has_security_issue and "security_sensitive" not in new_notes:
            if new_notes:
                new_notes = f"{new_notes};security_sensitive"
            else:
                new_notes = "security_sensitive"
        
        return RuleSuggestion(
            context_level=new_context_level,
            confidence=round(new_confidence, 2),
            notes=new_notes,
            extra_requests=new_extra_requests
        )

    def match(self, unit: Dict[str, Any]) -> Optional[RuleSuggestion]:  # pragma: no cover - interface
        """Match unit against all applicable rules.
        
        Args:
            unit: The unit dictionary to match
            
        Returns:
            RuleSuggestion if matched, None otherwise
        """
        raise NotImplementedError


__all__ = [
    "RuleSuggestion", 
    "RuleHandler", 
    "CHANGE_PATTERNS",
    "_detect_patterns",
    "_get_highest_risk_pattern",
    "_patterns_to_notes",
    "_analyze_symbols",
    "_SymbolAnalysisResult",
    "_is_interface_name",
    "_is_data_model",
]
