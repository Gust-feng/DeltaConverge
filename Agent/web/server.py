"""精简的 Web 封装，为 Web UI 暴露审查引擎。

接口（v1）：
- GET /health                  -> {"status": "ok"}
- GET /api/tools               -> {"tools": [...], "schemas": [...]}
- POST /api/review/start       -> 审查事件的 SSE 流
  请求体：{"prompt": str, "model": "auto|glm|moonshot|mock", "tools": [...], "autoApprove": bool}

保持极薄：实际逻辑均在 Agent/ui/service.py 与审查核心中。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from Agent.ui.service import run_review_async
from Agent.tool.registry import default_tool_names, get_tool_schemas

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="AI Review Web Wrapper", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ReviewRequest(BaseModel):
    prompt: str = Field(..., description="审查提示词（会自动拼接 diff 上下文）")
    model: str = Field("auto", description="auto | glm | bailian | moonshot | mock")
    projectRoot: Optional[str] = Field(
        None, description="待审查项目的根目录（git 仓库路径），为空则为当前仓库"
    )
    tools: Optional[List[str]] = Field(
        None, description="可用工具列表，默认使用当前已注册工具"
    )
    autoApprove: bool = Field(
        True, description="是否自动执行工具（True=全部自动执行；False=预留审批接口）"
    )


def _format_sse(event: Dict[str, Any]) -> str:
    """将事件字典格式化为 SSE 字符串。"""

    import json as _json

    return f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse({"message": "Static UI not found. Please build front-end."})


@app.get("/api/tools")
async def list_tools() -> Dict[str, Any]:
    names = default_tool_names()
    schemas = get_tool_schemas(names)
    return {"tools": list(names), "schemas": schemas}


@app.post("/api/review/start")
async def start_review(req: ReviewRequest):
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    tool_names = req.tools or default_tool_names()
    auto_approve = bool(req.autoApprove)

    queue: "asyncio.Queue[Optional[Dict[str, Any]]]" = asyncio.Queue()

    loop = asyncio.get_running_loop()

    def stream_callback(evt: Dict[str, Any]) -> None:
        """在同一事件循环中将事件写入 asyncio 队列（非异步观察者）。"""

        # 确保在事件循环中提交
        loop.call_soon_threadsafe(queue.put_nowait, evt)

    async def run_worker() -> None:
        try:
            result = await run_review_async(
                prompt,
                req.model,
                tool_names,
                auto_approve,
                req.projectRoot,
                stream_callback,
                None,  # 工具审批预留，v1 默认 auto_approve=True
            )
            await queue.put({"type": "final", "content": result})
        except Exception as exc:  # pragma: no cover - 错误透传给客户端
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)

    async def event_generator():
        worker = asyncio.create_task(run_worker())
        try:
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                yield _format_sse(evt)
        finally:
            worker.cancel()

    headers = {"Content-Type": "text/event-stream"}
    return StreamingResponse(event_generator(), headers=headers)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
