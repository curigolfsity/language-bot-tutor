"""Grammar lessons: topic suggestions, answer checking, and the HTTP flow (LLM faked)."""

from conftest import make_result
from test_api_flow import RESOLVE, resolve
from tutor_api.domain.lessons import TopicStats, check_exercise, suggest_topics
from tutor_api.llm import ReviewGrade

A1 = "A1"


def _a1(es):
    return [t for t in es.topics_up_to(A1)]


def test_suggest_new_learner_gets_curriculum_order(es):
    picks = suggest_topics(_a1(es), A1, {}, limit=4)
    assert [p.reason for p in picks] == ["next"] * 4
    first = es.topics[picks[0].topic_id]
    assert not first.prerequisites  # starts with something that needs nothing else


def test_suggest_weak_topics_first(es):
    topics = _a1(es)
    stats = {
        "es.a1.ser_vs_estar_basic": TopicStats(mastery=0.1, attempts=5, errors=4),
        "es.a1.gender_agreement": TopicStats(mastery=0.3, attempts=3, errors=1),
        "es.a1.present_regular": TopicStats(mastery=0.9, attempts=8, errors=0),  # fine
    }
    picks = suggest_topics(topics, A1, stats, limit=6)
    assert [(p.topic_id, p.reason) for p in picks[:2]] == [
        ("es.a1.ser_vs_estar_basic", "weak"),  # most errors first
        ("es.a1.gender_agreement", "weak"),
    ]
    assert "es.a1.present_regular" not in [p.topic_id for p in picks if p.reason != "refresh"]
    # "next" topics come only from unpractised ones whose prerequisites were practised first.
    nexts = [es.topics[p.topic_id] for p in picks if p.reason == "next"]
    assert all(t.id not in stats for t in nexts)
    assert len({p.topic_id for p in picks}) == len(picks)  # no duplicates


def test_check_exercise():
    assert check_exercise("Estoy", ["estoy"]) is True
    assert check_exercise("  ella está en Madrid ", ["Ella está en Madrid."]) is True
    assert check_exercise("esta", ["está"]) is None  # accents matter: ask the model
    assert check_exercise("soy", ["estoy"]) is None
    assert check_exercise("", ["estoy"]) is None


async def test_lesson_flow(client, fake_llm):
    pid = (await resolve(client))["profile"]["id"]
    # A real mistake on the topic first, so the lesson can use it.
    sid = (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]
    fake_llm.push_result(
        make_result(corrections=[("soy en", "estoy en", "es.a1.ser_vs_estar_basic", "major")])
    )
    await client.post(f"/v1/sessions/{sid}/turns", json={"text": "Yo soy en casa"})

    sugg = (await client.get(f"/v1/learners/{pid}/lessons")).json()
    assert sugg["suggested"][0] == {
        "id": "es.a1.ser_vs_estar_basic",
        "title": sugg["suggested"][0]["title"],
        "level": "A1",
        "mastery": sugg["suggested"][0]["mastery"],
        "lessons_taken": 0,
        "reason": "weak",
    }
    assert all(t["level"] == "A1" for t in sugg["level_topics"])

    r = await client.post(
        f"/v1/learners/{pid}/lessons", json={"topic_id": "es.a1.ser_vs_estar_basic"}
    )
    assert r.status_code == 201, r.text
    lesson = r.json()
    assert lesson["explanation"].startswith("Ser =")  # plain-text rendering
    assert "estar: estoy · estás · está" in lesson["explanation"]
    assert lesson["parts"]["examples"] == [
        {"sentence": "Estoy en casa.", "translation": "I'm at home."}
    ]
    assert lesson["parts"]["watch_out"]["right"] == "Estoy en casa."
    assert lesson["exercise"] == {
        "index": 0,
        "total": 3,
        "kind": "fill_blank",
        "instruction": "Fill the gap",
        "prompt": "Yo ___ en casa.",
    }
    assert "answer" not in lesson["exercise"]  # not revealed
    system, user = fake_llm.lesson_calls[-1]
    assert "Exactly 5 exercises" in system
    assert "<learner_mistakes>\n- soy en → estoy en" in user  # personalised

    lid = lesson["id"]
    # Exact answer: free.
    a1 = (
        await client.post(f"/v1/lessons/{lid}/answer", json={"index": 0, "answer": "Estoy"})
    ).json()
    assert a1["correct"] and a1["feedback"] is None and a1["score"] == 1
    assert a1["next"]["index"] == 1 and a1["progress"]["today"] == 2  # chat turn + this answer
    assert fake_llm.grade_calls == []

    # Answering the same question again is a conflict; skipping ahead is rejected.
    again = await client.post(f"/v1/lessons/{lid}/answer", json={"index": 0, "answer": "x"})
    assert again.status_code == 409
    skip = await client.post(f"/v1/lessons/{lid}/answer", json={"index": 2, "answer": "x"})
    assert skip.status_code == 400

    # Not an exact match: the model judges.
    fake_llm.grades.append(ReviewGrade(correct=False, feedback="Use está."))
    a2 = (
        await client.post(f"/v1/lessons/{lid}/answer", json={"index": 1, "answer": "Ella es"})
    ).json()
    assert not a2["correct"] and a2["feedback"] == "Use está."
    assert a2["expected"] == "Ella está en Madrid."
    assert "Ella es" in fake_llm.grade_calls[-1][1]
    mastery_after_error = a2["mastery"]

    a3 = (
        await client.post(
            f"/v1/lessons/{lid}/answer", json={"index": 2, "answer": "Estoy cansada."}
        )
    ).json()
    assert a3["correct"] and a3["next"] is None and (a3["score"], a3["total"]) == (2, 3)
    assert a3["mastery"] > mastery_after_error

    sugg = (await client.get(f"/v1/learners/{pid}/lessons")).json()
    taken = {t["id"]: t["lessons_taken"] for t in sugg["level_topics"]}
    assert taken["es.a1.ser_vs_estar_basic"] == 1


async def test_lesson_errors(client):
    pid = (await resolve(client))["profile"]["id"]
    r = await client.post(f"/v1/learners/{pid}/lessons", json={"topic_id": "es.a1.nope"})
    assert r.status_code == 404
    r = await client.post("/v1/lessons/999/answer", json={"index": 0, "answer": "x"})
    assert r.status_code == 404


async def test_second_lesson_reuses_explanation_with_fresh_exercises(client, fake_llm):
    pid = (await resolve(client))["profile"]["id"]
    url = f"/v1/learners/{pid}/lessons"
    topic = {"topic_id": "es.a1.ser_vs_estar_basic"}

    first = (await client.post(url, json=topic)).json()
    assert first["reused"] is False
    assert len(fake_llm.lesson_calls) == 1 and fake_llm.exercise_calls == []

    second = (await client.post(url, json=topic)).json()
    assert second["reused"] is True
    assert len(fake_llm.lesson_calls) == 1  # no new explanation
    assert len(fake_llm.exercise_calls) == 1  # only exercises, from the cheap model
    assert second["parts"]["summary"] == first["parts"]["summary"]
    assert second["id"] != first["id"] and second["exercise"]["index"] == 0
    # The exercise prompt carries the explanation the learner sees.
    assert first["parts"]["summary"] in fake_llm.exercise_calls[0][1]

    third = (await client.post(url, json={**topic, "fresh": True})).json()
    assert third["reused"] is False and len(fake_llm.lesson_calls) == 2

    # Answers on a reused lesson work as usual.
    r = await client.post(
        f"/v1/lessons/{second['id']}/answer", json={"index": 0, "answer": "estoy"}
    )
    assert r.status_code == 200 and r.json()["correct"] is True


async def test_cached_lesson_keeps_learner_mistakes_private(client, fake_llm):
    """A lesson written with one learner's mistakes is stored without their 'watch out'."""
    pid = (await resolve(client))["profile"]["id"]
    sid = (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]
    fake_llm.push_result(
        make_result(corrections=[("soy en", "estoy en", "es.a1.ser_vs_estar_basic", "major")])
    )
    await client.post(f"/v1/sessions/{sid}/turns", json={"text": "Yo soy en casa"})
    url = f"/v1/learners/{pid}/lessons"
    await client.post(url, json={"topic_id": "es.a1.ser_vs_estar_basic"})

    r = await client.post("/v1/users/resolve", json={**RESOLVE, "external_id": "someone-else"})
    other = r.json()["profile"]["id"]
    lesson = (
        await client.post(
            f"/v1/learners/{other}/lessons", json={"topic_id": "es.a1.ser_vs_estar_basic"}
        )
    ).json()
    assert lesson["reused"] is True
    w = lesson["parts"]["watch_out"]
    assert w is None or w["note"] != "Location."  # not the one written for the first learner
