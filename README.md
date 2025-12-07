# Agent 代码审查内核

基于 LLM 的自动化代码审查框架：感知 Git diff、规划所需上下文、按需调用工具取数，并流式产出审查意见。支持多家模型客户端与简单的 CLI/GUI 示例，便于集成到本地或自建前端。

## 功能特性

- **Diff 感知**：自动检测工作区/暂存区/PR（`auto` 模式）并构建 `review_index`，包含文件、行数、标签和规则建议等元数据。
- **智能规划**：
  - `IntentAgent` 提取项目概览与核心意图
  - `PlanningAgent` 基于索引输出上下文计划
  - `fusion.py` 融合规则与计划
  - `context_scheduler.py` 拉取 diff/函数/文件上下文、调用方和历史版本组成 ContextBundle
- **审查 Agent**：`CodeReviewAgent` 按计划上下文驱动审查，支持多工具并发执行、审批/白名单、流式输出与 tokens 统计。
- **工具链**：内置安全工具默认开启，可按需扩展注册；支持 `tool_approver` 审批机制。
- **LLM 适配与回退**：`LLMFactory` 统一创建多种模型客户端；缺失密钥时自动降级为可用模型或 Mock。
- **流式事件与日志**：支持阶段事件、LLM 增量、工具执行与用量汇总的流式回调；流水线日志便于追踪。
- **安全机制**：内置工具权限控制，支持工具调用审批，默认只启用安全工具。

## 目录结构

```
├── Agent/              # 核心代码审查引擎
│   ├── DIFF/           # Diff 收集与审查单元构建
│   ├── agents/         # 核心 Agent 实现
│   ├── core/           # API 门面、LLM 适配、上下文提供
│   ├── tool/           # 工具注册中心与内置工具定义
│   ├── examples/       # CLI/GUI 示例
│   ├── config/         # 配置文件
│   ├── domain/         # 领域模型
│   └── LLM/            # LLM 客户端适配
├── UI/                 # 基于 FastAPI 的前端联调 mock 服务
│   ├── static/         # 静态资源
│   ├── data/           # 测试数据
│   ├── log/            # UI 日志
│   ├── server.py       # FastAPI 服务入口
│   └── dialogs.py      # 对话框配置
├── tests/              # 测试用例
├── data/               # 数据目录
├── etc/                # 其他配置文件
├── log/                # 日志目录
├── scripts/            # 辅助脚本
├── requirements.txt    # 依赖清单
├── run_ui.py           # UI 启动脚本
├── docker-compose.yml  # Docker 配置
├── Dockerfile          # Docker 镜像构建
├── BUILD.md            # 构建文档
├── 1.srt               # 示例字幕文件
└── .env.example        # 环境变量示例
```

## 环境准备

### 系统要求
- Python 3.10+
- Git 2.20+
- 建议安装 `rg`（ripgrep）以支持调用方搜索

### 安装依赖

```bash
# 创建虚拟环境（推荐）
python -m venv venv

# 激活虚拟环境
# Linux/macOS
source venv/bin/activate
# Windows
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 配置环境变量

创建 `.env` 文件，根据需要配置以下环境变量：

```bash
# LLM 服务配置
GLM_API_KEY=your_glm_api_key
GLM_MODEL=glm-4

BAILIAN_API_KEY=your_bailian_api_key
BAILIAN_MODEL=eb-turbo-128k
BAILIAN_BASE_URL=https://bailian.aliyun.com

MODELSCOPE_API_KEY=your_modelscope_api_key
MODELSCOPE_MODEL=qwen-max

MOONSHOT_API_KEY=your_moonshot_api_key
MOONSHOT_MODEL=moonshot-v1-8k

OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=gpt-4
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# 超时配置
LLM_HTTP_TIMEOUT=30
LLM_CALL_TIMEOUT=600
PLANNER_TIMEOUT_SECONDS=300

# 日志配置
LOG_LEVEL=INFO
```

未配置密钥时会自动回退到 Mock 模型，便于离线联调。

## 快速开始

### 1. API 调用审查

```python
from Agent.core.api import run_review_sync
from Agent.tool.registry import default_tool_names
from Agent.agents import DEFAULT_USER_PROMPT

# 同步调用
result = run_review_sync(
    prompt=DEFAULT_USER_PROMPT,
    llm_preference="auto",           # 自动选择可用模型
    planner_llm_preference=None,     # 可选：单独指定规划模型
    tool_names=default_tool_names(), # 默认内置安全工具
    auto_approve=True,               # True: 所有工具自动执行
)
print(result)

# 异步调用
import asyncio
from Agent.core.api import run_review_async

async def main():
    result = await run_review_async(
        prompt=DEFAULT_USER_PROMPT,
        llm_preference="glm",
        auto_approve=True,
    )
    print(result)

asyncio.run(main())
```

### 2. 命令行示例

```bash
# 基本用法
python Agent/examples/run_agent.py --prompt "请审查本次改动"

# 指定模型
python Agent/examples/run_agent.py --prompt "请审查本次改动" --llm glm

# 自动审批所有工具调用
python Agent/examples/run_agent.py --prompt "请审查本次改动" --auto-approve
```

### 3. 简易 GUI

```bash
python Agent/examples/gui.py
```

基于 Tk + ttkbootstrap，适合本地手动测试（读取 `.env`，支持流式展示）。

### 4. 前端联调 Mock

```bash
# 方法一：直接运行 UI 服务
uvicorn UI.server:app --reload

# 方法二：使用启动脚本
python run_ui.py
```

提供模型/工具选项与模拟流式审查输出，仅用于前端开发演示，未接入真实审查链路。

访问地址：http://localhost:8000

## 工具链

### 内置默认工具

| 工具名称 | 描述 |
|---------|------|
| `list_project_files` | 按目录列出 Git 中的文件（含 `.gitignore` 内容） |
| `list_directory` | 列出指定目录下的文件和子目录（单层，非递归） |
| `read_file_hunk` | 读取文件片段，附带行号与上下文 |
| `read_file_info` | 获取文件大小、行数、推测语言等信息 |
| `search_in_project` | 基于 `git grep` 的关键字搜索 |
| `get_dependencies` | 扫描常见依赖文件（如 `requirements.txt`、`package.json`） |

### 工具审批机制

- **白名单工具**：默认安全工具无需审批
- **非白名单工具**：需要显式审批才能执行
- **auto_approve**：设置为 True 时跳过所有审批

### 扩展工具

可以通过注册机制扩展自定义工具：

```python
from Agent.tool.registry import register_tool
from Agent.tool.registry import ToolSpec

# 定义工具函数
def my_custom_tool(args: dict) -> str:
    """自定义工具描述"""
    param1 = args.get("param1", "")
    param2 = args.get("param2", 0)
    return f"Custom tool result: {param1} {param2}"

# 注册工具
register_tool(
    ToolSpec(
        name="my_custom_tool",
        description="自定义工具描述",
        parameters={
            "type": "object",
            "properties": {
                "param1": {"type": "string", "description": "参数1"},
                "param2": {"type": "integer", "description": "参数2"}
            },
            "required": ["param1", "param2"]
        },
        func=my_custom_tool
    )
)
```

## 流式事件与日志

### stream_callback 事件类型

| 事件类型 | 描述 |
|---------|------|
| `pipeline_stage_start` | 流水线阶段开始 |
| `pipeline_stage_end` | 流水线阶段结束 |
| `bundle_item` | 上下文构建阶段的项目 |
| `intent_delta` | 意图提取增量 |
| `planner_delta` | 规划生成增量 |
| `delta` | LLM 正文/推理增量 |
| `usage_summary` | 单次与会话累计 tokens |
| `tool_call_start` | 工具调用开始 |
| `tool_result` | 工具调用结果 |
| `tool_call_end` | 工具调用结束 |
| `error` | 异常告警 |
| `warning` | 警告信息 |

### 日志输出

- 流水线日志：`log/pipeline/`
- API 调用日志：`log/api/`
- 错误日志：`log/error.log`

## 开发与测试

### 运行测试

```bash
# 运行所有测试
pytest

# 运行特定文件的测试
pytest tests/test_diff_processing.py

# 运行特定测试函数
pytest tests/test_diff_processing.py::test_parse_diff
```

### 调试模式

```bash
# 设置 DEBUG 日志级别
export LOG_LEVEL=DEBUG

# 运行时显示详细日志
python Agent/examples/run_agent.py --prompt "请审查本次改动" --verbose
```

### 代码风格检查

```bash
# 使用 flake8 检查代码风格（需单独安装）
pip install flake8
flake8 Agent/

# 使用 pylint 检查代码质量（需单独安装）
pip install pylint
pylint Agent/
```

## 集成与扩展

### 集成到 CI/CD 流程

```yaml
# GitHub Actions 示例
name: Code Review
on: [pull_request]

jobs:
  code-review:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.10'
    - name: Install dependencies
      run: pip install -r requirements.txt
    - name: Run code review
      env:
        GLM_API_KEY: ${{ secrets.GLM_API_KEY }}
      run: python Agent/examples/run_agent.py --prompt "请审查本次 PR 改动" --auto-approve
```

### 自定义 LLM 客户端

```python
from Agent.core.llm.client import BaseLLMClient
from typing import List, Dict, Any, AsyncIterator

class CustomLLMClient(BaseLLMClient):
    """自定义 LLM 客户端示例"""
    
    def __init__(self, model: str, api_key: str, base_url: str):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        # 初始化自定义客户端
    
    async def stream_chat(
        self, 
        messages: List[Dict[str, Any]], 
        **kwargs: Any
    ) -> AsyncIterator[Dict[str, Any]]:
        """实现流式聊天接口"""
        # 实现自定义流式生成逻辑
        # 示例：简单返回固定响应
        yield {
            "delta": {"role": "assistant", "content": "Hello from custom LLM!"},
            "finish_reason": "stop"
        }
    
    async def create_chat_completion(
        self, 
        messages: List[Dict[str, Any]], 
        **kwargs: Any
    ) -> Dict[str, Any]:
        """实现非流式聊天接口"""
        # 实现自定义非流式生成逻辑
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello from custom LLM!"
                    },
                    "finish_reason": "stop"
                }
            ]
        }

# 注册自定义客户端到 LLMFactory
from Agent.core.api.factory import LLMFactory, ProviderConfig

# 方式1：直接修改 PROVIDERS 字典（需要重启服务）
LLMFactory.PROVIDERS["custom"] = ProviderConfig(
    client_class=CustomLLMClient,
    api_key_env="CUSTOM_API_KEY",
    base_url="https://api.custom-llm.com/v1",
    label="Custom LLM"
)

# 方式2：在初始化时注册（推荐）
# 在应用启动时调用此注册方法
```

### 扩展审查规则

可以通过修改配置文件或扩展规则引擎来定制审查规则。

## 安全最佳实践

1. **仅启用必要工具**：默认只启用安全工具，根据需要添加其他工具
2. **使用工具审批**：在生产环境中建议关闭 `auto_approve`，启用工具审批
3. **配置适当的权限**：确保代码审查服务只能访问必要的资源
4. **保护 API 密钥**：使用环境变量或安全的密钥管理服务存储 API 密钥
5. **监控工具调用**：定期审查工具调用日志，检测异常行为
6. **使用 Mock 进行测试**：在开发和测试环境中使用 Mock 模型，避免不必要的 API 调用

## 性能优化

1. **安装 ripgrep**：`rg` 比 `git grep` 更快，能提升调用方搜索性能
2. **合理配置超时**：根据网络环境和模型响应时间调整超时设置
3. **优化上下文大小**：避免过大的上下文导致性能下降
4. **使用异步调用**：在高并发场景下建议使用异步 API
5. **缓存审查结果**：对于频繁审查的代码可以考虑缓存结果

## 故障排除

### 常见问题

1. **无法检测到 Git diff**
   - 确保当前目录是 Git 仓库
   - 确保存在未提交的变更或 PR
   - 尝试使用 `git status` 检查当前状态

2. **模型调用失败**
   - 检查 API 密钥是否正确
   - 检查网络连接
   - 查看日志文件获取详细错误信息

3. **工具调用被拒绝**
   - 检查工具是否在白名单中
   - 检查 `auto_approve` 设置
   - 查看工具调用日志

4. **GUI 无法启动**
   - 确保安装了 `tkinter`
   - 检查 Python 版本是否兼容

### 日志分析

```bash
# 查看最近的流水线日志
tail -n 100 log/pipeline/pipeline.log

# 查看 API 调用日志
tail -n 100 log/api/api.log

# 查看错误日志
tail -n 100 log/error.log
```

## 注意事项

- 需要在 Git 仓库内运行，且当前分支存在可检测的变更
- `auto` 模式优先检测暂存区，其次工作区，再尝试基于远端基线的 PR diff
- ripgrep（`rg`）可提升调用方搜索与工具性能；缺失时相关能力会自动降级
- GUI 依赖本地 `tkinter`，若系统未安装请先补齐
- 未配置密钥时会自动回退到 Mock 模型，便于离线联调
- 生产环境建议使用环境变量管理 API 密钥，避免硬编码

## 许可证

本项目采用 MIT License。

## 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 打开 Pull Request

## 联系方式

如有问题或建议，欢迎通过以下方式联系：

- 提交 Issue
- 发送邮件
- 加入讨论群

---

**Agent 代码审查内核** - 基于 LLM 的自动化代码审查框架

*最后更新：2025-12-07*
