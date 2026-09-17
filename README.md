# DeltaConverge

DeltaConverge 是一套 **Kernel-First** 的本地代码审查工作台：

- Python 内核：`kernel/`
- Web 适配层：`adapters/web`（仅 `/api/v2`）
- React 工作台：`frontend/react`（构建产物已入库）
- 命令行：`deltaconverge review|qa|sessions`

对外契约（HTTP + SSE）已冻结，见 [etc/核心文档/对外契约.md](etc/核心文档/对外契约.md)。
旧版原生脚本 UI、EXE 打包链路与早期示例已移入 [legacy/](legacy/)。

## Quick Start

### 方式一：Docker（推荐，无需安装 Python / Node）

```bash
docker run -d --name deltaconverge -p 54321:54321 \
  -v /你的代码仓库:/projects \
  -v $PWD/.env:/app/.env:ro \
  deltaconverge:latest
```

浏览器打开 `http://127.0.0.1:54321`。

自行构建镜像：

```bash
# 精简版：含 semgrep / pylint 等 Python 扫描器（约 1.3GB）
docker build -t deltaconverge:latest .

# 完整版：额外包含 eslint / tsc / checkstyle / pmd / go / rubocop（镜像显著变大）
docker build --build-arg WITH_EXTRA_SCANNERS=1 -t deltaconverge:full .
```

或用 compose：

```bash
docker compose up -d
```

### 方式二：本地运行

**环境要求**

- Python 3.11+
- Git 2.20+
- Node.js 18+ —— **仅在前端源码有改动、需要重新构建时才需要**

**安装**

```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
pip install -e .
```

**配置模型密钥**

在项目根目录创建 `.env`，至少配置一个可用模型：

```bash
GLM_API_KEY=your-key
OPENROUTER_API_KEY=your-key
```

更多可选项见 `.env.example`。

**启动**

```bash
python run_ui.py
```

默认地址 `http://127.0.0.1:54321`。前端构建产物（`frontend/react/dist`）已随仓库分发，
**无需安装 Node 即可启动**；只有当 `dist` 缺失或改动前端源码时，`run_ui.py` 才会尝试
`npm install && npm run build`。手动重建前端：

```bash
cd frontend/react && npm install && npm run build
```

## CLI

```bash
deltaconverge review --project-root Z:\\repo --prompt "请审查当前改动"
deltaconverge qa run_xxx "这个问题为什么严重？"
deltaconverge sessions --limit 20
deltaconverge config_doctor
```

CLI 与 Web 走同一个 `KernelFacade`，不是第二套业务实现。

## Architecture

### Kernel

- `KernelFacade` 是唯一稳定入口；组合根在 `kernel/bootstrap.py`。
- 分层：`kernel/{domain,ports,application,infrastructure}`，采用依赖倒置。
- `kernel/application` 与 `kernel/domain` **不得**直接依赖旧 `Agent/` 代码；
  旧实现一律通过 `kernel/infrastructure` 的 Legacy 适配器桥接（由 CI 强制守卫）。
- 会话存储为 SQLite + artifacts，落在 `data/kernel/`。

### Web

- 仅暴露 `/api/v2`；资源分组：`sessions / reviews / diff / projects / scans / config / rule-growth / system / dashboard`。
- 事件通过 SSE 推送（`/api/v2/reviews/{run_id}/stream`），按 `seq` 顺序消费。

### Frontend

- React + TypeScript + Vite，React Query 管理服务端数据，Zustand 管理界面状态。
- 样式位于 `frontend/react/src/styles/`，不依赖 `legacy/`。

## Data Policy

- 历史 `Agent/data/sessions/*.json` 为冷数据，不做迁移。
- 新内核只读 `data/kernel/`（SQLite 与 artifacts）。
- 旧版前端与旧 `/api/*` 不再兼容。

## Development

```bash
pip install -r requirements-dev.txt

python -m pytest tests/ -q            # 运行测试
python -m pyflakes kernel/ adapters/  # 静态检查（CI 要求零告警）
```

CI（`.github/workflows/ci.yml`）在 Python 3.11 与 3.12 上执行静态检查、内核独立性守卫与测试。

## License

[MIT](LICENSE)

## 友链

[Linux.do](https://linux.do/)
