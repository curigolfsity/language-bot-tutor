"""Placement test, word flashcards and weekly summary."""

from datetime import timedelta

from conftest import make_result
from sqlalchemy import update
from test_api_flow import resolve
from tutor_api.curriculum.models import Placement, PlacementQuestion
from tutor_api.db.models import VocabItem, utcnow
from tutor_api.domain.placement import Answered, next_step

LEVELS = ("A1", "A2", "B1")


def _placement() -> Placement:
    qs = [
        PlacementQuestion(
            id=f"es.place.{lv.lower()}_{i}", level=lv, prompt="x ___", options=("a", "b"), answer=0
        )
        for lv in LEVELS
        for i in range(3)
    ]
    return Placement(per_level=3, pass_mark=2, questions=tuple(qs))


def _ans(lv: str, *results: bool) -> list[Answered]:
    return [Answered(f"es.place.{lv.lower()}_{i}", lv, r) for i, r in enumerate(results)]


def test_placement_steps():
    p = _placement()
    assert next_step(p, LEVELS, []).question.level == "A1"
    # Two right at A1 passes it early: next question is A2.
    assert next_step(p, LEVELS, _ans("A1", True, True)).question.level == "A2"
    # Two wrong at A2 fails it: suggest A1.
    s = next_step(p, LEVELS, _ans("A1", True, True) + _ans("A2", False, False))
    assert s.question is None and s.result_level == "A1"
    # Failing A1 still suggests the lowest level; passing all suggests the highest.
    assert next_step(p, LEVELS, _ans("A1", False, False)).result_level == "A1"
    everything = _ans("A1", True, True) + _ans("A2", True, True) + _ans("B1", True, False, True)
    assert next_step(p, LEVELS, everything).result_level == "B1"


async def test_placement_flow_suggests_without_changing_level(client):
    pid = (await resolve(client))["profile"]["id"]
    step = (await client.post(f"/v1/learners/{pid}/placement")).json()
    run, asked = step["run_id"], 0
    while step["question"]:
        q = step["question"]
        asked += 1
        r = await client.post(
            f"/v1/placement/{run}/answer", json={"question_id": q["id"], "choice": 9}
        )
        if r.status_code == 400:  # choice 9 out of range on purpose first, then answer wrong
            r = await client.post(
                f"/v1/placement/{run}/answer", json={"question_id": q["id"], "choice": 0}
            )
        step = r.json()
        assert step["last"] is not None
    assert step["result"]["level"] in ("A1", "A2", "B1", "B2", "C1", "C2")
    assert step["result"]["current_level"] == "A1"
    again = await client.post(f"/v1/placement/{run}/answer", json={"question_id": "x", "choice": 0})
    assert again.status_code == 409  # finished
    me = (
        await client.post(
            "/v1/users/resolve",
            json={
                "provider": "telegram",
                "external_id": "42",
                "display_name": "Ana",
                "target_lang": "es",
                "native_lang": "en",
            },
        )
    ).json()
    assert me["profile"]["cefr_level"] == "A1"  # unchanged: the learner chooses


async def test_words_flashcards_and_weekly(client, ctx, fake_llm):
    pid = (await resolve(client))["profile"]["id"]
    sid = (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]
    fake_llm.push_result(make_result(vocab=["playa"]))
    await client.post(f"/v1/sessions/{sid}/turns", json={"text": "Voy a la playa"})

    q = (await client.get(f"/v1/learners/{pid}/words/next")).json()
    assert q["card"] is None and q["total"] == 1  # new words wait 10 minutes first
    async with ctx.sessionmaker.begin() as db:
        await db.execute(update(VocabItem).values(due_at=utcnow() - timedelta(minutes=1)))
    card = (await client.get(f"/v1/learners/{pid}/words/next")).json()["card"]
    assert card["word"] == "playa" and card["translation"] == "t"
    r = (await client.post(f"/v1/words/{card['id']}/answer", json={"knew": True})).json()
    assert r["knew"] and r["next_review_in_days"] == 1 and r["due"] == 0
    weekly = (await client.get(f"/v1/learners/{pid}/weekly")).json()
    assert weekly["days_active"] == 1 and weekly["messages"] == 2  # a turn and a flashcard
    assert weekly["suggested_lesson"] is not None
    claim = await client.post(
        "/v1/reminders/weekly/claim", json={"provider": "telegram", "target_lang": "es"}
    )
    assert claim.status_code == 200
