from uuid import UUID

from fastapi import APIRouter, Query
from tutor_contracts import (
    AskOut,
    AskRequest,
    DailyProgressOut,
    LearnerPatch,
    LearnerProfileOut,
    MistakeOut,
    ReviewQueueOut,
    SessionOut,
    VocabOut,
)

from tutor_api.routes.deps import Ctx
from tutor_api.services import habits_service, help_service, learner_service, review_service

router = APIRouter(prefix="/learners", tags=["learners"])


@router.get("/{profile_id}", response_model=LearnerProfileOut)
async def get_learner(profile_id: UUID, ctx: Ctx) -> LearnerProfileOut:
    return await learner_service.get_profile(ctx, profile_id)


@router.patch("/{profile_id}", response_model=LearnerProfileOut)
async def patch_learner(profile_id: UUID, body: LearnerPatch, ctx: Ctx) -> LearnerProfileOut:
    return await learner_service.patch_profile(ctx, profile_id, body)


@router.post("/{profile_id}/ask", response_model=AskOut)
async def ask(profile_id: UUID, body: AskRequest, ctx: Ctx) -> AskOut:
    """A side question (grammar, a word, ...). Does not interrupt or join the conversation."""
    return await help_service.ask(ctx, profile_id, body.question, body.turn_id)


@router.get("/{profile_id}/review/next", response_model=ReviewQueueOut)
async def next_review(profile_id: UUID, ctx: Ctx) -> ReviewQueueOut:
    """The next past mistake to practise (null card when caught up)."""
    return await review_service.next_card(ctx, profile_id)


@router.get("/{profile_id}/progress", response_model=DailyProgressOut)
async def get_progress(profile_id: UUID, ctx: Ctx) -> DailyProgressOut:
    """Streak and today's progress toward the daily goal."""
    return await habits_service.get_progress(ctx, profile_id)


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
