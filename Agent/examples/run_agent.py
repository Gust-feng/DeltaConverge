"""Example entrypoint to run the code review agent."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
import argparse
from typing import Any, List, Tuple, Callable
import json

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    def load_dotenv() -> None:
        return None

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def _inject_venv_sitepackages() -> None:
    candidates = [
        ROOT / "venv" / "Lib" / "site-packages",
    ]
    candidates.extend((ROOT / "venv" / "lib").glob("python*/site-packages"))
    for path in candidates:
        if path.exists() and str(path) not in sys.path:
            sys.path.insert(0, str(path))

_inject_venv_sitepackages()

load_dotenv()

from Agent.agents.review.code_reviewer import CodeReviewAgent
from Agent.core.adapter.llm_adapter import KimiAdapter, ToolDefinition
from Agent.core.stream.stream_processor import NormalizedToolCall
from Agent.core.context.provider import ContextProvider
from Agent.core.context.diff_provider import (
    collect_diff_context,
    build_markdown_and_json_context,
)
from Agent.core.llm.client import (
    BaseLLMClient,
    BailianLLMClient,
    GLMLLMClient,
    MockMoonshotClient,
    MoonshotLLMClient,
)
from Agent.core.logging.api_logger import APILogger
from Agent.core.state.conversation import ConversationState
from Agent.core.stream.stream_processor import StreamProcessor
from Agent.core.tools.runtime import ToolRuntime
from Agent.tool.registry import (
    default_tool_names,
    get_tool_functions,
    get_tool_schemas,
)


def create_llm_client() -> Tuple[BaseLLMClient, str]:
    glm_key = os.getenv("GLM_API_KEY")
    if glm_key:
        try:
            return GLMLLMClient(
                model=os.getenv("GLM_MODEL", "GLM-4.6"),
                api_key=glm_key,
            ), "glm"
        except Exception as exc:
            print(f"[警告] GLM 客户端初始化失败：{exc}")

    bailian_key = os.getenv("BAILIAN_API_KEY")
    if bailian_key:
        try:
            return (
                BailianLLMClient(
                    model=os.getenv("BAILIAN_MODEL", "qwen-max"),
                    api_key=bailian_key,
                    base_url=os.getenv("BAILIAN_BASE_URL"),
                ),
                "bailian",
            )
        except Exception as exc:
            print(f"[警告] Bailian 客户端初始化失败：{exc}")

    try:
        return (
            MoonshotLLMClient(
                model=os.getenv("MOONSHOT_MODEL", "kimi-k2.5"),
            ),
            "moonshot",
        )
    except (ValueError, RuntimeError) as exc:
        print(f"[警告] Moonshot 客户端初始化失败：{exc}")
        return MockMoonshotClient(), "mock"


def console_tool_approver(calls: List[NormalizedToolCall]) -> List[NormalizedToolCall]:
    approved: List[NormalizedToolCall] = []
    for call in calls:
        name = call.get("name")
        args = call.get("arguments")
        arg_text = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
        print(f"\n[工具请求] {name}\n参数: {arg_text}")
        choice = input("👀 执行该工具吗? [y/N]: ").strip().lower()
        if choice.startswith("y"):
            approved.append(call)
    return approved


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the code review agent.")
    parser.add_argument(
        "--prompt",
        default=(
            "你现在要审查一次代码变更（PR）。\n"
            "请先阅读下面自动生成的“代码审查上下文”（Markdown + 精简 JSON），"
            "理解本次变更的核心意图和高风险区域，然后给出审查意见。\n\n"
            "请重点从以下四个维度审查：\n"
            "1）静态缺陷：语法/类型错误、依赖缺失、导入错误、明显错误的 API 使用等；\n"
            "2）逻辑缺陷：条件判断/边界条件/状态流转是否正确，是否存在异常路径遗漏；\n"
            "3）内存与资源问题：循环中累积大对象、未关闭的文件/连接、可能无限增长的缓存等；\n"
            "4）安全漏洞：鉴权/权限控制、输入校验、敏感信息暴露、危险函数调用、不安全依赖等。\n\n"
            "如果需要更多上下文（例如完整函数、调用链、依赖信息），请通过工具调用获取，"
            "不要盲猜。若需要多个工具，请在同一轮一次性列出全部 tool_calls，"
            "等待所有工具结果返回后再继续推理，避免多轮往返。"
        ),
        help="Prompt sent to the agent (will被附加在 diff 上下文前面）。",
    )
    parser.add_argument(
        "--tools",
        nargs="*",
        default=None,
        help="Tool names to expose (default: current registry).",
    )
    parser.add_argument(
        "--auto-approve",
        nargs="*",
        default=None,
        help="Tool names that can run without manual approval.",
    )
    args = parser.parse_args()

    client, provider_name = create_llm_client()
    tool_names = args.tools or default_tool_names()
    runtime = ToolRuntime()
    for name, func in get_tool_functions(tool_names).items():
        runtime.register(name, func)

    if not tool_names:
        print("[警告] 未启用任何工具，本次只会输出审查文本。")

    adapter = KimiAdapter(client, StreamProcessor(), provider_name=provider_name)
    context_provider = ContextProvider()
    state = ConversationState()
    trace_logger = APILogger()

    try:
        diff_ctx = collect_diff_context()
    except Exception as exc:
        print(f"[错误] 无法收集 diff: {exc}")
        return

    markdown_ctx, _ = build_markdown_and_json_context(diff_ctx)
    full_prompt = f"{args.prompt}\n\n{markdown_ctx}"

    agent = CodeReviewAgent(adapter, runtime, context_provider, state, trace_logger=trace_logger)
    tool_schemas = get_tool_schemas(tool_names)
    if args.auto_approve is None and not sys.stdin.isatty():
        auto_approve = tool_names
        approver = None
    else:
        auto_approve = args.auto_approve or []
        approver = console_tool_approver

    result = await agent.run(
        prompt=full_prompt,
        files=diff_ctx.files,
        tools=tool_schemas,  # type: ignore[arg-type]  # schema 已符合 ToolDefinition
        auto_approve_tools=auto_approve,
        tool_approver=approver,
    )
    print("Agent result:", result)


if __name__ == "__main__":
    asyncio.run(main())
