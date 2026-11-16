"""Negotiate optional request parameters before any response is delivered."""

from __future__ import annotations

import copy
import re
from typing import Any


_REJECTION = re.compile(
    r"unsupported|not supported|does not support|doesn't support|not available|unavailable|"
    r"not allowed|not permitted|not accept|unrecognized|unknown (?:parameter|argument|field)|"
    r"unexpected keyword argument|extra inputs are not permitted|only .* supported|"
    r"only .* allowed|not compatible|invalid.*(?:schema|format)",
    re.IGNORECASE,
)
_TOKEN_LIMITS = {"max_tokens", "max_completion_tokens", "max_output_tokens"}
_RESERVED = {"model", "messages", "input", "stream", "store"}
_NORMALIZED = _TOKEN_LIMITS | {
    "tools", "tool_choice", "parallel_tool_calls", "response_format", "text",
    "temperature", "top_p", "seed", "stop", "frequency_penalty", "presence_penalty",
    "stream_options", "reasoning", "include", "instructions", "previous_response_id",
    "truncation", "metadata", "service_tier", "user", "prompt_cache_key",
    "safety_identifier", "background", "conversation", "prompt", "top_logprobs",
}
_OPTIONAL = {
    "temperature", "top_p", "seed", "stop", "frequency_penalty", "presence_penalty",
    "stream_options", "parallel_tool_calls", "tool_choice", "logprobs", "top_logprobs",
    "reasoning", "thinking", "reasoning_split", "include",
}


def normalize_options(kwargs):
    """Standard options have one source; extra_body cannot override request identity."""
    options = dict(kwargs)
    extra = dict(options.pop("extra_body", {}) or {})
    for key in list(extra):
        if key in _RESERVED:
            extra.pop(key)
        elif key in _NORMALIZED:
            options.setdefault(key, extra.pop(key))
    if extra:
        options["extra_body"] = extra
    return options


def select_response_format(client, response_format):
    """The user opts into API constraints; prompt JSON remains the default."""
    from Agent.core.api.config import get_structured_output_enabled
    if not response_format or response_format.get("type") == "text":
        return response_format
    if not get_structured_output_enabled():
        return None
    capabilities = getattr(client, "capabilities", {})
    kind = response_format.get("type")
    if kind == "json_schema":
        supported = capabilities.get("json_schema", capabilities.get("structured_output"))
        if supported is not False:
            return response_format
        return {"type": "json_object"} if capabilities.get("json_object") is not False else None
    if kind == "json_object" and capabilities.get("json_object") is False:
        return None
    return response_format


def _error_details(exc):
    status = getattr(exc, "status_code", None)
    if status not in (400, 422):
        return None
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    if not isinstance(error, dict):
        error = {}
    message = str(error.get("message") or str(exc))
    param = str(error.get("param") or "")
    code = str(error.get("code") or "")
    token_limit_error = any(_mentions(key, message, param) for key in _TOKEN_LIMITS) and bool(
        re.search(r"at most|maximum|less than or equal|<=|no (?:more|greater) than", message, re.IGNORECASE)
    )
    if not _REJECTION.search(message) and not token_limit_error and not re.search(
        r"required properties|additionalproperties|invalid_json_schema", message, re.IGNORECASE
    ) and code not in {
        "unsupported_parameter", "unsupported_value", "unknown_parameter", "invalid_json_schema",
    }:
        return None
    return message, param


def _mentions(name, message, param):
    if param:
        return param == name or param.startswith(name + ".") or param.startswith(name + "[")
    return bool(re.search(r"(?<![\w])" + re.escape(name) + r"(?![\w])", message, re.IGNORECASE))


def _format(params):
    if isinstance(params.get("response_format"), dict):
        return params["response_format"], False
    text = params.get("text")
    if isinstance(text, dict) and isinstance(text.get("format"), dict):
        return text["format"], True
    return None, False


def _apply(params, action):
    kind, name, value = action
    if kind == "format":
        current, responses = _format(params)
        if not current or current.get("type") != name:
            return False
        if responses:
            text = dict(params["text"])
            if value:
                text["format"] = {"type": value}
            else:
                text.pop("format", None)
            if text:
                params["text"] = text
            else:
                params.pop("text", None)
        elif value:
            params["response_format"] = {"type": value}
        else:
            params.pop("response_format", None)
        return True
    if kind == "rename" and name in params and value not in params:
        params[value] = params.pop(name)
        return True
    if kind == "limit" and name in params and params[name] > value:
        params[name] = value
        return True
    if kind == "drop_text":
        text = params.get("text")
        if isinstance(text, dict) and name in text:
            text.pop(name)
            if not text:
                params.pop("text", None)
            return True
    if kind == "drop":
        if name in params:
            params.pop(name)
            if name == "tools":
                params.pop("tool_choice", None)
                params.pop("parallel_tool_calls", None)
            return True
        extra = params.get("extra_body")
        if isinstance(extra, dict) and name in extra:
            extra.pop(name)
            if not extra:
                params.pop("extra_body", None)
            return True
    return False


def _next_action(params, message, param):
    text = params.get("text")
    if isinstance(text, dict) and "verbosity" in text and (
        param == "text.verbosity" or (not param and _mentions("verbosity", message, ""))
    ):
        return "drop_text", "verbosity", None
    fmt, responses = _format(params)
    if fmt and (
        _mentions("response_format", message, param)
        or _mentions("json_schema", message, param)
        or _mentions("json_object", message, param)
        or _mentions("schema", message, param)
        or (responses and (param == "text" or _mentions("text.format", message, param)))
    ):
        kind = fmt.get("type")
        if kind == "json_schema":
            return "format", kind, "json_object"
        if kind == "json_object":
            return "format", kind, None

    for old, new in [("max_tokens", "max_completion_tokens"), ("max_completion_tokens", "max_tokens")]:
        if old in params and _mentions(old, message, param) and _mentions(new, message, ""):
            return "rename", old, new
    for key in ("max_tokens", "max_completion_tokens", "max_output_tokens"):
        if key not in params or not _mentions(key, message, param):
            continue
        match = re.search(
            r"(?:at most|maximum(?: (?:allowed|value|is|of))?|less than or equal to|<=|no (?:more|greater) than)\s*[:=]?\s*(\d[\d,]*)",
            message, re.IGNORECASE,
        )
        if match:
            limit = int(match.group(1).replace(",", ""))
            if limit > 0 and params[key] > limit:
                return "limit", key, limit

    for key in sorted(_OPTIONAL | set(params.get("extra_body") or {})):
        if key in _RESERVED | _TOKEN_LIMITS | {"tools", "response_format", "text"}:
            continue
        if (key in params or key in (params.get("extra_body") or {})) and _mentions(key, message, param):
            return "drop", key, None
    # Tools are removed only when the endpoint explicitly rejects tool support.
    if "tools" in params and _mentions("tools", message, param) and re.search(
        r"unsupported|not supported|does not support|not available|unrecognized|unknown parameter", message, re.IGNORECASE
    ) and not re.search(r"schema|parameters|properties|function\.name", message, re.IGNORECASE):
        return "drop", "tools", None
    return None


async def create_with_compat(client, create, params: dict[str, Any], log_path):
    """Retry only rejected optional parameters, never a started/incomplete stream."""
    options = copy.deepcopy(params)
    if getattr(client, "capabilities", {}).get("tool_calling") is False:
        options.pop("tools", None)
        options.pop("tool_choice", None)
        options.pop("parallel_tool_calls", None)
    from Agent.core.api.config import get_structured_output_enabled
    if not get_structured_output_enabled():
        options.pop("response_format", None)
        text = options.get("text")
        if isinstance(text, dict):
            text.pop("format", None)
            if not text:
                options.pop("text", None)
    cache_key = (client.base_url, getattr(client, "protocol", "chat_completions"), client.model, bool(params.get("stream")))
    cache = getattr(client, "_parameter_compat", {})
    actions = cache.setdefault(cache_key, [])
    client._parameter_compat = cache
    for action in actions:
        _apply(options, action)
    attempted = set()
    learned = []
    for attempt in range(8):
        try:
            result = await create(**options)
            for action in learned:
                if action not in actions:
                    actions.append(action)
            return result
        except Exception as exc:
            details = _error_details(exc)
            action = _next_action(options, *details) if details else None
            if not action or action in attempted or attempt == 7 or not _apply(options, action):
                raise
            attempted.add(action)
            if re.search(r"unsupported|not supported|does not support|doesn't support|unavailable|not available|unrecognized|unknown parameter", details[0], re.IGNORECASE) and not re.search(
                r"invalid.*schema|required properties|additionalproperties|\bkeyword\b|\bproperties\b|"
                r"\bvalue\b|\bvalues\b|\boneof\b|\banyof\b|\ballof\b|\$ref", details[0], re.IGNORECASE
            ) and action[1] != "tool_choice":
                learned.append(action)
            client._logger.append(log_path, "PARAMETER_COMPAT", {
                "action": action[0], "parameter": action[1], "replacement": action[2],
                "status": getattr(exc, "status_code", None),
            })
    raise RuntimeError("Model parameter negotiation exceeded its retry limit")
