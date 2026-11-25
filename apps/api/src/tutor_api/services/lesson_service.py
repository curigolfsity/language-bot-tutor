"""Grammar lessons: suggest topics, generate a lesson with exercises, grade answers.

A lesson is generated once per start (explanation + exercises, one model call) and stored in
`lesson_runs`, so answers are graded against what the learner was actually shown. Exercise
answers update the topic's mastery like conversation turns do, and count as practice.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from tutor_contracts import (
    ExerciseOut,
    LessonAnswerOut,
    LessonOut,
    LessonPartsOut,
    LessonSuggestionsOut,
    LessonTopicOut,
)

from tutor_api.curriculum import Curriculum
from tutor_api.curriculum.models import GrammarTopic
from tutor_api.db.models import LearnerProfile, LessonRun, utcnow
from tutor_api.db.repositories import LessonRepo, MasteryRepo, MistakeRepo, ProfileRepo
from tutor_api.domain import mastery as mastery_math
from tutor_api.domain.lessons import (
    TopicStats,
    check_exercise,
    lesson_plain_text,
    suggest_topics,
)
from tutor_api.domain.policy import Policy, resolve_policy
from tutor_api.domain.prompt import build_exercise_grade_prompt, build_lesson_prompt
from tutor_api.llm import LLMError
from tutor_api.services.context import AppContext
from tutor_api.services.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    UpstreamError,
)
from tutor_api.services.habits_service import record_message
from tutor_api.services.usage import record_call

log = logging.getLogger(__name__)

MISTAKES_IN_LESSON = 5


def _policy(curriculum: Curriculum, profile: LearnerProfile) -> Policy:
    return resolve_policy(
        curriculum,
        profile.cefr_level,
        profile.native_lang,
        profile.explanation_lang_override,  # type: ignore[arg-type]
    )


def _topic_out(
    topic: GrammarTopic,
    stats: dict[str, TopicStats],
    studied: dict[str, int],
    reason: str | None = None,
) -> LessonTopicOut:
    s = stats.get(topic.id)
    return LessonTopicOut(
        id=topic.id,
        title=topic.title,
        level=topic.level,
        mastery=round(s.mastery, 2) if s and s.attempts else None,
        lessons_taken=studied.get(topic.id, 0),
        reason=reason,  # type: ignore[arg-type]
    )


def _exercise_out(run: LessonRun, index: int) -> ExerciseOut | None:
    if index >= len(run.exercises):
        return None
    ex = run.exercises[index]
    return ExerciseOut(
        index=index,
        total=len(run.exercises),
        kind=ex["kind"],
        instruction=ex["instruction"],
        prompt=ex["prompt"],
    )


async def suggestions(ctx: AppContext, profile_id: uuid.UUID) -> LessonSuggestionsOut:
    async with ctx.sessionmaker() as db:
        profile = await ProfileRepo(db).get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        curriculum = ctx.curriculum(profile.target_lang)
        rows = await MasteryRepo(db).all_for_profile(profile_id)
        studied = await LessonRepo(db).topics_studied(profile_id)
    stats = {tid: TopicStats(m.mastery, m.attempts, m.errors) for tid, m in rows.items()}
    topics = sorted(
        curriculum.topics_up_to(profile.cefr_level), key=lambda t: curriculum.rank(t.level)
    )
    picks = suggest_topics(topics, profile.cefr_level, stats)
    return LessonSuggestionsOut(
        suggested=[
            _topic_out(curriculum.topics[p.topic_id], stats, studied, p.reason) for p in picks
        ],
        level_topics=[
            _topic_out(t, stats, studied) for t in topics if t.level == profile.cefr_level
        ],
    )


async def start_lesson(ctx: AppContext, profile_id: uuid.UUID, topic_id: str) -> LessonOut:
    # 1) Context.
    async with ctx.sessionmaker() as db:
        profile = await ProfileRepo(db).get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        curriculum = ctx.curriculum(profile.target_lang)
        topic = curriculum.topics.get(topic_id)
        if topic is None or topic.deprecated:
            raise NotFoundError(f"unknown grammar topic {topic_id!r}")
        mistakes = await MistakeRepo(db).list(profile_id, topic_id, limit=20)
        state = (await MasteryRepo(db).get_many(profile_id, {topic_id})).get(topic_id)
        studied = await LessonRepo(db).topics_studied(profile_id)
        policy = _policy(curriculum, profile)
    own = list(dict.fromkeys((m.wrong, m.right) for m in mistakes))[:MISTAKES_IN_LESSON]

    # 2) Generate (no transaction held across the model call).
    system, user = build_lesson_prompt(
        curriculum, policy, topic, own, ctx.settings.lesson_exercises
    )
    try:
        outcome = await ctx.llm.generate_lesson(system, user)
    except LLMError as e:
        log.error("LLM lesson failed: %s", e)
        raise UpstreamError(str(e)) from e
    await record_call(ctx, "lesson", curriculum.code, outcome)
    if outcome.refused or outcome.lesson is None:
        raise UpstreamError("the model declined to write this lesson")
    exercises: list[dict[str, Any]] = [
        ex.model_dump()
        for ex in outcome.lesson.exercises
        if ex.prompt.strip() and ex.answer.strip()
    ][: ctx.settings.lesson_exercises]
    if not exercises:
        raise UpstreamError("the generated lesson had no usable exercises")
    parts = outcome.lesson.model_dump(exclude={"exercises"})

    # 3) Store.
    async with ctx.sessionmaker.begin() as db:
        run = await LessonRepo(db).add(
            LessonRun(
                profile_id=profile_id,
                topic_id=topic_id,
                explanation=lesson_plain_text(parts),
                parts=parts,
                exercises=exercises,
                answers=[],
                correct=0,
                llm_model=outcome.model,
            )
        )
        stats = {topic_id: TopicStats(state.mastery, state.attempts, state.errors)} if state else {}
        return LessonOut(
            id=run.id,
            topic=_topic_out(topic, stats, {**studied, topic_id: studied.get(topic_id, 0) + 1}),
            explanation=run.explanation,
            parts=LessonPartsOut.model_validate(parts),
            exercise=_exercise_out(run, 0),
        )


async def answer(ctx: AppContext, run_id: int, index: int, answer_text: str) -> LessonAnswerOut:
    # 1) Read.
    async with ctx.sessionmaker() as db:
        run = await LessonRepo(db).get(run_id)
        if run is None:
            raise NotFoundError("lesson not found")
        if index >= len(run.exercises):
            raise InvalidRequestError("no such exercise in this lesson")
        if index < len(run.answers):
            raise ConflictError("that exercise was already answered")
        if index > len(run.answers):
            raise InvalidRequestError("answer the exercises in order")
        profile = await ProfileRepo(db).get(run.profile_id)
        assert profile is not None
        policy = _policy(ctx.curriculum(profile.target_lang), profile)
        ex = dict(run.exercises[index])
    accepted = [ex["answer"], *ex.get("also_accept", [])]

    # 2) Grade: an exact match is free; anything else is judged by the model.
    correct = check_exercise(answer_text, accepted)
    feedback: str | None = None
    if correct is None:
        system, user = build_exercise_grade_prompt(
            policy, ex["kind"], ex["instruction"], ex["prompt"], accepted, answer_text
        )
        try:
            outcome = await ctx.llm.generate_grade(system, user)
        except LLMError as e:
            log.error("LLM exercise grading failed: %s", e)
            raise UpstreamError(str(e)) from e
        await record_call(ctx, "grade", profile.target_lang, outcome)
        correct = bool(outcome.grade and outcome.grade.correct)
        feedback = outcome.grade.feedback.strip() if outcome.grade else None

    # 3) Record, update mastery, count the practice.
    async with ctx.sessionmaker.begin() as db:
        run = await LessonRepo(db).get(run_id)
        assert run is not None
        if index != len(run.answers):  # answered concurrently
            raise ConflictError("that exercise was already answered")
        run.answers = [*run.answers, {"answer": answer_text, "correct": correct}]
        run.correct += int(correct)
        if len(run.answers) == len(run.exercises):
            run.finished_at = utcnow()

        mrepo = MasteryRepo(db)
        existing = (await mrepo.get_many(run.profile_id, {run.topic_id})).get(run.topic_id)
        m, attempts, errors = (
            (existing.mastery, existing.attempts, existing.errors) if existing else (0.0, 0, 0)
        )
        alpha = ctx.settings.mastery_alpha
        if correct:
            m = mastery_math.on_correct_use(m, alpha)
        else:
            m, errors = mastery_math.on_error(m, alpha, "major"), errors + 1
        await mrepo.upsert(run.profile_id, run.topic_id, m, attempts + 1, errors, existing)
        progress = await record_message(db, run.profile_id, ctx.settings)

        return LessonAnswerOut(
            correct=correct,
            expected=ex["answer"],
            why=ex.get("why", ""),
            feedback=feedback,
            score=run.correct,
            answered=len(run.answers),
            total=len(run.exercises),
            next=_exercise_out(run, index + 1),
            mastery=round(m, 2),
            progress=progress,
        )
