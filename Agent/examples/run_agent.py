"""Example entrypoint to run the code review agent."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
import argparse
from typing import Any, Dict

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
from Agent.core.adapter.llm_adapter import KimiAdapter
from Agent.core.context.provider import ContextProvider
from Agent.core.context.diff_provider import collect_diff_context
from Agent.core.llm.client import (
    GLMLLMClient,
    MockMoonshotClient,
    MoonshotLLMClient,
)
from Agent.core.state.conversation import ConversationState
from Agent.core.stream.stream_processor import StreamProcessor
from Agent.core.tools.runtime import ToolRuntime


def echo_tool(args: Dict[str, Any]) -> str:
    """Simple example tool that echoes text."""

    return f"TOOL ECHO: {args.get('text', '')}"

def create_llm_client():
    glm_key = os.getenv("GLM_API_KEY")
    if glm_key:
        try:
            return GLMLLMClient(
                model=os.getenv("GLM_MODEL", "GLM-4.6"),
                api_key=glm_key,
            )
        except Exception as exc:
            print(f"[警告] GLM 客户端初始化失败：{exc}")

    try:
        return MoonshotLLMClient(
            model=os.getenv("MOONSHOT_MODEL", "kimi-k2.5"),
        )
    except (ValueError, RuntimeError) as exc:
        print(f"[警告] Moonshot 客户端初始化失败：{exc}")
        return MockMoonshotClient()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the code review agent.")
    parser.add_argument(
        "--prompt",
        default="请审查本次 PR 的 diff，必要时调用 echo_tool 输出关键信息。",
        help="Prompt sent to the agent.",
    )
    args = parser.parse_args()

    runtime = ToolRuntime()
    runtime.register("echo_tool", echo_tool)

    client = create_llm_client()

    adapter = KimiAdapter(client, StreamProcessor())
    context_provider = ContextProvider()
    state = ConversationState()

    try:
        diff_ctx = collect_diff_context()
    except Exception as exc:
        print(f"[错误] 无法收集 diff: {exc}")
        return
    full_prompt = f"{args.prompt}\n\n[Diff Summary]\n{diff_ctx.summary}"

    agent = CodeReviewAgent(adapter, runtime, context_provider, state)
    result = await agent.run(prompt=full_prompt, files=diff_ctx.files)
    print("Agent result:", result)


if __name__ == "__main__":
    asyncio.run(main())
