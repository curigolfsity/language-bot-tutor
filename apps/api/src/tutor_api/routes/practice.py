"""Word flashcards, placement test and weekly summary."""

from uuid import UUID

from fastapi import APIRouter, Response
from tutor_contracts import (
    PlacementAnswerRequest,
    PlacementStepOut,
    PracticeItemOut,
    ReminderClaimRequest,
    SavedWordsOut,
    SaveWordsRequest,
    WeeklySummaryOut,
    WordAnswerOut,
    WordAnswerRequest,
    WordQueueOut,
)

from tutor_api.routes.deps import Ctx
from tutor_api.services import placement_service, speech_service, weekly_service, words_service

learner_router = APIRouter(prefix="/learners", tags=["practice"])
router = APIRouter(tags=["practice"])


@learner_router.get("/{profile_id}/words/next", response_model=WordQueueOut)
async def next_word(profile_id: UUID, ctx: Ctx) -> WordQueueOut:
    """Next word flashcard due (words met in conversation)."""
    return await words_service.next_word(ctx, profile_id)


@router.post("/words/{word_id}/answer", response_model=WordAnswerOut)
async def answer_word(word_id: int, body: WordAnswerRequest, ctx: Ctx) -> WordAnswerOut:
    """Record whether the learner knew the word and schedule its next review."""
    return await words_service.answer_word(ctx, word_id, body.knew)


@router.get("/words/{word_id}/speech", response_class=Response)
async def word_speech(word_id: int, ctx: Ctx) -> Response:
    speech = await speech_service.word_speech(ctx, word_id)
    return Response(content=speech.audio, media_type=speech.mime)


@learner_router.post("/{profile_id}/placement", response_model=PlacementStepOut, status_code=201)
async def start_placement(profile_id: UUID, ctx: Ctx) -> PlacementStepOut:
    """Start a placement test. The result is a suggestion; the level is not changed."""
    return await placement_service.start(ctx, profile_id)


@router.post("/placement/{run_id}/answer", response_model=PlacementStepOut)
async def answer_placement(run_id: int, body: PlacementAnswerRequest, ctx: Ctx) -> PlacementStepOut:
    return await placement_service.answer(ctx, run_id, body.question_id, body.choice)


@learner_router.get("/{profile_id}/weekly", response_model=WeeklySummaryOut)
async def weekly(profile_id: UUID, ctx: Ctx) -> WeeklySummaryOut:
    """The learner's last 7 days."""
    return await weekly_service.summary(ctx, profile_id)


@router.post("/reminders/weekly/claim", response_model=list[WeeklySummaryOut])
async def claim_weekly(body: ReminderClaimRequest, ctx: Ctx) -> list[WeeklySummaryOut]:
    """Learners due their weekly summary now (each at most once a week)."""
    return await weekly_service.claim(ctx, body.provider, body.target_lang)


@learner_router.post("/{profile_id}/words", response_model=SavedWordsOut, status_code=201)
async def save_words(profile_id: UUID, body: SaveWordsRequest, ctx: Ctx) -> SavedWordsOut:
    """Save words the learner picked (e.g. from a tutor message) as flashcards."""
    return await words_service.save_words(ctx, profile_id, body.text, body.turn_id)


@learner_router.get("/{profile_id}/practice/next", response_model=PracticeItemOut)
async def practice_next(profile_id: UUID, ctx: Ctx) -> PracticeItemOut:
    """Next item of a mixed practice round (mistake card or word card)."""
    return await words_service.practice_next(ctx, profile_id)
