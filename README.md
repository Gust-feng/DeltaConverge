# Agent 代码审查内核

基于 LLM 的自动化代码审查框架：感知 Git diff、规划所需上下文、按需调用工具取数，并流式产出审查意见。支持多家模型客户端与简单的 CLI/GUI 示例，便于集成到本地或自建前端。

## 功能特性
- **Diff 感知**：自动检测工作区/暂存区/PR（`auto` 模式）并构建 `review_index`，包含文件、行数、标签和规则建议等元数据（`Agent/DIFF`）。
- **规划链路**：`IntentAgent` 提取项目概览，`PlanningAgent` 基于索引输出上下文计划，`fusion.py` 融合规则与计划，`context_scheduler.py` 拉取 diff/函数/文件上下文、调用方和历史版本组成 ContextBundle。
- **审查 Agent**：`CodeReviewAgent` 按计划上下文驱动审查，支持多工具并发执行、审批/白名单、流式输出与 tokens 统计。
- **工具链**：内置安全工具默认开启（文件列表、代码片段、文件信息、项目搜索、依赖扫描），可按需扩展注册；支持 `tool_approver` 审批。
- **LLM 适配与回退**：`LLMFactory` 统一创建 GLM / Bailian / ModelScope / Moonshot / OpenRouter / Mock 客户端；缺失密钥时自动降级为可用模型或 Mock。
- **流式事件与日志**：`stream_callback` 能收到阶段事件、LLM 增量、工具执行与用量汇总；流水线日志输出到 `log/pipeline` 便于追踪。

## 目录速览
- `Agent/DIFF`：diff 收集与审查单元构建（`diff_collector.py`、`git_operations.py`、`review_units.py`、`output_formatting.py`）。
- `Agent/agents`：核心 Agent（`PlanningAgent`、`CodeReviewAgent`、`IntentAgent`）、上下文融合与调度。
- `Agent/core`：API 门面、LLM 适配、上下文提供、流水线事件、日志与工具运行时。
- `Agent/tool`：工具注册中心与内置工具定义。
- `Agent/examples`：命令行示例 `run_agent.py`、Tk GUI `gui.py`、接口说明文档。
- `UI`：基于 FastAPI 的前端联调 mock 服务（流式假数据，便于前端自测）。
- `tests`：基础单元测试示例。

## 环境准备
1) Python 3.10+，已安装 Git；建议安装 `rg`（ripgrep）以支持调用方搜索。  
2) 安装依赖（建议使用虚拟环境）：
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\\Scripts\\activate
   pip install -r requirements.txt
   ```
3) 可选 `.env` / 环境变量：  
   - `GLM_API_KEY` / `GLM_MODEL`  
   - `BAILIAN_API_KEY` / `BAILIAN_MODEL` / `BAILIAN_BASE_URL`  
   - `MODELSCOPE_API_KEY` / `MODELSCOPE_MODEL`  
   - `MOONSHOT_API_KEY` / `MOONSHOT_MODEL`  
   - `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` / `OPENROUTER_BASE_URL`  
   - 其他：`LLM_HTTP_TIMEOUT`、`LLM_CALL_TIMEOUT`、`PLANNER_TIMEOUT_SECONDS` 等可调超时。  
   未配置密钥时会自动回退到 Mock 模型，便于离线联调。

## 快速开始
### 1) 通过 API 调用审查
```python
from Agent.core.api import run_review_sync
from Agent.tool.registry import default_tool_names
from Agent.agents import DEFAULT_USER_PROMPT

result = run_review_sync(
    prompt=DEFAULT_USER_PROMPT,
    llm_preference="auto",           # 也可指定 glm/bailian/modelscope/moonshot/openrouter/mock
    planner_llm_preference=None,     # 可选：单独指定规划模型
    tool_names=default_tool_names(), # 默认内置安全工具
    auto_approve=True,               # True: 所有工具自动执行；False: 仅内置白名单自动执行
)
print(result)
```
- 异步版本：`run_review_async`（`Agent/core/api/api.py`）。  
- 查询可用模型/工具：`available_llm_options()`、`available_tools()`。
- 运行前确保当前工作目录是 Git 仓库且存在 diff（工作区、暂存区或 PR）。

### 2) 命令行示例
```bash
python Agent/examples/run_agent.py --prompt "请审查本次改动"
```
打印规划 JSON、融合结果与上下文包，再执行审查。非默认白名单的工具需要在命令行交互确认。

### 3) 简易 GUI
```bash
python Agent/examples/gui.py
```
基于 Tk + ttkbootstrap，适合本地手动测试（读取 `.env`，支持流式展示）。

### 4) 前端联调 Mock（可选）
```bash
uvicorn UI.server:app --reload
```
提供模型/工具选项与模拟流式审查输出，仅用于前端开发演示，未接入真实审查链路。

## 工具链（内置默认启用）
- `list_project_files`：按目录列出 Git 中的文件（含 `.gitignore` 内容）。
- `read_file_hunk`：读取文件片段，附带行号与上下文。
- `read_file_info`：文件大小、行数、推测语言。
- `search_in_project`：基于 `git grep` 的关键字搜索。
- `get_dependencies`：扫描常见依赖文件（如 `requirements.txt`、`package.json`）。  
调试工具 `echo_tool` 默认不启用，需显式暴露。

## 流式事件与日志
- `stream_callback` 可收到：  
  - `pipeline_stage_start/pipeline_stage_end`、`bundle_item`（上下文构建阶段）。  
  - `intent_delta`、`planner_delta`（意图/规划增量）。  
  - `delta`（LLM 正文/推理增量）、`usage_summary`（单次与会话累计 tokens）。  
  - `tool_call_start` / `tool_result` / `tool_call_end`（工具执行过程）。  
  - 异常/回退告警会以 `error`/`warning` 类型上报。  
- 日志：流水线日志默认写入 `log/pipeline`，API 调用日志写入 `log/api`；`fallback_tracker` 会总结读取/外部调用的降级情况。

## 运行测试
```bash
pytest
```
当前测试用例主要覆盖 diff 处理与规则解析，部分场景会因缺少真实 Git 环境被跳过。

## 注意
- 需要在 Git 仓库内运行，且当前分支存在可检测的变更；`auto` 模式优先检测暂存区，其次工作区，再尝试基于远端基线的 PR diff。  
- ripgrep（`rg`）可提升调用方搜索与工具性能；缺失时相关能力会自动降级。  
- GUI 依赖本地 `tkinter`，若系统未安装请先补齐。***
