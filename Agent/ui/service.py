"""UI-facing service layer: Web/GUI/CLI 调用入口，不直接触碰内核细节."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv() -> bool:
        return False

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv()

from Agent.agents.review.code_reviewer import CodeReviewAgent
from Agent.core.adapter.llm_adapter import KimiAdapter
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
from Agent.core.state.conversation import ConversationState
from Agent.core.stream.stream_processor import StreamProcessor
from Agent.core.tools.runtime import ToolRuntime
from Agent.core.logging.api_logger import APILogger
from Agent.tool.registry import (
    default_tool_names,
    get_tool_functions,
    get_tool_schemas,
)


def create_llm_client(preference: str = "auto") -> Tuple[BaseLLMClient, str]:
    """Instantiate an LLM client based on preference and available keys."""

    glm_key = os.getenv("GLM_API_KEY")
    if preference in {"glm", "auto"} and glm_key:
        try:
            return (
                GLMLLMClient(
                    model=os.getenv("GLM_MODEL", "GLM-4.6"),
                    api_key=glm_key,
                ),
                "glm",
            )
        except Exception:
            pass

    bailian_key = os.getenv("BAILIAN_API_KEY")
    if preference in {"bailian", "auto"} and bailian_key:
        try:
            return (
                BailianLLMClient(
                    model=os.getenv("BAILIAN_MODEL", "qwen-max"),
                    api_key=bailian_key,
                    base_url=os.getenv("BAILIAN_BASE_URL"),
                ),
                "bailian",
            )
        except Exception:
            pass

    if preference in {"moonshot", "auto"}:
        try:
            return (
                MoonshotLLMClient(
                    model=os.getenv("MOONSHOT_MODEL", "kimi-k2.5"),
                ),
                "moonshot",
            )
        except Exception:
            pass

    if preference == "glm":
        raise RuntimeError("GLM 模式被选择，但 GLM 客户端不可用。")
    if preference == "bailian":
        raise RuntimeError("Bailian 模式被选择，但 Bailian 客户端不可用。")
    if preference == "moonshot":
        raise RuntimeError("Moonshot 模式被选择，但 Moonshot 客户端不可用。")
    return MockMoonshotClient(), "mock"


class UsageAggregator:
    """Accumulate token usage per call_index and produce session totals."""

    def __init__(self) -> None:
        self._call_usage: Dict[int, Dict[str, int]] = {}

    def reset(self) -> None:
        self._call_usage.clear()

    def update(
        self, usage: Dict[str, Any], call_index: int | None
    ) -> Tuple[Dict[str, int], Dict[str, int]]:
        """Update usage for a call and return (call_totals, session_totals)."""

        def _to_int(v: Any) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        in_tok = _to_int(usage.get("input_tokens") or usage.get("prompt_tokens"))
        out_tok = _to_int(
            usage.get("output_tokens") or usage.get("completion_tokens")
        )
        total_tok = _to_int(usage.get("total_tokens"))
        idx = call_index or 1
        current = self._call_usage.get(idx, {"in": 0, "out": 0, "total": 0})
        current["in"] = max(current["in"], in_tok)
        current["out"] = max(current["out"], out_tok)
        current["total"] = max(current["total"], total_tok)
        self._call_usage[idx] = current

        session_totals = {
            "in": sum(v["in"] for v in self._call_usage.values()),
            "out": sum(v["out"] for v in self._call_usage.values()),
            "total": sum(v["total"] for v in self._call_usage.values()),
        }
        return current, session_totals


def run_review(
    prompt: str,
    llm_preference: str,
    tool_names: List[str],
    auto_approve: bool,
    project_root: Optional[str] = None,
    stream_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    tool_approver: Optional[
        Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]
    ] = None,
) -> str:
    """Run one review round (sync wrapper around the async agent)."""

    def _collect() -> "DiffContext":
        return collect_diff_context()

    if project_root:
        cwd = os.getcwd()
        root_path = Path(project_root).expanduser().resolve()
        if not root_path.is_dir():
            raise RuntimeError(f"项目目录不存在：{root_path}")
        os.chdir(root_path)
        try:
            diff_ctx = _collect()
        finally:
            os.chdir(cwd)
    else:
        diff_ctx = _collect()
    runtime = ToolRuntime()
    for name, func in get_tool_functions(tool_names).items():
        runtime.register(name, func)

    client, provider = create_llm_client(llm_preference)
    adapter = KimiAdapter(client, StreamProcessor(), provider_name=provider)
    context_provider = ContextProvider()
    state = ConversationState()
    trace_logger = APILogger()

    markdown_ctx, _ = build_markdown_and_json_context(diff_ctx)
    augmented_prompt = f"{prompt}\n\n{markdown_ctx}"
    tools = get_tool_schemas(tool_names)

    agent = CodeReviewAgent(
        adapter, runtime, context_provider, state, trace_logger=trace_logger
    )

    return asyncio.run(
        agent.run(
            augmented_prompt,
            files=diff_ctx.files,
            stream_observer=stream_callback,
            tools=tools,  # type: ignore[arg-type]
            auto_approve_tools=tool_names if auto_approve else [],
            tool_approver=tool_approver,
        )
    )


async def run_review_async(
    prompt: str,
    llm_preference: str,
    tool_names: List[str],
    auto_approve: bool,
    project_root: Optional[str] = None,
    stream_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    tool_approver: Optional[
        Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]
    ] = None,
) -> str:
    """Async version for asyncio servers (avoid asyncio.run inside loop)."""

    def _collect() -> "DiffContext":
        return collect_diff_context()

    if project_root:
        cwd = os.getcwd()
        root_path = Path(project_root).expanduser().resolve()
        if not root_path.is_dir():
            raise RuntimeError(f"项目目录不存在：{root_path}")
        os.chdir(root_path)
        try:
            diff_ctx = _collect()
        finally:
            os.chdir(cwd)
    else:
        diff_ctx = _collect()
    runtime = ToolRuntime()
    for name, func in get_tool_functions(tool_names).items():
        runtime.register(name, func)

    client, provider = create_llm_client(llm_preference)
    adapter = KimiAdapter(client, StreamProcessor(), provider_name=provider)
    context_provider = ContextProvider()
    state = ConversationState()
    trace_logger = APILogger()

    markdown_ctx, _ = build_markdown_and_json_context(diff_ctx)
    augmented_prompt = f"{prompt}\n\n{markdown_ctx}"
    tools = get_tool_schemas(tool_names)

    agent = CodeReviewAgent(
        adapter, runtime, context_provider, state, trace_logger=trace_logger
    )

    return await agent.run(
        augmented_prompt,
        files=diff_ctx.files,
        stream_observer=stream_callback,
        tools=tools,  # type: ignore[arg-type]
        auto_approve_tools=tool_names if auto_approve else [],
        tool_approver=tool_approver,
    )
