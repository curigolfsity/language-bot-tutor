"""Past days of practice and the daily chat tidy."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query
from tutor_contracts import DayListOut, DayTranscriptOut, ReminderClaimRequest, TidyOut

from tutor_api.routes.deps import Ctx
from tutor_api.services import history_service

learner_router = APIRouter(prefix="/learners", tags=["history"])
router = APIRouter(tags=["history"])


@learner_router.get("/{profile_id}/days", response_model=DayListOut)
async def list_days(
    profile_id: UUID, ctx: Ctx, limit: int = Query(default=14, ge=1, le=60)
) -> DayListOut:
    """The learner's active days, newest first, with their numbers."""
    return await history_service.list_days(ctx, profile_id, limit)


@learner_router.get("/{profile_id}/days/{day}", response_model=DayTranscriptOut)
async def day_transcript(profile_id: UUID, day: date, ctx: Ctx) -> DayTranscriptOut:
    """One local day: its numbers and the conversation turns, in order."""
    return await history_service.transcript(ctx, profile_id, day)


@router.post("/reminders/tidy/claim", response_model=list[TidyOut])
async def claim_tidy(body: ReminderClaimRequest, ctx: Ctx) -> list[TidyOut]:
    """Learners whose chat is due its daily tidy (each at most once per local day)."""
    return await history_service.claim_tidy(ctx, body.provider, body.target_lang)
