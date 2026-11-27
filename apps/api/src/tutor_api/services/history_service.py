"""Past days of practice: day cards, a day's conversation, and the daily chat tidy
(docs/architecture.md section 10, "Daily chat tidy")."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession
from tutor_contracts import (
    DayListOut,
    DayOut,
    DayTranscriptOut,
    TidyOut,
    TranscriptFix,
    TranscriptLine,
    WeeklyTopicOut,
)

from tutor_api.db.models import LearnerProfile, utcnow
from tutor_api.db.repositories import (
    ActivityRepo,
    LessonRepo,
    MistakeRepo,
    ProfileRepo,
    TurnRepo,
    VocabRepo,
)
from tutor_api.domain.streaks import TIDY_LOOKBACK_DAYS, days_to_tidy, tidy_due
from tutor_api.services.context import AppContext
from tutor_api.services.errors import NotFoundError
from tutor_api.services.habits_service import timezone_name
from tutor_api.services.mappers import topic_title

MAX_DAYS_LISTED = 60


def _bounds(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """[start, end) of a local day, in UTC (how timestamps are stored)."""
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(UTC)
    return start, end


def _tz(ctx: AppContext, profile: LearnerProfile) -> ZoneInfo:
    return ZoneInfo(timezone_name(profile, ctx.settings))


async def _day(
    ctx: AppContext, db: AsyncSession, profile: LearnerProfile, day: date, messages: int
) -> DayOut:
    start, end = _bounds(day, _tz(ctx, profile))
    curriculum = ctx.curriculum(profile.target_lang)
    mistakes = MistakeRepo(db)
    top = await mistakes.top_tags_between(profile.id, start, end)
    words = await VocabRepo(db).first_seen_between(profile.id, start, end)
    return DayOut(
        day=day,
        messages=messages,
        corrections=await mistakes.count_between(profile.id, start, end),
        new_words=len(words),
        lessons=len(await LessonRepo(db).between(profile.id, start, end)),
        top_mistakes=[
            WeeklyTopicOut(id=tag, title=topic_title(curriculum, tag) or tag, count=n)
            for tag, n in top
            if tag in curriculum.topics
        ],
    )


async def _profile(db: AsyncSession, profile_id: uuid.UUID) -> LearnerProfile:
    profile = await ProfileRepo(db).get(profile_id)
    if profile is None:
        raise NotFoundError("learner profile not found")
    return profile


async def list_days(ctx: AppContext, profile_id: uuid.UUID, limit: int) -> DayListOut:
    limit = max(1, min(limit, MAX_DAYS_LISTED))
    async with ctx.sessionmaker() as db:
        profile = await _profile(db, profile_id)
        activity = ActivityRepo(db)
        recent = await activity.recent_days(profile.id, limit)
        if not recent:
            return DayListOut(days=[])
        counts = await activity.between(profile.id, recent[-1], recent[0])
        return DayListOut(days=[await _day(ctx, db, profile, d, counts.get(d, 0)) for d in recent])


async def transcript(ctx: AppContext, profile_id: uuid.UUID, day: date) -> DayTranscriptOut:
    async with ctx.sessionmaker() as db:
        profile = await _profile(db, profile_id)
        counts = await ActivityRepo(db).between(profile.id, day, day)
        out = await _day(ctx, db, profile, day, counts.get(day, 0))
        start, end = _bounds(day, _tz(ctx, profile))
        rows = await TurnRepo(db).for_profile_between(profile.id, start, end)
        fixes: dict[int, list[TranscriptFix]] = defaultdict(list)
        learner_ids = [t.id for t, _ in rows if t.role == "learner"]
        for m in await MistakeRepo(db).for_turns(learner_ids):
            fixes[m.turn_id].append(
                TranscriptFix(wrong=m.wrong, right=m.right, explanation=m.explanation)
            )
        curriculum = ctx.curriculum(profile.target_lang)
        lines: list[TranscriptLine] = []
        last_session: uuid.UUID | None = None
        for turn, session in rows:
            title = None
            if session.id != last_session:
                scenario = curriculum.scenarios.get(session.scenario_id or "")
                title = scenario.title if scenario else "Free chat"
                last_session = session.id
            lines.append(
                TranscriptLine(
                    role=turn.role,  # type: ignore[arg-type]
                    text=turn.text,
                    at=turn.created_at,
                    fixes=fixes.get(turn.id, []),
                    scenario_title=title,
                )
            )
        return DayTranscriptOut(day=out, lines=lines)


async def claim_tidy(ctx: AppContext, provider: str, target_lang: str) -> list[TidyOut]:
    """Learners whose chat is due its daily tidy now; each is marked tidied for today."""
    settings, now = ctx.settings, utcnow()
    due: list[TidyOut] = []
    async with ctx.sessionmaker.begin() as db:
        activity = ActivityRepo(db)
        for profile, external_id in await activity.tidy_candidates(provider, target_lang):
            tz = _tz(ctx, profile)
            local_now = now.astimezone(tz)
            today = local_now.date()
            if not tidy_due(
                enabled=profile.tidy_chat,
                local_now=local_now,
                hour=settings.tidy_hour,
                last_tidied=profile.last_tidied_on,
            ):
                continue
            counts = await activity.between(
                profile.id, today - timedelta(days=TIDY_LOOKBACK_DAYS), today
            )
            days = days_to_tidy(list(counts), today, profile.last_tidied_on)
            profile.last_tidied_on = today
            due.append(
                TidyOut(
                    profile_id=profile.id,
                    external_id=external_id,
                    before=_bounds(today, tz)[0],
                    days=[await _day(ctx, db, profile, d, counts[d]) for d in days],
                )
            )
    return due
