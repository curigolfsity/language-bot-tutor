"""Practise past mistakes with spaced repetition (docs/architecture.md section 8b)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from tutor_contracts import Correction, ReviewAnswerOut, ReviewCardOut, ReviewQueueOut

from tutor_api.db.models import ReviewItem, utcnow
from tutor_api.db.repositories import ProfileRepo, ReviewRepo
from tutor_api.domain.policy import resolve_policy
from tutor_api.domain.prompt import build_grade_prompt
from tutor_api.domain.review import after_answer, new_card, quick_grade
from tutor_api.llm import LLMError
from tutor_api.services.context import AppContext
from tutor_api.services.errors import NotFoundError, UpstreamError
from tutor_api.services.habits_service import record_message
from tutor_api.services.mappers import topic_title

log = logging.getLogger(__name__)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite (tests) returns naive datetimes; everything stored is UTC."""
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


async def add_cards(
    db: AsyncSession, profile_id: uuid.UUID, source_text: str, corrections: Iterable[Correction]
) -> None:
    """One card per distinct mistake. Repeating a known mistake sends its card back to box 0.
    Runs inside the caller's turn transaction."""
    repo = ReviewRepo(db)
    now = utcnow()
    sched = new_card(now)
    for c in corrections:
        wrong, right = c.wrong.strip(), c.right.strip()
        if not wrong or not right or wrong == right:
            continue
        card = await repo.find(profile_id, wrong, right)
        if card is None:
            repo.add(
                ReviewItem(
                    profile_id=profile_id,
                    source_text=source_text,
                    wrong=wrong,
                    right=right,
                    rule_tag=c.rule_tag,
                    explanation=c.explanation,
                    box=sched.box,
                    due_at=sched.due_at,
                    reviews=0,
                    lapses=0,
                    created_at=now,
                )
            )
        else:
            card.source_text, card.explanation, card.rule_tag = (
                source_text,
                c.explanation,
                c.rule_tag,
            )
            card.box, card.due_at = sched.box, sched.due_at
            card.lapses += 1
    await db.flush()


async def next_card(ctx: AppContext, profile_id: uuid.UUID) -> ReviewQueueOut:
    async with ctx.sessionmaker() as db:
        profile = await ProfileRepo(db).get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        repo, now = ReviewRepo(db), utcnow()
        card = await repo.next_due(profile_id, now)
        due = await repo.count_due(profile_id, now)
        total = await repo.count_all(profile_id)
        curriculum = ctx.curriculum(profile.target_lang)
        return ReviewQueueOut(
            card=ReviewCardOut(
                id=card.id,
                source_text=card.source_text,
                wrong=card.wrong,
                rule_tag=card.rule_tag,
                rule_title=topic_title(curriculum, card.rule_tag),
                box=card.box,
            )
            if card
            else None,
            due=due,
            total=total,
            next_due_at=None if card else _aware(await repo.earliest_due(profile_id)),
        )


async def answer_card(ctx: AppContext, card_id: int, answer: str) -> ReviewAnswerOut:
    # 1) Read (no transaction held across the model call).
    async with ctx.sessionmaker() as db:
        card = await ReviewRepo(db).get(card_id)
        if card is None:
            raise NotFoundError("review card not found")
        profile = await ProfileRepo(db).get(card.profile_id)
        assert profile is not None
        curriculum = ctx.curriculum(profile.target_lang)
        policy = resolve_policy(
            curriculum,
            profile.cefr_level,
            profile.native_lang,
            profile.explanation_lang_override,  # type: ignore[arg-type]
        )
        source, wrong, right, why = card.source_text, card.wrong, card.right, card.explanation
        profile_id = profile.id

    # 2) Grade: exact match is free; anything else is judged by the model.
    correct = quick_grade(answer, wrong, right)
    feedback: str | None = None
    if correct is None:
        system, user = build_grade_prompt(policy, source, wrong, right, why, answer)
        try:
            outcome = await ctx.llm.generate_grade(system, user)
        except LLMError as e:
            log.error("LLM grading failed: %s", e)
            raise UpstreamError(str(e)) from e
        correct = bool(outcome.grade and outcome.grade.correct)
        feedback = outcome.grade.feedback.strip() if outcome.grade else None

    # 3) Reschedule and count the practice.
    async with ctx.sessionmaker.begin() as db:
        repo = ReviewRepo(db)
        card = await repo.get(card_id)
        if card is None:
            raise NotFoundError("review card not found")
        now = utcnow()
        sched = after_answer(card.box, correct, now)
        card.box, card.due_at = sched.box, sched.due_at
        card.reviews += 1
        card.lapses += 0 if correct else 1
        card.last_reviewed_at = now
        progress = await record_message(db, profile_id, ctx.settings)
        due = await repo.count_due(profile_id, now)

    return ReviewAnswerOut(
        correct=correct,
        wrong=wrong,
        right=right,
        explanation=why,
        feedback=feedback,
        next_review_in_days=round((sched.due_at - now).total_seconds() / 86400, 2),
        due=due,
        progress=progress,
    )
