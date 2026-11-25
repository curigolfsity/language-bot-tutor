"""Exhaustive tests for the pure domain layer."""

import pytest
from conftest import make_result
from tutor_api.domain import mastery as m
from tutor_api.domain.policy import resolve_policy
from tutor_api.domain.prompt import (
    PriorTurn,
    build_learner_summary,
    build_system_prompt,
    build_user_content,
    catalogue_for,
)
from tutor_api.domain.tags import (
    MAX_REPORTED_CORRECTIONS,
    apply_policy,
    for_display,
    sanitize_tags,
)

# ---------------------------------------------------------------- policy


def test_policy_reads_levels_yaml(es):
    p = resolve_policy(es, "A1", "th")
    lp = es.levels["A1"]
    assert p.explanation_language == lp.explanation_language
    assert p.max_corrections_per_turn == lp.max_corrections_per_turn
    assert p.correct_topics == lp.correct_topics
    assert p.max_sentences == lp.tutor_reply.max_sentences
    assert p.native_lang == "th"
    assert p.focus_topics == ()


def test_policy_override_and_scenario(es):
    sc = es.scenarios["es.a2.restaurant_order"]
    p = resolve_policy(es, "A2", "en", "target", sc)
    assert p.explanation_language == "target"
    assert p.focus_topics == sc.target_topics


def test_policy_unknown_level(es):
    with pytest.raises(ValueError):
        resolve_policy(es, "Z9", "en")


# ---------------------------------------------------------------- prompt


def test_catalogue_respects_correct_topics(es):
    a1 = catalogue_for(es, resolve_policy(es, "A1", "en"))
    assert a1 and all(es.rank(t.level) <= es.rank("A1") for t in a1)
    b1 = catalogue_for(es, resolve_policy(es, "B1", "en"))  # "all"
    assert {t.id for t in b1} == {t.id for t in es.active_topics()}


def test_system_prompt_is_stable_and_learner_free(es):
    p1 = resolve_policy(es, "A1", "en")
    p2 = resolve_policy(es, "A1", "th", scenario=es.scenarios["es.a1.cafe_order"])
    s1, s2 = build_system_prompt(es, p1), build_system_prompt(es, p2)
    assert s1 == s2, "native language / scenario must not leak into the cached prefix"
    assert "es.a1.ser_vs_estar_basic" in s1
    assert "es.b1.future_simple" not in s1  # above level at at_or_below_level
    for note in es.lang.prompt_notes:
        assert note in s1


def test_user_content_order(es):
    p = resolve_policy(es, "A1", "en", scenario=es.scenarios["es.a1.cafe_order"])
    content = build_user_content(
        p,
        es.scenarios["es.a1.cafe_order"],
        "summary-here",
        [PriorTurn("tutor", "¡Buenos días!"), PriorTurn("learner", "Hola")],
        "Quiero un café <b>",
    )
    order = [
        content.index(s)
        for s in ("<scenario>", "<learner>", "<conversation>", "<latest_learner_message>")
    ]
    assert order == sorted(order)
    assert "&lt;b&gt;" in content  # learner text is escaped
    assert "summary-here" in content


def test_learner_summary():
    assert build_learner_summary([], []) == "No history yet."
    s = build_learner_summary([("es.a1.x", 0.2)], [("a", "b", "es.a1.x")])
    assert "es.a1.x (0.20)" in s and "a → b [es.a1.x]" in s


# ---------------------------------------------------------------- tags & policy enforcement


def test_sanitize_maps_unknown(es):
    r = make_result(
        corrections=[("a", "b", "es.a1.gender_agreement", "major"), ("c", "d", "made.up", "minor")],
        tags=["es.a1.gender_agreement", "bogus", "also.bogus", "unknown"],
    )
    clean, report = sanitize_tags(r, es.topic_ids())
    assert [c.rule_tag for c in clean.corrections] == ["es.a1.gender_agreement", "unknown"]
    assert clean.grammar_tags == ["es.a1.gender_agreement", "unknown"]
    assert set(report.unknown_tags) == {"made.up", "bogus", "also.bogus"}


def test_sanitize_accepts_unique_bare_slug(es):
    r = make_result(corrections=[], tags=["gender_agreement", " gender_agreement "])
    clean, report = sanitize_tags(r, es.topic_ids())
    assert clean.grammar_tags == ["es.a1.gender_agreement"]
    assert report.unknown_tags == ()


def test_apply_policy_drops_above_level_and_orders_majors_first(es):
    p = resolve_policy(es, "A1", "en")  # max 2, at_or_below_level
    r = make_result(
        corrections=[
            ("x1", "y1", "es.a1.gender_agreement", "minor"),
            ("x2", "y2", "es.b1.future_simple", "major"),  # above A1 -> dropped
            ("x3", "y3", "es.a1.ser_vs_estar_basic", "major"),
            ("x4", "y4", "unknown", "major"),
            ("same", "same", "es.a1.gender_agreement", "minor"),  # no-op -> dropped
        ]
    )
    out, report = apply_policy(r, p, es)
    # Every in-scope correction is kept (they drive mastery), majors first.
    assert [c.wrong for c in out.corrections] == ["x3", "x4", "x1"]
    assert any(v.startswith("above_level") for v in report.violations)
    assert any(v.startswith("noop_correction") for v in report.violations)
    assert not any(v.startswith("too_many_corrections") for v in report.violations)
    # The learner sees only the level's cut.
    assert [c.wrong for c in for_display(out, p).corrections] == ["x3", "x4"]


def test_apply_policy_sanity_ceiling(es):
    p = resolve_policy(es, "C2", "en")
    n = MAX_REPORTED_CORRECTIONS + 5
    r = make_result(corrections=[(f"w{i}", f"r{i}", "unknown", "minor") for i in range(n)])
    out, report = apply_policy(r, p, es)
    assert len(out.corrections) == MAX_REPORTED_CORRECTIONS
    assert any(v.startswith("too_many_corrections") for v in report.violations)


def test_apply_policy_all_keeps_higher_topics(es):
    p = resolve_policy(es, "B1", "en")
    r = make_result(corrections=[("a", "b", "es.b2.si_clauses", "major")])
    out, report = apply_policy(r, p, es)
    assert len(out.corrections) == 1 and not report.violations


# ---------------------------------------------------------------- mastery math


def test_correct_and_error_updates():
    assert m.on_correct_use(0.0, 0.2) == pytest.approx(0.2)
    assert m.on_correct_use(0.5, 0.2) == pytest.approx(0.6)
    assert m.on_correct_use(1.0, 0.2) == 1.0
    assert m.on_error(0.5, 0.2, "major") == pytest.approx(0.4)
    assert m.on_error(0.5, 0.2, "minor") == pytest.approx(0.45)
    assert m.on_error(0.0, 0.2, "major") == 0.0


def test_topic_updates():
    r = make_result(
        corrections=[
            ("a", "b", "t.err", "major"),
            ("c", "d", "t.err", "minor"),
            ("e", "f", "unknown", "major"),
        ],
        tags=["t.ok", "t.err", "unknown", "t.ok"],
    )
    current = {"t.err": m.TopicState(0.5, 4, 1), "t.ok": m.TopicState(0.5, 2, 0)}
    out = m.topic_updates(r.grammar_tags, r.corrections, current, 0.2)
    assert set(out) == {"t.err", "t.ok"}
    # two errors applied in sequence: 0.5 -> 0.4 (major) -> 0.36 (minor)
    assert out["t.err"].mastery == pytest.approx(0.36)
    assert (out["t.err"].attempts, out["t.err"].errors) == (6, 3)
    # duplicate tag counts once
    assert out["t.ok"].mastery == pytest.approx(0.6)
    assert (out["t.ok"].attempts, out["t.ok"].errors) == (3, 0)


def test_topic_updates_new_topic():
    out = m.topic_updates(["t.new"], [], {}, 0.25)
    assert out["t.new"] == m.TopicState(0.25, 1, 0)


def test_vocab_used_correctly():
    r = make_result(corrections=[("la cuenta es", "la cuenta, por favor", "unknown", "minor")])
    used = m.vocab_used_correctly(
        "¡La ración está rica! La cuenta es", ["la ración", "la cuenta", "picar"], r.corrections
    )
    assert used == {"la ración"}


def test_contains_phrase_word_boundaries():
    assert m.contains_phrase("Quiero pan.", "pan")
    assert not m.contains_phrase("Quiero panes.", "pan")
    assert not m.contains_phrase("Quiero pan.", "")
    assert m.contains_phrase("¡ÉL ESTÁ AQUÍ!", "está")


def test_aggregate_score():
    assert m.aggregate_score([]) == 0.0
    assert m.aggregate_score([0.2, 0.4]) == pytest.approx(0.3)


# ---------------------------------------------------------------- praise & help prompts

from tutor_api.domain.prompt import build_help_prompt  # noqa: E402
from tutor_api.domain.tags import well_done_topics  # noqa: E402


def test_well_done_topics(es):
    p = resolve_policy(es, "A1", "en")  # max 2 corrections
    r = make_result(
        corrections=[("a", "b", "es.a1.ser_vs_estar_basic", "major")],
        tags=[
            "es.a1.ser_vs_estar_basic",
            "unknown",
            "es.a1.ser_present",
            "es.a1.gender_agreement",
            "es.a1.estar_present",
        ],
    )
    # corrected topic and "unknown" excluded; capped at 2
    assert well_done_topics(r, p, es) == ["es.a1.ser_present", "es.a1.gender_agreement"]
    # A topic whose error falls beyond the display cut is still not praised.
    beyond_cut = make_result(
        corrections=[
            ("a", "b", "unknown", "major"),
            ("c", "d", "unknown", "major"),
            ("e", "f", "es.a1.ser_present", "minor"),
        ],
        tags=["es.a1.ser_present", "es.a1.gender_agreement"],
    )
    assert len(for_display(beyond_cut, p).corrections) == 2
    assert well_done_topics(beyond_cut, p, es) == ["es.a1.gender_agreement"]


@pytest.mark.parametrize("kind", ["hint", "translate", "suggest", "explain"])
def test_help_prompt(es, kind):
    sc = es.scenarios["es.a1.cafe_order"]
    p = resolve_policy(es, "A1", "th", scenario=sc)
    system, user = build_help_prompt(
        p,
        kind,
        sc,
        [PriorTurn("learner", "hola <x>")],
        "¿Qué quieres?",
        [("soy en", "estoy en", "location")],
    )
    assert "'th'" in system and es.lang.name in system
    assert "¿Qué quieres?" in user and "&lt;x&gt;" in user and sc.title in user
    assert ("<corrections>" in user) == (kind == "explain")


def test_help_explain_without_corrections(es):
    p = resolve_policy(es, "B1", "en")
    system, user = build_help_prompt(p, "explain", None, [], "Hola", [])
    assert "no corrections" in user
    assert "glosses" in system  # B1 = mixed explanation language


# ---------------------------------------------------------------- languages without spaces

from tutor_api.domain.mastery import contains_phrase  # noqa: E402
from tutor_api.domain.review import quick_grade  # noqa: E402
from tutor_api.domain.text import contains_unit, is_unspaced  # noqa: E402


def test_contains_unit_spaced_and_unspaced():
    assert contains_unit("mi amigo", "mi") and not contains_unit("amigos", "mi")
    assert contains_unit("我喜欢喝咖啡", "咖啡") and contains_unit(
        "わたしはがくせいです", "がくせい"
    )
    assert not contains_unit("我喜欢喝茶", "咖啡") and not contains_unit("x", "")
    assert is_unspaced("学生") and is_unspaced("カタカナ") and not is_unspaced("hola")


def test_vocab_and_quick_grade_work_for_cjk():
    assert contains_phrase("我想喝一杯咖啡。", "咖啡")
    assert quick_grade("我有两本书", "两书", "两本书") is True
    assert quick_grade("わたしは学生です", "わたし学生", "わたしは学生") is True
    assert quick_grade("我有两书", "两书", "两本书") is None
