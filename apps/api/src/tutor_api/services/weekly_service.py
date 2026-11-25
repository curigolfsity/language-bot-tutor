"""Weekly summary: the learner's last 7 local days, on demand or claimed once a week."""

from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession
from tutor_contracts import WeeklySummaryOut, WeeklyTopicOut

from tutor_api.db.models import LearnerProfile, utcnow
from tutor_api.db.repositories import (
    ActivityRepo,
    LessonRepo,
    MistakeRepo,
    ProfileRepo,
    ReviewRepo,
    VocabRepo,
)
from tutor_api.domain.streaks import current_streak, weekly_due
from tutor_api.services import lesson_service
from tutor_api.services.context import AppContext
from tutor_api.services.errors import NotFoundError
from tutor_api.services.habits_service import STREAK_LOOKBACK_DAYS, timezone_name
from tutor_api.services.mappers import topic_title


async def _summary(
    ctx: AppContext, db: AsyncSession, profile: LearnerProfile, external_id: str | None = None
) -> WeeklySummaryOut:
    tz = ZoneInfo(timezone_name(profile, ctx.settings))
    now = utcnow()
    last_day = now.astimezone(tz).date()
    first_day = last_day - timedelta(days=6)
    start = datetime.combine(first_day, time.min, tzinfo=tz)
    curriculum = ctx.curriculum(profile.target_lang)

    activity = ActivityRepo(db)
    per_day = await activity.between(profile.id, first_day, last_day)
    days = await activity.recent_days(profile.id, STREAK_LOOKBACK_DAYS)
    streak = current_streak(days, last_day)
    lessons = await LessonRepo(db).between(profile.id, start, now)
    mrepo = MistakeRepo(db)
    top = await mrepo.top_tags_between(profile.id, start, now)
    new_words = await VocabRepo(db).first_seen_between(profile.id, start, now)
    return WeeklySummaryOut(
        profile_id=profile.id,
        external_id=external_id,
        first_day=first_day,
        last_day=last_day,
        days_active=len(per_day),
        messages=sum(per_day.values()),
        streak=streak,
        best_streak=max(profile.streak_best, streak),
        lessons=len(lessons),
        exercises_right=sum(r.correct for r in lessons),
        exercises_done=sum(len(r.answers) for r in lessons),
        mistakes=await mrepo.count_between(profile.id, start, now),
        top_mistakes=[
            WeeklyTopicOut(id=tag, title=topic_title(curriculum, tag) or tag, count=n)
            for tag, n in top
            if tag in curriculum.topics
        ],
        new_words=len(new_words),
        reviews_due=await ReviewRepo(db).count_due(profile.id, now),
        words_due=await VocabRepo(db).count_due(profile.id, now),
    )


async def _with_suggestion(ctx: AppContext, out: WeeklySummaryOut) -> WeeklySummaryOut:
    sugg = await lesson_service.suggestions(ctx, out.profile_id)
    if sugg.suggested:
        t = sugg.suggested[0]
        out.suggested_lesson = WeeklyTopicOut(id=t.id, title=t.title)
    return out


async def summary(ctx: AppContext, profile_id: uuid.UUID) -> WeeklySummaryOut:
    async with ctx.sessionmaker() as db:
        profile = await ProfileRepo(db).get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        out = await _summary(ctx, db, profile)
    return await _with_suggestion(ctx, out)


async def claim(ctx: AppContext, provider: str, target_lang: str) -> list[WeeklySummaryOut]:
    """Learners due their weekly summary now; each is marked sent for today."""
    settings, now = ctx.settings, utcnow()
    due: list[WeeklySummaryOut] = []
    async with ctx.sessionmaker.begin() as db:
        activity = ActivityRepo(db)
        for profile, external_id in await activity.reminder_candidates(provider, target_lang):
            local_now = now.astimezone(ZoneInfo(timezone_name(profile, settings)))
            days = await activity.recent_days(profile.id, 1)
            if not weekly_due(
                enabled=profile.reminders_enabled,
                local_now=local_now,
                weekday=settings.weekly_summary_weekday,
                hour=settings.reminder_hour,
                last_active=days[0] if days else None,
                last_sent=profile.last_weekly_on,
                max_idle_days=14,
            ):
                continue
            profile.last_weekly_on = local_now.date()
            due.append(await _summary(ctx, db, profile, external_id))
    return [await _with_suggestion(ctx, s) for s in due]
