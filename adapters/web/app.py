from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from adapters.web.routers import (
    config_router,
    dashboard_router,
    diff_router,
    projects_router,
    reviews_router,
    rule_growth_router,
    scans_router,
    sessions_router,
    system_router,
)
from kernel.bootstrap import prewarm_legacy_imports

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    # 单线程启动阶段预热旧模块导入，避免请求线程并发导入导致死锁（偶发 500）
    prewarm_legacy_imports()

    app = FastAPI(title="DeltaConverge Kernel Web Adapter")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(sessions_router)
    app.include_router(reviews_router)
    app.include_router(projects_router)
    app.include_router(dashboard_router)
    app.include_router(diff_router)
    app.include_router(scans_router)
    app.include_router(config_router)
    app.include_router(rule_growth_router)
    app.include_router(system_router)

    @app.exception_handler(ValueError)
    async def _value_error_handler(_request: Request, exc: ValueError):
        """参数类错误（如项目路径失效）回 400，避免暴露为 500。"""
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(KeyError)
    async def _key_error_handler(_request: Request, exc: KeyError):
        """资源不存在回 404（内核以 KeyError 表达 not found）。"""
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(FileNotFoundError)
    async def _not_found_handler(_request: Request, exc: FileNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.get("/api/v2/health")
    def health():
        return {"status": "ok"}

    dist_dir = Path(__file__).resolve().parents[2] / "frontend" / "react" / "dist"

    @app.get("/{path:path}")
    async def serve_frontend(path: str):
        if dist_dir.exists():
            candidate = dist_dir / path
            if path and candidate.exists() and candidate.is_file():
                return FileResponse(candidate)
            index_file = dist_dir / "index.html"
            if index_file.exists():
                return FileResponse(index_file)
        return HTMLResponse(
            "<html><body><h1>DeltaConverge React frontend not built</h1><p>Run npm install && npm run build in frontend/react.</p></body></html>",
            status_code=200,
        )

    return app


app = create_app()
