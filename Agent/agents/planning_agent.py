"""规划 Agent：消费 review_index 元数据并产出上下文计划（仅 JSON）。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from Agent.core.adapter.llm_adapter import LLMAdapter
from Agent.core.state.conversation import ConversationState
from Agent.agents.prompts import SYSTEM_PROMPT_PLANNER, PLANNER_USER_INSTRUCTIONS
from Agent.core.logging.pipeline_logger import PipelineLogger
from Agent.core.api.models import PlanItem, ExtraRequest
import asyncio
import os
from typing import cast


class PlanningAgent:
    """轻量规划 Agent，决定审查哪些 ReviewUnit 以及所需上下文（默认流式）。"""

    def __init__(self, adapter: LLMAdapter, state: ConversationState | None = None, logger: PipelineLogger | None = None) -> None:
        self.adapter = adapter
        self.state = state or ConversationState()
        self.logger = logger
        self.last_usage: Dict[str, Any] | None = None

    async def run(self, review_index: Dict[str, Any], *, stream: bool = True, observer=None, intent_md: str | None = None) -> Dict[str, Any]:
        """基于 review_index 生成上下文计划（仅返回 JSON，默认流式）。"""

        # 构建消息
        if not self.state.messages:
            self.state.add_system_message(SYSTEM_PROMPT_PLANNER)

        user_parts = [PLANNER_USER_INSTRUCTIONS]
        if intent_md:
            user_parts.append("### 项目意图摘要（来自分析Agent）")
            user_parts.append(intent_md.strip())
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

        # 快速失败：如果上游模型超时，返回空计划而不是卡死整条链路。
        plan_timeout = float(os.getenv("PLANNER_TIMEOUT_SECONDS", "90") or 90)
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
            assistant_msg = await asyncio.wait_for(
                self.adapter.complete(
                    self.state.messages,
                    stream=stream,
                    observer=observer,
                    response_format=response_format,
                ),
                timeout=plan_timeout,
            )
        except asyncio.TimeoutError as exc:
            if self.logger:
                self.logger.log(
                    "planner_error",
                    {
                        "error": "timeout",
                        "timeout_seconds": plan_timeout,
                        "units": len(review_index.get("units", [])),
                    },
                )
            return {"plan": [], "error": f"timeout_after_{plan_timeout}s"}

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
