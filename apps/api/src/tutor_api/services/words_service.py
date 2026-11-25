"""Word flashcards: words met in conversation, self-graded, on the Leitner schedule."""

from __future__ import annotations

import uuid

from tutor_contracts import WordAnswerOut, WordCardOut, WordQueueOut

from tutor_api.db.models import utcnow
from tutor_api.db.repositories import ProfileRepo, VocabRepo
from tutor_api.domain import mastery as mastery_math
from tutor_api.domain.review import after_answer
from tutor_api.services.context import AppContext
from tutor_api.services.errors import NotFoundError
from tutor_api.services.habits_service import record_message
from tutor_api.services.review_service import _aware


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
