from __future__ import annotations

import uuid

from tutor_contracts import CreateSessionRequest, MistakeCount, SessionOut, SessionSummary

from tutor_api.db.models import Turn, utcnow
from tutor_api.db.repositories import (
    MasteryRepo,
    MistakeRepo,
    ProfileRepo,
    SessionRepo,
    TurnRepo,
    VocabRepo,
)
from tutor_api.domain.mastery import aggregate_score
from tutor_api.services.context import AppContext
from tutor_api.services.errors import InvalidRequestError, NotFoundError
from tutor_api.services.mappers import session_out, topic_title, vocab_out


async def start_session(ctx: AppContext, req: CreateSessionRequest) -> SessionOut:
    """Close any open session for the profile, then open a new one with the tutor's first line."""
    async with ctx.sessionmaker.begin() as db:
        profile = await ProfileRepo(db).get(req.profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        curriculum = ctx.curriculum(profile.target_lang)

        scenario = None
        if req.scenario_id:
            scenario = curriculum.scenarios.get(req.scenario_id)
            if scenario is None or scenario.deprecated:
                raise InvalidRequestError(f"unknown scenario {req.scenario_id!r}")

        sessions = SessionRepo(db)
        open_session = await sessions.get_open(profile.id)
        if open_session is not None:
            await sessions.close(open_session)

        session = await sessions.create(
            profile.id,
            mode="roleplay" if scenario else "free",
            scenario_id=scenario.id if scenario else None,
            level=profile.cefr_level,
        )
        opening = (
            scenario.opening_line
            if scenario
            else curriculum.levels[profile.cefr_level].free_opening
        )
        opening_turn = await TurnRepo(db).add(
            Turn(session_id=session.id, seq=0, role="tutor", text=opening, grammar_tags=[])
        )
        return session_out(session, opening, curriculum, opening_turn.id)


async def end_session(ctx: AppContext, session_id: uuid.UUID) -> SessionSummary:
    """Close the session (idempotent), refresh aggregate skill scores, return a summary."""
    async with ctx.sessionmaker.begin() as db:
        sessions = SessionRepo(db)
        session = await sessions.get(session_id)
        if session is None:
            raise NotFoundError("session not found")
        if session.ended_at is None:
            await sessions.close(session)
        ended_at = session.ended_at or utcnow()

        profiles = ProfileRepo(db)
        profile = await profiles.get(session.profile_id)
        assert profile is not None
        curriculum = ctx.curriculum(profile.target_lang)

        # Skill scores change only from aggregates. Phase 1 updates grammar and vocab only.
        grammar_score = aggregate_score(await MasteryRepo(db).all_masteries(profile.id))
        vocab_score = aggregate_score(await VocabRepo(db).all_masteries(profile.id))
        await profiles.upsert_skill(profile.id, "grammar", profile.cefr_level, grammar_score)
        await profiles.upsert_skill(profile.id, "vocab", profile.cefr_level, vocab_score)

        turn_count = await TurnRepo(db).count_learner_turns(session.id)
        top = await MistakeRepo(db).top_tags_for_session(session.id)
        new_vocab = await VocabRepo(db).first_seen_between(profile.id, session.started_at, ended_at)
        return SessionSummary(
            session_id=session.id,
            turn_count=turn_count,
            top_mistakes=[
                MistakeCount(rule_tag=t, title=topic_title(curriculum, t), count=n) for t, n in top
            ],
            new_vocab=[vocab_out(v) for v in new_vocab],
        )
