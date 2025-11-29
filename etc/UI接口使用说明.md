# UI 接口使用说明（让前端少碰内核）

- 入口模块：`Agent/core/api/api.py` (Python 包路径: `Agent.core.api`)
- 适用场景：GUI/CLI/Web 直接调用，不关心 LLM 客户端、工具注册等细节。

## 可用模型
```python
from Agent.core.api import available_llm_options
opts = available_llm_options()  # [{"name":"auto"}, {"name":"glm", "available":True}, ...]
# UI 只用 opts[i]["name"] 填充选择项，必要时展示 opts[i]["reason"]
```

## 可用工具
```python
from Agent.core.api import available_tools
tools = available_tools()  # [{"name":"read_file_hunk", "default": True, "description": "..."}]
# 默认勾选用 tool["default"]
```

## 运行审查（同步）
```python
from Agent.core.api import run_review_sync

result = run_review_sync(
    prompt="请审查改动",
    llm_preference="auto",       # 审查 Agent 模型
    planner_llm_preference=None, # 规划 Agent 模型，不填则与 llm_preference 相同
    tool_names=["read_file_hunk","search_in_project"],
    auto_approve=True,           # True 则所有工具直接执行
    project_root="/path/to/repo",
    stream_callback=my_stream_handler,   # 可选
    tool_approver=my_tool_approver,      # 可选
)
```

## 运行审查（异步）
```python
from Agent.core.api import run_review_async_entry

result = await run_review_async_entry(...同上...)
```

## 流式事件协议（stream_callback 收到的 evt）
- `type="delta"`：增量文本
  - `content_delta`: 正文增量
  - `reasoning_delta`: 思考增量（有则优先展示）
- `type="planner_delta"`：规划阶段增量（同上，带 reasoning/content）
- `type="tool_call_start"/"tool_call_end"/"tool_result"`：工具生命周期与结果
- `type="bundle_item"`：上下文包条目预览
- `type="pipeline_stage_start"/"pipeline_stage_end"`：阶段状态
- `type="usage_summary"`：用量聚合
- `type="warning"`：回退/告警信息
- `type="done"`：最终结果（`result` 字段）
- `type="error"`：错误信息

## 工具审批（tool_approver）
```python
def my_tool_approver(calls):
    # calls: List[{"name":..., "arguments":...}]
    return calls  # 允许全部；可自定义弹窗筛选
```

## 说明
- GUI 现在只需依赖本文件暴露的接口，后续内核调整不会影响 UI 代码。
- 如果要扩展事件类型，请在 UI 与接口文档同步更新。***
