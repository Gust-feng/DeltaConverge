"""Pipeline 执行引擎。

按序执行 Stage 列表，内核信任原则：Stage 内部错误直接向上传播。
支持执行追踪、性能监控、错误定位和 Stage 级别错误恢复。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from kernel.domain.context import PipelineContext
from kernel.domain.protocols import EventEmitter, Stage, StageErrorMode


@dataclass
class StageMetrics:
    """单个 Stage 的执行指标。"""
    stage_name: str
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None
    retries: int = 0
    degraded: bool = False
    
    def complete(self, success: bool = True, error: Optional[str] = None) -> None:
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.success = success
        self.error = error


@dataclass
class PipelineMetrics:
    """Pipeline 整体执行指标。"""
    trace_id: str
    start_time: float
    end_time: float = 0.0
    total_duration_ms: float = 0.0
    stages: List[StageMetrics] = field(default_factory=list)
    success: bool = True
    failed_stage: Optional[str] = None
    error: Optional[str] = None
    
    def complete(self, success: bool = True, error: Optional[str] = None) -> None:
        self.end_time = time.time()
        self.total_duration_ms = (self.end_time - self.start_time) * 1000
        self.success = success
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "success": self.success,
            "failed_stage": self.failed_stage,
            "error": self.error,
            "stages": [
                {
                    "name": s.stage_name,
                    "duration_ms": round(s.duration_ms, 2),
                    "success": s.success,
                    "error": s.error,
                    "retries": s.retries,
                    "degraded": s.degraded,
                }
                for s in self.stages
            ],
        }


class PipelineExecutor:
    """线性执行 Stage 列表的引擎。

    职责：
    1. 按序调用每个 Stage 的 execute 方法
    2. 收集执行指标（时间、成功/失败）
    3. 发布追踪事件供可观测性使用
    
    不做错误吞咽，异常直接传播给调用方（ReviewOrchestrator）。
    """

    def __init__(self, stages: Sequence[Stage], emitter: EventEmitter) -> None:
        self.stages = stages
        self.emitter = emitter
        self._metrics: Optional[PipelineMetrics] = None

    @property
    def metrics(self) -> Optional[PipelineMetrics]:
        """获取最近一次执行的指标。"""
        return self._metrics

    def _get_error_mode(self, stage: Stage) -> StageErrorMode:
        """获取 Stage 的错误处理模式。"""
        try:
            return stage.error_mode
        except AttributeError:
            return StageErrorMode.ABORT

    def _get_max_retries(self, stage: Stage) -> int:
        """获取 Stage 的最大重试次数。"""
        try:
            return stage.max_retries
        except AttributeError:
            return 0

    async def _handle_stage_error(
        self, stage: Stage, ctx: PipelineContext, error: Exception, emit: EventEmitter
    ) -> bool:
        """调用 Stage 的错误处理回调。"""
        try:
            return await stage.on_error(ctx, error, emit)
        except AttributeError:
            return False
        except Exception:
            return False

    async def run(self, ctx: PipelineContext) -> str:
        """执行所有 Stage，返回最终审查报告。
        
        支持 Stage 级别的错误恢复：
        - ABORT: 中断整个 Pipeline（默认）
        - DEGRADE: 降级处理，继续后续 Stage
        - RETRY: 重试当前 Stage
        """
        trace_id = ctx.trace_id or str(uuid.uuid4())[:8]
        ctx.trace_id = trace_id
        
        self._metrics = PipelineMetrics(
            trace_id=trace_id,
            start_time=time.time(),
        )
        
        # 发布 pipeline 开始事件
        self.emitter._emit("pipeline.started", None, {
            "trace_id": trace_id,
            "stage_count": len(self.stages),
            "stages": [type(s).__name__ for s in self.stages],
        })
        
        for stage in self.stages:
            stage_name = type(stage).__name__
            error_mode = self._get_error_mode(stage)
            max_retries = self._get_max_retries(stage)
            
            stage_metrics = StageMetrics(
                stage_name=stage_name,
                start_time=time.time(),
            )
            
            retries = 0
            last_error: Optional[Exception] = None
            
            while True:
                try:
                    await stage.execute(ctx, self.emitter)
                    stage_metrics.complete(success=True)
                    break
                except Exception as e:
                    last_error = e
                    
                    # 尝试调用 Stage 的错误处理回调
                    handled = await self._handle_stage_error(stage, ctx, e, self.emitter)
                    if handled:
                        stage_metrics.complete(success=True)
                        stage_metrics.degraded = True
                        break
                    
                    # 根据错误模式处理
                    if error_mode == StageErrorMode.RETRY and retries < max_retries:
                        retries += 1
                        stage_metrics.retries = retries
                        self.emitter._emit("stage.retry", stage_name, {
                            "trace_id": trace_id,
                            "retry": retries,
                            "max_retries": max_retries,
                            "error": str(e),
                        })
                        continue
                    
                    if error_mode == StageErrorMode.DEGRADE:
                        stage_metrics.complete(success=False, error=str(e))
                        stage_metrics.degraded = True
                        self.emitter._emit("stage.degraded", stage_name, {
                            "trace_id": trace_id,
                            "error": str(e),
                        })
                        break
                    
                    # ABORT 模式或重试耗尽
                    stage_metrics.complete(success=False, error=str(e))
                    self._metrics.stages.append(stage_metrics)
                    self._metrics.failed_stage = stage_name
                    self._metrics.complete(success=False, error=str(e))
                    
                    # 发布 pipeline 失败事件（包含诊断信息）
                    self.emitter._emit("pipeline.failed", stage_name, {
                        "trace_id": trace_id,
                        "failed_stage": stage_name,
                        "error": str(e),
                        "error_mode": error_mode.value,
                        "retries": retries,
                        "metrics": self._metrics.to_dict(),
                    })
                    raise
            
            self._metrics.stages.append(stage_metrics)
        
        self._metrics.complete(success=True)
        
        # 发布 pipeline 完成事件（包含性能摘要）
        self.emitter._emit("pipeline.completed", None, {
            "trace_id": trace_id,
            "metrics": self._metrics.to_dict(),
        })
        
        return ctx.final_report or ""
