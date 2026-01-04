"""核心 API 层：对外暴露的统一接口。

提供 AgentAPI 类作为系统入口，支持 LLM 客户端工厂化创建、工具查询及任务调度。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

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
from Agent.core.context.runtime_context import set_project_root, set_session_id, set_diff_units, set_commit_range
from Agent.DIFF.rule.context_decision import set_rule_event_callback

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
    def get_llm_options(include_mock: bool = True) -> List[Dict[str, Any]]:
        """获取当前环境可用的 LLM 模型列表（按厂商分组）。"""
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
        def _collect(cwd: Optional[str] = None) -> DiffContext:
            return collect_diff_context(cwd=cwd)

        fallback_tracker.reset()
        if request.stream_callback:
            try:
                request.stream_callback({"type": "pipeline_stage_start", "stage": "diff_parse"})
            except Exception:
                pass

        # 确定项目根目录（但不切换全局 cwd，而是传递给底层）
        project_root_str: str | None = None
        if request.project_root:
            project_root_path = Path(request.project_root).expanduser().resolve()
            if not project_root_path.is_dir():
                raise RuntimeError(f"项目目录不存在：{project_root_path}")
            project_root_str = str(project_root_path)

        # 设置全局上下文中的 project_root 和 session_id，供工具使用
        set_project_root(project_root_str)
        set_session_id(request.session_id)
        set_commit_range(request.commit_from, request.commit_to)

        review_client = None
        planner_client = None
        review_provider = None
        planner_provider = None
        trace_id = None

        static_scan_task = None

        try:
            # 设置规则层事件回调，用于扫描器进度事件
            if request.stream_callback:
                set_rule_event_callback(request.stream_callback)
            
            # 根据diff_mode决定如何收集diff
            if request.diff_mode == "commit":
                # 历史提交模式：必须指定commit范围
                if not request.commit_from:
                    raise ValueError("Diff mode 'commit' requires 'commit_from' parameter.")
                
                from Agent.DIFF.git_operations import get_commit_diff
                from Agent.core.context.diff_provider import build_diff_context_from_text
                
                diff_text = get_commit_diff(
                    commit_from=request.commit_from,
                    commit_to=request.commit_to,
                    cwd=project_root_str
                )
                diff_ctx = build_diff_context_from_text(diff_text, cwd=project_root_str)
                logger.info(
                    "commit diff collected from=%s to=%s files=%d units=%d",
                    request.commit_from[:7],
                    (request.commit_to or "HEAD")[:7],
                    len(diff_ctx.files),
                    len(diff_ctx.units),
                )
            else:
                # 其他模式：使用collect_diff_context
                from Agent.DIFF.git_operations import DiffMode
                mode_map = {
                    "working": DiffMode.WORKING,
                    "staged": DiffMode.STAGED,
                    "pr": DiffMode.PR,
                    "auto": DiffMode.AUTO,
                }
                mode = mode_map.get(request.diff_mode, DiffMode.AUTO)
                diff_ctx = collect_diff_context(mode=mode, cwd=project_root_str)
                logger.info(
                    "diff collected mode=%s files=%d units=%d",
                    diff_ctx.mode.value,
                    len(diff_ctx.files),
                    len(diff_ctx.units),
                )

            if request.stream_callback:
                try:
                    review_files = diff_ctx.review_index.get("files", []) if diff_ctx.review_index else []
                    diff_files_snapshot = []
                    if isinstance(review_files, list) and review_files:
                        for f in review_files:
                            p = f.get("path", "") if isinstance(f, dict) else ""
                            if p:
                                diff_files_snapshot.append({
                                    "path": p,
                                    "display_path": p,
                                    "change_type": (f.get("change_type") if isinstance(f, dict) else None) or "modify",
                                })
                    if not diff_files_snapshot:
                        for fp in (diff_ctx.files or []):
                            diff_files_snapshot.append({
                                "path": str(fp),
                                "display_path": str(fp),
                                "change_type": "modify",
                            })

                    diff_units_snapshot = []
                    for u in (diff_ctx.units or []):
                        if not isinstance(u, dict):
                            continue
                        diff_units_snapshot.append({
                            "unit_id": u.get("unit_id") or u.get("id"),
                            "file_path": u.get("file_path"),
                            "change_type": u.get("change_type") or u.get("patch_type"),
                            "hunk_range": u.get("hunk_range") or {},
                            "unified_diff": u.get("unified_diff") or "",
                            "unified_diff_with_lines": u.get("unified_diff_with_lines"),
                            "tags": u.get("tags") or [],
                            "rule_context_level": u.get("rule_context_level"),
                            "rule_confidence": u.get("rule_confidence"),
                        })

                    request.stream_callback({
                        "type": "diff_units_snapshot",
                        "diff_files": diff_files_snapshot,
                        "diff_units": diff_units_snapshot,
                    })
                except Exception:
                    pass

            # 1.5 启动旁路静态扫描（如果启用）
            if request.enable_static_scan:
                try:
                    from Agent.DIFF.static_scan_service import run_static_scan, get_unique_files_from_diff_context
                    files_to_scan = get_unique_files_from_diff_context(diff_ctx)
                    if files_to_scan:
                        logger.info(f"Starting static scan bypass for {len(files_to_scan)} files")
                        static_scan_task = asyncio.create_task(
                            run_static_scan(
                                files=files_to_scan,
                                units=diff_ctx.units,
                                callback=request.stream_callback,
                                project_root=project_root_str,
                                session_id=request.session_id,
                                # 历史提交模式：从 head commit 读取文件
                                commit_sha=request.commit_to if request.diff_mode == "commit" else None,
                            )
                        )
                except Exception as e:
                    logger.warning(f"Failed to start static scan bypass: {e}")

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
                trace_id=trace_id or "",
            )
            
            # 运行
            return await kernel.run(
                prompt=request.prompt,
                tool_names=request.tool_names,
                auto_approve=request.auto_approve,
                diff_ctx=diff_ctx,
                stream_callback=request.stream_callback,
                tool_approver=request.tool_approver,
                message_history=request.message_history,
                agents=request.agents,
            )
        except asyncio.CancelledError:
            if static_scan_task and not static_scan_task.done():
                static_scan_task.cancel()
            raise
        finally:
            # 4. 资源清理
            if review_client:
                await review_client.aclose()
            if planner_client and planner_client is not review_client:
                await planner_client.aclose()
            # 清理上下文（可选，因为 ContextVar 是请求作用域的，但重置是个好习惯）
            set_project_root(None)
            set_session_id(None)
            set_diff_units([])
            set_commit_range(None, None)
            # 清理规则层事件回调
            set_rule_event_callback(None)

    @staticmethod
    def review_code_sync(request: ReviewRequest) -> str:
        """执行代码审查任务（同步封装）。"""
        return asyncio.run(AgentAPI.review_code(request))


# --- Legacy / Compatibility Interface ---
# 为了保持向下兼容，保留原有的函数接口，但内部代理到 AgentAPI

available_llm_options = AgentAPI.get_llm_options
available_tools = AgentAPI.get_tool_options

async def run_review_async_entry(
    prompt: str,
    llm_preference: str,
    tool_names: List[str],
    auto_approve: bool,
    project_root: Optional[str] = None,
    stream_callback: Optional[StreamCallback] = None,
    tool_approver: Optional[ToolApprover] = None,
    planner_llm_preference: Optional[str] = None,
    session_id: Optional[str] = None,
    message_history: Optional[List[Dict[str, Any]]] = None,
    agents: Optional[List[str]] = None,
    enable_static_scan: bool = False,
    diff_mode: Optional[str] = None,
    commit_from: Optional[str] = None,
    commit_to: Optional[str] = None,
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
        session_id=session_id,
        message_history=message_history,
        agents=agents,
        enable_static_scan=enable_static_scan,
        diff_mode=diff_mode,
        commit_from=commit_from,
        commit_to=commit_to,
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
    session_id: Optional[str] = None,
    message_history: Optional[List[Dict[str, Any]]] = None,
    agents: Optional[List[str]] = None,
    enable_static_scan: bool = False,
) -> str:
    return asyncio.run(run_review_async_entry(
        prompt=prompt,
        llm_preference=llm_preference,
        tool_names=tool_names,
        auto_approve=auto_approve,
        project_root=project_root,
        stream_callback=stream_callback,
        tool_approver=tool_approver,
        planner_llm_preference=planner_llm_preference,
        session_id=session_id,
        message_history=message_history,
        agents=agents,
        enable_static_scan=enable_static_scan,
    ))
