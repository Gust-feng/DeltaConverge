# 目录

1. [系统架构概述](#1-系统架构概述)
2. [核心审查API](#2-核心审查api)
3. [配置管理API](#3-配置管理api)
4. [缓存管理API](#4-缓存管理api)
5. [健康检查API](#5-健康检查api)
6. [LLM工厂API](#6-llm工厂api)
7. [Diff分析API](#7-diff分析api) *(新增)*
8. [工具管理API](#8-工具管理api) *(新增)*
9. [日志访问API](#9-日志访问api) *(新增)*
10. [项目信息API](#10-项目信息api) *(新增)*
11. [会话管理增强API](#11-会话管理增强api) *(新增)*
12. [Web服务端点](#12-web服务端点)
13. [流式事件协议](#13-流式事件协议)
14. [数据模型参考](#14-数据模型参考)
15. [使用示例](#15-使用示例)
16. [错误处理](#16-错误处理)

---

## 1. 系统架构概述

### 1.1 内核设计理念

本系统采用**内核理念**设计，核心原则如下：

- **内核纯粹性**：`ReviewKernel` 仅负责审查流程编排（意图分析→规划→融合→上下文调度→审查执行）
- **API作为控制面**：所有外部交互通过 `Agent.core.api` 模块进行
- **关注点分离**：配置、缓存、健康检查等运维功能独立于核心审查逻辑

### 1.2 API分层结构

```
┌─────────────────────────────────────────────────────────────┐
│                   外部调用层                                  │
│  (GUI / CLI / Web Server / 第三方集成)                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   API 门面层                                  │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐      │
│  │   AgentAPI    │ │   ConfigAPI   │ │   CacheAPI    │      │
│  │  (核心审查)    │ │  (配置管理)    │ │  (缓存管理)    │      │
│  └───────────────┘ └───────────────┘ └───────────────┘      │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐      │
│  │   HealthAPI   │ │  LLMFactory   │ │   DiffAPI     │      │
│  │  (健康检查)    │ │  (模型工厂)    │ │  (Diff分析)   │      │
│  └───────────────┘ └───────────────┘ └───────────────┘      │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐      │
│  │   ToolAPI     │ │    LogAPI     │ │  ProjectAPI   │      │
│  │  (工具管理)    │ │  (日志访问)    │ │  (项目信息)   │      │
│  └───────────────┘ └───────────────┘ └───────────────┘      │
│  ┌───────────────┐                                          │
│  │  SessionAPI   │                                          │
│  │  (会话管理)    │                                          │
│  └───────────────┘                                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   审查内核层                                  │
│                    ReviewKernel                              │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 导入方式

```python
# 推荐：统一从 api 模块导入
from Agent.core.api import (
    # 核心审查
    AgentAPI,
    ReviewRequest,
    
    # 运维管理
    ConfigAPI,
    CacheAPI,
    HealthAPI,
    
    # 功能性API (新增)
    DiffAPI,
    ToolAPI,
    LogAPI,
    ProjectAPI,
    SessionAPI,
    
    # 模型工厂
    LLMFactory,
    
    # 兼容性接口
    run_review_sync,
    run_review_async_entry,
    available_llm_options,
    available_tools,
)
```

---

## 2. 核心审查API

### 2.1 AgentAPI 类

`AgentAPI` 是系统的主入口，提供代码审查的核心功能。

#### 2.1.1 获取可用模型列表

```python
@staticmethod
def get_llm_options(include_mock: bool = True) -> List[Dict[str, Any]]
```

**功能**：获取当前环境可用的 LLM 模型列表（按厂商分组）

**参数**：
- `include_mock`: 是否包含Mock模型（用于测试）

**返回值**：
```python
[
    {
        "provider": "glm",
        "label": "智谱AI (GLM)",
        "is_active": True,  # 是否配置了API Key
        "models": [
            {
                "name": "glm:glm-4.5-flash",
                "label": "glm-4.5-flash",
                "available": True,
                "reason": None  # 不可用时显示原因
            }
        ]
    },
    # ... 其他厂商
]
```

**示例**：
```python
options = AgentAPI.get_llm_options()
for group in options:
    print(f"{group['label']}: {len(group['models'])} 个模型")
```

---

#### 2.1.2 获取可用工具列表

```python
@staticmethod
def get_tool_options() -> List[ToolOption]
```

**功能**：获取所有已注册工具及其元数据

**返回值**：
```python
[
    {
        "name": "read_file_hunk",
        "default": True,       # 是否默认启用
        "description": "读取文件指定行范围的内容"
    },
    {
        "name": "search_in_project",
        "default": True,
        "description": "在项目中搜索关键词"
    }
]
```

---

#### 2.1.3 执行代码审查（异步）

```python
@staticmethod
async def review_code(request: ReviewRequest) -> str
```

**功能**：执行代码审查任务的主入口（异步版本）

**参数**：`ReviewRequest` 对象（详见[数据模型参考](#9-数据模型参考)）

**返回值**：审查结果（Markdown格式字符串）

**示例**：
```python
import asyncio
from Agent.core.api import AgentAPI, ReviewRequest

async def main():
    request = ReviewRequest(
        prompt="请审查当前代码变更，重点关注安全性问题",
        llm_preference="glm:glm-4.5-flash",
        tool_names=["read_file_hunk", "search_in_project"],
        auto_approve=True,
        project_root="/path/to/your/repo",
    )
    
    result = await AgentAPI.review_code(request)
    print(result)

asyncio.run(main())
```

---

#### 2.1.4 执行代码审查（同步）

```python
@staticmethod
def review_code_sync(request: ReviewRequest) -> str
```

**功能**：同步版本的代码审查入口

**示例**：
```python
from Agent.core.api import AgentAPI, ReviewRequest

request = ReviewRequest(
    prompt="请审查改动",
    llm_preference="auto",
    tool_names=["read_file_hunk"],
    auto_approve=True,
)

result = AgentAPI.review_code_sync(request)
print(result)
```

---

### 2.2 兼容性接口

为保持向下兼容，保留以下函数式接口：

```python
# 等同于 AgentAPI.get_llm_options()
available_llm_options()

# 等同于 AgentAPI.get_tool_options()
available_tools()

# 异步审查入口（更多参数控制）
await run_review_async_entry(
    prompt="审查提示",
    llm_preference="auto",
    tool_names=["read_file_hunk"],
    auto_approve=True,
    project_root="/path/to/repo",
    stream_callback=my_callback,
    tool_approver=my_approver,
    planner_llm_preference="glm:glm-4.5-air",
    session_id="session_123",
    message_history=[...]
)

# 同步审查入口
run_review_sync(
    prompt="审查提示",
    llm_preference="auto",
    tool_names=["read_file_hunk"],
    auto_approve=True,
    project_root="/path/to/repo",
)
```

---

## 3. 配置管理API

### 3.1 ConfigAPI 类

提供运行时配置的获取、更新、重置功能。

#### 3.1.1 获取完整配置

```python
@staticmethod
def get_config() -> Dict[str, Any]
```

**返回值**：
```python
{
    "llm": {
        "call_timeout": 120,      # LLM调用超时（秒）
        "planner_timeout": 60,    # 规划阶段超时（秒）
        "max_retries": 3,         # 最大重试次数
        "retry_delay": 1.0        # 重试间隔（秒）
    },
    "context": {
        "max_context_chars": 50000,    # 单字段最大字符数
        "full_file_max_lines": 1000,   # 全文件模式最大行数
        "callers_max_hits": 10,        # 调用方搜索最大命中数
        "file_cache_ttl": 300          # 文件缓存TTL（秒）
    },
    "review": {
        "max_units_per_batch": 50,     # 单次审查最大单元数
        "enable_intent_cache": True,   # 是否启用意图分析缓存
        "intent_cache_ttl_days": 30,   # 意图缓存过期天数
        "stream_chunk_sample_rate": 20 # 流式日志采样率
    },
    "fusion_thresholds": {
        "high": 0.8,     # 高置信度阈值
        "medium": 0.5,   # 中置信度阈值
        "low": 0.3       # 低置信度阈值
    }
}
```

---

#### 3.1.2 更新配置

```python
@staticmethod
def update_config(updates: Dict[str, Any], persist: bool = True) -> Dict[str, Any]
```

**功能**：部分更新配置

**参数**：
- `updates`: 要更新的配置项（支持嵌套路径）
- `persist`: 是否持久化到文件

**示例**：
```python
# 更新LLM超时时间
ConfigAPI.update_config({
    "llm": {
        "call_timeout": 180
    }
})

# 更新融合阈值
ConfigAPI.update_config({
    "fusion_thresholds": {
        "high": 0.85,
        "medium": 0.6
    }
})
```

---

#### 3.1.3 重置配置

```python
@staticmethod
def reset_config(persist: bool = True) -> Dict[str, Any]
```

**功能**：重置为默认配置

---

#### 3.1.4 获取特定配置段

```python
ConfigAPI.get_llm_config()          # LLM相关配置
ConfigAPI.get_context_config()      # 上下文相关配置
ConfigAPI.get_review_config()       # 审查流程配置
ConfigAPI.get_fusion_thresholds()   # 融合层阈值
```

---

## 4. 缓存管理API

### 4.1 CacheAPI 类

提供意图缓存的管理功能。意图分析结果会缓存到文件系统，避免重复分析同一项目。

#### 4.1.1 获取缓存统计

```python
@staticmethod
def get_cache_stats() -> Dict[str, Any]
```

**返回值**：
```python
{
    "intent_cache_count": 5,           # 缓存文件数量
    "intent_cache_size_bytes": 102400, # 总大小（字节）
    "oldest_intent_cache": "2025-11-01T10:00:00",
    "newest_intent_cache": "2025-11-30T15:30:00",
    "projects_cached": ["project_a", "project_b", ...]
}
```

---

#### 4.1.2 列出缓存条目

```python
@staticmethod
def list_intent_caches() -> List[Dict[str, Any]]
```

**返回值**：
```python
[
    {
        "project_name": "my_project",
        "file_path": "/path/to/cache/my_project.json",
        "size_bytes": 20480,
        "created_at": "2025-11-30T10:00:00",
        "age_days": 0
    }
]
```

---

#### 4.1.3 清除缓存

```python
# 清除指定项目缓存
CacheAPI.clear_intent_cache("my_project")

# 清除所有缓存
CacheAPI.clear_intent_cache()

# 清除过期缓存（超过30天）
CacheAPI.clear_expired_caches(max_age_days=30)
```

---

#### 4.1.4 获取/刷新缓存

```python
# 获取指定项目的缓存内容
content = CacheAPI.get_intent_cache("my_project")

# 刷新缓存（删除后下次审查时重新生成）
CacheAPI.refresh_intent_cache("my_project")
```

---

## 5. 健康检查API

### 5.1 HealthAPI 类

提供服务健康状态检测和运行时指标统计。

#### 5.1.1 完整健康检查

```python
@staticmethod
def health_check() -> Dict[str, Any]
```

**返回值**：
```python
{
    "status": "healthy",  # "healthy" | "degraded" | "unhealthy"
    "timestamp": "2025-11-30T16:00:00",
    "providers": [
        {
            "name": "glm",
            "label": "智谱AI (GLM)",
            "available": True,
            "error": None
        },
        {
            "name": "moonshot",
            "label": "月之暗面 (Moonshot)",
            "available": False,
            "error": "缺少环境变量 MOONSHOT_API_KEY"
        }
    ],
    "disk_space_ok": True,
    "log_dir_writable": True,
    "cache_dir_writable": True,
    "available_provider_count": 4,
    "total_provider_count": 6
}
```

**状态判定规则**：
- `healthy`: 至少一半厂商可用，磁盘和日志目录正常
- `degraded`: 部分功能受限（如磁盘空间不足、多数厂商不可用）
- `unhealthy`: 无可用LLM厂商

---

#### 5.1.2 简单健康检查

```python
@staticmethod
def is_healthy() -> bool
```

**功能**：快速检查，仅返回布尔值

---

#### 5.1.3 获取系统指标

```python
@staticmethod
def get_metrics() -> Dict[str, Any]
```

**返回值**：
```python
{
    "total_reviews": 100,          # 总审查次数
    "successful_reviews": 95,      # 成功次数
    "failed_reviews": 5,           # 失败次数
    "total_tokens_used": 500000,   # 总Token消耗
    "tokens_by_provider": {        # 按厂商统计
        "glm": 300000,
        "moonshot": 200000
    },
    "avg_review_duration_ms": 15000.0,  # 平均审查耗时
    "cache_hit_rate": 0.75,        # 缓存命中率
    "fallback_count": 3,           # 回退次数
    "uptime_seconds": 86400.0      # 服务运行时长
}
```

**注意**：指标存储在内存中，服务重启后会重置。

---

#### 5.1.4 获取厂商状态

```python
@staticmethod
def get_provider_status() -> List[Dict[str, Any]]
```

---

## 6. LLM工厂API

### 6.1 LLMFactory 类

管理多厂商LLM客户端的创建。

#### 6.1.1 创建客户端

```python
@staticmethod
def create(preference: str = "auto", trace_id: str | None = None) -> Tuple[BaseLLMClient, str]
```

**参数**：
- `preference`:
  - `"auto"`: 按优先级自动选择可用厂商
  - `"mock"`: 使用Mock客户端（测试用）
  - `"glm"`: 使用GLM默认模型
  - `"glm:glm-4.5-flash"`: 使用指定模型

**返回值**：`(客户端实例, 厂商名称)`

---

#### 6.1.2 模型管理

```python
# 添加新模型
LLMFactory.add_model("glm", "glm-4.6-turbo")

# 移除模型
LLMFactory.remove_model("glm", "glm-4.6-turbo")

# 获取可用选项
options = LLMFactory.get_available_options(include_mock=True)
```

---

## 7. Diff分析API

### 7.1 DiffAPI 类

提供Git Diff相关的查询功能，无需启动完整审查流程即可获取变更信息。

#### 7.1.1 获取Diff状态

```python
@staticmethod
def get_diff_status(project_root: Optional[str] = None) -> Dict[str, Any]
```

**功能**：快速获取项目的Diff状态（不解析具体内容）

**返回值**：
```python
{
    "has_working_changes": True,    # 是否有工作区变更
    "has_staged_changes": False,    # 是否有暂存区变更
    "detected_mode": "working",     # 检测到的模式
    "base_branch": "main",          # 基准分支
    "error": None
}
```

---

#### 7.1.2 获取Diff摘要

```python
@staticmethod
def get_diff_summary(
    project_root: Optional[str] = None,
    mode: str = "auto"
) -> Dict[str, Any]
```

**功能**：获取Diff摘要信息（解析但不执行审查）

**参数**：
- `mode`: Diff模式 (`"auto"`, `"working"`, `"staged"`, `"pr"`)

**返回值**：
```python
{
    "summary": "修改了5个文件，新增120行，删除30行",
    "mode": "working",
    "base_branch": "main",
    "files": ["src/main.py", "src/utils.py", ...],
    "file_count": 5,
    "unit_count": 12,
    "lines_added": 120,
    "lines_removed": 30,
    "error": None
}
```

---

#### 7.1.3 获取变更文件列表

```python
@staticmethod
def get_diff_files(
    project_root: Optional[str] = None,
    mode: str = "auto"
) -> Dict[str, Any]
```

**返回值**：
```python
{
    "files": [
        {
            "path": "src/main.py",
            "language": "Python",
            "change_type": "modify",
            "lines_added": 50,
            "lines_removed": 10,
            "tags": ["core", "refactor"]
        }
    ],
    "error": None
}
```

---

#### 7.1.4 获取审查单元

```python
@staticmethod
def get_review_units(
    project_root: Optional[str] = None,
    mode: str = "auto",
    file_filter: Optional[str] = None
) -> Dict[str, Any]
```

**功能**：获取基于规则解析的审查单元列表

**返回值**：
```python
{
    "units": [
        {
            "unit_id": "unit_abc123",
            "file_path": "src/main.py",
            "location": "10-25",
            "lines_added": 15,
            "lines_removed": 5,
            "tags": ["function", "new"],
            "rule_context_level": "file_context",
            "rule_confidence": 0.85
        }
    ],
    "total_count": 12,
    "error": None
}
```

---

#### 7.1.5 获取单文件Diff

```python
@staticmethod
def get_file_diff(
    file_path: str,
    project_root: Optional[str] = None,
    mode: str = "auto"
) -> Dict[str, Any]
```

**返回值**：
```python
{
    "file_path": "src/main.py",
    "diff_text": "@@ -10,5 +10,15 @@\n...",
    "hunks": [
        {
            "source_start": 10,
            "source_length": 5,
            "target_start": 10,
            "target_length": 15,
            "content": "..."
        }
    ],
    "error": None
}
```

---

## 8. 工具管理API

### 8.1 ToolAPI 类

提供工具注册、查询、统计等功能。

#### 8.1.1 列出所有工具

```python
@staticmethod
def list_tools(
    include_builtin: bool = True,
    include_custom: bool = True
) -> List[Dict[str, Any]]
```

**返回值**：
```python
[
    {
        "name": "read_file_hunk",
        "description": "读取文件指定行范围的内容",
        "is_builtin": True,
        "is_default": True,
        "parameters": {...}
    }
]
```

---

#### 8.1.2 获取工具详情

```python
@staticmethod
def get_tool_detail(name: str) -> Optional[Dict[str, Any]]
```

**返回值**：
```python
{
    "name": "read_file_hunk",
    "description": "读取文件指定行范围的内容",
    "is_builtin": True,
    "is_default": True,
    "parameters": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"}
        }
    },
    "schema": {...}  # OpenAI格式
}
```

---

#### 8.1.3 获取工具统计

```python
@staticmethod
def get_tool_stats() -> Dict[str, Any]
```

**返回值**：
```python
{
    "by_tool": {
        "read_file_hunk": {
            "call_count": 150,
            "success_count": 148,
            "failure_count": 2,
            "success_rate": 0.987,
            "avg_duration_ms": 45.5,
            "total_duration_ms": 6825.0
        }
    },
    "summary": {
        "total_calls": 500,
        "total_successes": 495,
        "total_failures": 5,
        "overall_success_rate": 0.99
    }
}
```

---

#### 8.1.4 获取最近执行记录

```python
@staticmethod
def get_recent_executions(limit: int = 20) -> List[Dict[str, Any]]
```

**返回值**：
```python
[
    {
        "tool_name": "read_file_hunk",
        "arguments": {"file_path": "src/main.py", ...},
        "success": True,
        "error": None,
        "duration_ms": 42.5,
        "timestamp": 1701388800.0
    }
]
```

---

#### 8.1.5 注册自定义工具

```python
@staticmethod
def register_custom_tool(
    name: str,
    description: str,
    parameters: Dict[str, Any],
    handler: Callable[[Dict[str, Any]], Any]
) -> Dict[str, Any]
```

**示例**：
```python
def my_custom_handler(args):
    return {"result": f"处理了 {args.get('input')}"}

result = ToolAPI.register_custom_tool(
    name="my_tool",
    description="我的自定义工具",
    parameters={
        "type": "object",
        "properties": {
            "input": {"type": "string"}
        }
    },
    handler=my_custom_handler
)
```

---

## 9. 日志访问API

### 9.1 LogAPI 类

提供历史审查日志的查询、导出功能。

#### 9.1.1 列出日志会话

```python
@staticmethod
def list_sessions(
    limit: int = 50,
    offset: int = 0,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
) -> Dict[str, Any]
```

**返回值**：
```python
{
    "sessions": [
        {
            "trace_id": "b89af792a8f7",
            "date": "20251130",
            "time": "220524",
            "file_path": "log/pipeline/...",
            "file_size": 10240,
            "review_provider": "glm",
            "planner_provider": "glm"
        }
    ],
    "count": 25
}
```

---

#### 9.1.2 获取会话日志详情

```python
@staticmethod
def get_session_log(trace_id: str) -> Optional[Dict[str, Any]]
```

**返回值**：
```python
{
    "trace_id": "b89af792a8f7",
    "pipeline_log_path": "log/pipeline/...",
    "events": [
        {
            "event": "session_start",
            "stage": "init",
            "status": "start",
            "ts": "2025-11-30T22:05:24",
            "uptime_ms": 0,
            "payload_preview": "..."
        }
    ],
    "event_count": 50,
    "usage_summary": {
        "total_tokens": 5000,
        "input_tokens": 3000,
        "output_tokens": 2000
    },
    "human_log_preview": "# 代码审查报告\n..."
}
```

---

#### 9.1.3 获取API调用记录

```python
@staticmethod
def get_api_calls(trace_id: str) -> Dict[str, Any]
```

**返回值**：
```python
{
    "calls": [
        {
            "section": "review",
            "label": "llm_call",
            "ts": "2025-11-30T22:05:30",
            "payload_preview": "..."
        }
    ],
    "count": 10
}
```

---

#### 9.1.4 删除旧日志

```python
@staticmethod
def delete_old_logs(days: int = 30) -> Dict[str, Any]
```

**返回值**：
```python
{
    "deleted_files": 15,
    "freed_bytes": 1048576
}
```

---

#### 9.1.5 获取日志统计

```python
@staticmethod
def get_log_stats() -> Dict[str, Any]
```

**返回值**：
```python
{
    "api_log": {"file_count": 25, "total_size": 512000},
    "human_log": {"file_count": 25, "total_size": 256000},
    "pipeline_log": {"file_count": 25, "total_size": 1024000}
}
```

---

## 10. 项目信息API

### 10.1 ProjectAPI 类

提供项目上下文信息查询功能。

#### 10.1.1 获取项目信息

```python
@staticmethod
def get_project_info(project_root: Optional[str] = None) -> Dict[str, Any]
```

**返回值**：
```python
{
    "project_name": "my_project",
    "project_path": "/path/to/project",
    "is_git_repo": True,
    "git_branch": "main",
    "file_count": 150,
    "has_readme": True,
    "detected_languages": ["Python", "JavaScript", "TypeScript"]
}
```

---

#### 10.1.2 获取文件树

```python
@staticmethod
def get_file_tree(
    project_root: Optional[str] = None,
    max_depth: int = 3,
    include_hidden: bool = False
) -> Dict[str, Any]
```

**返回值**：
```python
{
    "root": "/path/to/project",
    "tree": {
        "src/": {
            "main.py": None,
            "utils/": {
                "helpers.py": None
            }
        },
        "tests/": {
            "test_main.py": None
        },
        "README.md": None
    }
}
```

---

#### 10.1.3 获取README内容

```python
@staticmethod
def get_readme_content(project_root: Optional[str] = None) -> Dict[str, Any]
```

**返回值**：
```python
{
    "found": True,
    "filename": "README.md",
    "content": "# My Project\n..."
}
```

---

#### 10.1.4 获取依赖信息

```python
@staticmethod
def get_dependencies(project_root: Optional[str] = None) -> Dict[str, Any]
```

**返回值**：
```python
{
    "requirements.txt": {
        "type": "python",
        "dependencies": ["fastapi>=0.100.0", "uvicorn", ...],
        "count": 15
    },
    "package.json": {
        "type": "npm",
        "dependencies": {"react": "^18.0.0", ...},
        "devDependencies": {"typescript": "^5.0.0", ...},
        "dep_count": 10,
        "dev_dep_count": 8
    }
}
```

---

#### 10.1.5 获取Git信息

```python
@staticmethod
def get_git_info(project_root: Optional[str] = None) -> Dict[str, Any]
```

**返回值**：
```python
{
    "is_git_repo": True,
    "current_branch": "feature/new-api",
    "remote_url": "https://github.com/user/repo.git",
    "recent_commits": [
        {
            "hash": "abc123",
            "message": "Add new feature",
            "author": "Developer",
            "time_ago": "2 hours ago"
        }
    ],
    "local_branches": ["main", "develop", "feature/new-api"],
    "has_uncommitted_changes": True
}
```

---

#### 10.1.6 搜索文件

```python
@staticmethod
def search_files(
    query: str,
    project_root: Optional[str] = None,
    file_pattern: Optional[str] = None,
    max_results: int = 50
) -> Dict[str, Any]
```

**返回值**：
```python
{
    "query": "TODO",
    "matches": [
        {
            "file": "src/main.py",
            "line": 42,
            "content": "# TODO: implement this feature"
        }
    ],
    "count": 5
}
```

---

## 11. 会话管理增强API

### 11.1 SessionAPI 类

对现有会话管理进行封装和扩展，提供更丰富的会话操作。

#### 11.1.1 创建会话

```python
@staticmethod
def create_session(
    session_id: str,
    project_root: Optional[str] = None,
    name: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]
```

**返回值**：
```python
{
    "success": True,
    "session": {
        "session_id": "session_123",
        "metadata": {
            "name": "代码审查会话",
            "created_at": "2025-12-01T10:00:00",
            "status": "active",
            "tags": ["review", "api"]
        }
    }
}
```

---

#### 11.1.2 列出会话

```python
@staticmethod
def list_sessions(
    status: Optional[str] = None,
    project_root: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> Dict[str, Any]
```

**参数**：
- `status`: 按状态过滤 (`"active"`, `"completed"`, `"archived"`)
- `project_root`: 按项目过滤
- `tag`: 按标签过滤

**返回值**：
```python
{
    "sessions": [...],
    "total": 25,
    "limit": 50,
    "offset": 0
}
```

---

#### 11.1.3 更新会话

```python
@staticmethod
def update_session(
    session_id: str,
    name: Optional[str] = None,
    status: Optional[str] = None,
    tags: Optional[List[str]] = None
) -> Dict[str, Any]
```

---

#### 11.1.4 导出会话

```python
@staticmethod
def export_session(
    session_id: str,
    format: str = "json"  # "json" 或 "markdown"
) -> Dict[str, Any]
```

**返回值**：
```python
{
    "success": True,
    "content": "...",  # JSON或Markdown内容
    "filename": "session_123.json"
}
```

---

#### 11.1.5 获取会话消息

```python
@staticmethod
def get_session_messages(
    session_id: str,
    limit: Optional[int] = None,
    role_filter: Optional[str] = None
) -> Dict[str, Any]
```

**返回值**：
```python
{
    "messages": [
        {"role": "user", "content": "请审查代码"},
        {"role": "assistant", "content": "# 审查报告\n..."}
    ],
    "count": 10
}
```

---

#### 11.1.6 获取会话统计

```python
@staticmethod
def get_session_stats() -> Dict[str, Any]
```

**返回值**：
```python
{
    "total_sessions": 50,
    "by_status": {
        "active": 10,
        "completed": 35,
        "archived": 5
    },
    "by_project": {
        "/path/to/project1": 20,
        "/path/to/project2": 30
    },
    "total_messages": 500
}
```

---

#### 11.1.7 归档旧会话

```python
@staticmethod
def archive_old_sessions(days: int = 30) -> Dict[str, Any]
```

**返回值**：
```python
{
    "archived_count": 15
}
```

---

## 12. Web服务端点

### 7.1 审查相关

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/options` | GET | 获取模型与工具选项 |
| `/api/diff/check` | POST | 检查项目Diff状态 |
| `/api/review/start` | POST | 启动代码审查（SSE流式） |
| `/api/chat/send` | POST | 多轮对话（SSE流式） |

### 7.2 会话管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/sessions/create` | POST | 创建新会话 |
| `/api/sessions/list` | GET | 列出所有会话 |
| `/api/sessions/{session_id}` | GET | 获取会话详情 |
| `/api/sessions/rename` | POST | 重命名会话 |
| `/api/sessions/delete` | POST | 删除会话 |

### 7.3 模型管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/models/add` | POST | 添加新模型 |
| `/api/models/delete` | POST | 删除模型 |

### 7.4 配置管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/config` | GET | 获取当前配置 |
| `/api/config` | PATCH | 更新配置 |
| `/api/config/reset` | POST | 重置配置 |
| `/api/config/llm` | GET | 获取LLM配置 |
| `/api/config/context` | GET | 获取上下文配置 |
| `/api/config/review` | GET | 获取审查配置 |
| `/api/config/fusion` | GET | 获取融合阈值 |

### 7.5 缓存管理

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/cache/stats` | GET | 获取缓存统计 |
| `/api/cache/intent` | GET | 列出所有意图缓存 |
| `/api/cache/intent/{project_name}` | GET | 获取指定缓存内容 |
| `/api/cache/intent` | DELETE | 清除意图缓存 |
| `/api/cache/intent/{project_name}/refresh` | POST | 刷新指定项目缓存 |
| `/api/cache/expired` | DELETE | 清除过期缓存 |

### 7.6 健康检查

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/health` | GET | 完整健康检查 |
| `/api/health/simple` | GET | 简单健康检查 |
| `/api/metrics` | GET | 获取系统指标 |
| `/api/providers/status` | GET | 获取厂商状态 |

### 7.7 Diff分析 *(新增)*

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/diff/status` | GET | 获取Diff状态概览 |
| `/api/diff/summary` | GET | 获取Diff摘要信息 |
| `/api/diff/files` | GET | 获取变更文件列表 |
| `/api/diff/units` | GET | 获取审查单元列表 |
| `/api/diff/file/{file_path}` | GET | 获取指定文件Diff详情 |
| `/api/diff/analyze` | POST | 完整Diff分析 |

### 7.8 工具管理 *(新增)*

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/tools/list` | GET | 获取所有工具列表 |
| `/api/tools/{tool_name}` | GET | 获取工具详情 |
| `/api/tools/stats/summary` | GET | 获取工具使用统计 |
| `/api/tools/stats/recent` | GET | 获取最近工具调用 |
| `/api/tools/stats/record` | POST | 记录工具调用 |
| `/api/tools/register` | POST | 注册自定义工具 |

### 7.9 日志访问 *(新增)*

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/logs/sessions` | GET | 列出日志会话 |
| `/api/logs/session/{trace_id}` | GET | 获取会话日志详情 |
| `/api/logs/session/{trace_id}/human` | GET | 获取人类可读日志 |
| `/api/logs/session/{trace_id}/api-calls` | GET | 获取API调用记录 |
| `/api/logs/session/{trace_id}/pipeline` | GET | 获取流水线日志 |
| `/api/logs/stats` | GET | 获取日志统计 |
| `/api/logs/old` | DELETE | 删除旧日志 |
| `/api/logs/export/{trace_id}` | GET | 导出会话日志 |

### 7.10 项目信息 *(新增)*

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/project/info` | GET | 获取项目基本信息 |
| `/api/project/tree` | GET | 获取文件树结构 |
| `/api/project/readme` | GET | 获取README内容 |
| `/api/project/dependencies` | GET | 获取依赖信息 |
| `/api/project/git` | GET | 获取Git信息 |
| `/api/project/search` | POST | 搜索文件内容 |
| `/api/project/languages` | GET | 获取编程语言统计 |

### 7.11 增强会话管理 *(新增)*

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/sessions/stats` | GET | 获取会话统计 |
| `/api/sessions/{session_id}/messages` | GET | 获取会话消息历史 |
| `/api/sessions/{session_id}/export` | GET | 导出会话数据 |
| `/api/sessions/{session_id}` | PATCH | 更新会话元数据 |
| `/api/sessions/search` | GET | 搜索会话 |
| `/api/sessions/archive` | POST | 归档旧会话 |

---

## 8. 流式事件协议

当使用 `stream_callback` 参数时，会收到以下类型的事件：

### 8.1 流水线阶段事件

```python
# 阶段开始
{"type": "pipeline_stage_start", "stage": "diff_parse"}

# 阶段结束
{"type": "pipeline_stage_end", "stage": "diff_parse", "summary": {"files": 5, "units": 12}}
```

**阶段顺序**：
1. `diff_parse` - Diff解析
2. `review_units` - 审查单元构建
3. `rule_layer` - 规则层分析
4. `review_index` - 审查索引生成
5. `intent_analysis` - 意图分析
6. `planner` - 规划阶段
7. `fusion` - 融合阶段
8. `context_bundle` - 上下文包构建
9. `reviewer` - 审查执行
10. `final_output` - 最终输出

### 8.2 内容增量事件

```python
# LLM正文增量
{
    "type": "delta",
    "content_delta": "这段代码存在以下问题：",
    "reasoning_delta": ""  # 思考过程（如有）
}

# 意图分析增量
{
    "type": "intent_delta",
    "content_delta": "## 项目概览\n这是一个...",
    "reasoning_delta": "分析项目结构..."
}

# 规划增量
{
    "type": "planner_delta",
    "content_delta": "{\"plan\": [...]}",
    "reasoning_delta": "根据代码变更类型..."
}
```

### 8.3 上下文包事件

```python
{
    "type": "bundle_item",
    "unit_id": "unit_abc123",
    "final_context_level": "file_context",
    "location": "src/main.py:10-25"
}
```

### 8.4 工具调用事件

```python
# 工具开始
{
    "type": "tool_call_start",
    "tool_name": "read_file_hunk",
    "arguments": {"file_path": "src/main.py", "start_line": 10, "end_line": 20}
}

# 工具结果
{
    "type": "tool_result",
    "tool_name": "read_file_hunk",
    "success": True,
    "content": "def main():\n    ...",
    "duration_ms": 50
}

# 工具结束
{
    "type": "tool_call_end",
    "tool_name": "read_file_hunk",
    "success": True,
    "duration_ms": 50
}
```

### 8.5 用量统计事件

```python
{
    "type": "usage_summary",
    "usage_stage": "review",  # "intent" | "planner" | "review"
    "call_index": 1,
    "usage": {
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500
    },
    "call_usage": {"in": 1000, "out": 500, "total": 1500},
    "session_usage": {"in": 2000, "out": 1000, "total": 3000}
}
```

### 8.6 告警与错误事件

```python
# 告警（如回退触发）
{
    "type": "warning",
    "message": "回退触发 2 次：{'llm_timeout': 2}",
    "fallback_summary": {"total": 2, "by_key": {"llm_timeout": 2}}
}

# 错误
{
    "type": "error",
    "stage": "planner",
    "message": "LLM调用超时"
}
```

### 8.7 最终结果事件

```python
# 最终结果
{"type": "final", "content": "# 代码审查报告\n..."}

# 完成标记
{"type": "done"}
```

---

## 9. 数据模型参考

### 9.1 ReviewRequest

```python
@dataclass
class ReviewRequest:
    """标准化审查请求参数。"""
    
    prompt: str                    # 审查提示
    llm_preference: str            # 模型偏好
    tool_names: List[str]          # 启用的工具列表
    auto_approve: bool             # 是否自动执行所有工具
    
    # 可选参数
    project_root: Optional[str] = None           # 项目根目录
    stream_callback: Optional[Callable] = None   # 流式回调
    tool_approver: Optional[Callable] = None     # 工具审批回调
    planner_llm_preference: Optional[str] = None # 规划模型偏好
    session_id: Optional[str] = None             # 会话ID
    message_history: Optional[List[Dict]] = None # 历史消息
```

### 9.2 KernelConfig

```python
@dataclass
class KernelConfig:
    llm: LLMConfig
    context: ContextConfig
    review: ReviewConfig
    fusion_thresholds: FusionThresholds
```

### 9.3 ToolOption

```python
class ToolOption(TypedDict):
    name: str               # 工具名称
    default: bool           # 是否默认启用
    description: str | None # 工具描述
```

---

## 10. 使用示例

### 10.1 基础审查流程

```python
import asyncio
from Agent.core.api import AgentAPI, ReviewRequest

async def basic_review():
    # 1. 检查可用模型
    options = AgentAPI.get_llm_options()
    available_models = [
        m["name"] for g in options 
        for m in g["models"] if m["available"]
    ]
    print(f"可用模型: {available_models}")
    
    # 2. 获取可用工具
    tools = AgentAPI.get_tool_options()
    default_tools = [t["name"] for t in tools if t["default"]]
    
    # 3. 执行审查
    request = ReviewRequest(
        prompt="请审查代码变更，重点关注：\n1. 代码规范\n2. 潜在bug\n3. 性能问题",
        llm_preference="auto",
        tool_names=default_tools,
        auto_approve=True,
        project_root="/path/to/your/project"
    )
    
    result = await AgentAPI.review_code(request)
    print(result)

asyncio.run(basic_review())
```

### 10.2 带流式回调的审查

```python
import asyncio
from Agent.core.api import AgentAPI, ReviewRequest

def stream_handler(event):
    """处理流式事件"""
    event_type = event.get("type")
    
    if event_type == "delta":
        # 增量内容
        print(event.get("content_delta", ""), end="", flush=True)
    
    elif event_type == "pipeline_stage_start":
        print(f"\n[阶段开始] {event['stage']}")
    
    elif event_type == "tool_call_start":
        print(f"\n[调用工具] {event['tool_name']}")
    
    elif event_type == "usage_summary":
        usage = event.get("session_usage", {})
        print(f"\n[Token用量] {usage.get('total', 0)}")
    
    elif event_type == "error":
        print(f"\n[错误] {event['message']}")

async def streaming_review():
    request = ReviewRequest(
        prompt="请审查改动",
        llm_preference="auto",
        tool_names=["read_file_hunk", "search_in_project"],
        auto_approve=True,
        project_root="/path/to/project",
        stream_callback=stream_handler
    )
    
    result = await AgentAPI.review_code(request)
    print(f"\n\n=== 最终结果 ===\n{result}")

asyncio.run(streaming_review())
```

### 10.3 运维操作示例

```python
from Agent.core.api import ConfigAPI, CacheAPI, HealthAPI

# --- 健康检查 ---
health = HealthAPI.health_check()
print(f"系统状态: {health['status']}")
print(f"可用厂商: {health['available_provider_count']}/{health['total_provider_count']}")

# --- 查看指标 ---
metrics = HealthAPI.get_metrics()
print(f"总审查次数: {metrics['total_reviews']}")
print(f"成功率: {metrics['successful_reviews'] / max(metrics['total_reviews'], 1) * 100:.1f}%")

# --- 配置管理 ---
# 查看当前配置
config = ConfigAPI.get_config()
print(f"LLM超时: {config['llm']['call_timeout']}秒")

# 调整超时时间
ConfigAPI.update_config({"llm": {"call_timeout": 180}})

# 重置配置
ConfigAPI.reset_config()

# --- 缓存管理 ---
# 查看缓存统计
stats = CacheAPI.get_cache_stats()
print(f"缓存项目数: {stats['intent_cache_count']}")

# 清理过期缓存
result = CacheAPI.clear_expired_caches(max_age_days=7)
print(f"已清理: {result['cleared_count']} 个文件")

# 刷新特定项目缓存
CacheAPI.refresh_intent_cache("my_project")
```

### 10.4 工具审批示例

```python
import asyncio
from Agent.core.api import AgentAPI, ReviewRequest

def custom_tool_approver(tool_calls):
    """自定义工具审批逻辑"""
    approved = []
    
    for call in tool_calls:
        tool_name = call.get("name")
        args = call.get("arguments", {})
        
        # 示例：只允许读取特定目录
        if tool_name == "read_file_hunk":
            file_path = args.get("file_path", "")
            if file_path.startswith("src/"):
                approved.append(call)
                print(f"[审批通过] {tool_name}: {file_path}")
            else:
                print(f"[审批拒绝] {tool_name}: {file_path} (不在允许目录)")
        else:
            # 其他工具默认通过
            approved.append(call)
    
    return approved

async def review_with_approval():
    request = ReviewRequest(
        prompt="请审查代码",
        llm_preference="auto",
        tool_names=["read_file_hunk", "search_in_project"],
        auto_approve=False,  # 关闭自动批准
        project_root="/path/to/project",
        tool_approver=custom_tool_approver
    )
    
    result = await AgentAPI.review_code(request)
    print(result)

asyncio.run(review_with_approval())
```

---

## 11. 错误处理

### 11.1 常见错误类型

| 错误 | 原因 | 处理建议 |
|------|------|----------|
| `RuntimeError: 无法创建指定的 LLM 客户端` | 缺少API Key | 检查环境变量配置 |
| `RuntimeError: 项目目录不存在` | 项目路径无效 | 检查 `project_root` 参数 |
| `HTTPException 400` | 请求参数错误 | 检查请求体格式 |
| `HTTPException 404` | 资源不存在 | 检查会话ID或缓存名称 |

### 11.2 错误处理示例

```python
import asyncio
from Agent.core.api import AgentAPI, ReviewRequest

async def safe_review():
    try:
        request = ReviewRequest(
            prompt="审查代码",
            llm_preference="nonexistent:model",  # 无效的模型
            tool_names=[],
            auto_approve=True
        )
        result = await AgentAPI.review_code(request)
    
    except RuntimeError as e:
        if "无法创建" in str(e):
            print(f"模型配置错误: {e}")
            # 降级到自动选择
            request.llm_preference = "auto"
            result = await AgentAPI.review_code(request)
        else:
            raise
    
    except Exception as e:
        print(f"未知错误: {e}")
        raise

asyncio.run(safe_review())
```

---

## 附录

### A. 环境变量列表

| 变量名 | 对应厂商 | 说明 |
|--------|----------|------|
| `GLM_API_KEY` | 智谱AI | GLM系列模型 |
| `BAILIAN_API_KEY` | 阿里百炼 | Qwen系列模型 |
| `MODELSCOPE_API_KEY` | 魔搭社区 | 多厂商模型 |
| `MOONSHOT_API_KEY` | 月之暗面 | Kimi系列模型 |
| `OPENROUTER_API_KEY` | OpenRouter | 多厂商聚合 |
| `SILICONFLOW_API_KEY` | 硅基流动 | 多厂商模型 |

### B. 文件路径

| 文件 | 说明 |
|------|------|
| `Agent/core/api/models_config.json` | 模型列表配置 |
| `Agent/core/api/kernel_config.json` | 内核运行时配置 |
| `Agent/data/Analysis/*.json` | 意图分析缓存 |
| `log/api_log/*.jsonl` | API调用日志 |
| `log/human_log/*.md` | 人类可读日志 |
| `log/pipeline/*.jsonl` | 流水线日志 |
| `Agent/data/sessions/*.json` | 会话持久化数据 |

### C. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 2.0 | 2025-12-01 | 新增功能性API：DiffAPI、ToolAPI、LogAPI、ProjectAPI、SessionAPI |
| 1.0 | 2025-11-30 | 初始版本：核心API + 运维API |

---

*本文档由系统自动生成，如有问题请联系开发团队。*
