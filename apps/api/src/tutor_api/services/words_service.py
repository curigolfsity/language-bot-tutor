"""Word flashcards: words met in conversation, self-graded, on the Leitner schedule."""

from __future__ import annotations

import uuid

from tutor_contracts import (
    PracticeItemOut,
    ReviewCardOut,
    SavedWordsOut,
    WordAnswerOut,
    WordCardOut,
    WordQueueOut,
)

from tutor_api.db.models import VocabItem, utcnow
from tutor_api.db.repositories import ProfileRepo, ReviewRepo, TurnRepo, VocabRepo
from tutor_api.domain import mastery as mastery_math
from tutor_api.domain.policy import resolve_policy
from tutor_api.domain.prompt import build_save_words_prompt
from tutor_api.domain.review import after_answer, new_card
from tutor_api.llm import LLMError
from tutor_api.services.context import AppContext
from tutor_api.services.errors import InvalidRequestError, NotFoundError, UpstreamError
from tutor_api.services.habits_service import record_message
from tutor_api.services.mappers import topic_title
from tutor_api.services.review_service import _aware
from tutor_api.services.usage import record_call

MAX_WORDS_PER_SAVE = 10


async def next_word(ctx: AppContext, profile_id: uuid.UUID) -> WordQueueOut:
    async with ctx.sessionmaker() as db:
        if await ProfileRepo(db).get(profile_id) is None:
            raise NotFoundError("learner profile not found")
        repo, now = VocabRepo(db), utcnow()
        item = await repo.next_due(profile_id, now)
        return WordQueueOut(
            card=WordCardOut(
                id=item.id,
                word=item.lemma,
                translation=item.translation,
                pos=item.pos,
                box=item.box,
            )
            if item
            else None,
            due=await repo.count_due(profile_id, now),
            total=await repo.count_cards(profile_id),
            next_due_at=None if item else _aware(await repo.earliest_due(profile_id)),
        )


async def answer_word(ctx: AppContext, word_id: int, knew: bool) -> WordAnswerOut:
    async with ctx.sessionmaker.begin() as db:
        repo = VocabRepo(db)
        item = await repo.get(word_id)
        if item is None:
            raise NotFoundError("word not found")
        now = utcnow()
        sched = after_answer(item.box, knew, now)
        item.box, item.due_at = sched.box, sched.due_at
        if knew:
            item.mastery = mastery_math.on_correct_use(item.mastery, ctx.settings.mastery_alpha)
        progress = await record_message(db, item.profile_id, ctx.settings)
        return WordAnswerOut(
            knew=knew,
            next_review_in_days=round((sched.due_at - now).total_seconds() / 86400, 2),
            due=await repo.count_due(item.profile_id, now),
            progress=progress,
        )


def _card(item: VocabItem) -> WordCardOut:
    return WordCardOut(
        id=item.id, word=item.lemma, translation=item.translation, pos=item.pos, box=item.box
    )


async def save_words(
    ctx: AppContext, profile_id: uuid.UUID, text: str, turn_id: int | None
) -> SavedWordsOut:
    """Words the learner chose to keep (e.g. from a tutor message): entries are written by the
    help model, then queued as flashcards. Words already saved are returned as they are."""
    async with ctx.sessionmaker() as db:
        profile = await ProfileRepo(db).get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        curriculum = ctx.curriculum(profile.target_lang)
        context = None
        if turn_id is not None:
            turn = await TurnRepo(db).get(turn_id)
            context = turn.text if turn is not None else None
        policy = resolve_policy(
            curriculum,
            profile.cefr_level,
            profile.native_lang,
            profile.explanation_lang_override,  # type: ignore[arg-type]
        )
    system, user = build_save_words_prompt(curriculum, policy, text, context)
    try:
        outcome = await ctx.llm.generate_vocab(system, user)
    except LLMError as e:
        raise UpstreamError(str(e)) from e
    await record_call(ctx, "words", curriculum.code, outcome)
    if outcome.refused or not outcome.items:
        raise InvalidRequestError("I couldn't find a word to save there")

    async with ctx.sessionmaker.begin() as db:
        repo = VocabRepo(db)
        known = await repo.all_for_profile(profile_id)
        now = utcnow()
        saved: list[VocabItem] = []
        for v in outcome.items[:MAX_WORDS_PER_SAVE]:
            lemma = v.lemma.strip()[:128]
            if not lemma:
                continue
            item = known.get(lemma)
            if item is None:
                item = VocabItem(
                    profile_id=profile_id,
                    lemma=lemma,
                    translation=v.translation[:256],
                    pos=v.pos[:32],
                    seen_count=1,
                    mastery=0.0,
                    first_seen_at=now,
                    last_seen_at=now,
                    box=0,
                    due_at=new_card(now).due_at,
                )
                repo.add(item)
                known[lemma] = item
            elif item.due_at is None:
                item.box, item.due_at = 0, new_card(now).due_at
            saved.append(item)
        await db.flush()
        return SavedWordsOut(words=[_card(i) for i in saved])


async def practice_next(ctx: AppContext, profile_id: uuid.UUID) -> PracticeItemOut:
    """The most overdue card of either kind, so a round mixes mistakes and words."""
    async with ctx.sessionmaker() as db:
        profile = await ProfileRepo(db).get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        now = utcnow()
        reviews, words = ReviewRepo(db), VocabRepo(db)
        card = await reviews.next_due(profile_id, now)
        word = await words.next_due(profile_id, now)
        mistakes_due = await reviews.count_due(profile_id, now)
        words_due = await words.count_due(profile_id, now)
        kind = None
        if card is not None and (word is None or _aware(card.due_at) <= _aware(word.due_at)):
            kind = "mistake"
        elif word is not None:
            kind = "word"
        curriculum = ctx.curriculum(profile.target_lang)
        return PracticeItemOut(
            kind=kind,  # type: ignore[arg-type]
            mistake=ReviewCardOut(
                id=card.id,
                source_text=card.source_text,
                wrong=card.wrong,
                rule_tag=card.rule_tag,
                rule_title=topic_title(curriculum, card.rule_tag),
                box=card.box,
            )
            if kind == "mistake" and card is not None
            else None,
            word=_card(word) if kind == "word" and word is not None else None,
            mistakes_due=mistakes_due,
            words_due=words_due,
        )
