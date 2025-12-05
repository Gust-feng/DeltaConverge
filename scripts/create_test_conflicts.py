"""创建测试冲突数据，用于验证规则优化页面的显示效果。

此脚本创建两类冲突数据：
1. 满足 ApplicableRule 条件的冲突（>=5次，>=90%一致性，>=2标签，>=2文件）
2. 仅满足 ReferenceHint 条件的冲突（不满足上述某个条件）
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Agent.DIFF.issue.conflict_tracker import (
    ConflictTracker,
    ConflictType,
    RuleConflict,
    get_conflict_tracker,
)
from Agent.DIFF.issue.rule_analyzer import RuleAnalyzer, get_rule_analyzer


def create_applicable_rule_conflicts():
    """创建满足 ApplicableRule 条件的冲突数据。
    
    条件：
    - 至少 5 次出现
    - 至少 90% 一致性
    - 至少 2 个通用标签
    - 至少 2 个不同文件
    """
    conflicts = []
    
    # 组1: Python API 端点函数修改 (6个冲突，3个文件，100%一致性，2个标签)
    # 应该生成 ApplicableRule
    for i, file_name in enumerate([
        "src/services/user_service.py",
        "src/services/order_service.py", 
        "src/services/payment_service.py",
        "src/services/user_service.py",  # 重复文件
        "src/services/order_service.py",
        "src/services/payment_service.py",
    ]):
        conflicts.append(RuleConflict(
            conflict_type=ConflictType.RULE_HIGH_LLM_EXPAND,
            unit_id=f"applicable_001_{i}",
            file_path=file_name,
            language="python",
            tags=["function_change", "api_endpoint"],  # 2个标签
            metrics={"lines_added": 15 + i, "lines_removed": 3},
            rule_context_level="function",
            rule_confidence=0.85,
            rule_notes="API 端点函数修改",
            llm_context_level="file_context",  # 100% 一致性
            llm_skip_review=False,
            llm_reason="此函数涉及多个依赖，需要查看完整文件上下文",
        ))
    
    # 组2: TypeScript 处理器修改 (5个冲突，3个文件，100%一致性，2个标签)
    # 应该生成 ApplicableRule
    for i, file_name in enumerate([
        "src/handlers/auth.ts",
        "src/handlers/payment.ts",
        "src/handlers/order.ts",
        "src/handlers/auth.ts",
        "src/handlers/payment.ts",
    ]):
        conflicts.append(RuleConflict(
            conflict_type=ConflictType.CONTEXT_LEVEL_MISMATCH,
            unit_id=f"applicable_002_{i}",
            file_path=file_name,
            language="typescript",
            tags=["handler_change", "async_function"],  # 2个标签
            metrics={"lines_added": 12 + i, "lines_removed": 5},
            rule_context_level="function",
            rule_confidence=0.55,
            rule_notes="处理器函数修改",
            llm_context_level="full_file",  # 100% 一致性
            llm_skip_review=False,
            llm_reason="处理器逻辑复杂，需要完整文件上下文",
        ))
    
    # 组3: Go 服务层修改 (7个冲突，4个文件，100%一致性，3个标签)
    # 应该生成 ApplicableRule
    for i, file_name in enumerate([
        "internal/service/user.go",
        "internal/service/order.go",
        "internal/service/payment.go",
        "internal/service/auth.go",
        "internal/service/user.go",
        "internal/service/order.go",
        "internal/service/payment.go",
    ]):
        conflicts.append(RuleConflict(
            conflict_type=ConflictType.RULE_LOW_LLM_CONSISTENT,
            unit_id=f"applicable_003_{i}",
            file_path=file_name,
            language="go",
            tags=["service_layer", "business_logic", "database_access"],  # 3个标签
            metrics={"lines_added": 20 + i, "lines_removed": 8},
            rule_context_level="function",
            rule_confidence=0.35,
            rule_notes="服务层函数修改",
            llm_context_level="file_context",  # 100% 一致性
            llm_skip_review=False,
            llm_reason="服务层需要更多上下文",
        ))
    
    return conflicts


def create_reference_hint_conflicts():
    """创建仅满足 ReferenceHint 条件的冲突数据。
    
    这些冲突不满足 ApplicableRule 的某个条件。
    """
    conflicts = []
    
    # 组1: 样本不足 (只有3个冲突，不满足>=5的条件)
    for i, file_name in enumerate([
        "tests/test_user.py",
        "tests/test_order.py",
        "tests/test_payment.py",
    ]):
        conflicts.append(RuleConflict(
            conflict_type=ConflictType.RULE_LOW_LLM_CONSISTENT,
            unit_id=f"hint_001_{i}",
            file_path=file_name,
            language="python",
            tags=["test_file", "unit_test"],  # 2个标签
            metrics={"lines_added": 20 + i, "lines_removed": 5},
            rule_context_level="function",
            rule_confidence=0.35,
            rule_notes="测试文件修改",
            llm_context_level="function",  # 100% 一致性
            llm_skip_review=False,
            llm_reason="测试用例修改，只需函数级别上下文",
        ))
    
    # 组2: 一致性不足 (5个冲突，但只有60%一致性)
    llm_levels = ["file_context", "file_context", "file_context", "function", "local"]
    for i, (file_name, llm_level) in enumerate(zip([
        "src/utils/helpers.py",
        "src/utils/validators.py",
        "src/utils/formatters.py",
        "src/utils/helpers.py",
        "src/utils/validators.py",
    ], llm_levels)):
        conflicts.append(RuleConflict(
            conflict_type=ConflictType.RULE_HIGH_LLM_EXPAND,
            unit_id=f"hint_002_{i}",
            file_path=file_name,
            language="python",
            tags=["utility_function", "helper"],  # 2个标签
            metrics={"lines_added": 8 + i, "lines_removed": 2},
            rule_context_level="function",
            rule_confidence=0.75,
            rule_notes="工具函数修改",
            llm_context_level=llm_level,  # 60% 一致性
            llm_skip_review=False,
            llm_reason="工具函数修改",
        ))
    
    # 组3: 通用标签不足 (5个冲突，但只有1个通用标签)
    tag_sets = [
        ["config_change"],
        ["config_change", "env_var"],
        ["config_change"],
        ["config_change", "secret"],
        ["config_change"],
    ]
    for i, (file_name, tags) in enumerate(zip([
        "config/settings.yaml",
        "config/database.yaml",
        "config/redis.yaml",
        "config/settings.yaml",
        "config/database.yaml",
    ], tag_sets)):
        conflicts.append(RuleConflict(
            conflict_type=ConflictType.RULE_HIGH_LLM_SKIP,
            unit_id=f"hint_003_{i}",
            file_path=file_name,
            language="yaml",
            tags=tags,  # 只有 config_change 是通用的
            metrics={"lines_added": 2 + i, "lines_removed": 1},
            rule_context_level="function",
            rule_confidence=0.78,
            rule_notes="配置文件修改",
            llm_context_level=None,
            llm_skip_review=True,
            llm_reason="配置文件修改，无需审查",
        ))
    
    # 组4: 文件覆盖不足 (5个冲突，但只来自1个文件)
    for i in range(5):
        conflicts.append(RuleConflict(
            conflict_type=ConflictType.RULE_LOW_LLM_CONSISTENT,
            unit_id=f"hint_004_{i}",
            file_path="src/models/user.py",  # 同一个文件
            language="python",
            tags=["model_change", "database_schema"],  # 2个标签
            metrics={"lines_added": 10 + i, "lines_removed": 3},
            rule_context_level="function",
            rule_confidence=0.40,
            rule_notes="模型修改",
            llm_context_level="file_context",  # 100% 一致性
            llm_skip_review=False,
            llm_reason="模型修改需要更多上下文",
        ))
    
    # 组5: Java 类修改 (4个冲突，不满足>=5的条件)
    for i, file_name in enumerate([
        "src/main/java/com/example/UserService.java",
        "src/main/java/com/example/OrderService.java",
        "src/main/java/com/example/PaymentService.java",
        "src/main/java/com/example/AuthService.java",
    ]):
        conflicts.append(RuleConflict(
            conflict_type=ConflictType.RULE_HIGH_LLM_EXPAND,
            unit_id=f"hint_005_{i}",
            file_path=file_name,
            language="java",
            tags=["service_class", "spring_bean"],  # 2个标签
            metrics={"lines_added": 25 + i, "lines_removed": 10},
            rule_context_level="function",
            rule_confidence=0.80,
            rule_notes="服务类修改",
            llm_context_level="full_file",  # 100% 一致性
            llm_skip_review=False,
            llm_reason="Spring 服务类需要完整文件上下文",
        ))
    
    return conflicts


def create_test_conflicts():
    """创建测试冲突数据。"""
    tracker = get_conflict_tracker()
    
    # 创建满足 ApplicableRule 条件的冲突
    applicable_conflicts = create_applicable_rule_conflicts()
    print(f"Creating {len(applicable_conflicts)} conflicts for ApplicableRule testing...")
    
    for conflict in applicable_conflicts:
        filepath = tracker.record(conflict)
        print(f"  Created: {filepath}")
    
    # 创建仅满足 ReferenceHint 条件的冲突
    hint_conflicts = create_reference_hint_conflicts()
    print(f"\nCreating {len(hint_conflicts)} conflicts for ReferenceHint testing...")
    
    for conflict in hint_conflicts:
        filepath = tracker.record(conflict)
        print(f"  Created: {filepath}")
    
    total = len(applicable_conflicts) + len(hint_conflicts)
    print(f"\nTotal {total} test conflicts created.")
    
    # 显示汇总
    summary = tracker.get_summary()
    print(f"\nSummary:")
    print(f"  Total conflicts: {summary['total_conflicts']}")
    print(f"  By type: {summary['by_type']}")
    print(f"  By language: {summary['by_language']}")
    
    # 使用 RuleAnalyzer 分析
    analyzer = get_rule_analyzer()
    applicable_rules, reference_hints = analyzer.analyze_all()
    
    print(f"\n=== Analysis Results ===")
    print(f"Applicable Rules: {len(applicable_rules)}")
    for rule in applicable_rules:
        print(f"  - {rule.rule_id}: {rule.language} [{', '.join(rule.required_tags)}]")
        print(f"    samples={rule.sample_count}, consistency={rule.consistency:.0%}, files={rule.unique_files}")
    
    print(f"\nReference Hints: {len(reference_hints)}")
    for hint in reference_hints:
        print(f"  - {hint.language} [{', '.join(hint.tags[:3])}...]")
        print(f"    samples={hint.sample_count}, consistency={hint.consistency:.0%}, reason={hint.reason}")


if __name__ == "__main__":
    create_test_conflicts()
