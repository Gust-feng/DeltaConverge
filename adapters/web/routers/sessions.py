from __future__ import annotations

import json
from typing import TYPE_CHECKING, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import AliasChoices, BaseModel, Field

from adapters.web.dependencies import get_facade
from adapters.web.schemas import SessionUpdatePayload
from adapters.web.utils import serialize

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade

router = APIRouter(prefix="/api/v2/sessions", tags=["sessions"])


class SessionCreatePayload(BaseModel):
    session_id: Optional[str] = None
    name: Optional[str] = None
    project_root: Optional[str] = None


class ChatPayload(BaseModel):
    message: str
    model: str = "auto"
    tools: List[str] = Field(default_factory=list)
    auto_approve: bool = Field(
        default=False,
        validation_alias=AliasChoices("auto_approve", "autoApprove"),
    )
    project_root: Optional[str] = None


@router.get("")
def list_sessions(
    status: str | None = None,
    project_root: str | None = None,
    limit: int = 50,
    offset: int = 0,
    facade: KernelFacade = Depends(get_facade),
):
    sessions = facade.list_sessions(status=status, project_root=project_root, limit=limit, offset=offset)
    return {"items": serialize(sessions), "count": len(sessions), "limit": limit, "offset": offset}


@router.post("")
def create_session(payload: SessionCreatePayload, facade: KernelFacade = Depends(get_facade)):
    session = facade.create_session(
        session_id=payload.session_id,
        name=payload.name,
        project_root=payload.project_root,
    )
    return {"status": "ok", "session": serialize(session)}


@router.post("/{session_id}/chat")
async def chat_with_session(
    session_id: str,
    payload: ChatPayload,
    facade: KernelFacade = Depends(get_facade),
):
    try:
        run_id = await facade.create_chat_turn(
            session_id=session_id,
            message=payload.message,
            model=payload.model,
            tools=payload.tools,
            auto_approve=payload.auto_approve,
            project_root=payload.project_root,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session_not_found") from exc

    async def event_stream():
        async for event in facade.stream_review(run_id):
            yield f"data: {json.dumps(serialize(event), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{session_id}/status")
def get_session_status(session_id: str, facade: KernelFacade = Depends(get_facade)):
    status = facade.get_session_status(session_id)
    if status is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return status


@router.get("/{session_id}")
def get_session(session_id: str, facade: KernelFacade = Depends(get_facade)):
    detail = facade.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="session_not_found")
    return serialize(detail)


@router.get("/{session_id}/messages")
def get_session_messages(
    session_id: str,
    limit: int = 200,
    offset: int = 0,
    facade: KernelFacade = Depends(get_facade),
):
    detail = facade.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="session_not_found")
    messages = facade.get_session_messages(session_id, limit=limit, offset=offset)
    return {"items": serialize(messages), "count": len(messages), "limit": limit, "offset": offset}


@router.get("/{session_id}/events")
def get_session_events(
    session_id: str,
    run_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    facade: KernelFacade = Depends(get_facade),
):
    detail = facade.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="session_not_found")
    target_run_id = run_id or detail.summary.latest_run_id
    if not target_run_id:
        return {"items": [], "count": 0, "limit": limit, "offset": offset}
    events = facade.get_session_events(target_run_id, limit=limit, offset=offset)
    return {"items": serialize(events), "count": len(events), "limit": limit, "offset": offset, "run_id": target_run_id}


@router.patch("/{session_id}")
def update_session(
    session_id: str,
    payload: SessionUpdatePayload,
    facade: KernelFacade = Depends(get_facade),
):
    session = facade.update_session(session_id, name=payload.name, status=payload.status, tags=payload.tags)
    if not session:
        raise HTTPException(status_code=404, detail="session_not_found")
    return serialize(session)


@router.delete("/{session_id}")
def delete_session(session_id: str, facade: KernelFacade = Depends(get_facade)):
    detail = facade.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="session_not_found")
    facade.delete_session(session_id)
    return {"status": "deleted", "session_id": session_id}
