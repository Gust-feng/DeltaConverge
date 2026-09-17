"""Legacy 提示词构建适配器

包装旧内核的 prompt_builder，实现新的 PromptPort 接口。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from kernel.ports.diff import ContextBundle
from kernel.ports.prompt import (
    PromptLimits,
    PromptPort,
    PromptStyle,
    ReviewPrompt,
    ReviewPromptConfig,
)

logger = logging.getLogger(__name__)


class LegacyPromptAdapter(PromptPort):
    """包装旧提示词构建器的适配器"""

    def build_review_user_prompt(
        self,
        *,
        review_index_md: str,
        context_bundle_json: str,
        user_prompt: str,
        intent_md: Optional[str] = None,
    ) -> str:
        """构建审查阶段的用户提示词（直接复用旧 prompt_builder）。"""
        from Agent.core.services.prompt_builder import build_review_prompt

        return build_review_prompt(
            review_index_md,
            context_bundle_json,
            user_prompt,
            intent_md=intent_md,
        )
    
    def build_review_prompt(
        self,
        *,
        context_bundle: ContextBundle,
        user_prompt: str,
        intent: Optional[str] = None,
        plan: Optional[str] = None,
        rule_findings: Optional[List[Dict[str, Any]]] = None,
        config: Optional[ReviewPromptConfig] = None,
    ) -> ReviewPrompt:
        """构建审查提示词"""
        from Agent.core.services.prompt_builder import build_review_prompt
        
        config = config or ReviewPromptConfig()
        
        # 准备输入
        diff_context_markdown = context_bundle.markdown_context
        planner_index = context_bundle.planner_index or ""
        
        # 调用旧函数
        try:
            prompt_text = build_review_prompt(
                diff_context=diff_context_markdown,
                planner_index=planner_index,
                user_prompt=user_prompt,
                intent_summary=intent,
                plan_text=plan,
            )
            
            # 构建结果
            return ReviewPrompt(
                system_message=self.get_system_prompt(config.style, language=config.language),
                user_message=prompt_text,
                estimated_tokens=len(prompt_text) // 4,
                config_used=config,
                parts={
                    "context": diff_context_markdown,
                    "intent": intent or "",
                    "plan": plan or "",
                    "user_prompt": user_prompt,
                },
            )
        except Exception as e:
            logger.error(f"Failed to build review prompt: {e}")
            # 回退：简单拼接
            prompt_parts = []
            if intent:
                prompt_parts.append(f"## 项目意图\n{intent}\n")
            if plan:
                prompt_parts.append(f"## 审查规划\n{plan}\n")
            if rule_findings:
                rules_text = self.format_rule_findings(rule_findings)
                prompt_parts.append(f"## 规则发现\n{rules_text}\n")
            prompt_parts.append(f"## 代码变更\n{diff_context_markdown}\n")
            prompt_parts.append(f"## 用户请求\n{user_prompt}\n")
            
            prompt_text = "\n".join(prompt_parts)
            
            return ReviewPrompt(
                system_message=self.get_system_prompt(config.style, language=config.language),
                user_message=prompt_text,
                estimated_tokens=len(prompt_text) // 4,
                config_used=config,
            )
    
    def build_intent_prompt(
        self,
        *,
        file_tree: str,
        readme: Optional[str] = None,
        recent_commits: Optional[List[str]] = None,
        dependencies: Optional[Dict[str, str]] = None,
    ) -> str:
        """构建项目意图分析提示词"""
        parts = ["# 项目分析\n"]
        
        if readme:
            parts.append(f"## README\n{readme}\n")
        
        parts.append(f"## 文件树\n{file_tree}\n")
        
        if dependencies:
            deps_text = "\n".join(f"- {k}: {v}" for k, v in dependencies.items())
            parts.append(f"## 依赖\n{deps_text}\n")
        
        if recent_commits:
            commits_text = "\n".join(f"- {c}" for c in recent_commits[:10])
            parts.append(f"## 最近提交\n{commits_text}\n")
        
        parts.append("\n请分析这个项目的核心功能、架构特点和技术栈。")
        
        return "\n".join(parts)
    
    def build_planner_prompt(
        self,
        *,
        planner_index: str,
        user_prompt: str,
        intent: Optional[str] = None,
    ) -> str:
        """构建审查规划提示词"""
        parts = []
        
        if intent:
            parts.append(f"## 项目意图\n{intent}\n")
        
        parts.append(f"## 代码变更索引\n{planner_index}\n")
        parts.append(f"## 用户请求\n{user_prompt}\n")
        parts.append("\n请生成代码审查规划，以 JSON 格式输出。")
        
        return "\n".join(parts)
    
    def build_fusion_prompt(
        self,
        *,
        plan: str,
        rule_findings: List[Dict[str, Any]],
    ) -> str:
        """构建融合提示词（合并规划与规则发现）"""
        parts = [
            f"## 审查规划\n{plan}\n",
            f"## 规则发现\n{self.format_rule_findings(rule_findings)}\n",
            "\n请将规则发现融合到审查规划中。",
        ]
        return "\n".join(parts)
    
    def estimate_prompt_tokens(
        self,
        prompt: ReviewPrompt,
    ) -> int:
        """估算提示词的 token 数"""
        total_chars = len(prompt.system_message) + len(prompt.user_message)
        return total_chars // 4
    
    def truncate_prompt(
        self,
        prompt: ReviewPrompt,
        max_tokens: int,
    ) -> ReviewPrompt:
        """截断提示词以适应 token 限制"""
        # 简化实现：截断用户消息
        estimated = self.estimate_prompt_tokens(prompt)
        if estimated <= max_tokens:
            return prompt
        
        # 计算需要截断的字符数
        chars_to_keep = max_tokens * 4 - len(prompt.system_message)
        truncated_user_message = prompt.user_message[:chars_to_keep] + "\n\n[内容已截断]"
        
        return ReviewPrompt(
            system_message=prompt.system_message,
            user_message=truncated_user_message,
            examples=prompt.examples,
            estimated_tokens=max_tokens,
            config_used=prompt.config_used,
            parts=prompt.parts,
        )
    
    def get_system_prompt(
        self,
        style: PromptStyle = PromptStyle.STANDARD,
        *,
        language: str = "zh-CN",
    ) -> str:
        """获取系统提示词"""
        base = "你是一个专业的代码审查助手。"
        
        if style == PromptStyle.SECURITY:
            base += "请特别关注安全漏洞和潜在的安全风险。"
        elif style == PromptStyle.PERFORMANCE:
            base += "请特别关注性能问题和优化机会。"
        elif style == PromptStyle.DETAILED:
            base += "请提供详细的审查意见，包括示例和改进建议。"
        elif style == PromptStyle.BRIEF:
            base += "请提供简洁的审查意见，突出关键问题。"
        
        return base
    
    def format_rule_findings(
        self,
        findings: List[Dict[str, Any]],
        *,
        max_findings: int = 20,
    ) -> str:
        """格式化规则发现为文本"""
        if not findings:
            return "无规则发现"
        
        lines = []
        for i, finding in enumerate(findings[:max_findings], 1):
            severity = finding.get("severity", "info")
            message = finding.get("message", "")
            file_path = finding.get("file", "")
            line = finding.get("line", "")
            
            lines.append(f"{i}. [{severity.upper()}] {file_path}:{line} - {message}")
        
        if len(findings) > max_findings:
            lines.append(f"\n...还有 {len(findings) - max_findings} 个发现")
        
        return "\n".join(lines)
