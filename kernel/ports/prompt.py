"""提示词构建接口定义

定义代码审查提示词的构建接口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from kernel.ports.diff import ContextBundle, DiffContext


class PromptStyle(str, Enum):
    """提示词风格"""
    STANDARD = "standard"       # 标准审查
    SECURITY = "security"       # 安全审查
    PERFORMANCE = "performance" # 性能审查
    BRIEF = "brief"             # 简要审查
    DETAILED = "detailed"       # 详细审查


@dataclass
class PromptLimits:
    """提示词限制配置"""
    max_context_tokens: int = 8000
    max_intent_tokens: int = 500
    max_plan_tokens: int = 1000
    max_rule_tokens: int = 500
    max_total_tokens: int = 12000
    
    # 截断策略
    truncate_context_first: bool = True
    preserve_recent_changes: bool = True


@dataclass
class ReviewPromptConfig:
    """审查提示词配置"""
    style: PromptStyle = PromptStyle.STANDARD
    limits: PromptLimits = field(default_factory=PromptLimits)
    
    # 可选部分
    include_intent: bool = True
    include_plan: bool = True
    include_rules: bool = True
    include_examples: bool = False
    
    # 语言和格式
    language: str = "zh-CN"  # 输出语言
    output_format: str = "markdown"  # markdown, json, plain
    
    # 自定义指令
    custom_instructions: Optional[str] = None


@dataclass
class ReviewPrompt:
    """构建完成的审查提示词"""
    # 系统消息
    system_message: str
    
    # 用户消息（主提示词）
    user_message: str
    
    # 可选的示例对话
    examples: List[Dict[str, str]] = field(default_factory=list)
    
    # 元信息
    estimated_tokens: int = 0
    config_used: Optional[ReviewPromptConfig] = None
    
    # 组成部分（用于调试）
    parts: Dict[str, str] = field(default_factory=dict)


@runtime_checkable
class PromptPort(Protocol):
    """提示词构建接口
    
    负责构建代码审查所需的各类提示词。
    """
    
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
        """构建审查提示词
        
        Args:
            context_bundle: 上下文包（含 Diff、JSON 上下文等）
            user_prompt: 用户原始请求
            intent: 项目意图摘要
            plan: 审查规划
            rule_findings: 规则扫描发现
            config: 提示词配置
            
        Returns:
            构建完成的提示词
        """
        ...
    
    def build_review_user_prompt(
        self,
        *,
        review_index_md: str,
        context_bundle_json: str,
        user_prompt: str,
        intent_md: Optional[str] = None,
    ) -> str:
        """构建审查阶段发送给引擎的用户提示词（纯文本形态）。

        与 ``build_review_prompt`` 的区别：本方法直接接受已序列化好的
        审查索引 Markdown 与上下文包 JSON 字符串，返回单个提示词文本，
        对应审查流水线的实际调用形态，不涉及 ContextBundle 结构体。
        """
        ...

    def build_intent_prompt(
        self,
        *,
        file_tree: str,
        readme: Optional[str] = None,
        recent_commits: Optional[List[str]] = None,
        dependencies: Optional[Dict[str, str]] = None,
    ) -> str:
        """构建项目意图分析提示词
        
        Args:
            file_tree: 项目文件树
            readme: README 内容
            recent_commits: 最近的提交消息
            dependencies: 项目依赖
            
        Returns:
            意图分析提示词
        """
        ...
    
    def build_planner_prompt(
        self,
        *,
        planner_index: str,
        user_prompt: str,
        intent: Optional[str] = None,
    ) -> str:
        """构建审查规划提示词
        
        Args:
            planner_index: Diff 索引摘要
            user_prompt: 用户请求
            intent: 项目意图
            
        Returns:
            规划提示词
        """
        ...
    
    def build_fusion_prompt(
        self,
        *,
        plan: str,
        rule_findings: List[Dict[str, Any]],
    ) -> str:
        """构建融合提示词（合并规划与规则发现）"""
        ...
    
    def estimate_prompt_tokens(
        self,
        prompt: ReviewPrompt,
    ) -> int:
        """估算提示词的 token 数"""
        ...
    
    def truncate_prompt(
        self,
        prompt: ReviewPrompt,
        max_tokens: int,
    ) -> ReviewPrompt:
        """截断提示词以适应 token 限制"""
        ...
    
    def get_system_prompt(
        self,
        style: PromptStyle = PromptStyle.STANDARD,
        *,
        language: str = "zh-CN",
    ) -> str:
        """获取系统提示词"""
        ...
    
    def format_rule_findings(
        self,
        findings: List[Dict[str, Any]],
        *,
        max_findings: int = 20,
    ) -> str:
        """格式化规则发现为文本"""
        ...


@dataclass
class PromptTemplate:
    """提示词模板"""
    name: str
    template: str
    variables: List[str] = field(default_factory=list)
    description: str = ""
    
    def render(self, **kwargs: Any) -> str:
        """渲染模板"""
        result = self.template
        for key, value in kwargs.items():
            placeholder = f"{{{{{key}}}}}"
            result = result.replace(placeholder, str(value) if value else "")
        return result


class PromptTemplateRegistry:
    """提示词模板注册表"""
    
    def __init__(self) -> None:
        self._templates: Dict[str, PromptTemplate] = {}
    
    def register(self, template: PromptTemplate) -> None:
        """注册模板"""
        self._templates[template.name] = template
    
    def get(self, name: str) -> Optional[PromptTemplate]:
        """获取模板"""
        return self._templates.get(name)
    
    def list_templates(self) -> List[str]:
        """列出所有模板名"""
        return list(self._templates.keys())
