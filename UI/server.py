import asyncio
import json
import random
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# 允许跨域（方便开发调试）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 模拟数据
MOCK_MODELS = [
    {"label": "GPT-4 (Auto)", "value": "gpt-4"},
    {"label": "Claude 3.5 Sonnet", "value": "claude-3-5-sonnet"},
    {"label": "DeepSeek Coder", "value": "deepseek-coder"},
]

MOCK_TOOLS = [
    {"label": "读取代码差异 (Diff)", "value": "read_diff", "checked": True},
    {"label": "项目全局搜索", "value": "search_project", "checked": True},
    {"label": "静态代码分析", "value": "static_analysis", "checked": False},
]

@app.get("/api/options")
async def get_options():
    """获取配置选项"""
    return {
        "models": MOCK_MODELS,
        "tools": MOCK_TOOLS
    }

async def mock_review_stream() -> AsyncGenerator[str, None]:
    """模拟流式审查输出"""
    
    # 1. 思考阶段
    yield f"data: {json.dumps({'type': 'stage', 'content': '正在分析项目结构...'})}\n\n"
    await asyncio.sleep(1)
    
    yield f"data: {json.dumps({'type': 'thought', 'content': '检测到 Python 项目，正在读取 requirements.txt...'})}\n\n"
    await asyncio.sleep(0.5)
    yield f"data: {json.dumps({'type': 'thought', 'content': '发现 FastAPI 依赖，准备检查路由定义...'})}\n\n"
    await asyncio.sleep(0.5)
    
    # 2. 工具调用
    yield f"data: {json.dumps({'type': 'tool_start', 'tool': 'read_diff'})}\n\n"
    await asyncio.sleep(1)
    yield f"data: {json.dumps({'type': 'tool_end', 'tool': 'read_diff', 'result': 'Found 3 modified files.'})}\n\n"
    
    # 3. 生成审查意见 (Markdown)
    review_content = """
# 代码审查报告

## 总体评价
本次提交主要增加了 **UI 模块**，代码结构清晰，使用了 FastAPI + Vue3 的技术栈，这是一个非常现代化的选择。

## 详细建议

### 1. 路由定义优化
在 `UI/server.py` 中，建议将路由定义拆分到单独的 `routers` 模块中，以便于后续扩展。

```python
# 建议的结构
from fastapi import APIRouter

router = APIRouter()

@router.get("/api/options")
async def get_options():
    pass
```

### 2. 前端资源管理
目前使用了 CDN 引入前端依赖，这在开发阶段非常方便。建议在生产环境中考虑：
- 使用构建工具 (Vite) 打包
- 或者将 CDN 资源本地化，避免内网环境无法访问

### 3. 错误处理
建议在 API 中增加全局异常处理中间件。

---
**总结**：代码质量良好，建议采纳上述建议后合并。
"""
    
    yield f"data: {json.dumps({'type': 'stage', 'content': '正在生成审查报告...'})}\n\n"
    
    # 模拟打字机效果
    chunk_size = 5
    for i in range(0, len(review_content), chunk_size):
        chunk = review_content[i:i+chunk_size]
        yield f"data: {json.dumps({'type': 'delta', 'content': chunk})}\n\n"
        await asyncio.sleep(0.05)  # 打字速度
    
    yield f"data: {json.dumps({'type': 'done'})}\n\n"

@app.post("/api/review")
async def start_review():
    """开始审查（流式）"""
    return StreamingResponse(mock_review_stream(), media_type="text/event-stream")

# 挂载静态文件（必须放在最后，否则会覆盖 API 路由）
app.mount("/", StaticFiles(directory="UI/static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
