# DeltaConverge

DeltaConverge 已收敛为一套 **Kernel-First** 的代码审查工作台：

- Python 内核：`kernel/`
- Web 适配层：`adapters/web`
- React 工作台：`frontend/react`
- 最小可用 CLI：`deltaconverge review|qa|sessions`

当前主线只支持 **开发态 Web**。旧版原生脚本 UI、Docker/EXE 打包链路和早期示例已经移入 [legacy/README.md](legacy/README.md)。

## Quick Start

### 环境要求

- Python 3.11+
- Node.js 18+
- Git 2.20+

### 安装

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

### 配置模型密钥

在项目根目录创建 `.env`，至少配置一个可用模型：

```bash
GLM_API_KEY=your-key
OPENROUTER_API_KEY=your-key
```

更多可选项见 `.env.example`。

### 启动 Web 工作台

```bash
python run_ui.py
```

默认地址为 `http://127.0.0.1:54321`。  
`run_ui.py` 会检测前端构建产物；如果不存在，会尝试自动执行 `npm install` 与 `npm run build`。

## CLI

安装为可编辑包后，可直接使用：

```bash
deltaconverge review --project-root Z:\\repo --prompt "请审查当前改动"
deltaconverge sessions --limit 20
deltaconverge qa run_xxx "这个问题为什么严重？"
```

## Architecture

### Kernel

- `KernelFacade` 是唯一稳定入口。
- 会话存储为 `SQLite + artifacts`，路径固定在 `kernel/data/kernel/`。
- Web 和 CLI 都只能通过内核调用，不再直接依赖旧 UI/路由实现。

### Web

- API 只保留 `/api/v2`。
- 资源分组固定为 `sessions / reviews / scans / projects / config`。
- SSE 事件类型固定为：
  - `review.started`
  - `stage.started`
  - `stage.finished`
  - `review.delta`
  - `tool.started`
  - `tool.finished`
  - `scan.started`
  - `scan.progress`
  - `scan.finished`
  - `review.completed`
  - `review.failed`

### Frontend

- React + TypeScript + Vite
- React Query 管理服务端数据
- Zustand 管理界面状态与当前工作区

## Data Policy

- 历史 `Agent/data/sessions/*.json` 会话保留为冷数据，不会迁移到新存储。
- 新系统只读取 `kernel/data/kernel/` 下的数据。
- 旧版前端与旧 `/api/*` 不再兼容。

## Supported Entry Points

- `python run_ui.py`
- `deltaconverge review`
- `deltaconverge qa`
- `deltaconverge sessions`

除以上入口外，仓库中的其他旧脚本、旧 UI 和旧分发文件都不属于当前支持范围。
