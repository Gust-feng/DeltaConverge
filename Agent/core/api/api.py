"""核心 API 层：对外暴露的统一接口。

提供 AgentAPI 类作为系统入口，支持 LLM 客户端工厂化创建、工具查询及任务调度。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import List, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv() -> bool:
        return False

# 确保项目根目录在 sys.path 中
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv()

from Agent.core.logging import get_logger
from Agent.core.logging.fallback_tracker import fallback_tracker
from Agent.core.logging.context import generate_trace_id
from Agent.core.adapter.llm_adapter import OpenAIAdapter
from Agent.core.context.diff_provider import collect_diff_context, DiffContext
from Agent.core.stream.stream_processor import StreamProcessor

from Agent.tool.registry import (
    default_tool_names,
    get_tool_spec,
    list_tool_names,
)

from Agent.core.api.models import (
    LLMOption,
    ToolOption,
    ReviewRequest,
    StreamCallback,
    ToolApprover
)
from Agent.core.api.factory import LLMFactory

logger = get_logger(__name__)


# --- Core API Facade ---

class AgentAPI:
    """Agent 系统核心 API 门面。
    
    统一管理资源初始化、任务分发与上下文生命周期。
    """

    @staticmethod
    def get_llm_options(include_mock: bool = True) -> List[LLMOption]:
        """获取当前环境可用的 LLM 模型列表。"""
        return LLMFactory.get_available_options(include_mock)

    @staticmethod
    def get_tool_options() -> List[ToolOption]:
        """获取所有已注册工具及其元数据。"""
        defaults = set(default_tool_names())
        tools: List[ToolOption] = []
        for name in list_tool_names():
            desc = None
            try:
                desc = get_tool_spec(name).description
            except Exception:
                desc = None
            tools.append({
                "name": name,
                "default": name in defaults,
                "description": desc,
            })
        return tools

    @staticmethod
    async def review_code(request: ReviewRequest) -> str:
        """执行代码审查任务（异步）。"""
        
        # 1. 环境准备与上下文收集
        def _collect() -> DiffContext:
            return collect_diff_context()

        fallback_tracker.reset()
        if request.stream_callback:
            try:
                request.stream_callback({"type": "pipeline_stage_start", "stage": "diff_parse"})
            except Exception:
                pass

        # 切换工作目录（如果指定）
        cwd = os.getcwd()
        if request.project_root:
            root_path = Path(request.project_root).expanduser().resolve()
            if not root_path.is_dir():
                raise RuntimeError(f"项目目录不存在：{root_path}")
            os.chdir(root_path)
        
        try:
            diff_ctx = _collect()
        finally:
            if request.project_root:
                os.chdir(cwd)

        logger.info(
            "diff collected mode=%s files=%d units=%d",
            diff_ctx.mode.value,
            len(diff_ctx.files),
            len(diff_ctx.units),
        )

        # 2. 资源初始化 (LLM Clients)
        trace_id = generate_trace_id()
        
        # Review Client
        review_client, review_provider = LLMFactory.create(request.llm_preference, trace_id=trace_id)
        
        # Planner Client
        planner_pref = request.planner_llm_preference or request.llm_preference
        if planner_pref == request.llm_preference:
            planner_client, planner_provider = review_client, review_provider
        else:
            planner_client, planner_provider = LLMFactory.create(planner_pref, trace_id=trace_id)

        # 3. 内核执行
        try:
            # 组装适配器
            review_adapter = OpenAIAdapter(review_client, StreamProcessor(), provider_name=review_provider)
            planner_adapter = OpenAIAdapter(planner_client, StreamProcessor(), provider_name=planner_provider)
            
            # 实例化内核
            from Agent.core.review_kernel import ReviewKernel
            kernel = ReviewKernel(
                review_adapter=review_adapter,
                planner_adapter=planner_adapter,
                review_provider=review_provider,
                planner_provider=planner_provider,
                trace_id=trace_id,
            )
            
            # 运行
            return await kernel.run(
                prompt=request.prompt,
                tool_names=request.tool_names,
                auto_approve=request.auto_approve,
                diff_ctx=diff_ctx,
                stream_callback=request.stream_callback,
                tool_approver=request.tool_approver,
            )
        finally:
            # 4. 资源清理
            await review_client.aclose()
            if planner_client is not review_client:
                await planner_client.aclose()

    @staticmethod
    def review_code_sync(request: ReviewRequest) -> str:
        """执行代码审查任务（同步封装）。"""
        return asyncio.run(AgentAPI.review_code(request))


# --- Legacy / Compatibility Interface ---
# 为了保持向下兼容，保留原有的函数接口，但内部代理到 AgentAPI

available_llm_options = AgentAPI.get_llm_options
available_tools = AgentAPI.get_tool_options

async def run_review_async(
    prompt: str,
    llm_preference: str,
    tool_names: List[str],
    auto_approve: bool,
    project_root: Optional[str] = None,
    stream_callback: Optional[StreamCallback] = None,
    tool_approver: Optional[ToolApprover] = None,
    planner_llm_preference: Optional[str] = None,
) -> str:
    req = ReviewRequest(
        prompt=prompt,
        llm_preference=llm_preference,
        tool_names=tool_names,
        auto_approve=auto_approve,
        project_root=project_root,
        stream_callback=stream_callback,
        tool_approver=tool_approver,
        planner_llm_preference=planner_llm_preference,
    )
    return await AgentAPI.review_code(req)

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
    return asyncio.run(
        run_review_async(
            prompt,
            llm_preference,
            tool_names,
            auto_approve,
            project_root,
            stream_callback,
            tool_approver,
            planner_llm_preference,
        )
    )

run_review_async_entry = run_review_async
