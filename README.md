# 🥳 欢迎使用 DeltaConverge

每一次新功能、新优化的诞生都始于一次**背离**，代码的价值不在于孤立存在，而在于回归与融合。当分支发起 Pull Request，它必须经过审核，与主支的代码、团队的规范、产品的愿景 **Converge**（汇聚合一）。

DeltaConverge，捕获 PR 中每一个细微的 Delta，以清晰的分析引导它完成 Converge 的使命。

> *差异在此汇聚，代码因此完整*


## 总体性能表现 (Overall Performance)

在基准测试中，DeltaConverge 与其他主流代码审查工具的性能对比如下：

| 工具 | 性能得分 |
|:---:|:---:|
| **Greptile** | 82% |
| **DeltaConverge** | 74% |
| Cursor | 58% |
| Copilot | 52% |
| CodeRabbit | 44% |
| Graphite | 6% |

> 详细的基准测试报告请查看 [benchmark-results](https://delta-converge.vercel.app/)	

## 系统架构

代码审查不应只是冰冷的规则匹配，也不应是 LLM 的泛泛而谈。它需要**理解**——理解这个项目是什么，理解这次变更要做什么，然后给出**真正贴合业务场景**的审查建议。

`DeltaConverge` 是一套**多 Agent 协同驱动**的智能代码审查系统，构建了从语义理解到决策执行的完整闭环：

### 核心架构

- **业务语义引擎** 
  分析 Agent 深度解析项目文档、README、提交历史与代码结构，构建项目的**业务语义图谱**。不只是提取关键词，而是将业务上下文注入审查链路，让审查从"就代码论代码"变成"结合业务场景分析"。
  
  系统会分析项目的技术栈、架构模式、开发规范等信息，并结合 Git 提交历史理解项目演进方向。这份语义分析报告会传递给后续所有 Agent，确保审查建议始终与项目意图保持一致。用户也可以手动编辑这份报告，系统将尊重修正的结果并作为审查基础。

- **混合决策架构**
  采用**规则层 + LLM 层双轨决策机制**。规则层基于模式匹配进行快速判断，LLM 层处理复杂的语义推理，通过**置信度加权融合**实现两者协同，既保证效率又兼顾深度。
  
  规则层会为每个变更计算置信度分数，高置信度时（如纯文档修改、注释变更）规则层决策优先，低置信度时（如复杂的业务逻辑变更）LLM 决策优先，中等置信度时取上下文级别更高者。这种设计避免了单纯依赖规则的僵化，也避免了完全依赖 LLM 的不可控性和成本问题。

- **智能上下文编排**
  规划 Agent 根据变更复杂度、代码关联度与影响范围，动态决定每个审查单元需要多少上下文（差异级 / 函数级 / 文件级），在**审查精度**与**Token 消耗**之间找到最优平衡点。
  
  不同于简单地将整个文件或 Diff 丢给 LLM，系统会分析每个变更的实际需求：函数签名变更可能需要调用方信息，逻辑变更可能需要完整函数体，新增函数可能需要相关依赖。上下文以结构化 JSON 格式组织，配合 Markdown 说明，将LLM 更多注意力放在代码变更，提高审查准确性。

- **多 Agent 流水线**
  分析 Agent → 规划 Agent → 审查 Agent 构成**串行协作链路**。变更感知基于 Git Diff 自动完成，审查过程通过 SSE 实时推送，思考链路、工具调用全程透明可见。
  
  每个 Agent 专注于自己的职责：分析 Agent 负责项目理解，规划 Agent 负责上下文调度，审查 Agent 负责代码审查。Agent 之间通过标准化数据格式传递信息，前置 Agent 的输出是后续 Agent 的输入，形成清晰的数据流。整个过程支持流式输出，用户可以实时看到每个 Agent 的工作进展和思考过程。

- **双链路并行架构**
  静态扫描器作为**旁路链路**与 Agent 主链路并行执行，互不阻塞。扫描器为 LLM 提供静态分析结果作为参考，结合传统规则检测与语义分析各自的优势。
  
  主链路处理业务语义审查时，旁路同步运行 Bandit、Ruff、ESLint 等静态扫描工具。扫描器结果通过工具接口暴露给审查 Agent，Agent 可以主动调用或在最终报告中整合扫描结果。这种设计避免了扫描耗时阻塞主流程，同时保留了静态分析的确定性优势。

- **自我学习机制**
  系统持续追踪规则层与 LLM 层的决策分歧，进行模式挖掘。当某类冲突达到统计阈值时，自动生成候选规则并纳入规则库，实现规则的**持续优化**与**能力增长**。
  
  每次审查都会记录规则层和 LLM 层的决策差异：规则认为需要审查但 LLM 跳过、规则跳过但 LLM 认为重要、上下文级别判断不一致等。系统会分析这些冲突的模式，提取可复用的规则特征。用户可以在前端查看所有冲突记录，手动批准或拒绝系统生成的候选规则，也可以根据阈值让系统自动应用。

### 适用范围

**支持的编程语言**

系统基于 AST 解析与规则匹配，当前支持以下主流语言的代码审查：
- **Python** - 配套 Pylint、Flake8、Mypy、Bandit、Ruff 等扫描器
- **Java** - 支持 Checkstyle、SpotBugs 等工具
- **Go** - 支持 golangci-lint、staticcheck 等工具
- **TypeScript/JavaScript** - 支持 ESLint、TSLint 等工具
- **Ruby** - 支持 RuboCop 等工具

得益于 LLM 的语言理解能力,系统对任何语言的代码都能提供**基于语义的审查建议**,但规则层面的自动化判断与静态扫描器集成需要针对特定语言适配。

**LLM 模型兼容性**

系统采用统一的 LLM 适配层,兼容 OpenAI API 格式的所有模型提供商，后续可便捷添加相关服务商：
- **Deepseek**
- **智谱 AI**
- **OpenRouter** 
- **MiniMax**
- **Moonshot**
- **魔搭**
- **百炼平台**
- **硅基流动**
- 其他兼容 OpenAI API 格式的模型服务

> 用户可在前端仪表盘中配置多个模型

## 快速开始

### 环境要求
- Python 3.12+
- Git 2.20+

### 方式一：本地运行（推荐）

本地运行通常拥有更好的性能与更低的 IO 开销（尤其在大仓库 Diff/文件扫描场景下）。

### 安装

```bash
# 克隆项目
git clone https://github.com/Gust-feng/DeltaConverge.git
cd DeltaConverge

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/macOS

# 安装依赖
pip install -r requirements.txt
```

### 配置API密钥

1. 在项目根目录创建 `.env` 文件，配置你使用的模型密钥：

```bash
# 任选一个或多个配置即可
GLM_API_KEY=你的智谱API密钥
OPENROUTER_API_KEY=你的OpenRouter密钥
# 更多模型配置见 .env.example
```

2. 或者启动服务后，在前端 Web 界面中配置模型与密钥。

### 运行

**Web界面（推荐）**

```bash
python run_ui.py
```

**命令行**

```bash
python Agent/examples/run_agent.py --prompt "请审查本次改动" --auto-approve
#暂未进行参数优化
```

### 方式二：Docker

镜像地址：`gustfeng/deltaconverge` | [Docker Hub](https://hub.docker.com/r/gustfeng/deltaconverge)

```bash
docker run -d -p 54321:54321 -v /your/projects:/projects gustfeng/deltaconverge:2.81
```

> 将 `/your/projects` 替换为你的代码仓库目录，访问 `http://localhost:54321`，API密钥可在 Web 界面中配置。

### 方式三：Windows 可执行程序

无需安装 Python 环境，下载后即可运行。

**下载地址**: [GitHub Releases](https://github.com/Gust-feng/DeltaConverge/releases/tag/V2.9.3)

**使用方法**:
1. 下载并解压 `DeltaConverge-Windows.zip`
2. 运行 `启动DeltaConverge.bat`
3. 浏览器访问 `http://127.0.0.1:54321`

> 注意：请保持 `DeltaConverge.exe` 与 `_internal` 文件夹在同一目录下，否则程序无法运行。

## 📁 项目结构

```
├── Agent/          # 核心审查引擎
│   ├── agents/     # Agent实现（分析、规划、审查）
│   ├── core/       # 核心模块（API、LLM适配、上下文）
│   └── DIFF/       # Diff解析与规则匹配
├── UI/             # Web前端
└── etc/            # 文档与配置
```

## 📖 了解更多

- [欢迎使用](etc/欢迎使用.md) - 开发历程与设计思路
- [核心文档](etc/核心文档) - 系统架构详解
- [技术详解](etc/技术详解) - 实现细节

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

*DeltaConverge - 让每一次代码汇聚都更有价值*
