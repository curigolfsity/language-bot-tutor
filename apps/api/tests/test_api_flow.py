"""End-to-end through HTTP with an in-memory DB and a fake LLM."""

from conftest import make_result
from tutor_api.llm import LLMError

RESOLVE = {
    "provider": "telegram",
    "external_id": "42",
    "display_name": "Ana",
    "target_lang": "es",
    "native_lang": "en",
}


async def resolve(client) -> dict:
    r = await client.post("/v1/users/resolve", json=RESOLVE)
    assert r.status_code == 200, r.text
    return r.json()


async def test_healthz_needs_no_key(client):
    r = await client.get("/healthz", headers={"X-Client-Key": ""})
    assert r.status_code == 200 and r.json()["languages"] == ["es"]


async def test_auth_required(client):
    r = await client.post("/v1/users/resolve", json=RESOLVE, headers={"X-Client-Key": "wrong"})
    assert r.status_code == 401


async def test_resolve_is_idempotent(client):
    first = await resolve(client)
    second = await resolve(client)
    assert first["created"] is True and second["created"] is False
    assert first["profile"]["id"] == second["profile"]["id"]
    assert first["profile"]["cefr_level"] == "A1"  # lowest rank from levels.yaml
    assert {s["skill"] for s in first["profile"]["skills"]} == {
        "speaking",
        "listening",
        "reading",
        "writing",
        "grammar",
        "vocab",
    }


async def test_resolve_unknown_language(client):
    r = await client.post("/v1/users/resolve", json={**RESOLVE, "target_lang": "zz"})
    assert r.status_code == 400


async def test_patch_level_validation(client):
    pid = (await resolve(client))["profile"]["id"]
    assert (await client.patch(f"/v1/learners/{pid}", json={"cefr_level": "Z9"})).status_code == 400
    r = await client.patch(
        f"/v1/learners/{pid}", json={"cefr_level": "B1", "explanation_lang_override": "target"}
    )
    body = r.json()
    assert body["cefr_level"] == "B1" and body["explanation_lang_override"] == "target"
    assert all(s["cefr_level"] == "B1" for s in body["skills"])
    r = await client.patch(f"/v1/learners/{pid}", json={"explanation_lang_override": None})
    assert r.json()["explanation_lang_override"] is None
    assert r.json()["cefr_level"] == "B1"  # omitted field untouched


async def test_curriculum_endpoints(client):
    levels = (await client.get("/v1/curriculum/es/levels")).json()
    assert [lv["code"] for lv in levels] == ["A1", "A2", "B1", "B2", "C1", "C2"]
    grammar = (await client.get("/v1/curriculum/es/grammar", params={"level": "A1"})).json()
    assert grammar and all(t["level"] == "A1" for t in grammar)
    scen = (await client.get("/v1/curriculum/es/scenarios", params={"level": "A1"})).json()
    assert {s["level"] for s in scen} <= {"A1", "A2"}
    assert (await client.get("/v1/curriculum/es/grammar", params={"level": "Q"})).status_code == 400


async def test_full_turn_flow(client, fake_llm):
    pid = (await resolve(client))["profile"]["id"]

    assert (await client.get(f"/v1/learners/{pid}/active-session")).status_code == 404
    r = await client.post(
        "/v1/sessions", json={"profile_id": pid, "scenario_id": "es.a1.cafe_order"}
    )
    assert r.status_code == 201, r.text
    session = r.json()
    assert session["mode"] == "roleplay"
    assert session["opening_line"] == "¡Buenos días! ¿Qué quieres tomar?"
    active = (await client.get(f"/v1/learners/{pid}/active-session")).json()
    assert active["id"] == session["id"] and active["opening_line"] == session["opening_line"]

    fake_llm.push_result(
        make_result(
            reply="¡Claro! Un café. ¿Algo más?",
            corrections=[
                ("Yo soy en", "Yo estoy en", "es.a1.ser_vs_estar_basic", "major"),
                ("el tostada", "la tostada", "invented.tag", "minor"),
            ],
            tags=["es.a1.ser_vs_estar_basic", "es.a1.gustar_basic", "nonsense"],
            vocab=["la tostada"],
        )
    )
    r = await client.post(
        f"/v1/sessions/{session['id']}/turns",
        json={"text": "Yo soy en el café. Me gusta el tostada."},
    )
    assert r.status_code == 200, r.text
    turn = r.json()
    assert turn["reply"] == "¡Claro! Un café. ¿Algo más?"
    assert [c["rule_tag"] for c in turn["corrections"]] == ["es.a1.ser_vs_estar_basic", "unknown"]
    assert "nonsense" not in turn["grammar_tags"]

    system, user = fake_llm.calls[-1]
    assert "Ordering at a café" in user and "¡Buenos días!" in user  # scenario + opening turn
    assert "Yo soy en el café" in user
    assert "Ordering at a café" not in system  # scenario is not in the cached prefix

    mistakes = (await client.get(f"/v1/learners/{pid}/mistakes")).json()
    assert {m["rule_tag"] for m in mistakes} == {"es.a1.ser_vs_estar_basic", "unknown"}
    only = (await client.get(f"/v1/learners/{pid}/mistakes", params={"topic": "unknown"})).json()
    assert len(only) == 1

    vocab = (await client.get(f"/v1/learners/{pid}/vocab")).json()
    assert [v["lemma"] for v in vocab] == ["la tostada"] and vocab[0]["mastery"] == 0.0

    # Second turn: learner uses the word correctly -> vocab mastery rises; correct topic use.
    fake_llm.push_result(make_result(tags=["es.a1.gender_agreement"]))
    await client.post(
        f"/v1/sessions/{session['id']}/turns", json={"text": "Y la tostada, por favor."}
    )
    vocab = (await client.get(f"/v1/learners/{pid}/vocab")).json()
    assert vocab[0]["mastery"] > 0 and vocab[0]["seen_count"] == 2

    # Second learner message's summary includes the earlier mistake.
    assert "Yo soy en → Yo estoy en" in fake_llm.calls[-1][1]

    summary = (await client.post(f"/v1/sessions/{session['id']}/end")).json()
    assert summary["turn_count"] == 2
    assert {m["rule_tag"] for m in summary["top_mistakes"]} == {
        "es.a1.ser_vs_estar_basic",
        "unknown",
    }
    assert [v["lemma"] for v in summary["new_vocab"]] == ["la tostada"]

    profile = (await client.get(f"/v1/learners/{pid}")).json()
    skills = {s["skill"]: s["score"] for s in profile["skills"]}
    assert skills["grammar"] > 0 and skills["vocab"] > 0

    # ended session rejects turns; end is idempotent
    r = await client.post(f"/v1/sessions/{session['id']}/turns", json={"text": "hola"})
    assert r.status_code == 409
    assert (await client.post(f"/v1/sessions/{session['id']}/end")).status_code == 200


async def test_new_session_closes_open_one(client):
    pid = (await resolve(client))["profile"]["id"]
    s1 = (await client.post("/v1/sessions", json={"profile_id": pid})).json()
    assert s1["mode"] == "free" and s1["opening_line"] == "¡Hola! ¿Cómo estás?"
    s2 = (await client.post("/v1/sessions", json={"profile_id": pid})).json()
    active = (await client.get(f"/v1/learners/{pid}/active-session")).json()
    assert active["id"] == s2["id"] != s1["id"]
    r = await client.post(f"/v1/sessions/{s1['id']}/turns", json={"text": "hola"})
    assert r.status_code == 409


async def test_unknown_scenario(client):
    pid = (await resolve(client))["profile"]["id"]
    r = await client.post("/v1/sessions", json={"profile_id": pid, "scenario_id": "es.a1.nope"})
    assert r.status_code == 400


async def test_refusal_returns_polite_reply(client, fake_llm, es):
    pid = (await resolve(client))["profile"]["id"]
    sid = (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]
    fake_llm.push_refusal()
    r = await client.post(f"/v1/sessions/{sid}/turns", json={"text": "..."})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.pop("turn_id"), int)
    assert body == {
        "reply": es.lang.refusal_reply,
        "corrections": [],
        "new_vocab": [],
        "grammar_tags": [],
        "well_done": [],
    }
    assert (await client.get(f"/v1/learners/{pid}/mistakes")).json() == []


async def test_llm_failure_is_502(client, fake_llm):
    pid = (await resolve(client))["profile"]["id"]
    sid = (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]
    fake_llm.queue.append(LLMError("boom"))
    r = await client.post(f"/v1/sessions/{sid}/turns", json={"text": "hola"})
    assert r.status_code == 502


async def test_language_overview_has_friendly_levels(client, es):
    lang = (await client.get("/v1/curriculum/es")).json()
    assert lang["name"] == es.lang.name
    first = lang["levels"][0]
    assert first["code"] == es.lowest_level
    assert first["label"] == es.levels[es.lowest_level].label
    assert first["starter_scenario"] in es.scenarios


async def test_turn_response_praise_and_turn_id(client, fake_llm):
    pid = (await resolve(client))["profile"]["id"]
    sid = (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]
    fake_llm.push_result(make_result(tags=["es.a1.ser_present", "es.a1.gender_agreement"]))
    body = (await client.post(f"/v1/sessions/{sid}/turns", json={"text": "Soy Ana."})).json()
    assert isinstance(body["turn_id"], int)
    assert [t["id"] for t in body["well_done"]] == ["es.a1.ser_present", "es.a1.gender_agreement"]
    assert body["well_done"][0]["title"]

    # A1 shows 2 corrections. A third (hidden) error is still recorded as a mistake, and its
    # topic is not praised even though the model also listed it in grammar_tags.
    fake_llm.push_result(
        make_result(
            corrections=[
                ("a", "b", "es.a1.ser_vs_estar_basic", "major"),
                ("c", "d", "es.a1.tener_expressions", "major"),
                ("e", "f", "es.a1.possessive_agreement", "minor"),
            ],
            tags=["es.a1.possessive_agreement", "es.a1.gender_agreement"],
        )
    )
    body = (await client.post(f"/v1/sessions/{sid}/turns", json={"text": "x"})).json()
    assert [c["wrong"] for c in body["corrections"]] == ["a", "c"]
    assert [t["id"] for t in body["well_done"]] == ["es.a1.gender_agreement"]
    mistakes = (await client.get(f"/v1/learners/{pid}/mistakes")).json()
    assert {m["wrong"] for m in mistakes} == {"a", "c", "e"}


async def test_help_on_opening_and_turn(client, fake_llm):
    pid = (await resolve(client))["profile"]["id"]
    session = (
        await client.post(
            "/v1/sessions", json={"profile_id": pid, "scenario_id": "es.a1.cafe_order"}
        )
    ).json()
    opening_id = session["opening_turn_id"]
    assert isinstance(opening_id, int)
    active = (await client.get(f"/v1/learners/{pid}/active-session")).json()
    assert active["opening_turn_id"] == opening_id

    r = await client.post(f"/v1/turns/{opening_id}/help", json={"kind": "translate"})
    assert r.status_code == 200 and r.json() == {"kind": "translate", "text": "help text"}
    system, user = fake_llm.help_calls[-1]
    assert "Translate" in system and "¡Buenos días! ¿Qué quieres tomar?" in user

    fake_llm.push_result(
        make_result(corrections=[("Yo soy en", "Yo estoy en", "es.a1.ser_vs_estar_basic", "major")])
    )
    turn = (
        await client.post(f"/v1/sessions/{session['id']}/turns", json={"text": "Yo soy en el café"})
    ).json()
    r = await client.post(f"/v1/turns/{turn['turn_id']}/help", json={"kind": "explain"})
    assert r.status_code == 200
    _, user = fake_llm.help_calls[-1]
    assert "Yo soy en → Yo estoy en" in user  # corrections of that turn are passed
    assert "Yo soy en el café" in user  # conversation context before the tutor message


async def test_help_errors(client, fake_llm, es):
    pid = (await resolve(client))["profile"]["id"]
    sid = (await client.post("/v1/sessions", json={"profile_id": pid})).json()["id"]
    turn = (await client.post(f"/v1/sessions/{sid}/turns", json={"text": "hola"})).json()
    assert (await client.post("/v1/turns/999999/help", json={"kind": "hint"})).status_code == 404
    learner_turn_id = turn["turn_id"] - 1
    r = await client.post(f"/v1/turns/{learner_turn_id}/help", json={"kind": "hint"})
    assert r.status_code == 400
    r = await client.post(f"/v1/turns/{turn['turn_id']}/help", json={"kind": "dance"})
    assert r.status_code == 422
    fake_llm.help_refuse = True
    r = await client.post(f"/v1/turns/{turn['turn_id']}/help", json={"kind": "hint"})
    assert r.json()["text"] == es.lang.refusal_reply
