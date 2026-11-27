"""Data access. Repositories take an AsyncSession; services own the transaction.

Upserts are written as select-then-write so the same code runs on Postgres and the SQLite test
database. Writes for one profile happen inside one service transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tutor_api.db.models import (
    DailyActivity,
    GrammarMastery,
    LearnerProfile,
    LessonCache,
    LessonRun,
    Mistake,
    PlacementRun,
    ReviewItem,
    Session,
    SkillLevel,
    Turn,
    User,
    UserIdentity,
    VocabItem,
    utcnow,
)


class UserRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_identity(self, provider: str, external_id: str) -> User | None:
        stmt = (
            select(User)
            .join(UserIdentity, UserIdentity.user_id == User.id)
            .where(UserIdentity.provider == provider, UserIdentity.external_id == external_id)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def create_with_identity(
        self, provider: str, external_id: str, display_name: str
    ) -> User:
        user = User(display_name=display_name)
        self.db.add(user)
        await self.db.flush()
        self.db.add(UserIdentity(provider=provider, external_id=external_id, user_id=user.id))
        await self.db.flush()
        return user


class ProfileRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, profile_id: uuid.UUID) -> LearnerProfile | None:
        return await self.db.get(LearnerProfile, profile_id)

    async def get_for_user(self, user_id: uuid.UUID, target_lang: str) -> LearnerProfile | None:
        stmt = select(LearnerProfile).where(
            LearnerProfile.user_id == user_id, LearnerProfile.target_lang == target_lang
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def create(
        self, user_id: uuid.UUID, target_lang: str, native_lang: str, cefr_level: str
    ) -> LearnerProfile:
        p = LearnerProfile(
            user_id=user_id, target_lang=target_lang, native_lang=native_lang, cefr_level=cefr_level
        )
        self.db.add(p)
        await self.db.flush()
        return p

    async def skills(self, profile_id: uuid.UUID) -> Sequence[SkillLevel]:
        stmt = (
            select(SkillLevel).where(SkillLevel.profile_id == profile_id).order_by(SkillLevel.skill)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def upsert_skill(
        self, profile_id: uuid.UUID, skill: str, cefr_level: str, score: float | None = None
    ) -> None:
        row = await self.db.get(SkillLevel, (profile_id, skill))
        if row is None:
            self.db.add(
                SkillLevel(
                    profile_id=profile_id, skill=skill, cefr_level=cefr_level, score=score or 0.0
                )
            )
        else:
            row.cefr_level = cefr_level
            if score is not None:
                row.score = score
            row.updated_at = utcnow()
        await self.db.flush()


class SessionRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, session_id: uuid.UUID) -> Session | None:
        return await self.db.get(Session, session_id)

    async def get_open(self, profile_id: uuid.UUID) -> Session | None:
        stmt = select(Session).where(Session.profile_id == profile_id, Session.ended_at.is_(None))
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def create(
        self, profile_id: uuid.UUID, mode: str, scenario_id: str | None, level: str
    ) -> Session:
        s = Session(profile_id=profile_id, mode=mode, scenario_id=scenario_id, level_at_start=level)
        self.db.add(s)
        await self.db.flush()
        return s

    async def close(self, session: Session, at: datetime | None = None) -> None:
        session.ended_at = at or utcnow()
        await self.db.flush()


class TurnRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def next_seq(self, session_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(Turn.seq), -1)).where(Turn.session_id == session_id)
        return int((await self.db.execute(stmt)).scalar_one()) + 1

    async def add(self, turn: Turn) -> Turn:
        self.db.add(turn)
        await self.db.flush()
        return turn

    async def recent(self, session_id: uuid.UUID, limit: int) -> list[Turn]:
        if limit <= 0:
            return []
        stmt = (
            select(Turn).where(Turn.session_id == session_id).order_by(Turn.seq.desc()).limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(reversed(rows))

    async def get(self, turn_id: int) -> Turn | None:
        return await self.db.get(Turn, turn_id)

    async def recent_until(self, session_id: uuid.UUID, seq: int, limit: int) -> list[Turn]:
        """Up to `limit` turns ending at (and including) `seq`, oldest first."""
        if limit <= 0:
            return []
        stmt = (
            select(Turn)
            .where(Turn.session_id == session_id, Turn.seq <= seq)
            .order_by(Turn.seq.desc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return list(reversed(rows))

    async def first(self, session_id: uuid.UUID) -> Turn | None:
        stmt = select(Turn).where(Turn.session_id == session_id).order_by(Turn.seq).limit(1)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def for_profile_between(
        self, profile_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[Turn, Session]]:
        """The profile's turns created in [start, end), oldest first, with their session."""
        stmt = (
            select(Turn, Session)
            .join(Session, Session.id == Turn.session_id)
            .where(
                Session.profile_id == profile_id,
                Turn.created_at >= start,
                Turn.created_at < end,
            )
            .order_by(Turn.created_at, Turn.session_id, Turn.seq)
        )
        return [(t, s) for t, s in (await self.db.execute(stmt)).all()]

    async def count_learner_turns(self, session_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(Turn.session_id == session_id, Turn.role == "learner")
        return int((await self.db.execute(stmt)).scalar_one())


class MistakeRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add_many(self, mistakes: Iterable[Mistake]) -> None:
        self.db.add_all(list(mistakes))
        await self.db.flush()

    async def list(
        self, profile_id: uuid.UUID, topic: str | None = None, limit: int = 20
    ) -> Sequence[Mistake]:
        stmt = select(Mistake).where(Mistake.profile_id == profile_id)
        if topic:
            stmt = stmt.where(Mistake.rule_tag == topic)
        stmt = stmt.order_by(Mistake.created_at.desc(), Mistake.id.desc()).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def top_tags_for_session(
        self, session_id: uuid.UUID, limit: int = 5
    ) -> list[tuple[str, int]]:
        stmt = (
            select(Mistake.rule_tag, func.count().label("n"))
            .join(Turn, Turn.id == Mistake.turn_id)
            .where(Turn.session_id == session_id)
            .group_by(Mistake.rule_tag)
            .order_by(func.count().desc(), Mistake.rule_tag)
            .limit(limit)
        )
        return [(tag, int(n)) for tag, n in (await self.db.execute(stmt)).all()]

    async def top_tags_between(
        self, profile_id: uuid.UUID, start: datetime, end: datetime, limit: int = 3
    ) -> list[tuple[str, int]]:
        stmt = (
            select(Mistake.rule_tag, func.count().label("n"))
            .where(
                Mistake.profile_id == profile_id,
                Mistake.created_at >= start,
                Mistake.created_at < end,
            )
            .group_by(Mistake.rule_tag)
            .order_by(func.count().desc(), Mistake.rule_tag)
            .limit(limit)
        )
        return [(tag, int(n)) for tag, n in (await self.db.execute(stmt)).all()]

    async def for_turns(self, turn_ids: Iterable[int]) -> Sequence[Mistake]:
        ids = list(turn_ids)
        if not ids:
            return []
        stmt = select(Mistake).where(Mistake.turn_id.in_(ids)).order_by(Mistake.id)
        return (await self.db.execute(stmt)).scalars().all()

    async def count_between(self, profile_id: uuid.UUID, start: datetime, end: datetime) -> int:
        stmt = select(func.count()).where(
            Mistake.profile_id == profile_id,
            Mistake.created_at >= start,
            Mistake.created_at < end,
        )
        return int((await self.db.execute(stmt)).scalar_one())


class MasteryRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_many(
        self, profile_id: uuid.UUID, topic_ids: Iterable[str]
    ) -> dict[str, GrammarMastery]:
        ids = list(set(topic_ids))
        if not ids:
            return {}
        stmt = select(GrammarMastery).where(
            GrammarMastery.profile_id == profile_id, GrammarMastery.topic_id.in_(ids)
        )
        return {m.topic_id: m for m in (await self.db.execute(stmt)).scalars().all()}

    async def weakest(self, profile_id: uuid.UUID, limit: int = 5) -> Sequence[GrammarMastery]:
        stmt = (
            select(GrammarMastery)
            .where(GrammarMastery.profile_id == profile_id, GrammarMastery.errors > 0)
            .order_by(GrammarMastery.mastery, GrammarMastery.topic_id)
            .limit(limit)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def all_for_profile(self, profile_id: uuid.UUID) -> dict[str, GrammarMastery]:
        stmt = select(GrammarMastery).where(GrammarMastery.profile_id == profile_id)
        return {m.topic_id: m for m in (await self.db.execute(stmt)).scalars().all()}

    async def all_masteries(self, profile_id: uuid.UUID) -> list[float]:
        stmt = select(GrammarMastery.mastery).where(
            GrammarMastery.profile_id == profile_id, GrammarMastery.attempts > 0
        )
        return [float(x) for x in (await self.db.execute(stmt)).scalars().all()]

    async def upsert(
        self,
        profile_id: uuid.UUID,
        topic_id: str,
        mastery: float,
        attempts: int,
        errors: int,
        existing: GrammarMastery | None,
    ) -> None:
        if existing is None:
            self.db.add(
                GrammarMastery(
                    profile_id=profile_id,
                    topic_id=topic_id,
                    mastery=mastery,
                    attempts=attempts,
                    errors=errors,
                )
            )
        else:
            existing.mastery = mastery
            existing.attempts = attempts
            existing.errors = errors
            existing.last_seen_at = utcnow()


class VocabRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def all_for_profile(self, profile_id: uuid.UUID) -> dict[str, VocabItem]:
        stmt = select(VocabItem).where(VocabItem.profile_id == profile_id)
        return {v.lemma: v for v in (await self.db.execute(stmt)).scalars().all()}

    async def list(self, profile_id: uuid.UUID, limit: int = 50) -> Sequence[VocabItem]:
        stmt = (
            select(VocabItem)
            .where(VocabItem.profile_id == profile_id)
            .order_by(VocabItem.last_seen_at.desc(), VocabItem.id.desc())
            .limit(limit)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def first_seen_between(
        self, profile_id: uuid.UUID, start: datetime, end: datetime
    ) -> Sequence[VocabItem]:
        stmt = (
            select(VocabItem)
            .where(
                VocabItem.profile_id == profile_id,
                VocabItem.first_seen_at >= start,
                VocabItem.first_seen_at < end,
            )
            .order_by(VocabItem.first_seen_at)
        )
        return (await self.db.execute(stmt)).scalars().all()

    def add(self, item: VocabItem) -> None:
        self.db.add(item)

    async def all_masteries(self, profile_id: uuid.UUID) -> list[float]:
        stmt = select(VocabItem.mastery).where(VocabItem.profile_id == profile_id)
        return [float(x) for x in (await self.db.execute(stmt)).scalars().all()]

    async def get(self, item_id: int) -> VocabItem | None:
        return await self.db.get(VocabItem, item_id)

    async def next_due(self, profile_id: uuid.UUID, now: datetime) -> VocabItem | None:
        stmt = (
            select(VocabItem)
            .where(VocabItem.profile_id == profile_id, VocabItem.due_at <= now)
            .order_by(VocabItem.due_at, VocabItem.id)
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def count_due(self, profile_id: uuid.UUID, now: datetime) -> int:
        stmt = select(func.count()).where(
            VocabItem.profile_id == profile_id, VocabItem.due_at <= now
        )
        return int((await self.db.execute(stmt)).scalar_one())

    async def count_cards(self, profile_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            VocabItem.profile_id == profile_id, VocabItem.due_at.is_not(None)
        )
        return int((await self.db.execute(stmt)).scalar_one())

    async def earliest_due(self, profile_id: uuid.UUID) -> datetime | None:
        stmt = select(func.min(VocabItem.due_at)).where(VocabItem.profile_id == profile_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()


class ActivityRepo:
    """Learner messages per local day (streaks, daily goal)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def count_on(self, profile_id: uuid.UUID, day: date) -> int:
        row = await self.db.get(DailyActivity, (profile_id, day))
        return row.messages if row else 0

    async def bump(self, profile_id: uuid.UUID, day: date) -> int:
        """Add one message to `day`; returns the new count."""
        row = await self.db.get(DailyActivity, (profile_id, day))
        if row is None:
            row = DailyActivity(profile_id=profile_id, day=day, messages=0)
            self.db.add(row)
        row.messages += 1
        await self.db.flush()
        return row.messages

    async def recent_days(self, profile_id: uuid.UUID, limit: int) -> list[date]:
        """Active days, newest first."""
        stmt = (
            select(DailyActivity.day)
            .where(DailyActivity.profile_id == profile_id, DailyActivity.messages > 0)
            .order_by(DailyActivity.day.desc())
            .limit(limit)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def between(self, profile_id: uuid.UUID, first: date, last: date) -> dict[date, int]:
        """Messages per local day from `first` to `last` (inclusive), active days only."""
        stmt = select(DailyActivity.day, DailyActivity.messages).where(
            DailyActivity.profile_id == profile_id,
            DailyActivity.day >= first,
            DailyActivity.day <= last,
            DailyActivity.messages > 0,
        )
        return {d: int(n) for d, n in (await self.db.execute(stmt)).all()}

    async def reminder_candidates(
        self, provider: str, target_lang: str
    ) -> list[tuple[LearnerProfile, str]]:
        """Profiles with reminders on, with the external id of their `provider` identity."""
        stmt = (
            select(LearnerProfile, UserIdentity.external_id)
            .join(UserIdentity, UserIdentity.user_id == LearnerProfile.user_id)
            .where(
                UserIdentity.provider == provider,
                LearnerProfile.target_lang == target_lang,
                LearnerProfile.reminders_enabled.is_(True),
            )
        )
        return [(p, ext) for p, ext in (await self.db.execute(stmt)).all()]

    async def tidy_candidates(
        self, provider: str, target_lang: str
    ) -> list[tuple[LearnerProfile, str]]:
        """Profiles with the daily chat tidy on, with the external id of their identity."""
        stmt = (
            select(LearnerProfile, UserIdentity.external_id)
            .join(UserIdentity, UserIdentity.user_id == LearnerProfile.user_id)
            .where(
                UserIdentity.provider == provider,
                LearnerProfile.target_lang == target_lang,
                LearnerProfile.tidy_chat.is_(True),
            )
        )
        return [(p, ext) for p, ext in (await self.db.execute(stmt)).all()]


class ReviewRepo:
    """Spaced-repetition cards made from mistakes."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, card_id: int) -> ReviewItem | None:
        return await self.db.get(ReviewItem, card_id)

    async def find(self, profile_id: uuid.UUID, wrong: str, right: str) -> ReviewItem | None:
        stmt = select(ReviewItem).where(
            ReviewItem.profile_id == profile_id,
            ReviewItem.wrong == wrong,
            ReviewItem.right == right,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    def add(self, item: ReviewItem) -> None:
        self.db.add(item)

    async def next_due(self, profile_id: uuid.UUID, now: datetime) -> ReviewItem | None:
        stmt = (
            select(ReviewItem)
            .where(ReviewItem.profile_id == profile_id, ReviewItem.due_at <= now)
            .order_by(ReviewItem.due_at, ReviewItem.id)
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def count_due(self, profile_id: uuid.UUID, now: datetime) -> int:
        stmt = select(func.count()).where(
            ReviewItem.profile_id == profile_id, ReviewItem.due_at <= now
        )
        return int((await self.db.execute(stmt)).scalar_one())

    async def count_all(self, profile_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(ReviewItem.profile_id == profile_id)
        return int((await self.db.execute(stmt)).scalar_one())

    async def earliest_due(self, profile_id: uuid.UUID) -> datetime | None:
        stmt = select(func.min(ReviewItem.due_at)).where(ReviewItem.profile_id == profile_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()


class LessonRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, run_id: int) -> LessonRun | None:
        return await self.db.get(LessonRun, run_id)

    async def add(self, run: LessonRun) -> LessonRun:
        self.db.add(run)
        await self.db.flush()
        return run

    async def topics_studied(self, profile_id: uuid.UUID) -> dict[str, int]:
        """topic_id -> number of lessons taken on it."""
        stmt = (
            select(LessonRun.topic_id, func.count())
            .where(LessonRun.profile_id == profile_id)
            .group_by(LessonRun.topic_id)
        )
        return {tid: int(n) for tid, n in (await self.db.execute(stmt)).all()}

    async def between(
        self, profile_id: uuid.UUID, start: datetime, end: datetime
    ) -> Sequence[LessonRun]:
        stmt = select(LessonRun).where(
            LessonRun.profile_id == profile_id,
            LessonRun.created_at >= start,
            LessonRun.created_at < end,
        )
        return (await self.db.execute(stmt)).scalars().all()


class LessonCacheRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(
        self, topic_id: str, level: str, native_lang: str, explanation_language: str
    ) -> LessonCache | None:
        stmt = select(LessonCache).where(
            LessonCache.topic_id == topic_id,
            LessonCache.level == level,
            LessonCache.native_lang == native_lang,
            LessonCache.explanation_language == explanation_language,
        )
        return (await self.db.execute(stmt)).scalars().first()

    async def add(self, entry: LessonCache) -> None:
        """Store unless an equal entry exists (two first lessons at once: keep the first)."""
        if await self.get(
            entry.topic_id, entry.level, entry.native_lang, entry.explanation_language
        ):
            return
        self.db.add(entry)
        await self.db.flush()

    async def delete(self, topic_id: str, level: str, native_lang: str, expl: str) -> None:
        entry = await self.get(topic_id, level, native_lang, expl)
        if entry is not None:
            await self.db.delete(entry)


class PlacementRepo:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def add(self, run: PlacementRun) -> PlacementRun:
        self.db.add(run)
        await self.db.flush()
        return run

    async def get(self, run_id: int, for_update: bool = False) -> PlacementRun | None:
        stmt = select(PlacementRun).where(PlacementRun.id == run_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()
