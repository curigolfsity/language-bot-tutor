"""Daily streaks, goals and reminder timing. Pure: callers convert to the learner's local time."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

ONE_DAY = timedelta(days=1)


def current_streak(active_days_desc: Sequence[date], today: date) -> int:
    """Consecutive active days ending today, or yesterday (today is not over yet).

    `active_days_desc` are the learner's active local days, newest first.
    """
    if not active_days_desc:
        return 0
    expected = today if active_days_desc[0] >= today else today - ONE_DAY
    streak = 0
    for day in active_days_desc:
        if day > expected:  # today when counting from yesterday, or a duplicate
            continue
        if day < expected:
            break
        streak += 1
        expected -= ONE_DAY
    return streak


@dataclass(frozen=True)
class Milestones:
    first_today: bool  # this message started (or kept) the streak for today
    goal_just_met: bool  # this message reached the daily goal


def turn_milestones(before: int, after: int, goal: int) -> Milestones:
    """`before`/`after`: the learner's message count today before and after this turn."""
    return Milestones(first_today=before == 0 and after > 0, goal_just_met=before < goal <= after)


def reminder_due(
    *,
    enabled: bool,
    local_now: datetime,
    reminder_hour: int,
    messages_today: int,
    last_active: date | None,
    last_reminded: date | None,
    max_idle_days: int,
) -> bool:
    """Remind at most once a day, after `reminder_hour`, only if the learner has not practised
    today, has practised before, and has not been away longer than `max_idle_days`."""
    today = local_now.date()
    return (
        enabled
        and messages_today == 0
        and last_active is not None
        and (today - last_active).days <= max_idle_days
        and local_now.hour >= reminder_hour
        and last_reminded != today
    )


def weekly_due(
    *,
    enabled: bool,
    local_now: datetime,
    weekday: int,
    hour: int,
    last_active: date | None,
    last_sent: date | None,
    max_idle_days: int,
) -> bool:
    """Weekly summary: once on `weekday` (0 = Monday) after `hour`, for learners active
    within `max_idle_days`."""
    today = local_now.date()
    return (
        enabled
        and local_now.weekday() == weekday
        and local_now.hour >= hour
        and last_active is not None
        and (today - last_active).days <= max_idle_days
        and last_sent != today
    )


# Telegram (and most chat apps) only let a bot delete messages from the last 48 hours, so a
# tidy never looks further back than this.
TIDY_LOOKBACK_DAYS = 2


def tidy_due(*, enabled: bool, local_now: datetime, hour: int, last_tidied: date | None) -> bool:
    """Daily chat tidy: once per local day, after `hour`."""
    return enabled and local_now.hour >= hour and last_tidied != local_now.date()


def days_to_tidy(active_days: Sequence[date], today: date, last_tidied: date | None) -> list[date]:
    """Past active days that get a day card, oldest first: after the last tidy, before today,
    and recent enough that their messages can still be deleted."""
    earliest = today - timedelta(days=TIDY_LOOKBACK_DAYS)
    return sorted(
        d
        for d in set(active_days)
        if earliest <= d < today and (last_tidied is None or d >= last_tidied)
    )
