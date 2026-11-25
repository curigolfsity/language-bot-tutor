from uuid import UUID

from fastapi import APIRouter
from tutor_contracts import (
    LessonAnswerOut,
    LessonAnswerRequest,
    LessonOut,
    LessonSuggestionsOut,
    StartLessonRequest,
)

from tutor_api.routes.deps import Ctx
from tutor_api.services import lesson_service

# Learner-scoped endpoints live under /learners; answering is addressed by the lesson id.
learner_router = APIRouter(prefix="/learners", tags=["lessons"])
router = APIRouter(prefix="/lessons", tags=["lessons"])


@learner_router.get("/{profile_id}/lessons", response_model=LessonSuggestionsOut)
async def suggested_lessons(profile_id: UUID, ctx: Ctx) -> LessonSuggestionsOut:
    """Grammar topics to study: suggestions (weak first, then next new) and all at the level."""
    return await lesson_service.suggestions(ctx, profile_id)


@learner_router.post("/{profile_id}/lessons", response_model=LessonOut, status_code=201)
async def start_lesson(profile_id: UUID, body: StartLessonRequest, ctx: Ctx) -> LessonOut:
    """Generate a short lesson with exercises on one grammar topic."""
    return await lesson_service.start_lesson(ctx, profile_id, body.topic_id)


@router.post("/{lesson_id}/answer", response_model=LessonAnswerOut)
async def answer(lesson_id: int, body: LessonAnswerRequest, ctx: Ctx) -> LessonAnswerOut:
    """Grade one exercise answer (in order) and return the next exercise."""
    return await lesson_service.answer(ctx, lesson_id, body.index, body.answer)
