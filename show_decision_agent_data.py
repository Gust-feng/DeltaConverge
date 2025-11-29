#!/usr/bin/env python3
"""展示发送给决策agent的具体数据结构"""

import json
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Any, Optional

# 模拟DiffMode枚举
class DiffMode:
    WORKSPACE = "workspace"
    STAGED = "staged"
    COMMIT = "commit"
    BRANCH = "branch"

# 模拟build_review_index函数的简化版本，用于生成示例数据
def build_sample_review_index() -> Dict[str, Any]:
    """生成示例审查索引数据"""
    
    # 模拟审查单元数据
    sample_units = [
        {
            "id": "unit_1",
            "file_path": "src/rule_base.py",
            "change_type": "modify",
            "hunk_range": {
                "new_start": 10,
                "new_lines": 25,
                "old_start": 10,
                "old_lines": 20
            },
            "line_numbers": {
                "new_compact": "10-34",
                "old_compact": "10-29"
            },
            "metrics": {
                "added_lines": 15,
                "removed_lines": 5,
                "total_lines": 34
            },
            "tags": ["rule_parsing", "architecture", "python"],
            "rule_context_level": "high",
            "rule_confidence": 0.95,
            "rule_notes": "优化了规则匹配算法，提高了匹配准确性",
            "context_mode": "normal",
            "symbol": {
                "name": "RuleHandler",
                "type": "class",
                "start_line": 15,
                "end_line": 40
            },
            "rule_suggestion": {
                "rule_id": "rule_001",
                "suggestion_type": "optimization",
                "description": "建议添加更多单元测试以验证规则匹配逻辑",
                "confidence": 0.95,
                "priority": "high"
            },
            "agent_decision": "需要详细审查",
            "rule_extra_requests": ["检查规则匹配的边界情况"],
            "unified_diff_with_lines": "@@ -10,20 +10,25 @@ class RuleHandler:\n+    def __init__(self):\n+        self.rules = []\n+        self.confidence_adjusters = []\n+\n     def match_rule(self, code_context):\n-        for rule in self.rules:\n-            if rule.match(code_context):\n-                return rule\n+        # 按置信度排序规则，优先匹配高置信度规则\n+        sorted_rules = sorted(self.rules, key=lambda r: r.base_confidence, reverse=True)\n+        for rule in sorted_rules:\n+            if rule.match(code_context):\n+                return rule\n         return None"
        },
        {
            "id": "unit_2",
            "file_path": "src/rule_config.py",
            "change_type": "modify",
            "hunk_range": {
                "new_start": 50,
                "new_lines": 10,
                "old_start": 50,
                "old_lines": 8
            },
            "line_numbers": {
                "new_compact": "50-59",
                "old_compact": "50-57"
            },
            "metrics": {
                "added_lines": 5,
                "removed_lines": 3,
                "total_lines": 200
            },
            "tags": ["configuration", "python"],
            "rule_context_level": "medium",
            "rule_confidence": 0.85,
            "rule_notes": "更新了规则配置结构，添加了置信度调整器",
            "context_mode": "normal",
            "symbol": {
                "name": "load_rules",
                "type": "function",
                "start_line": 45,
                "end_line": 65
            },
            "rule_suggestion": {
                "rule_id": "rule_002",
                "suggestion_type": "refactoring",
                "description": "建议将配置加载逻辑提取为独立函数",
                "confidence": 0.85,
                "priority": "medium"
            },
            "agent_decision": "快速审查",
            "rule_extra_requests": [],
            "unified_diff_with_lines": "@@ -50,8 +50,10 @@ def load_rules():\n     for rule_config in config.get('rules', []):\n-        confidence = rule_config.get('confidence', 0.5)\n+        base_confidence = rule_config.get('base_confidence', 0.5)\n+        confidence_adjusters = rule_config.get('confidence_adjusters', [])\n         rule = Rule(\n-            confidence=confidence,\n+            base_confidence=base_confidence,\n+            confidence_adjusters=confidence_adjusters,\n             patterns=rule_config.get('patterns', []),\n             tags=rule_config.get('tags', [])\n         )"
        },
        {
            "id": "unit_3",
            "file_path": "tests/test_rule_parser.py",
            "change_type": "add",
            "hunk_range": {
                "new_start": 1,
                "new_lines": 100,
                "old_start": 0,
                "old_lines": 0
            },
            "line_numbers": {
                "new_compact": "1-100",
                "old_compact": None
            },
            "metrics": {
                "added_lines": 100,
                "removed_lines": 0,
                "total_lines": 100
            },
            "tags": ["test", "python", "unit_test"],
            "rule_context_level": "low",
            "rule_confidence": 0.75,
            "rule_notes": "添加了规则解析器的单元测试",
            "context_mode": "normal",
            "symbol": None,
            "rule_suggestion": {
                "rule_id": "rule_003",
                "suggestion_type": "testing",
                "description": "建议添加更多边界情况测试",
                "confidence": 0.75,
                "priority": "low"
            },
            "agent_decision": "快速审查",
            "rule_extra_requests": [],
            "unified_diff_with_lines": "@@ -0,0 +1,100 @@\n+\"\"\"规则解析模块的单元测试\"\"\"\n+\n+import unittest\n+from src.rule_base import RuleHandler, RuleSuggestion\n+from src.rule_config import load_rules\n+\n+class TestRuleParser(unittest.TestCase):\n+    \n+    def setUp(self):\n+        self.rule_handler = RuleHandler()\n+        self.rules = load_rules()\n+    \n+    def test_rule_matching(self):\n+        # 测试规则匹配逻辑\n+        code_context = {\n+            'file_path': 'test.py',\n+            'content': 'def hello():\n    print(\"Hello world\")',\n+            'language': 'python'\n+        }\n+        suggestion = self.rule_handler.match_rule(code_context)\n+        self.assertIsNotNone(suggestion)\n+\n+if __name__ == '__main__':\n+    unittest.main()"
        }
    ]
    
    # 构建文件字典
    files_dict: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for unit in sample_units:
        files_dict[unit["file_path"]].append(unit)
    
    # 计算统计信息
    total_lines_summary = {
        "added": sum(u["metrics"]["added_lines"] for u in sample_units),
        "removed": sum(u["metrics"]["removed_lines"] for u in sample_units),
    }
    
    changes_by_type = {"add": 0, "modify": 0, "delete": 0}
    for file_units in files_dict.values():
        change_kind = file_units[0].get("change_type", "modify")
        if change_kind in changes_by_type:
            changes_by_type[change_kind] += 1
    
    # 构建文件条目和单元索引
    file_entries: List[Dict[str, Any]] = []
    units_index: List[Dict[str, Any]] = []
    
    for file_path in sorted(files_dict.keys()):
        file_units = files_dict[file_path]
        file_tags = sorted({tag for u in file_units for tag in u.get("tags", [])})
        file_added = sum(u["metrics"]["added_lines"] for u in file_units)
        file_removed = sum(u["metrics"]["removed_lines"] for u in file_units)
        
        changes: List[Dict[str, Any]] = []
        for unit in file_units:
            hunk_range = unit.get("hunk_range", {})
            changes.append({
                "id": unit.get("id"),
                "unit_id": unit.get("unit_id") or unit.get("id"),
                "rule_context_level": unit.get("rule_context_level"),
                "rule_confidence": unit.get("rule_confidence"),
                "rule_notes": unit.get("rule_notes"),
                "hunk_range": hunk_range,
                "line_numbers": unit.get("line_numbers"),
                "metrics": unit.get("metrics", {}),
                "tags": unit.get("tags", []),
                "context_mode": unit.get("context_mode"),
                "symbol": unit.get("symbol"),
                "rule_suggestion": unit.get("rule_suggestion"),
                "agent_decision": unit.get("agent_decision"),
                "rule_extra_requests": unit.get("rule_extra_requests"),
                "unified_diff_with_lines": unit.get("unified_diff_with_lines"),
            })
            
            units_index.append({
                "unit_id": unit.get("unit_id") or unit.get("id"),
                "file_path": file_path,
                "patch_type": unit.get("patch_type") or unit.get("change_type"),
                "tags": unit.get("tags", []),
                "metrics": unit.get("metrics", {}),
                "rule_context_level": unit.get("rule_context_level"),
                "rule_confidence": unit.get("rule_confidence"),
                "line_numbers": unit.get("line_numbers"),
            })
        
        file_entries.append({
            "path": file_path,
            "language": "python",  # 简化处理
            "change_type": file_units[0].get("change_type", "modify"),
            "metrics": {
                "added_lines": file_added,
                "removed_lines": file_removed,
                "changes": len(changes),
            },
            "tags": file_tags,
            "changes": changes,
        })
    
    # 构建最终的审查索引
    review_index = {
        "review_metadata": {
            "mode": DiffMode.WORKSPACE,
            "base_branch": "main",
            "total_files": len(files_dict),
            "total_changes": len(sample_units),
            "timestamp": datetime.now().isoformat(),
        },
        "summary": {
            "changes_by_type": changes_by_type,
            "total_lines": total_lines_summary,
            "files_changed": sorted(files_dict.keys()),
        },
        "units": units_index,
        "files": file_entries,
    }
    
    return review_index

def main():
    """主函数"""
    print("=" * 80)
    print("发送给决策agent的具体数据结构")
    print("=" * 80)
    
    # 生成示例数据
    review_index = build_sample_review_index()
    
    # 打印数据结构
    print("\n1. 数据概览：")
    print(f"   - 总文件数：{review_index['review_metadata']['total_files']}")
    print(f"   - 总变更数：{review_index['review_metadata']['total_changes']}")
    print(f"   - 变更类型：{review_index['summary']['changes_by_type']}")
    print(f"   - 总行数变化：{review_index['summary']['total_lines']}")
    print(f"   - 变更文件：{', '.join(review_index['summary']['files_changed'])}")
    
    print("\n2. 详细数据结构（JSON格式）：")
    print("=" * 80)
    print(json.dumps(review_index, ensure_ascii=False, indent=2))
    print("=" * 80)
    
    print("\n3. 数据说明：")
    print("   - review_metadata：审查元数据，包含模式、基础分支、时间戳等")
    print("   - summary：变更摘要，包含变更类型统计、总行数变化和变更文件列表")
    print("   - units：审查单元索引，每个单元包含ID、文件路径、补丁类型、标签、指标等")
    print("   - files：文件条目，每个文件包含路径、语言、变更类型、指标、标签和变更列表")
    print("\n4. 关键字段说明：")
    print("   - rule_context_level：规则上下文级别（high/medium/low）")
    print("   - rule_confidence：规则置信度（0.0-1.0）")
    print("   - rule_suggestion：规则建议，包含规则ID、建议类型、描述和优先级")
    print("   - symbol：符号信息，包含名称、类型、起始行和结束行")
    print("   - unified_diff_with_lines：带行号的统一差异")
    print("   - tags：自动生成的标签，用于分类和筛选")

if __name__ == "__main__":
    main()
