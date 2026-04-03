"""规划 Agent：消费 review_index 元数据并产出上下文计划（仅 JSON）。"""

from __future__ import annotations

import time
import json
from typing import Any, Dict, List

from Agent.core.adapter.llm_adapter import LLMAdapter
from Agent.core.state.conversation import ConversationState
from Agent.agents.prompts import SYSTEM_PROMPT_PLANNER, PLANNER_USER_INSTRUCTIONS
from Agent.agents.fusion import _is_high_risk
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


ALLOWED_CONTEXT_LEVELS = (
    "function",
    "file_context",
    "full_file",
    "diff_only",
)
ALLOWED_EXTRA_REQUEST_TYPES = (
    "callers",
    "previous_version",
    "search",
    "search_config_usage",
    "search_implementations",
)
TARGET_REQUIRED_EXTRA_REQUEST_TYPES = {
    "callers",
    "search",
    "search_config_usage",
    "search_implementations",
}
EXTRA_REQUEST_TYPE_ALIASES = {
    "search_callers": "callers",
}
JSON_SCHEMA_RESPONSE_FORMAT_PROVIDERS = {"openrouter", "minimax"}
PLANNER_FILES_CHANGED_SAMPLE_LIMIT = 24
PLANNER_TAGS_LIMIT = 6
PLANNER_EXTRA_REQUESTS_LIMIT = 4
PLANNER_MANDATORY_UNIT_SAMPLE_LIMIT = 12

NOISY_PATH_PREFIXES = ("legacy/", "frontend/reference/", "output/", "dist/")
NOISY_PATH_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".webp",
    ".lock",
)


class PlannerContractError(RuntimeError):
    """Planner 输出不满足内核契约时直接失败。"""


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _normalize_extra_request(req: Dict[str, Any]) -> Dict[str, Any] | None:
    raw_type = _clean_string(req.get("type"))
    if not raw_type:
        raise PlannerContractError("planner extra_request missing type")

    req_type = EXTRA_REQUEST_TYPE_ALIASES.get(raw_type, raw_type)
    if req_type not in ALLOWED_EXTRA_REQUEST_TYPES:
        raise PlannerContractError(f"planner extra_request type not allowed: {raw_type}")

    details = (
        _clean_string(req.get("details"))
        or _clean_string(req.get("symbol"))
        or _clean_string(req.get("keyword"))
        or _clean_string(req.get("text"))
    )
    if req_type in TARGET_REQUIRED_EXTRA_REQUEST_TYPES and not details:
        raise PlannerContractError(f"planner extra_request missing target: {req_type}")

    normalized: Dict[str, Any] = {"type": req_type}
    if details:
        normalized["details"] = details

    for key in ("symbol", "keyword", "text"):
        value = _clean_string(req.get(key))
        if value:
            normalized[key] = value

    if details:
        if req_type in {"callers", "search_implementations"}:
            normalized.setdefault("symbol", details)
        if req_type in {"search", "search_config_usage", "search_implementations"}:
            normalized.setdefault("keyword", details)
            normalized.setdefault("text", details)

    return normalized


def _supports_json_schema_response_format(adapter: LLMAdapter) -> bool:
    provider = _clean_string(getattr(adapter, "provider_name", None))
    return bool(provider and provider in JSON_SCHEMA_RESPONSE_FORMAT_PROVIDERS)


def _normalize_path(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("\\", "/").strip().lower()


def _compact_metrics(metrics: Any) -> Dict[str, int]:
    if not isinstance(metrics, dict):
        return {}
    compact: Dict[str, int] = {}
    for key in ("added_lines", "removed_lines", "hunk_count"):
        value = metrics.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            normalized = int(value)
            if normalized > 0:
                compact[key] = normalized
    return compact


def _compact_line_numbers(line_numbers: Any) -> Dict[str, str]:
    if not isinstance(line_numbers, dict):
        return {}
    compact: Dict[str, str] = {}
    for key in ("new_compact", "old_compact"):
        value = _clean_string(line_numbers.get(key))
        if value:
            compact[key] = value
    return compact


def _compact_rule_extra_requests(extra_requests: Any) -> List[Dict[str, Any]]:
    if not isinstance(extra_requests, list):
        return []
    compact: List[Dict[str, Any]] = []
    for req in extra_requests[:PLANNER_EXTRA_REQUESTS_LIMIT]:
        if not isinstance(req, dict):
            continue
        req_type = _clean_string(req.get("type"))
        if not req_type:
            continue
        if req_type == "scanner_issues":
            scanner_req: Dict[str, Any] = {"type": req_type}
            for key in ("issue_count", "error_count", "warning_count"):
                value = req.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    scanner_req[key] = int(value)
            note = _clean_string(req.get("note"))
            if note:
                scanner_req["note"] = note
            compact.append(scanner_req)
            continue

        item: Dict[str, Any] = {"type": EXTRA_REQUEST_TYPE_ALIASES.get(req_type, req_type)}
        for key in ("details", "symbol", "keyword", "text"):
            value = _clean_string(req.get(key))
            if value:
                item[key] = value
        compact.append(item)
    return compact


def _planner_unit_priority(unit: Dict[str, Any]) -> tuple[int, int, int, str]:
    file_path = _normalize_path(unit.get("file_path"))
    tags = {str(tag) for tag in (unit.get("tags") or []) if isinstance(tag, str)}
    metrics = unit.get("metrics") if isinstance(unit.get("metrics"), dict) else {}

    risk_bonus = 0
    if "security_sensitive" in tags:
        risk_bonus += 40
    if "config_file" in tags:
        risk_bonus += 24
    if "routing_file" in tags:
        risk_bonus += 20
    if "clustered_changes" in tags:
        risk_bonus += 4

    noise_penalty = 0
    if file_path.startswith(NOISY_PATH_PREFIXES):
        noise_penalty -= 25
    if file_path.endswith(NOISY_PATH_SUFFIXES):
        noise_penalty -= 20
    if "only_comments" in tags or "only_imports" in tags or "only_logging" in tags:
        noise_penalty -= 10

    confidence = unit.get("rule_confidence")
    confidence_score = int(float(confidence) * 100) if isinstance(confidence, (int, float)) else 0
    change_score = 0
    if isinstance(metrics, dict):
        change_score = int(metrics.get("added_lines") or 0) + int(metrics.get("removed_lines") or 0)

    return (
        risk_bonus + noise_penalty,
        confidence_score,
        change_score,
        str(unit.get("unit_id") or ""),
    )


def _compact_planner_unit(unit: Dict[str, Any]) -> Dict[str, Any]:
    compact: Dict[str, Any] = {
        "unit_id": unit.get("unit_id"),
        "file_path": unit.get("file_path"),
        "patch_type": unit.get("patch_type"),
    }

    tags = [tag for tag in (unit.get("tags") or []) if isinstance(tag, str)]
    if tags:
        compact["tags"] = tags[:PLANNER_TAGS_LIMIT]

    metrics = _compact_metrics(unit.get("metrics"))
    if metrics:
        compact["metrics"] = metrics

    level = _clean_string(unit.get("rule_context_level"))
    if level:
        compact["rule_context_level"] = level

    confidence = unit.get("rule_confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        compact["rule_confidence"] = round(float(confidence), 2)

    line_numbers = _compact_line_numbers(unit.get("line_numbers"))
    if line_numbers:
        compact["line_numbers"] = line_numbers

    extra_requests = _compact_rule_extra_requests(unit.get("rule_extra_requests"))
    if extra_requests:
        compact["rule_extra_requests"] = extra_requests

    return compact


def _build_prompt_review_index(review_index: Dict[str, Any]) -> Dict[str, Any]:
    units = [unit for unit in (review_index.get("units") or []) if isinstance(unit, dict)]
    mandatory_units = [unit for unit in units if _is_high_risk(unit)]
    optional_units = [unit for unit in units if not _is_high_risk(unit)]
    ranked_optional_units = sorted(optional_units, key=_planner_unit_priority, reverse=True)
    ranked_mandatory_units = sorted(mandatory_units, key=_planner_unit_priority, reverse=True)
    compact_units = [_compact_planner_unit(unit) for unit in ranked_optional_units]
    compact_mandatory_units = [_compact_planner_unit(unit) for unit in ranked_mandatory_units[:PLANNER_MANDATORY_UNIT_SAMPLE_LIMIT]]

    review_metadata = review_index.get("review_metadata") if isinstance(review_index.get("review_metadata"), dict) else {}
    summary = review_index.get("summary") if isinstance(review_index.get("summary"), dict) else {}

    sampled_files: List[str] = []
    seen_files = set()
    for unit in ranked_optional_units:
        file_path = _clean_string(unit.get("file_path"))
        if not file_path or file_path in seen_files:
            continue
        seen_files.add(file_path)
        sampled_files.append(file_path)
        if len(sampled_files) >= PLANNER_FILES_CHANGED_SAMPLE_LIMIT:
            break

    total_files = review_metadata.get("total_files")
    if not isinstance(total_files, int):
        total_files = len(summary.get("files_changed") or [])

    compact_summary: Dict[str, Any] = {
        "changes_by_type": summary.get("changes_by_type") or {},
        "total_lines": summary.get("total_lines") or {},
        "files_changed_total": total_files,
        "files_changed_sample": sampled_files,
        "files_changed_omitted": max(0, total_files - len(sampled_files)),
    }

    compact_metadata: Dict[str, Any] = {
        "mode": review_metadata.get("mode"),
        "base_branch": review_metadata.get("base_branch"),
        "total_files": total_files,
        "total_changes": review_metadata.get("total_changes") or len(units),
        "rule_mandatory_units_total": len(mandatory_units),
        "optional_units_total": len(optional_units),
    }

    return {
        "review_metadata": compact_metadata,
        "summary": compact_summary,
        "units": compact_units,
        "rule_mandatory_units_sample": compact_mandatory_units,
        "rule_mandatory_units_omitted": max(0, len(mandatory_units) - len(compact_mandatory_units)),
    }


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

        prompt_review_index = _build_prompt_review_index(review_index)
        prompt_review_index_json = json.dumps(
            prompt_review_index,
            ensure_ascii=False,
            separators=(",", ":"),
        )

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
        user_parts.append(prompt_review_index_json)
        user_content = "\n".join(user_parts)
        self.state.add_user_message(user_content)

        if self.logger:
            # 日志：记录规划请求（仅摘要，避免过大）
            self.logger.log(
                "planner_request",
                {
                    "units": len(review_index.get("units", [])),
                    "files": prompt_review_index.get("review_metadata", {}).get("total_files"),
                    "planner_optional_units": prompt_review_index.get("review_metadata", {}).get("optional_units_total"),
                    "planner_mandatory_units": prompt_review_index.get("review_metadata", {}).get("rule_mandatory_units_total"),
                    "planner_prompt_chars": len(prompt_review_index_json),
                    "planner_sampled_files": len(prompt_review_index.get("summary", {}).get("files_changed_sample", [])),
                    "planner_omitted_files": prompt_review_index.get("summary", {}).get("files_changed_omitted"),
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
                                                        "search_config_usage",
                                                        "search_implementations",
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

            async def _complete_with_json_contract() -> Dict[str, Any]:
                completion_kwargs = {
                    "stream": stream,
                    "observer": _wrapped_observer,
                    "temperature": 0.0,
                    "top_p": 1.0,
                }
                if _supports_json_schema_response_format(self.adapter):
                    completion_kwargs["response_format"] = response_format
                return await self.adapter.complete(
                    self.state.messages,
                    **completion_kwargs,
                )

            task = asyncio.create_task(
                _complete_with_json_contract()
            )

            if not stream:
                if timeout_enabled:
                    try:
                        assistant_msg = await asyncio.wait_for(task, timeout=plan_timeout)
                    except asyncio.TimeoutError as exc:
                        task.cancel()
                        raise asyncio.TimeoutError(f"planner_timeout_after_{plan_timeout}s") from exc
                else:
                    assistant_msg = await task
            elif first_token_timeout_enabled:
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
            err = str(exc)
            timeout_kind = "idle"
            if "first_token_timeout" in err:
                timeout_kind = "first_token"
            elif "planner_timeout_after_" in err:
                timeout_kind = "overall"
            timeout_value = float(first_token_timeout) if timeout_kind == "first_token" else float(plan_timeout)
            if self.logger:
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
            raise PlannerContractError(f"planner timeout after {timeout_value}s") from exc
        except asyncio.CancelledError:
            raise
        except Exception:
            if task is not None and not task.done():
                task.cancel()
            raise

        self.last_usage = assistant_msg.get("usage") if isinstance(assistant_msg, dict) else None

        content = (assistant_msg.get("content") or "") if isinstance(assistant_msg, dict) else ""
        parsed = assistant_msg.get("content_json") if isinstance(assistant_msg, dict) else None
        if not isinstance(parsed, dict):
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
                        raise PlannerContractError("planner returned invalid JSON")

        if not isinstance(parsed, dict):
            raise PlannerContractError("planner response must be a JSON object")
        raw_items = parsed.get("plan", [])
        if not isinstance(raw_items, list):
            raise PlannerContractError("planner response 'plan' must be a list")

        allowed_keys = {"unit_id", "llm_context_level", "extra_requests", "skip_review", "reason"}
        seen_ids = set()
        clean_plan = {"plan": []}
        # 对 planner 返回做白名单过滤，确保进入融合层的数据结构化、可预期。
        for item in raw_items:
            if not isinstance(item, dict):
                raise PlannerContractError("planner returned non-object plan item")
            unit_id = item.get("unit_id")
            if not unit_id:
                raise PlannerContractError("planner returned plan item without unit_id")
            if unit_id in seen_ids:
                raise PlannerContractError(f"planner returned duplicate unit_id: {unit_id}")
            seen_ids.add(unit_id)
            clean_item = {k: item.get(k) for k in allowed_keys if k in item}
            clean_item["unit_id"] = unit_id
            llm_level = clean_item.get("llm_context_level")
            if llm_level is not None and llm_level not in ALLOWED_CONTEXT_LEVELS:
                raise PlannerContractError(f"planner returned invalid llm_context_level: {llm_level}")
            extra_reqs = clean_item.get("extra_requests")
            if isinstance(extra_reqs, list):
                filtered_reqs = []
                for req in extra_reqs:
                    if not isinstance(req, dict):
                        raise PlannerContractError("planner extra_request must be an object")
                    normalized = _normalize_extra_request(req)
                    if normalized:
                        filtered_reqs.append(normalized)
                clean_item["extra_requests"] = filtered_reqs
            elif extra_reqs is not None:
                raise PlannerContractError("planner extra_requests must be a list")
            else:
                clean_item.pop("extra_requests", None)
            clean_item["skip_review"] = bool(clean_item.get("skip_review", False))

            # 转为数据类（域模型）
            extra_list = []
            normalized_extra_requests = cast(List[Dict[str, Any]], clean_item.get("extra_requests", []) or [])
            for er in normalized_extra_requests:
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
                "extra_requests": normalized_extra_requests,
                "skip_review": plan_item_obj.skip_review,
                "reason": plan_item_obj.reason,
            })
        parsed = clean_plan

        if self.logger:
            self.logger.log(
                "planner_response",
                {
                    "raw": content[:2000] if isinstance(content, str) else None,
                    "content_json_present": isinstance(
                        assistant_msg.get("content_json") if isinstance(assistant_msg, dict) else None,
                        dict,
                    ),
                    "parsed_units": len(parsed.get("plan", [])) if isinstance(parsed, dict) else None,
                },
            )
        return parsed


__all__ = [
    "PlanningAgent",
]
