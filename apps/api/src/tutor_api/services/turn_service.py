"""One conversation turn (docs/architecture.md section 6).

`run_correction` is the LLM + domain path with no DB access. Both `handle_turn` and the
correction eval (evals/corrections/run_eval.py) use it, so the eval measures production behaviour.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tutor_contracts import TopicRef, TurnResponse, TurnResult

from tutor_api.curriculum import Curriculum, Scenario
from tutor_api.db.models import Mistake, Turn, VocabItem, utcnow
from tutor_api.db.repositories import (
    MasteryRepo,
    MistakeRepo,
    ProfileRepo,
    SessionRepo,
    TurnRepo,
    VocabRepo,
)
from tutor_api.domain import mastery as mastery_math
from tutor_api.domain.policy import Policy, resolve_policy
from tutor_api.domain.prompt import (
    PriorTurn,
    build_learner_summary,
    build_system_prompt,
    build_user_content,
)
from tutor_api.domain.tags import apply_policy, for_display, sanitize_tags, well_done_topics
from tutor_api.llm import LLMError, LLMTurnOutcome, TurnLLM
from tutor_api.services.context import AppContext
from tutor_api.services.errors import ConflictError, NotFoundError, UpstreamError

log = logging.getLogger(__name__)

WEAK_TOPICS_IN_SUMMARY = 5
RECENT_MISTAKES_IN_SUMMARY = 5


@dataclass(frozen=True)
class CorrectionRun:
    final: TurnResult  # all in-scope corrections: persisted, drives mistakes and mastery
    shown: TurnResult  # the display cut of `final`: what the learner sees
    raw: TurnResult | None  # exactly what the model returned (None on refusal)
    refused: bool
    unknown_tags: tuple[str, ...]
    policy_violations: tuple[str, ...]
    outcome: LLMTurnOutcome


async def run_correction(
    llm: TurnLLM,
    curriculum: Curriculum,
    policy: Policy,
    scenario: Scenario | None,
    learner_summary: str,
    recent_turns: Sequence[PriorTurn],
    text: str,
) -> CorrectionRun:
    system_prompt = build_system_prompt(curriculum, policy)
    user_content = build_user_content(policy, scenario, learner_summary, recent_turns, text)
    try:
        outcome = await llm.generate_turn(system_prompt, user_content)
    except LLMError as e:
        log.error("LLM turn failed: %s", e)
        raise UpstreamError(str(e)) from e

    if outcome.refused or outcome.result is None:
        final = TurnResult(
            reply=curriculum.lang.refusal_reply, corrections=[], new_vocab=[], grammar_tags=[]
        )
        return CorrectionRun(final, final, None, True, (), (), outcome)

    raw = outcome.result
    clean, sreport = sanitize_tags(raw, curriculum.topic_ids())
    if sreport.unknown_tags:
        log.warning(
            "unknown curriculum ids from model mapped to 'unknown': %s", sreport.unknown_tags
        )
    final, preport = apply_policy(clean, policy, curriculum)
    if preport.violations:
        log.info("level-policy enforcement: %s", preport.violations)
    return CorrectionRun(
        final,
        for_display(final, policy),
        raw,
        False,
        sreport.unknown_tags,
        preport.violations,
        outcome,
    )


async def handle_turn(ctx: AppContext, session_id: uuid.UUID, text: str) -> TurnResponse:
    # 1) Read context (short transaction; no DB transaction is held across the LLM call).
    async with ctx.sessionmaker() as db:
        session = await SessionRepo(db).get(session_id)
        if session is None:
            raise NotFoundError("session not found")
        if session.ended_at is not None:
            raise ConflictError("session has ended; start a new one")
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
        recent = await TurnRepo(db).recent(session.id, ctx.settings.recent_turns_in_prompt)
        weak = await MasteryRepo(db).weakest(profile.id, WEAK_TOPICS_IN_SUMMARY)
        mistakes = await MistakeRepo(db).list(profile.id, limit=RECENT_MISTAKES_IN_SUMMARY)
        summary = build_learner_summary(
            [(m.topic_id, m.mastery) for m in weak],
            [(m.wrong, m.right, m.rule_tag) for m in mistakes],
        )
        prior = [PriorTurn(role=t.role, text=t.text) for t in recent]
        profile_id = profile.id

    # 2) Model call + pure post-processing.
    run = await run_correction(ctx.llm, curriculum, policy, scenario, summary, prior, text)
    final = run.final

    # 3) Persist everything for this turn in one transaction.
    try:
        async with ctx.sessionmaker.begin() as db:
            session = await SessionRepo(db).get(session_id)
            if session is None or session.ended_at is not None:
                raise ConflictError("session ended while the turn was being processed")
            turns = TurnRepo(db)
            seq = await turns.next_seq(session_id)
            learner_turn = await turns.add(
                Turn(
                    session_id=session_id,
                    seq=seq,
                    role="learner",
                    text=text,
                    grammar_tags=list(final.grammar_tags),
                )
            )
            tutor_turn = await turns.add(
                Turn(
                    session_id=session_id,
                    seq=seq + 1,
                    role="tutor",
                    text=final.reply,
                    grammar_tags=[],
                    llm_model=run.outcome.model,
                    result_json={
                        "raw": run.raw.model_dump() if run.raw else None,
                        "final": final.model_dump(),
                        "shown": run.shown.model_dump(),
                        "refused": run.refused,
                        "refusal_category": run.outcome.refusal_category,
                        "unknown_tags": list(run.unknown_tags),
                        "policy_violations": list(run.policy_violations),
                        "cache_read_input_tokens": run.outcome.cache_read_input_tokens,
                        "cache_creation_input_tokens": run.outcome.cache_creation_input_tokens,
                    },
                    input_tokens=run.outcome.input_tokens,
                    output_tokens=run.outcome.output_tokens,
                )
            )
            if not run.refused:
                await _persist_learning(ctx, db, profile_id, learner_turn, text, final)
    except IntegrityError as e:
        raise ConflictError("another turn for this session was saved at the same time") from e

    praised = [] if run.refused else well_done_topics(final, policy, curriculum)
    return TurnResponse(
        **run.shown.model_dump(),
        turn_id=tutor_turn.id,
        well_done=[TopicRef(id=t, title=curriculum.topics[t].title) for t in praised],
    )


async def _persist_learning(
    ctx: AppContext,
    db: AsyncSession,
    profile_id: uuid.UUID,
    learner_turn: Turn,
    text: str,
    result: TurnResult,
) -> None:
    # Mistakes
    await MistakeRepo(db).add_many(
        Mistake(
            profile_id=profile_id,
            turn_id=learner_turn.id,
            wrong=c.wrong,
            right=c.right,
            rule_tag=c.rule_tag,
            explanation=c.explanation,
            severity=c.severity,
        )
        for c in result.corrections
    )

    # Grammar mastery
    mrepo = MasteryRepo(db)
    touched = set(result.grammar_tags) | {c.rule_tag for c in result.corrections}
    existing = await mrepo.get_many(profile_id, touched)
    current = {
        tid: mastery_math.TopicState(m.mastery, m.attempts, m.errors) for tid, m in existing.items()
    }
    updates = mastery_math.topic_updates(
        result.grammar_tags, result.corrections, current, ctx.settings.mastery_alpha
    )
    for tid, st in updates.items():
        await mrepo.upsert(profile_id, tid, st.mastery, st.attempts, st.errors, existing.get(tid))

    # Vocabulary: introduced words are "seen"; mastery rises only when the learner uses a word.
    vrepo = VocabRepo(db)
    known = await vrepo.all_for_profile(profile_id)
    now = utcnow()
    for lemma in mastery_math.vocab_used_correctly(text, known.keys(), result.corrections):
        item = known[lemma]
        item.mastery = mastery_math.on_correct_use(item.mastery, ctx.settings.mastery_alpha)
        item.seen_count += 1
        item.last_seen_at = now
    for v in result.new_vocab:
        lemma = v.lemma.strip()
        if not lemma:
            continue
        item = known.get(lemma)
        if item is None:
            item = VocabItem(
                profile_id=profile_id,
                lemma=lemma,
                translation=v.translation,
                pos=v.pos,
                seen_count=1,
                mastery=0.0,
                first_seen_at=now,
                last_seen_at=now,
            )
            vrepo.add(item)
            known[lemma] = item
        else:
            item.seen_count += 1
            item.last_seen_at = now
    await db.flush()
