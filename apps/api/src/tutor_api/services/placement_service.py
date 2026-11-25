"""Placement test: multiple-choice questions from curriculum/<lang>/placement.yaml.

Free (no model calls). The result is a suggestion only; the learner keeps choosing their level.
"""

from __future__ import annotations

import uuid

from tutor_contracts import (
    PlacementFeedbackOut,
    PlacementLevelScoreOut,
    PlacementQuestionOut,
    PlacementResultOut,
    PlacementStepOut,
)

from tutor_api.curriculum import Curriculum
from tutor_api.curriculum.models import Placement
from tutor_api.db.models import LearnerProfile, PlacementRun, utcnow
from tutor_api.db.repositories import PlacementRepo, ProfileRepo
from tutor_api.domain.placement import Answered, Step, next_step
from tutor_api.services.context import AppContext
from tutor_api.services.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    UnavailableError,
)


def _placement(curriculum: Curriculum) -> Placement:
    if curriculum.placement is None:
        raise UnavailableError(f"no placement test for {curriculum.lang.name} yet")
    return curriculum.placement


def _answers(run: PlacementRun) -> list[Answered]:
    return [Answered(a["question_id"], a["level"], bool(a["correct"])) for a in run.answers]


def _step_out(
    run: PlacementRun,
    step: Step,
    curriculum: Curriculum,
    profile: LearnerProfile,
    last: PlacementFeedbackOut | None = None,
) -> PlacementStepOut:
    question = None
    if step.question is not None:
        q = step.question
        question = PlacementQuestionOut(
            id=q.id,
            level=q.level,
            prompt=q.prompt,
            options=list(q.options),
            number=len(run.answers) + 1,
        )
    result = None
    if step.result_level is not None:
        policy = curriculum.levels[step.result_level]
        result = PlacementResultOut(
            level=step.result_level,
            label=policy.label,
            can_do=policy.can_do,
            current_level=profile.cefr_level,
            scores=[
                PlacementLevelScoreOut(level=s.level, right=s.right, asked=s.asked)
                for s in step.scores
            ],
        )
    return PlacementStepOut(run_id=run.id, last=last, question=question, result=result)


async def start(ctx: AppContext, profile_id: uuid.UUID) -> PlacementStepOut:
    async with ctx.sessionmaker.begin() as db:
        profile = await ProfileRepo(db).get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        curriculum = ctx.curriculum(profile.target_lang)
        placement = _placement(curriculum)
        run = await PlacementRepo(db).add(PlacementRun(profile_id=profile_id, answers=[]))
        step = next_step(placement, curriculum.ordered_levels, [], seed=run.id)
        return _step_out(run, step, curriculum, profile)


async def answer(ctx: AppContext, run_id: int, question_id: str, choice: int) -> PlacementStepOut:
    async with ctx.sessionmaker.begin() as db:
        run = await PlacementRepo(db).get(run_id, for_update=True)
        if run is None:
            raise NotFoundError("placement test not found")
        profile = await ProfileRepo(db).get(run.profile_id)
        assert profile is not None
        curriculum = ctx.curriculum(profile.target_lang)
        placement = _placement(curriculum)
        if run.finished_at is not None:
            raise ConflictError("this placement test is already finished")
        step = next_step(placement, curriculum.ordered_levels, _answers(run), seed=run.id)
        if step.question is None or step.question.id != question_id:
            if any(a["question_id"] == question_id for a in run.answers):
                raise ConflictError("that question was already answered")
            raise InvalidRequestError("that is not the current question")
        q = step.question
        if choice >= len(q.options):
            raise InvalidRequestError("no such option")
        correct = choice == q.answer
        run.answers = [
            *run.answers,
            {"question_id": q.id, "level": q.level, "choice": choice, "correct": correct},
        ]
        step = next_step(placement, curriculum.ordered_levels, _answers(run), seed=run.id)
        if step.result_level is not None:
            run.result_level, run.finished_at = step.result_level, utcnow()
        last = PlacementFeedbackOut(correct=correct, right_option=q.options[q.answer])
        return _step_out(run, step, curriculum, profile, last)
