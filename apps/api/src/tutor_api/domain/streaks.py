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
