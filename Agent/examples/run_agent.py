"""运行代码审查 Agent 的示例入口。"""

# 废弃文件，仅为前期内核快速开发使用，后续迁移到前端中测试

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
import argparse
from typing import Any, List, Tuple, Callable
import json
import subprocess
import shutil

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - 可选依赖
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

from Agent.agents import (
    PlanningAgent,
    DEFAULT_USER_PROMPT,
    CodeReviewAgent,
    fuse_plan,
    build_context_bundle,
)
from Agent.core.logging import get_logger
from Agent.core.logging.fallback_tracker import (
    fallback_tracker,
    record_fallback,
)
from Agent.core.logging.pipeline_logger import PipelineLogger
from Agent.core.adapter.llm_adapter import KimiAdapter, ToolDefinition
from Agent.core.stream.stream_processor import NormalizedToolCall
from Agent.core.context.provider import ContextProvider
from Agent.core.context.diff_provider import (
    collect_diff_context,
    build_markdown_and_json_context,
)
from Agent.core.logging.context import generate_trace_id
from Agent.core.llm.client import (
    BaseLLMClient,
    BailianLLMClient,
    GLMLLMClient,
    MockMoonshotClient,
    MoonshotLLMClient,
    ModelScopeLLMClient,
)
from Agent.core.logging.api_logger import APILogger
from Agent.core.state.conversation import ConversationState
from Agent.core.stream.stream_processor import StreamProcessor
from Agent.core.tools.runtime import ToolRuntime
from Agent.tool.registry import (
    builtin_tool_names,
    default_tool_names,
    get_tool_functions,
    get_tool_schemas,
)

logger = get_logger(__name__)


def create_llm_client(trace_id: str | None = None) -> Tuple[BaseLLMClient, str]:
    glm_key = os.getenv("GLM_API_KEY")
    if glm_key:
        try:
            return GLMLLMClient(
                model=os.getenv("GLM_MODEL", "GLM-4.6"),
                api_key=glm_key,
                logger=APILogger(trace_id=trace_id) if trace_id else None,
            ), "glm"
        except Exception as exc:
            print(f"[警告] GLM 客户端初始化失败：{exc}")
            record_fallback(
                "llm_client_fallback",
                "GLM 初始化失败，继续尝试其他模型",
                meta={"provider": "glm", "error": str(exc)},
            )

    bailian_key = os.getenv("BAILIAN_API_KEY")
    if bailian_key:
        try:
            return (
                BailianLLMClient(
                    model=os.getenv("BAILIAN_MODEL", "qwen-max"),
                    api_key=bailian_key,
                    base_url=os.getenv("BAILIAN_BASE_URL"),
                    logger=APILogger(trace_id=trace_id) if trace_id else None,
                ),
                "bailian",
            )
        except Exception as exc:
            print(f"[警告] Bailian 客户端初始化失败：{exc}")
            record_fallback(
                "llm_client_fallback",
                "Bailian 初始化失败，继续尝试其他模型",
                meta={"provider": "bailian", "error": str(exc)},
            )

    modelscope_key = os.getenv("MODELSCOPE_API_KEY")
    if modelscope_key:
        try:
            return (
                ModelScopeLLMClient(
                    model=os.getenv("MODELSCOPE_MODEL", "qwen-plus"),
                    api_key=modelscope_key,
                    logger=APILogger(trace_id=trace_id) if trace_id else None,
                ),
                "modelscope",
            )
        except Exception as exc:
            print(f"[警告] ModelScope 客户端初始化失败：{exc}")
            record_fallback(
                "llm_client_fallback",
                "ModelScope 初始化失败，继续尝试其他模型",
                meta={"provider": "modelscope", "error": str(exc)},
            )

    try:
            return (
                MoonshotLLMClient(
                    model=os.getenv("MOONSHOT_MODEL", "kimi-k2.5"),
                    logger=APILogger(trace_id=trace_id) if trace_id else None,
                ),
                "moonshot",
            )
    except (ValueError, RuntimeError) as exc:
        print(f"[警告] Moonshot 客户端初始化失败：{exc}")
        record_fallback(
            "llm_client_fallback",
            "Moonshot 初始化失败，降级为 Mock",
            meta={"provider": "moonshot", "error": str(exc)},
        )
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
        default=DEFAULT_USER_PROMPT,
        help="Prompt sent to the agent (will被附加在 diff 上下文前面）。",
    )
    parser.add_argument(
        "--setup",
        choices=["none", "basic", "all"],
        default="none",
        help="Install and enable scanners automatically (basic/all).",
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

    def _ensure_scanners(mode: str) -> None:
        if mode == "none":
            return
        py = sys.executable
        def _pip(pkg: str) -> None:
            try:
                subprocess.run([py, "-m", "pip", "install", pkg], check=False)
            except Exception:
                pass
        if shutil.which("semgrep") is None:
            _pip("semgrep")
        if shutil.which("pylint") is None:
            _pip("pylint")
        if shutil.which("flake8") is None:
            _pip("flake8")
        if mode == "all":
            if shutil.which("mypy") is None:
                _pip("mypy")
            if shutil.which("node") is not None:
                try:
                    subprocess.run(["npm", "install", "-g", "eslint", "typescript"], check=False)
                except Exception:
                    pass
            if shutil.which("go") is not None:
                try:
                    subprocess.run(["go", "install", "github.com/golangci/golangci-lint/cmd/golangci-lint@latest"], check=False)
                except Exception:
                    pass
            if shutil.which("gem") is not None:
                try:
                    subprocess.run(["gem", "install", "rubocop"], check=False)
                except Exception:
                    pass
    _ensure_scanners(mode=args.setup)
    fallback_tracker.reset()
    trace_id = generate_trace_id()
    client, provider_name = create_llm_client(trace_id=trace_id)
    tool_names = args.tools or default_tool_names()
    adapter = KimiAdapter(client, StreamProcessor(), provider_name=provider_name)
    pipe_logger = PipelineLogger(trace_id=trace_id)

    try:
        diff_ctx = collect_diff_context()
    except Exception as exc:
        print(f"[错误] 无法收集 diff: {exc}")
        return
    logger.info(
        "diff collected mode=%s files=%d units=%d",
        diff_ctx.mode.value,
        len(diff_ctx.files),
        len(diff_ctx.units),
    )
    session_log = pipe_logger.start("planning_review", {"provider": provider_name, "trace_id": trace_id})
    pipe_logger.log(
        "diff_summary",
        {
            "mode": diff_ctx.mode.value,
            "files": len(diff_ctx.files),
            "units": len(diff_ctx.units),
            "review_index_units": len(diff_ctx.review_index.get("units", [])),
            "review_index_preview": diff_ctx.review_index.get("units", [])[:3],
        },
    )

    # 规划链路：只消费元数据索引，输出上下文计划
    planner_state = ConversationState()
    planner = PlanningAgent(adapter, planner_state, logger=pipe_logger)
    plan = await planner.run(diff_ctx.review_index)
    fused = fuse_plan(diff_ctx.review_index, plan)
    context_bundle = build_context_bundle(diff_ctx, fused)
    logger.info(
        "plan fused provider=%s plan_units=%d bundle_items=%d",
        provider_name,
        len(plan.get("plan", [])) if isinstance(plan, dict) else 0,
        len(context_bundle),
    )
    pipe_logger.log("planning_output", {"plan": plan})
    pipe_logger.log("fusion_output", {"fused": fused})
    pipe_logger.log(
        "context_bundle_summary",
        {
            "bundle_size": len(context_bundle),
            "unit_ids": [c.get("unit_id") for c in context_bundle],
        },
    )
    print("规划结果(JSON):", json.dumps(plan, ensure_ascii=False, indent=2))
    print("融合结果(JSON):", json.dumps(fused, ensure_ascii=False, indent=2))
    print("上下文包（占位）:", json.dumps(context_bundle, ensure_ascii=False, indent=2))

    # 审查 Agent：消费 ContextBundle 作为上下文
    runtime = ToolRuntime()
    for name, func in get_tool_functions(tool_names).items():
        runtime.register(name, func)
    if not tool_names:
        print("[警告] 未启用任何工具，本次只会输出审查文本。")

    context_provider = ContextProvider()
    state = ConversationState()
    trace_logger = APILogger(trace_id=trace_id)

    review_index_md, _ = build_markdown_and_json_context(diff_ctx)
    ctx_json = json.dumps({"context_bundle": context_bundle}, ensure_ascii=False, indent=2)
    full_prompt = (
        f"{args.prompt}\n\n"
        f"审查索引（仅元数据，无代码正文，需代码请调用工具）：\n{review_index_md}\n\n"
        f"上下文包（按规划抽取的片段）：\n```json\n{ctx_json}\n```"
    )
    pipe_logger.log(
        "review_request",
        {
            "prompt_preview": full_prompt[:2000],
            "context_bundle_size": len(context_bundle),
        },
    )

    agent = CodeReviewAgent(adapter, runtime, context_provider, state, trace_logger=trace_logger)
    tool_schemas = get_tool_schemas(tool_names)
    default_auto = [name for name in tool_names if name in builtin_tool_names()]
    approver: Callable[[List[NormalizedToolCall]], List[NormalizedToolCall]] | None = None
    if args.auto_approve is None:
        auto_approve = default_auto
        if set(auto_approve) != set(tool_names):
            approver = console_tool_approver
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
    pipe_logger.log("review_result", {"result": result})
    fb_summary = fallback_tracker.emit_summary(logger=logger, pipeline_logger=pipe_logger)
    if fb_summary.get("total"):
        print(f"[回退告警] 本次触发 {fb_summary['total']} 次：{fb_summary['by_key']}")
    pipe_logger.log(
        "session_end",
        {"log_path": str(session_log), "result_preview": (result[:200] if isinstance(result, str) else "")},
    )
    print("Agent result:", result)


if __name__ == "__main__":
    asyncio.run(main())
