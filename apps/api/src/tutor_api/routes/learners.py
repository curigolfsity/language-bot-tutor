from uuid import UUID

from fastapi import APIRouter, Query
from tutor_contracts import LearnerPatch, LearnerProfileOut, MistakeOut, SessionOut, VocabOut

from tutor_api.routes.deps import Ctx
from tutor_api.services import learner_service

router = APIRouter(prefix="/learners", tags=["learners"])


@router.get("/{profile_id}", response_model=LearnerProfileOut)
async def get_learner(profile_id: UUID, ctx: Ctx) -> LearnerProfileOut:
    return await learner_service.get_profile(ctx, profile_id)


@router.patch("/{profile_id}", response_model=LearnerProfileOut)
async def patch_learner(profile_id: UUID, body: LearnerPatch, ctx: Ctx) -> LearnerProfileOut:
    return await learner_service.patch_profile(ctx, profile_id, body)


@router.get("/{profile_id}/mistakes", response_model=list[MistakeOut])
async def list_mistakes(
    profile_id: UUID,
    ctx: Ctx,
    topic: str | None = None,
    limit: int = Query(default=20, ge=1, le=200),
) -> list[MistakeOut]:
    return await learner_service.list_mistakes(ctx, profile_id, topic, limit)


@router.get("/{profile_id}/vocab", response_model=list[VocabOut])
async def list_vocab(
    profile_id: UUID, ctx: Ctx, limit: int = Query(default=50, ge=1, le=500)
) -> list[VocabOut]:
    return await learner_service.list_vocab(ctx, profile_id, limit)


@router.get("/{profile_id}/active-session", response_model=SessionOut)
async def active_session(profile_id: UUID, ctx: Ctx) -> SessionOut:
    return await learner_service.active_session(ctx, profile_id)
