"""审查编排器（全 Stage 版本）。

Pipeline 组成：DiffStage → LLMSetupStage → IntentStage → PlannerStage → FusionStage → ReviewStage

编排器负责生命周期管理与资源清理。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict
from typing import Any

from kernel.domain.context import PipelineContext
from kernel.domain.models import ReviewCreateRequest, ReviewRun
from kernel.ports.stores import ArtifactStore, ScanServicePort, SessionStore

from .emitter import WorkflowEventEmitter, sanitize_payload
from .event_bus import RunEventBus
from .pipeline_executor import PipelineExecutor
from .stages.diff_stage import DiffStage
from .stages.llm_setup_stage import LLMSetupStage
from .stages.intent_stage import IntentStage
from .stages.planner_stage import PlannerStage
from .stages.fusion_stage import FusionStage
from .stages.review_stage import ReviewStage

logger = logging.getLogger(__name__)


def _generate_trace_id() -> str:
    """生成唯一的追踪 ID，格式: <时间戳前缀>-<随机后缀>。"""
    import time
    ts = int(time.time() * 1000) % 100000000  # 毫秒时间戳后8位
    suffix = uuid.uuid4().hex[:6]
    return f"{ts:08d}-{suffix}"


class ReviewOrchestrator:
    """审查编排器。管理审查任务完整生命周期。"""

    def __init__(
        self,
        store: SessionStore,
        artifact_store: ArtifactStore,
        event_bus: RunEventBus,
        scan_service: ScanServicePort | None = None,
        # Port 依赖注入
        llm_factory: Any | None = None,
        git_port: Any | None = None,
        diff_port: Any | None = None,
    ) -> None:
        self.store = store
        self.artifact_store = artifact_store
        self.event_bus = event_bus
        self.scan_service = scan_service
        
        # Port 依赖（延迟导入以避免循环依赖）
        self._llm_factory = llm_factory
        self._git_port = git_port
        self._diff_port = diff_port

    async def start_review(self, request: ReviewCreateRequest, run: ReviewRun) -> None:
        asyncio.create_task(self._run_review(request, run))

    async def _run_review(self, request: ReviewCreateRequest, run: ReviewRun) -> None:
        session_id = run.session_id
        trace_id = _generate_trace_id()

        # ── 生命周期：启动 ──
        self.store.update_run(run.id, status="running")
        self.store.update_session(
            session_id, status="active", latest_run_id=run.id, last_error=""
        )
        self.store.add_message(
            session_id=session_id,
            run_id=run.id,
            role="user",
            content=request.prompt,
            metadata={"channel": "review", "kind": "prompt", "trace_id": trace_id},
        )

        emitter = WorkflowEventEmitter(
            run_id=run.id,
            session_id=session_id,
            store=self.store,
            event_bus=self.event_bus,
        )
        emitter._emit(
            "review.started", None,
            {"request": sanitize_payload(asdict(request)), "trace_id": trace_id},
        )

        # ── 组装 Pipeline（使用注入的 Port 依赖） ──
        # 如果没有注入依赖，创建默认的 Legacy 适配器
        if self._llm_factory is None:
            from kernel.infrastructure import LegacyLLMFactory
            self._llm_factory = LegacyLLMFactory()
        
        if self._git_port is None:
            from kernel.infrastructure import LegacyGitAdapter
            self._git_port = LegacyGitAdapter(default_cwd=request.project_root)
        
        if self._diff_port is None:
            from kernel.infrastructure import LegacyDiffAdapter
            self._diff_port = LegacyDiffAdapter(git_adapter=self._git_port)
        
        stages = [
            DiffStage(
                store=self.store,
                artifact_store=self.artifact_store,
                git_port=self._git_port,
                diff_port=self._diff_port,
                scan_service=self.scan_service,
            ),
            LLMSetupStage(llm_factory=self._llm_factory),
            IntentStage(),
            PlannerStage(),
            FusionStage(),
            ReviewStage(),
        ]
        pipeline = PipelineExecutor(stages, emitter)
        ctx = PipelineContext(
            request=request,
            run=run,
            session_id=session_id,
            project_root=request.project_root,
            trace_id=trace_id,
        )

        try:
            final_content = await pipeline.run(ctx)

            # ── 更新会话标题（如果生成了的话） ──
            if ctx.session_title:
                self.store.update_session(session_id, name=ctx.session_title)

            # ── 保存报告 ──
            report_artifact = self.artifact_store.save_text(
                session_id=session_id,
                run_id=run.id,
                kind="final_report",
                content=final_content,
                extension="md",
                mime_type="text/markdown",
                metadata={"source": "review_run"},
            )
            self.store.register_artifact(report_artifact)
            self.store.add_message(
                session_id=session_id,
                run_id=run.id,
                role="assistant",
                content=final_content,
                metadata={
                    "channel": "review",
                    "kind": "final_report",
                    "artifact_id": report_artifact.id,
                },
            )
            self.store.update_run(
                run.id, status="completed",
                final_report_artifact_id=report_artifact.id,
            )
            self.store.update_session(
                session_id, status="completed", latest_run_id=run.id
            )
            emitter._emit(
                "review.completed", None,
                {"artifact_id": report_artifact.id, "content_preview": final_content[:500]},
            )

            # ── 等待旁路扫描 ──
            if ctx.scan_started and not ctx.scan_complete and ctx.scan_done_event:
                try:
                    await asyncio.wait_for(ctx.scan_done_event.wait(), timeout=120.0)
                except asyncio.TimeoutError:
                    emitter._emit("scan.finished", "scan", {
                        "status": "timed_out",
                        "message": "scan stream timeout after review completion",
                    })

        except Exception as exc:
            self.store.update_run(run.id, status="failed", error_message=str(exc))
            self.store.update_session(
                session_id, status="failed",
                last_error=str(exc), latest_run_id=run.id,
            )
            self.store.add_message(
                session_id=session_id, run_id=run.id,
                role="assistant", content=str(exc),
                metadata={"channel": "review", "kind": "error"},
            )
            emitter._emit("review.failed", None, {"error": str(exc)})

        finally:
            # ── 资源清理 ──
            if ctx.review_client:
                await ctx.review_client.aclose()
            if ctx.planner_client and ctx.planner_client is not ctx.review_client:
                await ctx.planner_client.aclose()

            if ctx.static_scan_task and not ctx.static_scan_task.done():
                ctx.static_scan_task.cancel()

            # 清理项目级缓存（生命周期管理：每次 run 结束清理该项目缓存）
            try:
                from Agent.agents.context_scheduler import clear_file_caches
                if ctx.project_root:
                    clear_file_caches(ctx.project_root)
            except Exception:
                # 缓存清理失败不影响审查结果，但可能导致后续内存占用偏高
                logger.warning(
                    "清理项目文件缓存失败 (project_root=%s)",
                    ctx.project_root,
                    exc_info=True,
                )

            # 清理全局上下文（兼容旧工具层）- 使用安全方式防止泄漏
            # 注意: 新内核不应依赖这些全局状态，但旧工具可能需要
            from Agent.core.context.runtime_context import set_project_root, set_session_id, set_diff_units
            from Agent.DIFF.rule.context_decision import set_rule_event_callback
            try:
                set_project_root(None)
                set_session_id(None)
                set_diff_units([])
                set_rule_event_callback(None)
            except Exception:
                # 清理失败不应影响其他清理步骤，但静默会掩盖全局状态泄漏
                logger.warning("重置全局运行时上下文失败", exc_info=True)

            event_log_artifact = self.artifact_store.save_json(
                session_id=session_id,
                run_id=run.id,
                kind="review_event_log",
                payload={"events": emitter.raw_log},
                metadata={"event_count": len(emitter.raw_log)},
            )
            self.store.register_artifact(event_log_artifact)
            # 确保所有事件都已发布完成再关闭总线
            await emitter.flush()
            await self.event_bus.close(run.id)
