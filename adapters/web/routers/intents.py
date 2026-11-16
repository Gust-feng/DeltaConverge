from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from adapters.web.dependencies import get_facade

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade

intents_router = APIRouter(prefix="/api/v2/intent", tags=["intent"])


class IntentUpdatePayload(BaseModel):
    project_root: str
    content: str


class IntentAnalyzePayload(BaseModel):
    project_root: str
    model: Optional[str] = None
    force_refresh: bool = Field(default=False)


@intents_router.get("")
def get_intent(
    project_root: Optional[str] = None,
    project_name: Optional[str] = None,
    facade: KernelFacade = Depends(get_facade),
):
    if not (project_root or "").strip() and not (project_name or "").strip():
        raise HTTPException(status_code=400, detail="project_root_required")
    result = facade.get_intent(project_root, project_name)
    if not result.get("found"):
        raise HTTPException(status_code=404, detail="intent_cache_not_found")
    return result


@intents_router.post("/update")
def update_intent(payload: IntentUpdatePayload, facade: KernelFacade = Depends(get_facade)):
    if not payload.content or not payload.content.strip():
        raise HTTPException(status_code=400, detail="Content cannot be empty")
    return facade.update_intent(payload.project_root, payload.content)


@intents_router.post("/analyze-stream")
async def analyze_intent_stream(
    payload: IntentAnalyzePayload,
    facade: KernelFacade = Depends(get_facade),
):
    if not Path(payload.project_root).is_dir():
        raise HTTPException(status_code=400, detail="project_root_not_found")

    async def event_stream():
        done_sent = False
        try:
            async for event in facade.stream_intent_analysis(
                payload.project_root,
                model=payload.model,
                force_refresh=payload.force_refresh,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done":
                    done_sent = True
                    break
        except Exception as exc:
            error_payload = {"type": "error", "message": str(exc)}
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
        finally:
            if not done_sent:
                yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
