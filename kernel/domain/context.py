"""审查流水线的统一数据容器。

PipelineContext 贯穿所有 Stage，每个 Stage 从中读取输入、写入输出。
内核内部数据流可信，不做冗余校验。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .models import ReviewCreateRequest, ReviewRun


@dataclass
class IntentStageOutput:
    summary: Optional[str]
    project_file_tree: Dict[str, Any]
    cache_hit: bool
    source: str
    usage: Optional[Dict[str, Any]] = None


@dataclass
class PlannerStageOutput:
    plan: Dict[str, Any]
    usage: Optional[Dict[str, Any]] = None


@dataclass
class FusionStageOutput:
    fused_plan: Dict[str, Any]
    context_bundle: List[Dict[str, Any]]
    omitted_items: int = 0
    approx_chars: int = 0


@dataclass
class ReviewStageOutput:
    final_report: str
    session_title: Optional[str] = None


@dataclass
class PipelineContext:
    """审查流水线上下文。

    生命周期：由 ReviewOrchestrator 创建，传入 PipelineExecutor，
    各 Stage 按序读写其中的字段。
    """

    # ── 输入（创建时确定，Stage 不应修改）──
    request: ReviewCreateRequest
    run: ReviewRun
    session_id: str
    project_root: Optional[str]
    trace_id: str

    # ── Diff 阶段输出 ──
    diff_ctx: Any = None

    # ── Intent 阶段输出 ──
    intent_summary: Optional[str] = None
    project_file_tree: Optional[Dict[str, Any]] = None
    intent_output: Optional[IntentStageOutput] = None

    # ── Planner 阶段输出 ──
    plan: Optional[Dict[str, Any]] = None
    planner_output: Optional[PlannerStageOutput] = None

    # ── Fusion & Context 阶段输出 ──
    fused_plan: Optional[Dict[str, Any]] = None
    context_bundle: Optional[List[Dict[str, Any]]] = None
    fusion_output: Optional[FusionStageOutput] = None

    # ── Review 阶段输出 ──
    final_report: Optional[str] = None
    session_title: Optional[str] = None
    review_output: Optional[ReviewStageOutput] = None

    # ── LLM 资源（由 LLMSetupStage 填充）──
    review_adapter: Any = None
    planner_adapter: Any = None
    review_client: Any = None
    planner_client: Any = None
    review_provider: Optional[str] = None
    planner_provider: Optional[str] = None

    # ── 扫描器状态（由 DiffStage 管理）──
    scan_started: bool = False
    scan_complete: bool = False
    scan_done_event: Any = None       # asyncio.Event
    static_scan_task: Any = None      # asyncio.Task

    # ── 诊断统计（由各 Stage 累积更新）──
    tool_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
