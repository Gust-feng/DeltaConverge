from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from adapters.web.dependencies import get_facade
from adapters.web.schemas import QARequestPayload, ReviewCreatePayload
from adapters.web.utils import serialize
from kernel.domain.models import QARequest, ReviewCreateRequest

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade

router = APIRouter(prefix="/api/v2/reviews", tags=["reviews"])


@router.post("")
async def create_review(payload: ReviewCreatePayload, facade: KernelFacade = Depends(get_facade)):
    request = ReviewCreateRequest(
        prompt=payload.prompt,
        model=payload.model,
        tools=payload.tools,
        auto_approve=payload.auto_approve,
        project_root=payload.project_root,
        session_id=payload.session_id,
        session_name=payload.session_name,
        agents=payload.agents,
        enable_static_scan=payload.enable_static_scan,
        diff_mode=payload.diff_mode,
        commit_from=payload.commit_from,
        commit_to=payload.commit_to,
        planner_model=payload.planner_model,
    )
    result = await facade.create_review_run(request)
    return serialize(result)


@router.get("/{run_id}")
def get_review_run(run_id: str, facade: KernelFacade = Depends(get_facade)):
    run = facade.get_review_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")
    return serialize(run)


@router.get("/{run_id}/stream")
async def stream_review(run_id: str, facade: KernelFacade = Depends(get_facade)):
    run = facade.get_review_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run_not_found")

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


@router.post("/{run_id}/qa")
async def ask_review_qa(
    run_id: str,
    payload: QARequestPayload,
    facade: KernelFacade = Depends(get_facade),
):
    try:
        response = await facade.ask_review_qa(
            QARequest(run_id=run_id, question=payload.question, model=payload.model, project_root=payload.project_root)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return serialize(response)


@router.get("/{run_id}/diff")
def get_review_diff(run_id: str, facade: KernelFacade = Depends(get_facade)):
    if not facade.get_review_run(run_id):
        raise HTTPException(status_code=404, detail="run_not_found")
    return facade.get_review_diff(run_id)
