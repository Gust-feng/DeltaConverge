"""规划 Agent：消费 review_index 元数据并产出上下文计划（仅 JSON）。"""

from __future__ import annotations

import time
import json
from typing import Any, Dict, List

from Agent.core.adapter.llm_adapter import LLMAdapter
from Agent.core.state.conversation import ConversationState
from Agent.agents.prompts import SYSTEM_PROMPT_PLANNER, PLANNER_USER_INSTRUCTIONS
from Agent.core.logging.pipeline_logger import PipelineLogger
from Agent.core.api.models import PlanItem, ExtraRequest
from Agent.core.api.config import (
    get_planner_timeout,
    get_planner_first_token_timeout,
    get_planner_first_token_timeout_thinking,
)
import asyncio
from typing import cast


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
                continue
            if ch == "\\":
                esc = True
                continue
            if ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


class PlanningAgent:
    """轻量规划 Agent，决定审查哪些 ReviewUnit 以及所需上下文（默认流式）。"""

    def __init__(self, adapter: LLMAdapter, state: ConversationState | None = None, logger: PipelineLogger | None = None) -> None:
        self.adapter = adapter
        self.state = state or ConversationState()
        self.logger = logger
        self.last_usage: Dict[str, Any] | None = None

    async def run(self, review_index: Dict[str, Any], *, stream: bool = True, observer=None, intent_md: str | None = None, user_prompt: str | None = None) -> Dict[str, Any]:
        """基于 review_index 生成上下文计划（仅返回 JSON，默认流式）。"""

        # 构建消息
        if not self.state.messages:
            self.state.add_system_message(SYSTEM_PROMPT_PLANNER)

        user_parts = []
        if intent_md:
            user_parts.append("### 项目意图摘要")
            user_parts.append(intent_md.strip())
            user_parts.append("\n---\n")
        
        if user_prompt:
            user_parts.append("### 用户审查指令")
            user_parts.append(f"用户有额外的审查要求：{user_prompt.strip()}")
            user_parts.append("请根据此要求调整你的上下文规划策略。")
            user_parts.append("\n---\n")

        user_parts.append(PLANNER_USER_INSTRUCTIONS)
        user_parts.append("review_index JSON:")
        user_parts.append(json.dumps(review_index, ensure_ascii=False, indent=2))
        user_content = "\n".join(user_parts)
        self.state.add_user_message(user_content)

        if self.logger:
            # 日志：记录规划请求（仅摘要，避免过大）
            self.logger.log(
                "planner_request",
                {
                    "units": len(review_index.get("units", [])),
                    "files": len(review_index.get("summary", {}).get("files_changed", [])),
                },
            )

        # 快速失败：规划阶段采用“空闲超时 (idle timeout)”
        # 只要模型持续流式输出（observer 有事件），就不会被截断。
        # 只有在连续 plan_timeout 秒没有任何增量事件时，才判定超时。
        plan_timeout = get_planner_timeout(default=120.0)
        timeout_enabled = plan_timeout > 0

        # 首 token 超时：用于捕捉“完全没有流式输出”的卡死情况。
        # - 非思考模型：期望 < 20s 有任何输出
        # - 思考模型：允许更长时间（默认 120s）
        # 这里不依赖硬编码模型名，而是用 provider 返回的 model 字符串做轻量判断。
        model_hint = str(getattr(getattr(self.adapter, "client", None), "model", "") or "")
        thinking_mode = "thinking" in model_hint.lower()
        first_token_timeout = (
            get_planner_first_token_timeout_thinking(default=120.0)
            if thinking_mode
            else get_planner_first_token_timeout(default=20.0)
        )
        first_token_timeout_enabled = first_token_timeout > 0

        planner_started_at = time.monotonic()

        idle_event: asyncio.Event = asyncio.Event()
        last_activity_at = time.monotonic()

        first_token_event: asyncio.Event = asyncio.Event()
        first_token_at: float | None = None

        task: asyncio.Task | None = None

        def _wrapped_observer(evt: Dict[str, Any]) -> None:
            nonlocal last_activity_at
            last_activity_at = time.monotonic()
            idle_event.set()

            nonlocal first_token_at
            # 首 token 只需要“收到任意流式片段”即可；
            # 否则部分 provider 先发 role/tool_calls 等，可能导致误判为无输出。
            if first_token_at is None:
                first_token_at = last_activity_at
                first_token_event.set()
            if observer:
                try:
                    observer(evt)
                except Exception:
                    pass

        try:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "context_plan",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "plan": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "unit_id": {"type": "string"},
                                        "llm_context_level": {
                                            "type": "string",
                                            "enum": [
                                                "function",
                                                "file_context",
                                                "full_file",
                                                "diff_only",
                                            ],
                                        },
                                        "extra_requests": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "type": {
                                                        "type": "string",
                                                        "enum": [
                                                            "callers",
                                                            "previous_version",
                                                            "search",
                                                        ],
                                                    },
                                                    "details": {"type": "string"},
                                                },
                                                "required": ["type"],
                                                "additionalProperties": False,
                                            },
                                        },
                                        "skip_review": {"type": "boolean"},
                                        "reason": {"type": "string"},
                                    },
                                    "required": ["unit_id"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["plan"],
                        "additionalProperties": False,
                    },
                },
            }
            task = asyncio.create_task(
                self.adapter.complete(
                    self.state.messages,
                    stream=stream,
                    observer=_wrapped_observer,
                    # response_format=response_format,  # 移除强制 JSON 约束以允许输出思考过程
                    temperature=0.5,
                    top_p=0.9,
                )
            )

            if first_token_timeout_enabled:
                first_token_wait_task = asyncio.create_task(first_token_event.wait())
                try:
                    done, pending = await asyncio.wait(
                        {task, first_token_wait_task},
                        timeout=first_token_timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if task in done:
                        # LLM 已结束（可能是网络/协议错误），不额外等待首 token 超时。
                        pass
                    elif first_token_wait_task in done:
                        if self.logger and first_token_at is not None:
                            self.logger.log(
                                "planner_first_token",
                                {
                                    "first_token_ms": int((first_token_at - planner_started_at) * 1000),
                                    "thinking_mode": bool(thinking_mode),
                                    "timeout_seconds": float(first_token_timeout),
                                    "model": model_hint or None,
                                },
                            )
                    else:
                        task.cancel()
                        raise asyncio.TimeoutError(
                            f"planner_first_token_timeout_after_{first_token_timeout}s"
                        )
                finally:
                    if not first_token_wait_task.done():
                        first_token_wait_task.cancel()

            if timeout_enabled:
                while True:
                    if task.done():
                        break
                    idle_event.clear()
                    remaining = plan_timeout - (time.monotonic() - last_activity_at)
                    if remaining <= 0:
                        task.cancel()
                        raise asyncio.TimeoutError(f"planner_idle_timeout_after_{plan_timeout}s")

                    idle_wait_task = asyncio.create_task(idle_event.wait())
                    try:
                        done, pending = await asyncio.wait(
                            {task, idle_wait_task},
                            timeout=remaining,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if task in done:
                            break
                        if idle_wait_task in done:
                            continue
                        task.cancel()
                        raise asyncio.TimeoutError(f"planner_idle_timeout_after_{plan_timeout}s")
                    finally:
                        if not idle_wait_task.done():
                            idle_wait_task.cancel()

            assistant_msg = await task

        except asyncio.TimeoutError as exc:
            if self.logger:
                err = str(exc)
                timeout_kind = "idle"
                if "first_token_timeout" in err:
                    timeout_kind = "first_token"
                timeout_value = float(first_token_timeout) if timeout_kind == "first_token" else float(plan_timeout)
                self.logger.log(
                    "planner_error",
                    {
                        "error": "timeout",
                        "timeout_kind": timeout_kind,
                        "timeout_seconds": timeout_value,
                        "idle_timeout_seconds": float(plan_timeout),
                        "first_token_timeout_seconds": float(first_token_timeout),
                        "units": len(review_index.get("units", [])),
                    },
                )
            return {"plan": [], "error": f"timeout_after_{timeout_value}s"}
        except asyncio.CancelledError:
            raise
        except Exception:
            if task is not None and not task.done():
                task.cancel()
            raise

        self.last_usage = assistant_msg.get("usage") if isinstance(assistant_msg, dict) else None

        content = assistant_msg.get("content") or ""
        try:
            parsed = json.loads(content)
        except Exception:
            cleaned = content.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("` \n")
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].lstrip()
            try:
                parsed = json.loads(cleaned)
            except Exception:
                candidate = _extract_json_object(cleaned)
                if candidate:
                    try:
                        parsed = json.loads(candidate)
                    except Exception:
                        parsed = None
                else:
                    parsed = None
 
                if parsed is None:
                    if self.logger:
                        self.logger.log(
                            "planner_error",
                            {"error": "invalid_json", "raw": content[:2000]},
                        )
                    return {"plan": [], "error": "invalid_json"}

        clean_plan = {"plan": []}
        raw_items = cast(List[Dict[str, Any]], parsed.get("plan", []) if isinstance(parsed, dict) else [])

        allowed_levels = {"function", "file_context", "full_file", "diff_only"}
        allowed_extra_types = {"callers", "previous_version", "search"}
        allowed_keys = {"unit_id", "llm_context_level", "extra_requests", "skip_review", "reason"}
        seen_ids = set()
        dropped = 0
        # 对 planner 返回做白名单过滤，确保进入融合层的数据结构化、可预期。
        for item in raw_items:
            if not isinstance(item, dict):
                dropped += 1
                continue
            unit_id = item.get("unit_id")
            if not unit_id or unit_id in seen_ids:
                dropped += 1
                continue
            seen_ids.add(unit_id)
            clean_item = {k: item.get(k) for k in allowed_keys if k in item}
            clean_item["unit_id"] = unit_id
            llm_level = clean_item.get("llm_context_level")
            if llm_level not in allowed_levels:
                clean_item.pop("llm_context_level", None)
            extra_reqs = clean_item.get("extra_requests")
            if isinstance(extra_reqs, list):
                filtered_reqs = []
                for req in extra_reqs:
                    if not isinstance(req, dict):
                        continue
                    if req.get("type") not in allowed_extra_types:
                        continue
                    filtered_reqs.append(req)
                clean_item["extra_requests"] = filtered_reqs
            else:
                clean_item.pop("extra_requests", None)
            clean_item["skip_review"] = bool(clean_item.get("skip_review", False))

            # 转为数据类（域模型）
            extra_list = []
            for er in clean_item.get("extra_requests", []) or []:
                extra_list.append(ExtraRequest(type=er.get("type"), details=er.get("details")))
            plan_item_obj = PlanItem(
                unit_id=clean_item["unit_id"],
                llm_context_level=clean_item.get("llm_context_level"),
                extra_requests=extra_list or None,
                skip_review=bool(clean_item.get("skip_review", False)),
                reason=clean_item.get("reason"),
            )
            # 目前下游仍消费 dict，保持兼容：
            clean_plan["plan"].append({
                "unit_id": plan_item_obj.unit_id,
                "llm_context_level": plan_item_obj.llm_context_level,
                "extra_requests": [{"type": er.type, "details": er.details} for er in (plan_item_obj.extra_requests or [])],
                "skip_review": plan_item_obj.skip_review,
                "reason": plan_item_obj.reason,
            })
        if dropped and self.logger:
            self.logger.log(
                "planner_response_filtered",
                {"dropped_items": dropped, "kept_items": len(clean_plan["plan"])},
            )

        parsed = clean_plan

        if self.logger:
            self.logger.log(
                "planner_response",
                {
                    "raw": content[:2000],
                    "parsed_units": len(parsed.get("plan", [])) if isinstance(parsed, dict) else None,
                },
            )
        return parsed


__all__ = [
    "PlanningAgent",
]
