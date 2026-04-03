from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

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


def create_app() -> FastAPI:
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
