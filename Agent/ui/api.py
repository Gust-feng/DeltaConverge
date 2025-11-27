"""UI/前端可直接调用的审查系统接口，隔离内核细节。"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, TypedDict

from Agent.tool.registry import (
    default_tool_names,
    get_tool_spec,
    list_tool_names,
)
from Agent.ui.service import run_review, run_review_async


class LLMOption(TypedDict, total=False):
    name: str
    available: bool
    reason: str | None


class ToolOption(TypedDict, total=False):
    name: str
    default: bool
    description: str | None


def available_llm_options(include_mock: bool = True) -> List[LLMOption]:
    """返回可用的 LLM 选项（根据环境变量探测）。"""

    opts: List[LLMOption] = [{"name": "auto", "available": True, "reason": None}]

    glm_key = os.getenv("GLM_API_KEY")
    opts.append(
        {
            "name": "glm",
            "available": bool(glm_key),
            "reason": None if glm_key else "缺少 GLM_API_KEY",
        }
    )

    bailian_key = os.getenv("BAILIAN_API_KEY")
    opts.append(
        {
            "name": "bailian",
            "available": bool(bailian_key),
            "reason": None if bailian_key else "缺少 BAILIAN_API_KEY",
        }
    )

    moon_key = os.getenv("MOONSHOT_API_KEY")
    opts.append(
        {
            "name": "moonshot",
            "available": bool(moon_key),
            "reason": None if moon_key else "缺少 MOONSHOT_API_KEY",
        }
    )

    if include_mock:
        opts.append({"name": "mock", "available": True, "reason": None})

    return [opt for opt in opts if opt["available"]]


def available_tools() -> List[ToolOption]:
    """返回工具列表及默认勾选状态。"""

    defaults = set(default_tool_names())
    tools: List[ToolOption] = []
    for name in list_tool_names():
        desc = None
        try:
            desc = get_tool_spec(name).description
        except Exception:
            desc = None
        tools.append(
            {
                "name": name,
                "default": name in defaults,
                "description": desc,
            }
        )
    return tools


StreamCallback = Callable[[Dict[str, Any]], None]
ToolApprover = Callable[[List[Dict[str, Any]]], List[Dict[str, Any]]]


def run_review_sync(
    prompt: str,
    llm_preference: str,
    tool_names: List[str],
    auto_approve: bool,
    project_root: Optional[str] = None,
    stream_callback: Optional[StreamCallback] = None,
    tool_approver: Optional[ToolApprover] = None,
    planner_llm_preference: Optional[str] = None,
) -> str:
    """同步运行一次审查，UI/CLI 调用入口。"""

    return run_review(
        prompt=prompt,
        llm_preference=llm_preference,
        tool_names=tool_names,
        auto_approve=auto_approve,
        project_root=project_root,
        stream_callback=stream_callback,
        tool_approver=tool_approver,
        planner_llm_preference=planner_llm_preference,
    )


async def run_review_async_entry(
    prompt: str,
    llm_preference: str,
    tool_names: List[str],
    auto_approve: bool,
    project_root: Optional[str] = None,
    stream_callback: Optional[StreamCallback] = None,
    tool_approver: Optional[ToolApprover] = None,
    planner_llm_preference: Optional[str] = None,
) -> str:
    """异步运行一次审查，供 asyncio 应用调用。"""

    return await run_review_async(
        prompt=prompt,
        llm_preference=llm_preference,
        tool_names=tool_names,
        auto_approve=auto_approve,
        project_root=project_root,
        stream_callback=stream_callback,
        tool_approver=tool_approver,
        planner_llm_preference=planner_llm_preference,
    )


__all__ = [
    "LLMOption",
    "ToolOption",
    "available_llm_options",
    "available_tools",
    "run_review_sync",
    "run_review_async_entry",
]
