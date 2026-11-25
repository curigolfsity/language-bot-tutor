from fastapi import APIRouter
from tutor_contracts import ReviewAnswerOut, ReviewAnswerRequest

from tutor_api.routes.deps import Ctx
from tutor_api.services import review_service

router = APIRouter(prefix="/review", tags=["review"])


@router.post("/{card_id}/answer", response_model=ReviewAnswerOut)
async def answer(card_id: int, body: ReviewAnswerRequest, ctx: Ctx) -> ReviewAnswerOut:
    """Grade the learner's fix of a past mistake and schedule the card's next review."""
    return await review_service.answer_card(ctx, card_id, body.answer)
