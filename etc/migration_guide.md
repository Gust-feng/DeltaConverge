# 内核迁移指南

## 概述

本文档指导如何从旧内核（`Agent/core/review_kernel.py`）迁移到新内核架构（`kernel/`）。

新内核提供以下改进：

- **分层架构**：清晰的领域模型、应用服务、基础设施分离
- **错误恢复**：Stage 级别的降级、重试机制
- **可观测性**：完整的追踪、诊断和审计能力
- **可配置性**：统一的配置中心，支持热更新

## 迁移步骤

### 1. 启用新内核

新内核没有开关配置，直接通过 bootstrap 入口获取门面即可：

```python
from kernel.bootstrap import get_kernel_facade

facade = get_kernel_facade()
```

> 历史说明：`kernel_config.json` 曾有一段 `kernel_switch`
> （`use_new_kernel` / `fallback_on_error` / `enable_comparison`），
> 但这三个字段在代码中从未被读取，已在内核收口阶段删除。
> 不要再依赖它们来切换内核。

### 2. 验证基础功能

运行以下测试确保新内核正常工作：

```bash
# 运行内核测试套件
pytest tests/test_stage_contract.py
pytest tests/test_planner_stage_contract.py
pytest tests/test_fusion_review_stage_contract.py
```

### 3. 配置调整

新内核的配置项统一在 `kernel_config.json` 中管理：

| 旧配置位置 | 新配置路径 |
|-----------|-----------|
| 硬编码常量 | `context.merge_gap`, `context.function_window` |
| 环境变量 | `llm.call_timeout`, `llm.max_retries` |
| 分散配置 | `review.*` |

### 4. API 适配

#### 旧 API

```python
from Agent.core.review_kernel import ReviewKernel, run_review

kernel = ReviewKernel(...)
result = await kernel.execute(diff_ctx, prompt, ...)
```

#### 新 API

```python
from kernel.bootstrap import get_kernel
from kernel.domain.models import ReviewCreateRequest

kernel = get_kernel()
request = ReviewCreateRequest(
    prompt=prompt,
    project_root=project_root,
    base_ref=base_ref,
)
run = await kernel.create_review(session, request)
# 结果通过事件流获取
```

### 5. 事件监听

新内核使用事件驱动架构，所有阶段状态通过事件通知：

```python
async for event in kernel.event_bus.subscribe(run_id):
    if event.type == "review.completed":
        report = event.payload["content"]
    elif event.type == "pipeline.failed":
        error = event.payload["error"]
```

## 架构对比

### 旧架构

```
ReviewKernel (单文件 1072 行)
├── collect_diff_context()
├── intent_analysis()
├── plan_review()
├── fuse_and_schedule()
└── execute_review()
```

### 新架构

```
kernel/
├── domain/          # 领域模型
│   ├── context.py   # PipelineContext
│   ├── models.py    # ReviewRun, Session
│   └── protocols.py # Stage, EventEmitter
├── application/     # 应用服务
│   ├── stages/      # 6 个独立 Stage
│   ├── pipeline_executor.py
│   └── review_orchestrator.py
├── infrastructure/  # 基础设施
│   └── stores/      # 持久化实现
├── ports/           # 端口定义
│   └── stores.py    # 存储协议
└── bootstrap.py     # 启动入口
```

## 常见问题

### Q: 如何回退到旧内核？

没有配置开关。旧内核入口 `Agent.core.review_kernel` 仍然存在（已标记
`DeprecationWarning`），需要回退时直接调用旧入口即可；新内核不会自动回退。

### Q: 如何查看诊断信息？

每次审查结束后，可通过以下方式获取诊断：

```python
from kernel.application.diagnostics import build_diagnostic

diagnostic = build_diagnostic(ctx, pipeline.metrics)
print(diagnostic.to_summary_text())
```

### Q: 工具调用如何追踪？

```python
from kernel.application.tool_audit import get_audit_log

log = get_audit_log(trace_id)
print(log.get_summary())
print(log.export_for_replay())  # 导出完整日志
```

### Q: 如何自定义 Stage 错误处理？

在 Stage 实现中定义 `error_mode` 和 `on_error`：

```python
from kernel.domain.protocols import Stage, StageErrorMode

class MyStage:
    @property
    def error_mode(self) -> StageErrorMode:
        return StageErrorMode.DEGRADE  # 降级继续
    
    @property
    def max_retries(self) -> int:
        return 2
    
    async def on_error(self, ctx, error, emit) -> bool:
        # 自定义错误处理
        emit.stage_finished(self.name, degraded=True)
        return True  # 返回 True 表示已处理
```

## 版本计划

- **v3.0**: 新内核稳定版，支持双内核切换
- **v3.1**: 旧内核标记废弃，新内核为默认
- **v4.0**: 移除旧内核代码

## 反馈与支持

如遇问题，请：

1. 检查 `log/` 目录下的日志
2. 使用诊断工具导出 trace 信息
3. 提交 issue 并附上 trace_id
