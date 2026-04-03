"""Fusion 与上下文生成 Stage。

负责：
1. 融合规则与 LLM 的规划结果 (fuse_plan)
2. 根据融合结果提取代码上下文 (build_context_bundle)
3. 统计上下文大小并在超过预算时实施截断策略
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, cast

from kernel.domain.context import PipelineContext
from kernel.domain.protocols import EventEmitter


def _context_priority(item: Dict[str, Any]) -> int:
    """计算上下文项的保留优先级。"""
    level = str(item.get("final_context_level") or "")
    level_weight = {
        "full_file": 40,
        "file_context": 30,
        "function": 20,
        "diff_only": 10,
    }.get(level, 0)

    meta = cast(Dict[str, Any], item.get("meta") or {})
    file_path = str(meta.get("file_path") or "").replace("\\", "/").lower()
    penalty = 0
    if file_path.startswith(("legacy/", "frontend/reference/", "output/", "dist/")):
        penalty -= 20
    if file_path.endswith((".png", ".jpg", ".jpeg", ".ico", ".gif")):
        penalty -= 20
    if file_path.endswith((".css", ".scss", ".sass", ".less", ".styl")):
        penalty -= 8
    if file_path.endswith((".md", ".txt")):
        penalty -= 6
    if file_path.endswith(("package-lock.json", "pnpm-lock.yaml", "yarn.lock")):
        penalty -= 10

    tags = set(meta.get("tags") or [])
    bonus = 0
    if "security_sensitive" in tags:
        bonus += 12
    if "config_file" in tags or "routing_file" in tags:
        bonus += 8
    if "clustered_changes" in tags:
        bonus += 2

    diff_text = item.get("diff")
    diff_bonus = min(len(diff_text), 4000) // 400 if isinstance(diff_text, str) else 0
    return level_weight + bonus + diff_bonus + penalty


def _truncate_prompt_text(text: str | None, max_chars: int, *, label: str) -> str | None:
    if not text:
        return text
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[已截断 {label}，省略 {omitted} 字符。]"


def _compact_context_item(item: Dict[str, Any], limits: Dict[str, int]) -> Dict[str, Any]:
    meta = cast(Dict[str, Any], item.get("meta") or {})
    compact: Dict[str, Any] = {
        "unit_id": item.get("unit_id"),
        "file_path": meta.get("file_path"),
        "location": meta.get("location"),
        "context_level": item.get("final_context_level"),
    }

    tags = list(meta.get("tags") or [])
    if tags:
        compact["tags"] = tags[: limits.get("tags_max_count", 6)]

    diff_excerpt = _truncate_prompt_text(
        cast(Optional[str], item.get("diff")),
        limits.get("context_field_max_chars", 1800),
        label="diff 片段",
    )
    if diff_excerpt:
        compact["diff_excerpt"] = diff_excerpt

    context_fields = (
        ("function_context", "function"),
        ("file_context", "file"),
        ("full_file", "full_file"),
    )
    for field_name, label in context_fields:
        value = _truncate_prompt_text(
            cast(Optional[str], item.get(field_name)),
            limits.get("context_field_max_chars", 1800),
            label=f"{label} 上下文",
        )
        if value:
            compact["context_kind"] = label
            compact["context_excerpt"] = value
            break

    previous_version = _truncate_prompt_text(
        cast(Optional[str], item.get("previous_version")),
        limits.get("context_field_max_chars", 1800) // 2,
        label="历史版本片段",
    )
    if previous_version:
        compact["previous_version_excerpt"] = previous_version

    extra_requests = item.get("extra_requests") or []
    if extra_requests:
        compact["extra_requests"] = [
            req.get("type") if isinstance(req, dict) else str(req) for req in extra_requests[:4]
        ]

    callers: List[Dict[str, str]] = []
    for caller in cast(List[Dict[str, Any]], item.get("callers") or [])[:1]:
        callers.append(
            {
                "file_path": str(caller.get("file_path") or ""),
                "snippet": _truncate_prompt_text(
                    cast(Optional[str], caller.get("snippet")),
                    limits.get("caller_max_chars", 500),
                    label="调用方片段",
                )
                or "",
            }
        )
    if callers:
        compact["callers"] = callers

    return compact


class FusionStage:
    """融合与上下文生成。"""

    @property
    def name(self) -> str:
        return "fusion"

    async def execute(self, ctx: PipelineContext, emit: EventEmitter) -> None:
        request = ctx.request
        agents = set(request.agents or ["intent", "planner", "reviewer"])
        if "reviewer" not in agents:
            return

        from Agent.agents.fusion import fuse_plan
        from Agent.agents.context_scheduler import build_context_bundle
        from Agent.core.api.config import get_review_prompt_limits

        # 1. 融合规则与规划
        emit.stage_started("fusion")
        fused = fuse_plan(ctx.diff_ctx.review_index, ctx.plan or {})
        ctx.fused_plan = fused
        emit.stage_finished("fusion")

        # 2. 构建原始上下文包
        emit.stage_started("context_provider")
        emit.stage_started("context_bundle")
        
        context_bundle = build_context_bundle(ctx.diff_ctx, fused)
        
        for item in context_bundle:
            emit.tool_event("bundle_item", "context_provider", **{
                "unit_id": item.get("unit_id"),
                "final_context_level": item.get("final_context_level"),
                "location": (item.get("meta") or {}).get("location"),
            })
            
        emit.stage_finished("context_bundle")
        emit.stage_finished("context_provider")

        # 3. 截断与紧凑化 (复用旧内核逻辑)
        try:
            limits = get_review_prompt_limits()
        except Exception:
            limits = {
                "context_bundle_max_items": 10,
                "context_bundle_max_chars": 45000,
                "context_field_max_chars": 1800,
                "caller_max_chars": 500,
                "tags_max_count": 6,
            }

        ranked = sorted(context_bundle, key=_context_priority, reverse=True)
        kept: List[Dict[str, Any]] = []
        omitted = 0
        total_chars = 0

        for item in ranked:
            compact = _compact_context_item(item, limits)
            serialized = json.dumps(compact, ensure_ascii=False)
            next_chars = total_chars + len(serialized)
            if kept and (
                len(kept) >= limits.get("context_bundle_max_items", 10)
                or next_chars > limits.get("context_bundle_max_chars", 45000)
            ):
                omitted += 1
                continue
            kept.append(compact)
            total_chars = next_chars

        # 将紧凑后的包存入 ctx，供 ReviewStage 使用
        ctx.context_bundle = kept
