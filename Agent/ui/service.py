"""面向 UI 的服务层：Web/GUI/CLI 调用入口，不直接触碰内核细节。"""

from __future__ import annotations

import asyncio
import os
import sys
import json
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

from Agent.agents import (
    CodeReviewAgent,
    PlanningAgent,
    fuse_plan,
    build_context_bundle,
)
from Agent.core.logging import get_logger
from Agent.core.logging.fallback_tracker import (
    fallback_tracker,
    record_fallback,
)
from Agent.core.logging.context import generate_trace_id
from Agent.core.adapter.llm_adapter import KimiAdapter
from Agent.core.context.provider import ContextProvider
from Agent.core.context.diff_provider import collect_diff_context, build_markdown_and_json_context
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
from Agent.core.logging.pipeline_logger import PipelineLogger
from Agent.tool.registry import (
    builtin_tool_names,
    default_tool_names,
    get_tool_functions,
    get_tool_schemas,
)

logger = get_logger(__name__)


def _summarize_context_bundle(bundle: List[Dict[str, Any]]) -> Dict[str, Any]:
    """生成上下文包的体积/截断概览，便于监控是否回退到“大包”。"""

    if not bundle:
        return {"items": 0, "total_chars": 0, "truncated_fields": 0, "by_level": {}}

    text_fields = ("diff", "function_context", "file_context", "full_file", "previous_version")
    total_chars = 0
    truncated_fields = 0
    level_count: Dict[str, int] = {}

    for item in bundle:
        level = str(item.get("final_context_level") or "unknown")
        level_count[level] = level_count.get(level, 0) + 1
        for field in text_fields:
            val = item.get(field)
            if isinstance(val, str):
                total_chars += len(val)
                if "TRUNCATED" in val:
                    truncated_fields += 1
        callers = item.get("callers") or []
        for c in callers:
            snippet = c.get("snippet")
            if isinstance(snippet, str):
                total_chars += len(snippet)
                if "TRUNCATED" in snippet:
                    truncated_fields += 1

    avg_chars = total_chars // max(len(bundle), 1)
    return {
        "items": len(bundle),
        "total_chars": total_chars,
        "avg_chars": avg_chars,
        "truncated_fields": truncated_fields,
        "by_level": level_count,
    }


def create_llm_client(preference: str = "auto", trace_id: str | None = None) -> Tuple[BaseLLMClient, str]:
    """根据偏好与可用密钥实例化 LLM 客户端。"""

    glm_key = os.getenv("GLM_API_KEY")
    if preference in {"glm", "auto"} and glm_key:
        try:
            return (
                GLMLLMClient(
                    model=os.getenv("GLM_MODEL", "GLM-4.6"),
                    api_key=glm_key,
                    logger=APILogger(trace_id=trace_id) if trace_id else None,
                ),
                "glm",
            )
        except Exception as exc:
            record_fallback(
                "llm_client_fallback",
                "GLM 初始化失败，继续尝试其他模型",
                meta={"provider": "glm", "error": str(exc)},
            )

    if preference == "glm" and not glm_key:
        record_fallback(
            "llm_client_fallback",
            "GLM 密钥缺失，无法按优先级创建",
            meta={"provider": "glm"},
        )

    bailian_key = os.getenv("BAILIAN_API_KEY")
    if preference in {"bailian", "auto"} and bailian_key:
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
            record_fallback(
                "llm_client_fallback",
                "Bailian 初始化失败，继续尝试其他模型",
                meta={"provider": "bailian", "error": str(exc)},
            )

    if preference == "bailian" and not bailian_key:
        record_fallback(
            "llm_client_fallback",
            "Bailian 密钥缺失，无法按优先级创建",
            meta={"provider": "bailian"},
        )

    if preference in {"moonshot", "auto"}:
        try:
            return (
                MoonshotLLMClient(
                    model=os.getenv("MOONSHOT_MODEL", "kimi-k2.5"),
                    logger=APILogger(trace_id=trace_id) if trace_id else None,
                ),
                "moonshot",
            )
        except Exception as exc:
            record_fallback(
                "llm_client_fallback",
                "Moonshot 初始化失败，继续尝试 Mock",
                meta={"provider": "moonshot", "error": str(exc)},
            )

    if preference == "glm":
        raise RuntimeError("GLM 模式被选择，但 GLM 客户端不可用。")
    if preference == "bailian":
        raise RuntimeError("Bailian 模式被选择，但 Bailian 客户端不可用。")
    if preference == "moonshot":
        raise RuntimeError("Moonshot 模式被选择，但 Moonshot 客户端不可用。")
    record_fallback(
        "llm_client_fallback",
        "未找到可用 LLM 客户端，降级为 Mock",
        meta={"preference": preference},
    )
    return MockMoonshotClient(), "mock"


class UsageAggregator:
    """按 call_index 累积 tokens 用量并生成会话汇总。"""

    def __init__(self) -> None:
        self._call_usage: Dict[int, Dict[str, int]] = {}

    def reset(self) -> None:
        self._call_usage.clear()

    def update(
        self, usage: Dict[str, Any], call_index: int | None
    ) -> Tuple[Dict[str, int], Dict[str, int]]:
        """更新某次调用的用量并返回（单次、会话）汇总。"""

        def _to_int(v: Any) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        in_tok = _to_int(usage.get("input_tokenss") or usage.get("prompt_tokenss"))
        out_tok = _to_int(
            usage.get("output_tokenss") or usage.get("completion_tokenss")
        )
        total_tok = _to_int(usage.get("total_tokenss"))
        try:
            idx = int(call_index) if call_index is not None else 1
        except (TypeError, ValueError):
            idx = 1
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

    def session_totals(self) -> Dict[str, int]:
        """返回最新的会话用量汇总。"""

        return {
            "in": sum(v["in"] for v in self._call_usage.values()),
            "out": sum(v["out"] for v in self._call_usage.values()),
            "total": sum(v["total"] for v in self._call_usage.values()),
        }


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
    planner_llm_preference: Optional[str] = None,
) -> str:
    """运行一次审查（对异步 Agent 的同步封装）。"""

    return asyncio.run(
        run_review_async(
            prompt,
            llm_preference,
            tool_names,
            auto_approve,
            project_root,
            stream_callback,
            tool_approver,
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
    planner_llm_preference: Optional[str] = None,
) -> str:
    """适用于 asyncio 服务的异步版本（避免在循环中调用 asyncio.run）。"""

    def _collect() -> "DiffContext":
        return collect_diff_context()

    fallback_tracker.reset()
    if stream_callback:
        try:
            stream_callback({"type": "pipeline_stage_start", "stage": "diff_parse"})
        except Exception:
            pass
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

    logger.info(
        "diff collected mode=%s files=%d units=%d",
        diff_ctx.mode.value,
        len(diff_ctx.files),
        len(diff_ctx.units),
    )

    trace_id = generate_trace_id()
    review_client, review_provider = create_llm_client(llm_preference, trace_id=trace_id)
    planner_pref = planner_llm_preference or llm_preference
    planner_client, planner_provider = create_llm_client(planner_pref, trace_id=trace_id)
    review_adapter = KimiAdapter(review_client, StreamProcessor(), provider_name=review_provider)
    planner_adapter = KimiAdapter(planner_client, StreamProcessor(), provider_name=planner_provider)
    pipe_logger = PipelineLogger(trace_id=trace_id)
    usage_agg = UsageAggregator()
    session_log = pipe_logger.start(
        "planning_review_service_async",
        {
            "review_provider": review_provider,
            "planner_provider": planner_provider,
            "trace_id": trace_id,
        },
    )
    pipe_logger.log(
        "diff_summary",
        {
            "mode": diff_ctx.mode.value,
            "files": len(diff_ctx.files),
            "units": len(diff_ctx.units),
            "review_index_units": len(diff_ctx.review_index.get("units", [])),
            "review_index_preview": diff_ctx.review_index.get("units", [])[:3],
            "trace_id": trace_id,
        },
    )
    if stream_callback:
        try:
            stream_callback({
                "type": "pipeline_stage_end",
                "stage": "diff_parse",
                "summary": {"files": len(diff_ctx.files), "units": len(diff_ctx.units)}
            })
            stream_callback({"type": "pipeline_stage_end", "stage": "review_units"})
            stream_callback({"type": "pipeline_stage_end", "stage": "rule_layer"})
            stream_callback({"type": "pipeline_stage_end", "stage": "review_index"})
        except Exception:
            pass

    if stream_callback:
        try:
            stream_callback({"type": "pipeline_stage_start", "stage": "planner"})
        except Exception:
            pass
    planner_state = ConversationState()
    planner = PlanningAgent(planner_adapter, planner_state, logger=pipe_logger)
    def _planner_observer(evt: Dict[str, Any]) -> None:
        if not stream_callback:
            return
        try:
            reasoning = evt.get("reasoning_delta") or ""
            content = evt.get("content_delta") or ""
            payload = reasoning or content
            if payload:
                stream_callback(
                    {
                        "type": "planner_delta",
                        "content_delta": payload,
                        "reasoning_delta": reasoning or None,
                    }
                )
        except Exception:
            pass
    try:
        plan = await planner.run(diff_ctx.review_index, stream=True, observer=_planner_observer)
        if stream_callback:
            try:
                stream_callback({"type": "pipeline_stage_end", "stage": "planner"})
            except Exception:
                pass
        planner_usage = getattr(planner, "last_usage", None)
        if planner_usage:
            call_usage, session_usage = usage_agg.update(planner_usage, 0)
            pipe_logger.log(
                "planner_usage",
                {
                    "call_index": 0,
                    "usage": planner_usage,
                    "call_usage": call_usage,
                    "session_usage": session_usage,
                    "trace_id": trace_id,
                },
            )
            if stream_callback:
                stream_callback(
                    {
                        "type": "usage_summary",
                        "usage_stage": "planner",
                        "call_index": 0,
                        "usage": planner_usage,
                        "call_usage": call_usage,
                        "session_usage": session_usage,
                    }
                )
        if stream_callback:
            try:
                stream_callback({"type": "pipeline_stage_start", "stage": "fusion"})
            except Exception:
                pass
        fused = fuse_plan(diff_ctx.review_index, plan)
        if stream_callback:
            try:
                stream_callback({"type": "pipeline_stage_start", "stage": "context_provider"})
                stream_callback({"type": "pipeline_stage_start", "stage": "context_bundle"})
            except Exception:
                pass
        context_bundle = build_context_bundle(diff_ctx, fused)
        bundle_stats = _summarize_context_bundle(context_bundle)
        logger.info(
            "plan fused provider=%s plan_units=%d bundle_items=%d",
            review_provider,
            len(plan.get("plan", [])) if isinstance(plan, dict) else 0,
            len(context_bundle),
        )
        pipe_logger.log("planning_output", {"plan": plan})
        pipe_logger.log("fusion_output", {"fused": fused})
        if stream_callback:
            try:
                stream_callback({"type": "pipeline_stage_end", "stage": "fusion"})
                stream_callback({"type": "pipeline_stage_end", "stage": "final_context_plan"})
            except Exception:
                pass
        pipe_logger.log(
            "context_bundle_summary",
            {
                "bundle_size": len(context_bundle),
                "unit_ids": [c.get("unit_id") for c in context_bundle],
                "bundle_stats": bundle_stats,
            },
        )
        if stream_callback:
            try:
                for item in context_bundle:
                    stream_callback({
                        "type": "bundle_item",
                        "unit_id": item.get("unit_id"),
                        "final_context_level": item.get("final_context_level"),
                        "location": (item.get("meta") or {}).get("location"),
                        "sizes": {
                            "diff": len(item.get("diff") or ""),
                            "function_context": len(item.get("function_context") or ""),
                            "file_context": len(item.get("file_context") or ""),
                            "full_file": len(item.get("full_file") or ""),
                        }
                    })
            except Exception:
                pass
        if stream_callback:
            try:
                stream_callback({"type": "pipeline_stage_end", "stage": "context_bundle"})
                stream_callback({"type": "pipeline_stage_end", "stage": "context_provider"})
            except Exception:
                pass
    except Exception as exc:
        logger.exception("pipeline failure after planner")
        pipe_logger.log(
            "pipeline_error",
            {"stage": "post_planner", "error": repr(exc), "trace_id": trace_id},
        )
        if stream_callback:
            try:
                stream_callback(
                    {
                        "type": "error",
                        "stage": "post_planner",
                        "message": str(exc),
                    }
                )
            except Exception:
                pass
        raise

    runtime = ToolRuntime()
    for name, func in get_tool_functions(tool_names).items():
        runtime.register(name, func)
    builtin_whitelist = set(builtin_tool_names())

    context_provider = ContextProvider()
    state = ConversationState()
    trace_logger = APILogger(trace_id=trace_id)

    review_index_md, _ = build_markdown_and_json_context(diff_ctx)
    ctx_json = json.dumps({"context_bundle": context_bundle}, ensure_ascii=False, indent=2)
    augmented_prompt = (
        f"{prompt}\n\n"
        f"审查索引（仅元数据，无代码正文，需代码请调用工具）：\n{review_index_md}\n\n"
        f"上下文包（按规划抽取的片段）：\n```json\n{ctx_json}\n```"
    )
    pipe_logger.log(
        "review_request",
        {
            "prompt_preview": augmented_prompt[:2000],
            "context_bundle_size": len(context_bundle),
            "trace_id": trace_id,
        },
    )
    tools = get_tool_schemas(tool_names)
    auto_approve_list = (
        tool_names
        if auto_approve
        else [name for name in tool_names if name in builtin_whitelist]
    )

    if stream_callback:
        try:
            stream_callback({"type": "pipeline_stage_start", "stage": "reviewer"})
        except Exception:
            pass
    agent = CodeReviewAgent(
        review_adapter, runtime, context_provider, state, trace_logger=trace_logger
    )

    def _dispatch_stream(evt: Dict[str, Any]) -> None:
        """为用量事件补充聚合统计并记录日志。"""

        usage = evt.get("usage")
        call_index = evt.get("call_index")
        stage = evt.get("usage_stage") or ("planner" if call_index == 0 else "review")
        enriched = dict(evt)

        if usage:
            call_usage, session_usage = usage_agg.update(usage, call_index)
            enriched["call_usage"] = call_usage
            enriched["session_usage"] = session_usage
            enriched["usage_stage"] = stage
            if pipe_logger and evt.get("type") == "usage_summary":
                pipe_logger.log(
                    "review_call_usage",
                    {
                        "call_index": call_index,
                        "usage_stage": stage,
                        "usage": usage,
                        "call_usage": call_usage,
                        "session_usage": session_usage,
                        "trace_id": trace_id,
                    },
                )

        if stream_callback:
            stream_callback(enriched)

    result = await agent.run(
        augmented_prompt,
        files=diff_ctx.files,
        stream_observer=_dispatch_stream,
        tools=tools,  # type: ignore[arg-type]
        auto_approve_tools=auto_approve_list,
        tool_approver=tool_approver,
    )
    pipe_logger.log("review_result", {"result_preview": str(result)[:500]})
    if stream_callback:
        try:
            stream_callback({"type": "pipeline_stage_end", "stage": "reviewer"})
        except Exception:
            pass
    fb_summary = fallback_tracker.emit_summary(logger=logger, pipeline_logger=pipe_logger)
    if fb_summary.get("total") and stream_callback:
        stream_callback(
            {
                "type": "warning",
                "message": f"回退触发 {fb_summary['total']} 次：{fb_summary['by_key']}",
                "fallback_summary": fb_summary,
            }
        )
    pipe_logger.log(
        "session_end",
        {
            "log_path": str(session_log),
            "session_usage": usage_agg.session_totals(),
            "trace_id": trace_id,
        },
    )
    if stream_callback:
        try:
            stream_callback({"type": "pipeline_stage_end", "stage": "final_output", "result_preview": str(result)[:300]})
        except Exception:
            pass
    return result
