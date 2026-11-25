"""Practise-my-mistakes: Leitner scheduling, quick grading, and the HTTP flow."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import make_result
from test_api_flow import resolve
from tutor_api.domain.review import (
    BOX_INTERVALS,
    MAX_BOX,
    RETRY_DELAY,
    after_answer,
    new_card,
    quick_grade,
)
from tutor_api.llm import ReviewGrade
from tutor_api.services import habits_service, review_service

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)


def test_schedule():
    assert new_card(NOW).box == 0 and new_card(NOW).due_at == NOW + RETRY_DELAY
    s = after_answer(0, True, NOW)
    assert s.box == 1 and s.due_at == NOW + timedelta(days=1)
    assert after_answer(3, False, NOW).box == 0
    assert after_answer(MAX_BOX, True, NOW).due_at == NOW + BOX_INTERVALS[MAX_BOX]
    intervals = [after_answer(b, True, NOW).due_at - NOW for b in range(MAX_BOX)]
    assert intervals == sorted(intervals)  # each success waits longer


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("estoy en", True),
        ("Yo ESTOY en la playa.", True),  # full sentence, case and punctuation ignored
        ("soy en", None),  # unchanged: let the model say why
        ("estoy", None),  # partial
        ("estóy en", None),  # accents matter
        ("", None),
    ],
)
def test_quick_grade(answer, expected):
    assert quick_grade(answer, "soy en", "estoy en") is expected


def test_quick_grade_wrong_inside_right():
    # "amigos" is in both; containing the wrong span is fine when it is part of the fix.
    assert quick_grade("mis amigos", "amigos", "mis amigos") is True


# ------------------------------------------------------------------------------ HTTP


class Clock:
    def __init__(self, monkeypatch, start: datetime) -> None:
        self.now = start
        for mod in (review_service, habits_service):
            monkeypatch.setattr(mod, "utcnow", lambda: self.now)


async def test_review_flow(client, fake_llm, monkeypatch):
    clock = Clock(monkeypatch, NOW)
    pid = (await resolve(client))["profile"]["id"]
    sid = (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]

    queue = (await client.get(f"/v1/learners/{pid}/review/next")).json()
    assert queue == {"card": None, "due": 0, "total": 0, "next_due_at": None}

    corrections = [
        ("soy en", "estoy en", "es.a1.ser_vs_estar_basic", "major"),
        ("mi amigos", "mis amigos", "es.a1.possessive_agreement", "minor"),
    ]
    fake_llm.push_result(make_result(corrections=corrections))
    text = "Yo soy en la playa con mi amigos."
    await client.post(f"/v1/sessions/{sid}/turns", json={"text": text})

    # Cards exist but are not due straight away.
    queue = (await client.get(f"/v1/learners/{pid}/review/next")).json()
    assert queue["card"] is None and queue["total"] == 2 and queue["next_due_at"]

    clock.now += timedelta(minutes=11)
    queue = (await client.get(f"/v1/learners/{pid}/review/next")).json()
    card = queue["card"]
    assert queue["due"] == 2
    assert card["source_text"] == text and card["wrong"] == "soy en"
    assert card["rule_title"] and "right" not in card  # the answer is not revealed

    # Exact fix: graded locally, no model call.
    r = await client.post(
        f"/v1/review/{card['id']}/answer", json={"answer": "Yo estoy en la playa"}
    )
    body = r.json()
    assert r.status_code == 200 and body["correct"] and body["feedback"] is None
    assert body["next_review_in_days"] == 1.0 and body["due"] == 1
    assert body["progress"]["today"] == 2  # the chat message + this review
    assert fake_llm.grade_calls == []

    # Anything else goes to the model, which can accept an alternative.
    second = (await client.get(f"/v1/learners/{pid}/review/next")).json()["card"]
    fake_llm.grades.append(ReviewGrade(correct=False, feedback="Use the plural possessive."))
    body = (
        await client.post(f"/v1/review/{second['id']}/answer", json={"answer": "mi amigo"})
    ).json()
    assert not body["correct"] and body["right"] == "mis amigos"
    assert body["feedback"] == "Use the plural possessive."
    system, user = fake_llm.grade_calls[-1]
    assert "past mistakes" in system and "<learner_answer>mi amigo</learner_answer>" in user

    # A missed card comes back after the retry delay; repeating the mistake in chat resets a card.
    clock.now += timedelta(minutes=11)
    assert (await client.get(f"/v1/learners/{pid}/review/next")).json()["card"]["id"] == second[
        "id"
    ]
    fake_llm.push_result(make_result(corrections=corrections[:1]))
    await client.post(f"/v1/sessions/{sid}/turns", json={"text": "Soy en casa."})
    clock.now += timedelta(minutes=11)
    queue = (await client.get(f"/v1/learners/{pid}/review/next")).json()
    assert queue["total"] == 2 and queue["due"] == 2  # same cards, not duplicates


async def test_answer_unknown_card_404(client):
    r = await client.post("/v1/review/999/answer", json={"answer": "x"})
    assert r.status_code == 404


async def test_reminder_includes_reviews_due(client, fake_llm, monkeypatch):
    clock = Clock(monkeypatch, datetime(2026, 11, 20, 10, tzinfo=UTC))
    pid = (await resolve(client))["profile"]["id"]
    sid = (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]
    fake_llm.push_result(make_result(corrections=[("a", "b", "unknown", "major")]))
    await client.post(f"/v1/sessions/{sid}/turns", json={"text": "a"})
    clock.now = datetime(2026, 11, 21, 19, 30, tzinfo=UTC)
    r = await client.post("/v1/reminders/claim", json={"provider": "telegram", "target_lang": "es"})
    assert [d["reviews_due"] for d in r.json()] == [1]
