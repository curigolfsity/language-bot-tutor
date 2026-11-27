"""Past days and the daily chat tidy: pure rules, then end-to-end through HTTP."""

from datetime import UTC, date, datetime, time, timedelta

from conftest import make_result
from test_api_flow import resolve
from tutor_api.domain.streaks import days_to_tidy, tidy_due
from tutor_api.services import history_service

D = date(2026, 11, 20)


def test_tidy_due():
    at = datetime(2026, 11, 20, 4, 30)
    assert tidy_due(enabled=True, local_now=at, hour=4, last_tidied=None)
    assert tidy_due(enabled=True, local_now=at, hour=4, last_tidied=D - timedelta(days=1))
    assert not tidy_due(enabled=False, local_now=at, hour=4, last_tidied=None)
    assert not tidy_due(enabled=True, local_now=at, hour=5, last_tidied=None)  # too early
    assert not tidy_due(enabled=True, local_now=at, hour=4, last_tidied=D)  # once a day


def test_days_to_tidy():
    d = lambda n: D + timedelta(days=n)  # noqa: E731
    active = [d(0), d(-1), d(-2), d(-3)]
    assert days_to_tidy(active, D, None) == [d(-2), d(-1)]  # today kept; 48 h limit
    assert days_to_tidy(active, D, d(-1)) == [d(-1)]  # after 04:00 yesterday
    assert days_to_tidy(active, D, D) == []
    assert days_to_tidy([d(-1), d(-1)], D, None) == [d(-1)]
    assert days_to_tidy([], D, None) == []


async def _setup(client, fake_llm) -> tuple[str, date]:
    pid = (await resolve(client))["profile"]["id"]
    sid = (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]
    fake_llm.push_result(
        make_result(
            reply="¿Y hoy?",
            corrections=[("soy cansado", "estoy cansado", "es.a1.ser_vs_estar_basic", "major")],
            vocab=["cansado"],
        )
    )
    r = await client.post(f"/v1/sessions/{sid}/turns", json={"text": "Yo soy cansado"})
    assert r.status_code == 200, r.text
    return pid, datetime.now(UTC).date()  # turns are stamped with the real clock


async def test_days_and_transcript(client, fake_llm):
    pid, today = await _setup(client, fake_llm)

    days = (await client.get(f"/v1/learners/{pid}/days")).json()["days"]
    assert len(days) == 1
    day = days[0]
    assert (day["day"], day["messages"], day["corrections"], day["new_words"]) == (
        today.isoformat(),
        1,
        1,
        1,
    )
    assert [t["id"] for t in day["top_mistakes"]] == ["es.a1.ser_vs_estar_basic"]

    r = await client.get(f"/v1/learners/{pid}/days/{today.isoformat()}")
    assert r.status_code == 200, r.text
    lines = r.json()["lines"]
    assert [ln["role"] for ln in lines] == ["tutor", "learner", "tutor"]  # opening line first
    assert lines[0]["scenario_title"] and lines[1]["scenario_title"] is None
    assert lines[1]["text"] == "Yo soy cansado"
    assert lines[1]["fixes"] == [
        {"wrong": "soy cansado", "right": "estoy cansado", "explanation": "x"}
    ]
    assert lines[2]["text"] == "¿Y hoy?"

    empty = (await client.get(f"/v1/learners/{pid}/days/2020-01-01")).json()
    assert empty["lines"] == [] and empty["day"]["messages"] == 0


async def _claim(client) -> list[dict]:
    r = await client.post(
        "/v1/reminders/tidy/claim", json={"provider": "telegram", "target_lang": "es"}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_tidy_claim(client, fake_llm, monkeypatch):
    pid, today = await _setup(client, fake_llm)
    tomorrow = today + timedelta(days=1)
    now = {"t": datetime.combine(tomorrow, time(3, 59), tzinfo=UTC)}
    monkeypatch.setattr(history_service, "utcnow", lambda: now["t"])

    assert await _claim(client) == []  # before TIDY_HOUR (4)
    now["t"] = datetime.combine(tomorrow, time(4, 5), tzinfo=UTC)
    due = await _claim(client)
    assert len(due) == 1
    assert (due[0]["profile_id"], due[0]["external_id"]) == (pid, "42")
    assert datetime.fromisoformat(due[0]["before"]) == datetime.combine(tomorrow, time.min, UTC)
    assert [(d["day"], d["messages"]) for d in due[0]["days"]] == [(today.isoformat(), 1)]
    assert await _claim(client) == []  # once a day

    # A day with no practice still tidies (menus, reminders), with no card.
    now["t"] += timedelta(days=1)
    assert [d["days"] for d in await _claim(client)] == [[]]

    now["t"] += timedelta(days=1)
    r = await client.patch(f"/v1/learners/{pid}", json={"tidy_chat": False})
    assert r.json()["tidy_chat"] is False
    assert await _claim(client) == []
