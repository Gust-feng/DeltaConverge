---
layout: default
title: DeltaConverge
---

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

`DeltaConverge` 是一套**多 Agent 协同驱动**的智能代码审查系统，构建了从语义理解到决策执行的完整闭环。

### 核心架构

- **业务语义引擎** - 分析 Agent 深度解析项目文档、README、提交历史与代码结构，构建项目的**业务语义图谱**
- **混合决策架构** - 采用**规则层 + LLM 层双轨决策机制**
- **智能上下文编排** - 规划 Agent 根据变更复杂度、代码关联度与影响范围，动态决定每个审查单元需要多少上下文
- **多 Agent 流水线** - 分析 Agent → 规划 Agent → 审查 Agent 构成**串行协作链路**
- **双链路并行架构** - 静态扫描器作为**旁路链路**与 Agent 主链路并行执行
- **自我学习机制** - 系统持续追踪规则层与 LLM 层的决策分歧，进行模式挖掘

## 快速开始

### 环境要求
- Python 3.12+
- Git 2.20+

### 安装

详细安装说明请查看 [主仓库 README](https://github.com/Gust-feng/DeltaConverge)

## 资源链接

- [GitHub 仓库](https://github.com/Gust-feng/DeltaConverge)
- [性能基准测试](https://delta-converge.vercel.app/)
