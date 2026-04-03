"""会话诊断视图模块。

为每次审查生成诊断简报，包含：
- 总耗时和各阶段耗时
- Token 消耗统计
- 工具调用次数
- 失败点和错误信息
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from kernel.domain.context import PipelineContext
from kernel.application.pipeline_executor import PipelineMetrics


@dataclass
class StageDiagnostic:
    """单个 Stage 的诊断信息。"""
    name: str
    duration_ms: float
    success: bool
    error: Optional[str] = None
    retries: int = 0
    degraded: bool = False


@dataclass
class SessionDiagnostic:
    """会话诊断简报。"""
    trace_id: str
    total_duration_ms: float
    success: bool
    
    # Stage 统计
    stage_count: int
    stages: List[StageDiagnostic] = field(default_factory=list)
    failed_stage: Optional[str] = None
    
    # Token 统计
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    
    # 工具统计
    tool_calls: int = 0
    
    # 错误信息
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式。"""
        return {
            "trace_id": self.trace_id,
            "summary": {
                "total_duration_ms": round(self.total_duration_ms, 2),
                "success": self.success,
                "stage_count": self.stage_count,
                "failed_stage": self.failed_stage,
            },
            "tokens": {
                "input": self.total_input_tokens,
                "output": self.total_output_tokens,
                "total": self.total_input_tokens + self.total_output_tokens,
            },
            "tools": {
                "total_calls": self.tool_calls,
            },
            "stages": [
                {
                    "name": s.name,
                    "duration_ms": round(s.duration_ms, 2),
                    "success": s.success,
                    "error": s.error,
                    "retries": s.retries,
                    "degraded": s.degraded,
                }
                for s in self.stages
            ],
            "error": self.error,
        }
    
    def to_summary_text(self) -> str:
        """生成人类可读的诊断摘要。"""
        lines = [
            f"📊 诊断简报 (trace: {self.trace_id})",
            "─" * 40,
            f"状态: {'✅ 成功' if self.success else '❌ 失败'}",
            f"总耗时: {self.total_duration_ms:.0f}ms",
            f"Token消耗: {self.total_input_tokens + self.total_output_tokens} (输入: {self.total_input_tokens}, 输出: {self.total_output_tokens})",
            f"工具调用: {self.tool_calls}次",
            "",
            "阶段耗时:",
        ]
        
        for s in self.stages:
            status = "✅" if s.success else ("⚠️" if s.degraded else "❌")
            retry_info = f" (重试{s.retries}次)" if s.retries > 0 else ""
            lines.append(f"  {status} {s.name}: {s.duration_ms:.0f}ms{retry_info}")
        
        if self.error:
            lines.extend(["", f"错误: {self.error}"])
        
        return "\n".join(lines)


def build_diagnostic(ctx: PipelineContext, metrics: Optional[PipelineMetrics]) -> SessionDiagnostic:
    """从 PipelineContext 和 PipelineMetrics 构建诊断简报。
    
    Args:
        ctx: Pipeline 上下文
        metrics: Pipeline 执行指标
        
    Returns:
        SessionDiagnostic: 诊断简报
    """
    if metrics is None:
        return SessionDiagnostic(
            trace_id=ctx.trace_id or "unknown",
            total_duration_ms=0,
            success=False,
            stage_count=0,
            error="No metrics available",
        )
    
    stages = [
        StageDiagnostic(
            name=s.stage_name,
            duration_ms=s.duration_ms,
            success=s.success,
            error=s.error,
            retries=s.retries,
            degraded=s.degraded,
        )
        for s in metrics.stages
    ]
    
    return SessionDiagnostic(
        trace_id=metrics.trace_id,
        total_duration_ms=metrics.total_duration_ms,
        success=metrics.success,
        stage_count=len(metrics.stages),
        stages=stages,
        failed_stage=metrics.failed_stage,
        total_input_tokens=ctx.total_input_tokens,
        total_output_tokens=ctx.total_output_tokens,
        tool_calls=ctx.tool_calls,
        error=metrics.error,
    )
