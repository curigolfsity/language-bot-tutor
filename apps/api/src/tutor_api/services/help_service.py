"""Learner help: hint / translate / suggest / explain on a tutor message, and side questions."""

from __future__ import annotations

import logging
import uuid

from tutor_contracts import AskOut, HelpKind, HelpOut

from tutor_api.db.repositories import ProfileRepo, SessionRepo, TurnRepo
from tutor_api.domain.policy import resolve_policy
from tutor_api.domain.prompt import PriorTurn, build_ask_prompt, build_help_prompt
from tutor_api.llm import LLMError
from tutor_api.services.context import AppContext
from tutor_api.services.errors import InvalidRequestError, NotFoundError, UpstreamError

log = logging.getLogger(__name__)

CONTEXT_TURNS = 6


async def get_help(ctx: AppContext, turn_id: int, kind: HelpKind) -> HelpOut:
    async with ctx.sessionmaker() as db:
        turns = TurnRepo(db)
        turn = await turns.get(turn_id)
        if turn is None:
            raise NotFoundError("turn not found")
        if turn.role != "tutor":
            raise InvalidRequestError("help is only available on tutor messages")
        session = await SessionRepo(db).get(turn.session_id)
        assert session is not None
        profile = await ProfileRepo(db).get(session.profile_id)
        assert profile is not None
        curriculum = ctx.curriculum(profile.target_lang)
        scenario = curriculum.scenarios.get(session.scenario_id) if session.scenario_id else None
        policy = resolve_policy(
            curriculum,
            profile.cefr_level,
            profile.native_lang,
            profile.explanation_lang_override,  # type: ignore[arg-type]
            scenario,
        )
        # Context before the tutor message (the message itself is passed separately).
        history = await turns.recent_until(session.id, turn.seq - 1, CONTEXT_TURNS)
        prior = [PriorTurn(role=t.role, text=t.text) for t in history]
        # Explain what the learner was shown ("final" for turns saved before the display cut).
        rj = turn.result_json or {}
        shown = rj.get("shown") or rj.get("final") or {}
        corrections = [
            (c["wrong"], c["right"], c.get("explanation", "")) for c in shown.get("corrections", [])
        ]

    system, user = build_help_prompt(policy, kind, scenario, prior, turn.text, corrections)
    try:
        outcome = await ctx.llm.generate_help(system, user)
    except LLMError as e:
        log.error("LLM help failed: %s", e)
        raise UpstreamError(str(e)) from e
    if outcome.refused or not outcome.text:
        return HelpOut(kind=kind, text=curriculum.lang.refusal_reply)
    return HelpOut(kind=kind, text=outcome.text.strip())


async def ask(
    ctx: AppContext, profile_id: uuid.UUID, question: str, turn_id: int | None = None
) -> AskOut:
    """Answer a side question. Context: the given tutor turn and the history before it, or
    else the open conversation (if any)."""
    async with ctx.sessionmaker() as db:
        profile = await ProfileRepo(db).get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        curriculum = ctx.curriculum(profile.target_lang)
        turns = TurnRepo(db)
        about: str | None = None
        if turn_id is not None:
            turn = await turns.get(turn_id)
            session = await SessionRepo(db).get(turn.session_id) if turn else None
            if turn is None or session is None or session.profile_id != profile.id:
                raise NotFoundError("turn not found")
            if turn.role != "tutor":
                raise InvalidRequestError("questions can only be attached to tutor messages")
            about = turn.text
            history = await turns.recent_until(session.id, turn.seq - 1, CONTEXT_TURNS)
        else:
            session = await SessionRepo(db).get_open(profile.id)
            history = await turns.recent(session.id, CONTEXT_TURNS) if session else []
        scenario = None
        if session is not None and session.scenario_id:
            scenario = curriculum.scenarios.get(session.scenario_id)
        prior = [PriorTurn(role=t.role, text=t.text) for t in history]
        policy = resolve_policy(
            curriculum,
            profile.cefr_level,
            profile.native_lang,
            profile.explanation_lang_override,  # type: ignore[arg-type]
            scenario,
        )

    system, user = build_ask_prompt(policy, scenario, prior, question, about)
    try:
        outcome = await ctx.llm.generate_help(system, user)
    except LLMError as e:
        log.error("LLM ask failed: %s", e)
        raise UpstreamError(str(e)) from e
    text = curriculum.lang.refusal_reply if outcome.refused or not outcome.text else outcome.text
    return AskOut(question=question, answer=text.strip())
