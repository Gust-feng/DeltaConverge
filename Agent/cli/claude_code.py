"""Claude Code 集成 CLI 入口"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
import argparse
from typing import Any, List, Optional, Tuple, Dict
import json

# 加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 添加项目根目录到路径
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Agent.cli.utils import load_config, format_output, validate_model, get_default_model
from Agent.core.adapter.llm_adapter import LLMAdapter
from Agent.core.llm.client import BaseLLMClient
from Agent.core.context.diff_provider import collect_diff_context, DiffContext
from Agent.core.context.provider import ContextProvider
from Agent.core.state.conversation import ConversationState
from Agent.core.tools.runtime import ToolRuntime

from Agent.agents.code_reviewer import CodeReviewAgent
from Agent.agents.planning_agent import PlanningAgent
from Agent.agents.fusion import fuse_plan
from Agent.agents.context_scheduler import build_context_bundle
from Agent.core.logging import get_logger
from Agent.core.logging.api_logger import APILogger
from Agent.core.logging.context import generate_trace_id
from Agent.core.context.diff_provider import build_markdown_and_json_context
from Agent.core.stream.stream_processor import StreamProcessor
from Agent.core.adapter.llm_adapter import KimiAdapter

logger = get_logger(__name__)


def default_tool_names() -> List[str]:
    """返回默认启用的内置工具列表（排除调试类工具）。"""
    return [
        "list_project_files",
        "list_directory",
        "read_file_hunk",
        "read_file_info",
        "search_in_project",
        "get_dependencies",
        "get_scanner_results",
    ]


def builtin_tool_names() -> List[str]:
    """与 default_tool_names 等价，向后兼容命名。"""
    return default_tool_names()


class ClaudeCodeCLI:
    """Claude Code 集成 CLI 类"""

    def __init__(self):
        self.parser = argparse.ArgumentParser(description="Claude Code 集成代码审查工具")
        self._setup_args()
        self.args = self.parser.parse_args()
        self.config = load_config(self.args.config)

    def _setup_args(self):
        """设置命令行参数"""
        self.parser.add_argument(
            "--mode",
            choices=["diff", "file", "snippet"],
            default="diff",
            help="审查模式（diff: Git差异, file: 文件, snippet: 代码片段）"
        )
        self.parser.add_argument(
            "--target",
            help="审查目标（Git差异、文件路径或代码片段）"
        )
        self.parser.add_argument(
            "--model",
            default=get_default_model(),
            help="使用的 LLM 模型"
        )
        self.parser.add_argument(
            "--depth",
            choices=["basic", "detailed", "comprehensive"],
            default="detailed",
            help="审查深度"
        )
        self.parser.add_argument(
            "--output",
            choices=["text", "json", "markdown"],
            default="text",
            help="输出格式"
        )
        self.parser.add_argument(
            "--config",
            help="配置文件路径"
        )
        self.parser.add_argument(
            "--api-key",
            help="API 密钥"
        )
        self.parser.add_argument(
            "--tools",
            nargs="*",
            default=None,
            help="启用的工具"
        )
        self.parser.add_argument(
            "--auto-approve",
            action="store_true",
            help="自动批准工具调用"
        )

    def _create_llm_client(self, trace_id: str) -> Tuple[BaseLLMClient, str]:
        """创建 LLM 客户端"""
        # 优先使用命令行参数中的 API 密钥
        api_key = self.args.api_key or self.config.get('api_key')
        
        # 验证模型
        if not validate_model(self.args.model):
            print(f"[警告] 模型 {self.args.model} 可能不是有效的 Claude 模型")
        
        # 尝试创建 Claude 客户端
        try:
            from Agent.core.llm.client import ClaudeLLMClient
            client = ClaudeLLMClient(
                model=self.args.model,
                api_key=api_key,
                logger=APILogger(trace_id=trace_id)
            )
            return client, "claude"
        except Exception as exc:
            print(f"[警告] Claude 客户端初始化失败：{exc}")
            # 回退到其他模型
            try:
                from Agent.core.llm.client import MoonshotLLMClient
                client = MoonshotLLMClient(
                    model=os.getenv("MOONSHOT_MODEL", "kimi-k2.5"),
                    logger=APILogger(trace_id=trace_id)
                )
                return client, "moonshot"
            except Exception as exc:
                print(f"[警告] Moonshot 客户端初始化失败：{exc}")
                # 回退到 Mock 客户端
                try:
                    from Agent.core.llm.client import MockMoonshotClient
                    client = MockMoonshotClient()
                    print("[信息] 使用 Mock 客户端进行测试")
                    return client, "mock"
                except Exception as exc:
                    print(f"[错误] 无法初始化 LLM 客户端：{exc}")
                    sys.exit(1)

    async def process_diff_mode(self) -> str:
        """处理 Git 差异审查模式"""
        try:
            diff_ctx = collect_diff_context()
        except Exception as exc:
            return f"[错误] 无法收集 Git 差异：{exc}"
        
        return await self._run_review(diff_ctx)

    async def process_file_mode(self) -> str:
        """处理文件审查模式"""
        if not self.args.target:
            return "[错误] 文件模式需要指定 --target 参数（文件路径）"
        
        file_path = Path(self.args.target)
        if not file_path.exists() or not file_path.is_file():
            return f"[错误] 文件不存在：{file_path}"
        
        try:
            # 读取文件内容
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            
            # 创建临时的 DiffContext
            from Agent.DIFF.git_operations import DiffMode
            diff_ctx = DiffContext(
                summary=f"文件审查: {file_path}",
                files=[str(file_path)],
                units=[],
                mode=DiffMode.FILE,
                base_branch=None,
                review_index={"units": []}
            )
            
            # 构建审查单元
            import uuid
            unit_id = str(uuid.uuid4())
            lines = content.split('\n')
            line_count = len(lines)
            
            # 创建审查单元字典
            unit = {
                "id": unit_id,
                "unit_id": unit_id,
                "file_path": str(file_path),
                "language": "python",  # 简单判断，实际应该使用 guess_language
                "change_type": "add",
                "unified_diff": f"+++ b/{file_path.name}\n@@ -0,0 +1,{line_count} @@\n+{content.replace('\n', '\n+')}",
                "hunk_range": {
                    "new_start": 1,
                    "new_lines": line_count,
                    "old_start": 0,
                    "old_lines": 0
                },
                "code_snippets": {
                    "before": "",
                    "after": content,
                    "context": content,
                    "context_start": 1,
                    "context_end": line_count
                },
                "tags": [],
                "metrics": {
                    "added_lines": line_count,
                    "removed_lines": 0,
                    "hunk_count": 1
                }
            }
            
            diff_ctx.units.append(unit)
            diff_ctx.review_index["units"].append({
                "file": str(file_path),
                "start_line": 1,
                "end_line": line_count,
                "change_type": "add",
                "context_level": "file"
            })
            
            return await self._run_review(diff_ctx)
        except Exception as exc:
            return f"[错误] 处理文件时出错：{exc}"

    async def process_snippet_mode(self) -> str:
        """处理代码片段审查模式"""
        if not self.args.target:
            return "[错误] 代码片段模式需要指定 --target 参数（代码片段）"
        
        try:
            # 创建临时的 DiffContext
            from Agent.DIFF.git_operations import DiffMode
            diff_ctx = DiffContext(
                summary="代码片段审查",
                files=["snippet"],
                units=[],
                mode=DiffMode.SNIPPET,
                base_branch=None,
                review_index={"units": []}
            )
            
            # 构建审查单元
            import uuid
            content = self.args.target
            unit_id = str(uuid.uuid4())
            lines = content.split('\n')
            line_count = len(lines)
            
            # 创建审查单元字典
            unit = {
                "id": unit_id,
                "unit_id": unit_id,
                "file_path": "snippet",
                "language": "python",  # 简单判断，实际应该使用 guess_language
                "change_type": "add",
                "unified_diff": f"+++ b/snippet\n@@ -0,0 +1,{line_count} @@\n+{content.replace('\n', '\n+')}",
                "hunk_range": {
                    "new_start": 1,
                    "new_lines": line_count,
                    "old_start": 0,
                    "old_lines": 0
                },
                "code_snippets": {
                    "before": "",
                    "after": content,
                    "context": content,
                    "context_start": 1,
                    "context_end": line_count
                },
                "tags": [],
                "metrics": {
                    "added_lines": line_count,
                    "removed_lines": 0,
                    "hunk_count": 1
                }
            }
            
            diff_ctx.units.append(unit)
            diff_ctx.review_index["units"].append({
                "file": "snippet",
                "start_line": 1,
                "end_line": line_count,
                "change_type": "add",
                "context_level": "file"
            })
            
            return await self._run_review(diff_ctx)
        except Exception as exc:
            return f"[错误] 处理代码片段时出错：{exc}"

    async def _run_review(self, diff_ctx: DiffContext) -> str:
        """运行审查流程"""
        trace_id = generate_trace_id()
        client, provider_name = self._create_llm_client(trace_id)
        
        tool_names = self.args.tools or default_tool_names()
        adapter = KimiAdapter(client, StreamProcessor(), provider_name=provider_name)
        
        # 规划阶段
        planner_state = ConversationState()
        planner = PlanningAgent(adapter, planner_state)
        plan = await planner.run(diff_ctx.review_index)
        fused = fuse_plan(diff_ctx.review_index, plan)
        context_bundle = build_context_bundle(diff_ctx, fused)
        
        # 审查阶段
        runtime = ToolRuntime()
        
        # 简化版工具注册，避免导入 registry.py
        from Agent.tool.registry import _TOOL_REGISTRY
        for name in tool_names:
            if name in _TOOL_REGISTRY:
                spec = _TOOL_REGISTRY[name]
                runtime.register(name, spec.func)
        
        context_provider = ContextProvider()
        state = ConversationState()
        trace_logger = APILogger(trace_id=trace_id)
        
        review_index_md, _ = build_markdown_and_json_context(diff_ctx)
        ctx_json = json.dumps({"context_bundle": context_bundle}, ensure_ascii=False, indent=2)
        
        # 根据审查深度构建提示
        depth_prompts = {
            "basic": "请对代码进行基本审查，重点关注语法错误和明显的问题。",
            "detailed": "请对代码进行详细审查，包括语法错误、逻辑问题、性能优化和最佳实践。",
            "comprehensive": "请对代码进行全面审查，包括语法错误、逻辑问题、性能优化、最佳实践、安全性和可维护性。"
        }
        prompt = depth_prompts.get(self.args.depth, depth_prompts["detailed"])
        
        full_prompt = (
            f"{prompt}\n\n"
            f"审查索引（仅元数据，无代码正文，需代码请调用工具）：\n{review_index_md}\n\n"
            f"上下文包（按规划抽取的片段）：\n```json\n{ctx_json}\n```"
        )
        
        agent = CodeReviewAgent(adapter, runtime, context_provider, state, trace_logger=trace_logger)
        
        # 构建工具 schemas
        tool_schemas = []
        from Agent.tool.registry import _TOOL_REGISTRY
        for name in tool_names:
            if name in _TOOL_REGISTRY:
                spec = _TOOL_REGISTRY[name]
                tool_schemas.append({
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": spec.parameters,
                    },
                })
        
        auto_approve = tool_names if self.args.auto_approve else [name for name in tool_names if name in builtin_tool_names()]
        
        result = await agent.run(
            prompt=full_prompt,
            files=diff_ctx.files,
            tools=tool_schemas,
            auto_approve_tools=auto_approve
        )
        
        return result

    async def run(self):
        """运行 CLI"""
        try:
            if self.args.mode == "diff":
                result = await self.process_diff_mode()
            elif self.args.mode == "file":
                result = await self.process_file_mode()
            elif self.args.mode == "snippet":
                result = await self.process_snippet_mode()
            else:
                result = f"[错误] 不支持的审查模式：{self.args.mode}"
            
            formatted_result = format_output(result, self.args.output)
            print(formatted_result)
        except Exception as exc:
            print(f"[错误] 运行时出错：{exc}")
            import traceback
            traceback.print_exc()


def main():
    """主函数"""
    cli = ClaudeCodeCLI()
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
