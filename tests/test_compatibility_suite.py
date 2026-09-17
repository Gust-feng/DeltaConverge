"""兼容性测试套件。

对比新旧内核的输出一致性，验证迁移质量。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class TestCase:
    """测试用例定义。"""
    name: str
    project_root: str
    base_ref: str
    prompt: str
    expected_sections: List[str] = field(default_factory=list)  # 期望的报告章节
    tags: List[str] = field(default_factory=list)  # 测试标签


@dataclass
class ComparisonResult:
    """对比结果。"""
    test_case: str
    old_kernel_success: bool
    new_kernel_success: bool
    old_report_length: int
    new_report_length: int
    old_sections: List[str]
    new_sections: List[str]
    section_match_ratio: float
    content_similarity: float
    passed: bool
    details: str = ""


class CompatibilityTestSuite:
    """兼容性测试套件。
    
    收集典型 PR 测试用例，对比新旧内核输出。
    """
    
    def __init__(self, test_cases: Optional[List[TestCase]] = None) -> None:
        self.test_cases = test_cases or []
        self.results: List[ComparisonResult] = []
    
    def add_test_case(self, case: TestCase) -> None:
        """添加测试用例。"""
        self.test_cases.append(case)
    
    def load_test_cases(self, path: Path) -> None:
        """从 JSON 文件加载测试用例。"""
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data.get("test_cases", []):
            self.test_cases.append(TestCase(**item))
    
    def save_test_cases(self, path: Path) -> None:
        """保存测试用例到 JSON 文件。"""
        data = {
            "test_cases": [
                {
                    "name": tc.name,
                    "project_root": tc.project_root,
                    "base_ref": tc.base_ref,
                    "prompt": tc.prompt,
                    "expected_sections": tc.expected_sections,
                    "tags": tc.tags,
                }
                for tc in self.test_cases
            ]
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    async def run_comparison(
        self,
        old_kernel_runner: Any,
        new_kernel_runner: Any,
        threshold: float = 0.9,
    ) -> Dict[str, Any]:
        """运行对比测试。
        
        Args:
            old_kernel_runner: 旧内核执行器（callable）
            new_kernel_runner: 新内核执行器（callable）
            threshold: 一致性阈值（0-1）
            
        Returns:
            测试报告
        """
        self.results = []
        
        for case in self.test_cases:
            result = await self._run_single_comparison(
                case, old_kernel_runner, new_kernel_runner
            )
            result.passed = result.content_similarity >= threshold
            self.results.append(result)
        
        return self._generate_report(threshold)
    
    async def _run_single_comparison(
        self,
        case: TestCase,
        old_runner: Any,
        new_runner: Any,
    ) -> ComparisonResult:
        """运行单个测试用例的对比。"""
        old_report = ""
        new_report = ""
        old_success = False
        new_success = False
        
        try:
            old_report = await old_runner(
                project_root=case.project_root,
                base_ref=case.base_ref,
                prompt=case.prompt,
            )
            old_success = True
        except Exception as e:
            old_report = f"Error: {e}"
        
        try:
            new_report = await new_runner(
                project_root=case.project_root,
                base_ref=case.base_ref,
                prompt=case.prompt,
            )
            new_success = True
        except Exception as e:
            new_report = f"Error: {e}"
        
        old_sections = self._extract_sections(old_report)
        new_sections = self._extract_sections(new_report)
        
        section_match = self._calculate_section_match(old_sections, new_sections)
        content_sim = self._calculate_content_similarity(old_report, new_report)
        
        return ComparisonResult(
            test_case=case.name,
            old_kernel_success=old_success,
            new_kernel_success=new_success,
            old_report_length=len(old_report),
            new_report_length=len(new_report),
            old_sections=old_sections,
            new_sections=new_sections,
            section_match_ratio=section_match,
            content_similarity=content_sim,
            passed=False,  # 由调用方设置
        )
    
    def _extract_sections(self, report: str) -> List[str]:
        """从报告中提取章节标题。"""
        sections = []
        for line in report.splitlines():
            line = line.strip()
            if line.startswith("## "):
                sections.append(line[3:])
            elif line.startswith("### "):
                sections.append(line[4:])
        return sections
    
    def _calculate_section_match(
        self, old_sections: List[str], new_sections: List[str]
    ) -> float:
        """计算章节匹配率。"""
        if not old_sections and not new_sections:
            return 1.0
        if not old_sections or not new_sections:
            return 0.0
        
        old_set = set(old_sections)
        new_set = set(new_sections)
        intersection = old_set & new_set
        union = old_set | new_set
        
        return len(intersection) / len(union) if union else 0.0
    
    def _calculate_content_similarity(self, old: str, new: str) -> float:
        """计算内容相似度（简单的基于长度的估算）。"""
        if not old and not new:
            return 1.0
        if not old or not new:
            return 0.0
        
        # 简单的长度比较 + 关键词匹配
        len_ratio = min(len(old), len(new)) / max(len(old), len(new))
        
        # 提取关键词（简单实现）
        old_words = set(old.split())
        new_words = set(new.split())
        word_ratio = len(old_words & new_words) / len(old_words | new_words) if old_words | new_words else 0
        
        return (len_ratio + word_ratio) / 2
    
    def _generate_report(self, threshold: float) -> Dict[str, Any]:
        """生成测试报告。"""
        passed = sum(1 for r in self.results if r.passed)
        failed = len(self.results) - passed
        
        return {
            "summary": {
                "total": len(self.results),
                "passed": passed,
                "failed": failed,
                "pass_rate": passed / len(self.results) if self.results else 0,
                "threshold": threshold,
            },
            "results": [
                {
                    "test_case": r.test_case,
                    "passed": r.passed,
                    "old_success": r.old_kernel_success,
                    "new_success": r.new_kernel_success,
                    "section_match": round(r.section_match_ratio, 3),
                    "content_similarity": round(r.content_similarity, 3),
                }
                for r in self.results
            ],
            "details": [
                {
                    "test_case": r.test_case,
                    "old_sections": r.old_sections,
                    "new_sections": r.new_sections,
                    "old_length": r.old_report_length,
                    "new_length": r.new_report_length,
                }
                for r in self.results
            ],
        }


# 预定义的典型测试用例模板
DEFAULT_TEST_CASES = [
    TestCase(
        name="simple-function-change",
        project_root="",  # 需要填充
        base_ref="HEAD~1",
        prompt="请审查这次代码变更",
        expected_sections=["变更概述", "问题发现"],
        tags=["basic", "function"],
    ),
    TestCase(
        name="multi-file-refactor",
        project_root="",
        base_ref="HEAD~1",
        prompt="请审查这次重构变更",
        expected_sections=["变更概述", "架构影响"],
        tags=["refactor", "multi-file"],
    ),
    TestCase(
        name="new-feature-addition",
        project_root="",
        base_ref="HEAD~1",
        prompt="请审查这个新功能的实现",
        expected_sections=["变更概述", "功能评估"],
        tags=["feature", "addition"],
    ),
]


def create_default_suite() -> CompatibilityTestSuite:
    """创建默认测试套件。"""
    suite = CompatibilityTestSuite()
    for case in DEFAULT_TEST_CASES:
        suite.add_test_case(case)
    return suite
