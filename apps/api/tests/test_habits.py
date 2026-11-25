"""Streaks, daily goal and reminders: pure rules, then end-to-end through HTTP."""

from datetime import UTC, date, datetime, timedelta

import pytest
from conftest import make_result
from test_api_flow import resolve
from tutor_api.domain.streaks import current_streak, reminder_due, turn_milestones
from tutor_api.services import habits_service

D = date(2026, 11, 20)


def days(*offsets: int) -> list[date]:
    """Dates relative to D, newest first."""
    return sorted((D + timedelta(days=o) for o in offsets), reverse=True)


@pytest.mark.parametrize(
    ("active", "expected"),
    [
        ([], 0),
        (days(0), 1),
        (days(-1), 1),  # today not over yet: yesterday keeps the streak alive
        (days(0, -1, -2), 3),
        (days(-1, -2, -3), 3),
        (days(0, -1, -3, -4), 2),  # gap breaks it
        (days(-2, -3), 0),  # missed yesterday: lapsed
    ],
)
def test_current_streak(active, expected):
    assert current_streak(active, D) == expected


def test_turn_milestones():
    assert turn_milestones(0, 1, 10).first_today
    assert not turn_milestones(1, 2, 10).first_today
    assert turn_milestones(9, 10, 10).goal_just_met
    assert not turn_milestones(10, 11, 10).goal_just_met
    assert turn_milestones(0, 1, 1) == turn_milestones(0, 1, 1)  # both flags at once
    assert turn_milestones(0, 1, 1).goal_just_met


def _due(**kw) -> bool:
    base = dict(
        enabled=True,
        local_now=datetime(2026, 11, 20, 19, 30),
        reminder_hour=19,
        messages_today=0,
        last_active=D - timedelta(days=1),
        last_reminded=None,
        max_idle_days=7,
    )
    return reminder_due(**(base | kw))


def test_reminder_due():
    assert _due()
    assert not _due(enabled=False)
    assert not _due(local_now=datetime(2026, 11, 20, 18, 59))  # too early
    assert not _due(messages_today=1)  # already practised
    assert not _due(last_active=None)  # never practised: no nagging
    assert not _due(last_active=D - timedelta(days=8))  # away too long
    assert _due(last_active=D - timedelta(days=7))
    assert not _due(last_reminded=D)  # once a day
    assert _due(last_reminded=D - timedelta(days=1))


# ------------------------------------------------------------------------------ HTTP


class Clock:
    def __init__(self, monkeypatch, start: datetime) -> None:
        self.now = start
        monkeypatch.setattr(habits_service, "utcnow", lambda: self.now)


async def _turn(client, fake_llm, sid: str) -> dict:
    fake_llm.push_result(make_result())
    r = await client.post(f"/v1/sessions/{sid}/turns", json={"text": "Hola"})
    assert r.status_code == 200, r.text
    return r.json()["progress"]


async def _setup(client) -> tuple[str, str]:
    pid = (await resolve(client))["profile"]["id"]
    sid = (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]
    return pid, sid


async def test_streak_and_goal_through_turns(client, fake_llm, monkeypatch):
    clock = Clock(monkeypatch, datetime(2026, 11, 20, 10, tzinfo=UTC))
    pid, sid = await _setup(client)
    r = await client.patch(f"/v1/learners/{pid}", json={"daily_goal": 2})
    assert r.status_code == 200 and r.json()["daily_goal"] == 2

    p1 = await _turn(client, fake_llm, sid)
    assert (p1["streak"], p1["today"], p1["first_today"], p1["goal_just_met"]) == (
        1,
        1,
        True,
        False,
    )
    p2 = await _turn(client, fake_llm, sid)
    assert (p2["today"], p2["first_today"], p2["goal_just_met"], p2["goal_met"]) == (
        2,
        False,
        True,
        True,
    )
    p3 = await _turn(client, fake_llm, sid)
    assert not p3["goal_just_met"] and p3["goal_met"]

    clock.now += timedelta(days=1)
    p = await _turn(client, fake_llm, sid)
    assert (p["streak"], p["today"], p["first_today"]) == (2, 1, True)

    clock.now += timedelta(days=3)  # missed two days
    progress = (await client.get(f"/v1/learners/{pid}/progress")).json()
    assert (progress["streak"], progress["best_streak"], progress["today"]) == (0, 2, 0)
    p = await _turn(client, fake_llm, sid)
    assert (p["streak"], p["best_streak"]) == (1, 2)


async def test_day_boundary_uses_learner_timezone(client, fake_llm, monkeypatch):
    clock = Clock(monkeypatch, datetime(2026, 11, 20, 16, 30, tzinfo=UTC))  # 23:30 in Bangkok
    pid, sid = await _setup(client)
    assert (await client.patch(f"/v1/learners/{pid}", json={"timezone": "Asia/Bangkok"})).json()[
        "timezone"
    ] == "Asia/Bangkok"
    await _turn(client, fake_llm, sid)
    clock.now += timedelta(hours=1)  # 00:30 next day in Bangkok, same UTC day
    p = await _turn(client, fake_llm, sid)
    assert (p["streak"], p["today"], p["first_today"]) == (2, 1, True)


async def test_invalid_timezone_rejected(client):
    pid = (await resolve(client))["profile"]["id"]
    r = await client.patch(f"/v1/learners/{pid}", json={"timezone": "Mars/Olympus"})
    assert r.status_code == 400
    assert (await client.get(f"/v1/learners/{pid}")).json()["timezone"] == "UTC"


async def _claim(client) -> list[dict]:
    r = await client.post("/v1/reminders/claim", json={"provider": "telegram", "target_lang": "es"})
    assert r.status_code == 200, r.text
    return r.json()


async def test_reminders(client, fake_llm, monkeypatch):
    clock = Clock(monkeypatch, datetime(2026, 11, 20, 10, tzinfo=UTC))
    pid, sid = await _setup(client)
    assert await _claim(client) == []  # never practised: nothing to remind about

    await _turn(client, fake_llm, sid)
    clock.now = datetime(2026, 11, 20, 20, tzinfo=UTC)
    assert await _claim(client) == []  # practised today

    clock.now = datetime(2026, 11, 21, 18, tzinfo=UTC)
    assert await _claim(client) == []  # before REMINDER_HOUR (19)
    clock.now = datetime(2026, 11, 21, 19, 5, tzinfo=UTC)
    due = await _claim(client)
    assert [(d["profile_id"], d["external_id"], d["streak"]) for d in due] == [(pid, "42", 1)]
    assert await _claim(client) == []  # once per day

    clock.now += timedelta(days=1)
    await client.patch(f"/v1/learners/{pid}", json={"reminders_enabled": False})
    assert await _claim(client) == []
    await client.patch(f"/v1/learners/{pid}", json={"reminders_enabled": True})
    assert [d["streak"] for d in await _claim(client)] == [0]  # lapsed, still nudged

    clock.now += timedelta(days=10)
    assert await _claim(client) == []  # away too long: stop nagging
