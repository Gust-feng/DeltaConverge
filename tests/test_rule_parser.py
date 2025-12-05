"""规则解析模块的单元测试"""

import unittest
from Agent.DIFF.rule.context_decision import build_rule_suggestion
from Agent.DIFF.rule.rule_base import RuleSuggestion
from Agent.DIFF.rule.rule_config import get_rule_config
from Agent.DIFF.rule.rule_registry import (
    get_all_rule_handlers,
    get_rule_handler,
    initialize_handlers
)


class TestRuleParser(unittest.TestCase):
    """测试规则解析功能"""
    
    def setUp(self):
        """设置测试环境"""
        initialize_handlers()
    
    def test_build_rule_suggestion(self):
        """测试构建规则建议"""
        test_unit = {
            "file_path": "src/migrations/0001_initial.py",
            "language": "python",
            "change_type": "modify",
            "metrics": {
                "added_lines": 20,
                "removed_lines": 5,
                "hunk_count": 1
            },
            "tags": ["migration_file"],
            "symbol": {
                "kind": "function",
                "name": "test_function",
                "start_line": 10,
                "end_line": 20
            }
        }
        
        suggestion = build_rule_suggestion(test_unit)
        
        # 验证返回结果的类型和结构
        self.assertIsInstance(suggestion, dict)
        self.assertIn("context_level", suggestion)
        self.assertIn("confidence", suggestion)
        self.assertIn("notes", suggestion)
        
        # 验证置信度在合理范围内
        self.assertGreaterEqual(suggestion["confidence"], 0.0)
        self.assertLessEqual(suggestion["confidence"], 1.0)
    
    def test_get_rule_config(self):
        """测试获取规则配置"""
        config = get_rule_config()
        self.assertIsInstance(config, dict)
        self.assertIn("base", config)
        self.assertIn("languages", config)
        
        # 验证基础配置结构
        base_config = config["base"]
        self.assertIn("large_change_lines", base_config)
        self.assertIn("moderate_change_lines", base_config)
        self.assertIn("noise_tags", base_config)
        
        # 验证语言配置结构
        languages = config["languages"]
        self.assertIsInstance(languages, dict)
        self.assertIn("python", languages)
        self.assertIn("typescript", languages)
        self.assertIn("go", languages)
        self.assertIn("java", languages)
        self.assertIn("ruby", languages)
    
    def test_rule_registry(self):
        """测试规则注册表"""
        # 验证注册表中有处理器
        handlers = get_all_rule_handlers()
        self.assertGreater(len(handlers), 0)
        
        # 验证可以获取特定语言的处理器
        python_handler = get_rule_handler("python")
        self.assertIsNotNone(python_handler)
        
        # 验证无法获取不存在语言的处理器
        invalid_handler = get_rule_handler("invalid_language")
        self.assertIsNone(invalid_handler)
    
    def test_migration_file_rule(self):
        """测试迁移文件规则"""
        test_unit = {
            "file_path": "src/migrations/0001_initial.py",
            "language": "python",
            "change_type": "modify",
            "metrics": {
                "added_lines": 20,
                "removed_lines": 5,
                "hunk_count": 1
            },
            "tags": ["migration_file"],
            "symbol": {}
        }
        
        suggestion = build_rule_suggestion(test_unit)
        
        # 迁移文件应该匹配到特定规则
        self.assertEqual(suggestion["context_level"], "file")
        self.assertGreater(suggestion["confidence"], 0.5)
    
    def test_test_file_rule(self):
        """测试测试文件规则"""
        test_unit = {
            "file_path": "tests/test_example.py",
            "language": "python",
            "change_type": "modify",
            "metrics": {
                "added_lines": 10,
                "removed_lines": 2,
                "hunk_count": 1
            },
            "tags": ["test_file"],
            "symbol": {}
        }
        
        suggestion = build_rule_suggestion(test_unit)
        
        # 测试文件应该匹配到特定规则
        self.assertEqual(suggestion["context_level"], "function")
        self.assertGreater(suggestion["confidence"], 0.5)
    
    def test_small_change_rule(self):
        """测试小变更规则"""
        test_unit = {
            "file_path": "src/utils.py",
            "language": "python",
            "change_type": "modify",
            "metrics": {
                "added_lines": 3,
                "removed_lines": 1,
                "hunk_count": 1
            },
            "tags": ["small_change"],
            "symbol": {}
        }
        
        suggestion = build_rule_suggestion(test_unit)
        
        # 小变更应该匹配到特定规则
        self.assertEqual(suggestion["context_level"], "local")
        self.assertGreater(suggestion["confidence"], 0.5)
    
    def test_large_change_rule(self):
        """测试大变更规则"""
        test_unit = {
            "file_path": "src/main.py",
            "language": "python",
            "change_type": "modify",
            "metrics": {
                "added_lines": 150,
                "removed_lines": 50,
                "hunk_count": 5
            },
            "tags": ["large_change"],
            "symbol": {}
        }
        
        suggestion = build_rule_suggestion(test_unit)
        
        # 大变更应该匹配到特定规则
        self.assertEqual(suggestion["context_level"], "file")
        self.assertGreater(suggestion["confidence"], 0.5)
    
    def test_no_match_rule(self):
        """测试没有匹配规则的情况"""
        test_unit = {
            "file_path": "src/random_file.txt",
            "language": "text",
            "change_type": "modify",
            "metrics": {
                "added_lines": 5,
                "removed_lines": 2,
                "hunk_count": 1
            },
            "tags": [],
            "symbol": {}
        }
        
        suggestion = build_rule_suggestion(test_unit)
        
        # 没有匹配规则应该返回默认值 "function" 而非 "unknown"（Requirements 7.1, 7.2）
        # confidence 应在 0.3-0.45 范围内，notes 应包含 "default_fallback"
        self.assertEqual(suggestion["context_level"], "function")
        self.assertGreaterEqual(suggestion["confidence"], 0.3)
        self.assertLessEqual(suggestion["confidence"], 0.45)
        self.assertIn("default_fallback", suggestion["notes"])


if __name__ == "__main__":
    unittest.main()
