"""Habits: daily streaks, the daily goal and reminders (docs/architecture.md section 10)."""

from __future__ import annotations

import uuid
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession
from tutor_contracts import DailyProgressOut, ReminderOut, TurnProgress

from tutor_api.config import Settings
from tutor_api.db.models import LearnerProfile, utcnow
from tutor_api.db.repositories import ActivityRepo, ProfileRepo, ReviewRepo
from tutor_api.domain.streaks import current_streak, reminder_due, turn_milestones
from tutor_api.services.context import AppContext
from tutor_api.services.errors import InvalidRequestError, NotFoundError

STREAK_LOOKBACK_DAYS = 1000  # longest streak we can count; plenty for a personal tutor


def parse_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise InvalidRequestError(f"unknown IANA timezone {name!r}") from e


def timezone_name(profile: LearnerProfile, settings: Settings) -> str:
    return profile.timezone or settings.default_timezone


def learner_today(profile: LearnerProfile, settings: Settings) -> date:
    tz = ZoneInfo(timezone_name(profile, settings))  # validated on write and at startup
    return utcnow().astimezone(tz).date()


def daily_goal(profile: LearnerProfile, settings: Settings) -> int:
    return profile.daily_goal or settings.default_daily_goal


async def _progress(
    db: AsyncSession, profile: LearnerProfile, settings: Settings, today: date
) -> DailyProgressOut:
    activity = ActivityRepo(db)
    streak = current_streak(await activity.recent_days(profile.id, STREAK_LOOKBACK_DAYS), today)
    count = await activity.count_on(profile.id, today)
    goal = daily_goal(profile, settings)
    return DailyProgressOut(
        streak=streak,
        best_streak=max(profile.streak_best, streak),
        today=count,
        goal=goal,
        goal_met=count >= goal,
    )


async def record_message(
    db: AsyncSession, profile_id: uuid.UUID, settings: Settings
) -> TurnProgress:
    """Count one learner message for today. Runs inside the caller's turn transaction."""
    profile = await ProfileRepo(db).get(profile_id)
    assert profile is not None
    today = learner_today(profile, settings)
    activity = ActivityRepo(db)
    before = await activity.count_on(profile.id, today)
    await activity.bump(profile.id, today)
    progress = await _progress(db, profile, settings, today)
    profile.streak_best = progress.best_streak
    m = turn_milestones(before, progress.today, progress.goal)
    return TurnProgress(
        **progress.model_dump(), first_today=m.first_today, goal_just_met=m.goal_just_met
    )


async def get_progress(ctx: AppContext, profile_id: uuid.UUID) -> DailyProgressOut:
    async with ctx.sessionmaker() as db:
        profile = await ProfileRepo(db).get(profile_id)
        if profile is None:
            raise NotFoundError("learner profile not found")
        return await _progress(db, profile, ctx.settings, learner_today(profile, ctx.settings))


async def claim_reminders(ctx: AppContext, provider: str, target_lang: str) -> list[ReminderOut]:
    """Learners due a reminder now. Each one is marked reminded for their local day, so a
    learner is reminded at most once a day even if the client polls often."""
    settings = ctx.settings
    now = utcnow()
    due: list[ReminderOut] = []
    async with ctx.sessionmaker.begin() as db:
        activity = ActivityRepo(db)
        for profile, external_id in await activity.reminder_candidates(provider, target_lang):
            local_now = now.astimezone(ZoneInfo(timezone_name(profile, settings)))
            today = local_now.date()
            days = await activity.recent_days(profile.id, STREAK_LOOKBACK_DAYS)
            if not reminder_due(
                enabled=profile.reminders_enabled,
                local_now=local_now,
                reminder_hour=settings.reminder_hour,
                messages_today=await activity.count_on(profile.id, today),
                last_active=days[0] if days else None,
                last_reminded=profile.last_reminded_on,
                max_idle_days=settings.reminder_max_idle_days,
            ):
                continue
            profile.last_reminded_on = today
            due.append(
                ReminderOut(
                    profile_id=profile.id,
                    external_id=external_id,
                    streak=current_streak(days, today),
                    goal=daily_goal(profile, settings),
                    reviews_due=await ReviewRepo(db).count_due(profile.id, now),
                )
            )
    return due
