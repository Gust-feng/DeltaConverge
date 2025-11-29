import asyncio
import json
from typing import Any, AsyncGenerator, Dict, List, Optional
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from Agent.core.api import available_llm_options, available_tools, run_review_async_entry
from Agent.core.context.diff_provider import collect_diff_context
from Agent.tool.registry import default_tool_names, get_tool_schemas

app = FastAPI()

# 允许跨域（方便前端调试）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReviewRequest(BaseModel):
    prompt: Optional[str] = None
    model: str = "auto"
    tools: Optional[List[str]] = None
    autoApprove: bool = False
    project_root: Optional[str] = None


def _safe_event(evt: Dict[str, Any]) -> Dict[str, Any]:
    """避免把巨型 raw 字段塞进 SSE。"""
    cleaned = dict(evt)
    cleaned.pop("raw", None)
    return cleaned


@app.post("/api/diff/check")
async def check_diff(req: ReviewRequest):
    """检查当前项目的 Diff 状态，返回变更文件列表。"""
    try:
        # 切换目录（如果指定）
        cwd = os.getcwd()
        if req.project_root:
            target_path = Path(req.project_root).expanduser().resolve()
            if not target_path.is_dir():
                raise HTTPException(status_code=400, detail=f"Directory not found: {req.project_root}")
            os.chdir(target_path)
        
        try:
            diff_ctx = collect_diff_context()
            return {
                "summary": diff_ctx.summary,
                "files": diff_ctx.files,
                "stats": {
                    "total_files": len(diff_ctx.files),
                    "mode": diff_ctx.mode.value,
                    "base_branch": diff_ctx.base_branch
                }
            }
        finally:
            if req.project_root:
                os.chdir(cwd)
    except Exception as e:
        return {"error": str(e), "files": []}


@app.get("/api/options")
async def get_options():
    """模型与工具选项（含默认工具 schema），缺省时提供兜底值。"""
    models = available_llm_options()
    if not models:
        models = [
            {"name": "auto", "available": True, "reason": None},
            {"name": "mock", "available": True, "reason": "fallback"},
        ]

    tools = available_tools()
    if not tools:
        defaults = set(default_tool_names())
        tools = [
            {"name": name, "default": name in defaults, "description": None}
            for name in defaults
        ]

    schemas = get_tool_schemas(default_tool_names())
    return {"models": models, "tools": tools, "schemas": schemas}


@app.post("/api/review/start")
async def start_review(req: ReviewRequest):
    """启动一次代码审查，使用 SSE 流式返回事件。"""

    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

    def stream_callback(evt: Dict[str, Any]) -> None:
        try:
            queue.put_nowait(_safe_event(evt))
        except Exception:
            pass

    async def run_agent() -> None:
        try:
            result = await run_review_async_entry(
                prompt=req.prompt or "请审查当前项目的代码变更",
                llm_preference=req.model,
                tool_names=req.tools or default_tool_names(),
                auto_approve=req.autoApprove,
                stream_callback=stream_callback,
                project_root=req.project_root,
            )
            await queue.put({"type": "final", "content": result})
        except Exception as exc:
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put({"type": "done"})

    asyncio.create_task(run_agent())

    async def event_stream() -> AsyncGenerator[str, None]:
        while True:
            evt = await queue.get()
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
            if evt.get("type") in {"done", "error", "final"}:
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# 挂载静态文件（必须放在最后，否则会覆盖 API 路由）
app.mount("/", StaticFiles(directory="UI/static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=54321)
