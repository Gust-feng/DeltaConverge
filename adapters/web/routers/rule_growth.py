from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from adapters.web.dependencies import get_facade
from adapters.web.schemas import RuleApplyPayload, RuleCleanupPayload, RulePromotePayload
from adapters.web.utils import serialize

if TYPE_CHECKING:
    from kernel.application.facade import KernelFacade


router = APIRouter(prefix="/api/v2/rule-growth", tags=["rule-growth"])


@router.get("/summary")
def get_summary(facade: KernelFacade = Depends(get_facade)):
    return serialize(facade.get_rule_growth_summary())


@router.get("/enhanced-suggestions")
def get_enhanced_suggestions(facade: KernelFacade = Depends(get_facade)):
    return serialize(facade.get_rule_growth_suggestions())


@router.post("/apply")
def apply_rule(payload: RuleApplyPayload, facade: KernelFacade = Depends(get_facade)):
    return serialize(facade.apply_rule_growth_rule(payload.rule_id))


@router.post("/promote-hint")
def promote_hint(payload: RulePromotePayload, facade: KernelFacade = Depends(get_facade)):
    return serialize(
        facade.promote_rule_growth_hint(
            language=payload.language,
            tags=payload.tags,
            suggested_context_level=payload.suggested_context_level,
            sample_count=payload.sample_count,
            consistency=payload.consistency,
            conflict_type=payload.conflict_type,
        )
    )


@router.post("/cleanup")
def cleanup(payload: RuleCleanupPayload, facade: KernelFacade = Depends(get_facade)):
    return serialize(
        facade.cleanup_rule_growth(
            max_age_days=payload.max_age_days,
            clear_session=payload.clear_session,
        )
    )
