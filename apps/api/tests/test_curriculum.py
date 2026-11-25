from pathlib import Path

import pytest
from conftest import write_tree
from tutor_api.config import REPO_ROOT
from tutor_api.curriculum import CurriculumError, load_all_curricula, load_curriculum

LANG = "code: xx\nname: Testish\nnative_name: Testish\nrefusal_reply: 'no'\n"
LEVELS = """
A1: {rank: 1, explanation_language: native, max_corrections_per_turn: 2,
     correct_topics: at_or_below_level,
     tutor_reply: {max_sentences: 2, vocab_ceiling: A1}, free_opening: hi, label: x}
A2: {rank: 2, explanation_language: native, max_corrections_per_turn: 3, correct_topics: all,
     tutor_reply: {max_sentences: 3, vocab_ceiling: A2}, free_opening: hi, label: x}
"""


def topic(tid: str, level: str = "A1", prereqs: str = "[]") -> str:
    return f"- {{id: {tid}, level: {level}, title: t, description: d, prerequisites: {prereqs}}}\n"


def scenario(sid: str, targets: str, level: str = "A1") -> str:
    return (
        f"- {{id: {sid}, level: {level}, title: t, setting: s, bot_role: b, goals: [g], "
        f"target_topics: {targets}, opening_line: hola}}\n"
    )


def make_lang(
    tmp_path: Path, grammar_a1: str, grammar_a2: str = "", scenarios: str = "", levels: str = LEVELS
) -> Path:
    return write_tree(
        tmp_path / "xx",
        {
            "language.yaml": LANG,
            "levels.yaml": levels,
            "grammar/a1.yaml": grammar_a1,
            "grammar/a2.yaml": grammar_a2,
            "scenarios/a1.yaml": scenarios,
        },
    )


def test_real_curriculum_is_valid():
    curricula = load_all_curricula(REPO_ROOT / "curriculum")
    es = curricula["es"]
    assert es.ordered_levels == ("A1", "A2", "B1", "B2", "C1", "C2")
    assert "es.a1.ser_vs_estar_basic" in es.topics
    assert es.lowest_level == "A1"


def test_valid_minimal(tmp_path):
    cur = load_curriculum(
        make_lang(
            tmp_path,
            topic("xx.a1.one") + topic("xx.a1.two", prereqs="[xx.a1.one]"),
            scenarios=scenario("xx.a1.sc", "[xx.a1.two]"),
        )
    )
    assert set(cur.topics) == {"xx.a1.one", "xx.a1.two"}
    assert cur.scenarios_near("A1")[0].id == "xx.a1.sc"


@pytest.mark.parametrize(
    ("a1", "a2", "scen", "needle"),
    [
        (topic("xx.a1.one") + topic("xx.a1.one"), "", "", "duplicate topic id"),
        (topic("xx.a1.one", prereqs="[xx.a1.nope]"), "", "", "unknown prerequisite"),
        (
            topic("xx.a1.one", prereqs="[xx.a1.two]") + topic("xx.a1.two", prereqs="[xx.a1.one]"),
            "",
            "",
            "prerequisite cycle",
        ),
        (topic("xx.a1.one", prereqs="[xx.a2.high]"), topic("xx.a2.high", "A2"), "", "higher level"),
        (topic("xx.a1.one"), "", scenario("xx.a1.sc", "[xx.a1.missing]"), "unknown target_topic"),
        (topic("xx.b1.one", "B1"), "", "", "missing from levels.yaml"),
        (topic("xx.a2.wrongprefix", "A1"), "", "", "must start with"),
    ],
)
def test_invalid_curricula_are_rejected(tmp_path, a1, a2, scen, needle):
    with pytest.raises(CurriculumError, match=needle):
        load_curriculum(make_lang(tmp_path, a1, a2, scen))


def test_self_cycle(tmp_path):
    with pytest.raises(CurriculumError, match="cycle"):
        load_curriculum(make_lang(tmp_path, topic("xx.a1.one", prereqs="[xx.a1.one]")))


def test_duplicate_rank_and_bad_ceiling(tmp_path):
    levels = LEVELS.replace("rank: 2", "rank: 1").replace("vocab_ceiling: A2", "vocab_ceiling: Z9")
    with pytest.raises(CurriculumError) as e:
        load_curriculum(make_lang(tmp_path, topic("xx.a1.one"), levels=levels))
    assert "ranks must be unique" in str(e.value)
    assert "vocab_ceiling" in str(e.value)


def test_yaml_syntax_error(tmp_path):
    with pytest.raises(CurriculumError, match="YAML syntax"):
        load_curriculum(make_lang(tmp_path, "- {id: [unclosed"))


def test_unknown_field_rejected(tmp_path):
    with pytest.raises(CurriculumError):
        load_curriculum(
            make_lang(
                tmp_path, "- {id: xx.a1.one, level: A1, title: t, description: d, colour: red}\n"
            )
        )


def test_starter_scenario_validation(tmp_path):
    bad_ref = LEVELS.replace(
        "free_opening: hi, label: x}",
        "free_opening: hi, label: x, starter_scenario: xx.a1.nope}",
        1,
    )
    with pytest.raises(CurriculumError, match="unknown starter_scenario"):
        load_curriculum(make_lang(tmp_path, topic("xx.a1.one"), levels=bad_ref))


def test_starter_scenario_wrong_level(tmp_path):
    levels = LEVELS.replace(
        "free_opening: hi, label: x}", "free_opening: hi, label: x, starter_scenario: xx.a1.sc}"
    )
    # A2's starter points at an A1 scenario
    with pytest.raises(CurriculumError, match="is at level A1, not A2"):
        load_curriculum(
            make_lang(
                tmp_path,
                topic("xx.a1.one"),
                scenarios=scenario("xx.a1.sc", "[xx.a1.one]"),
                levels=levels,
            )
        )


def test_all_shipped_languages_load():
    from tutor_api.config import REPO_ROOT
    from tutor_api.curriculum import load_all_curricula

    curricula = load_all_curricula(REPO_ROOT / "curriculum")
    assert {"es", "zh", "ja"} <= set(curricula)
    for code, cur in curricula.items():
        assert cur.lang.flag, code
        assert cur.ordered_levels[0] == cur.lowest_level
        for level in cur.levels.values():  # every level has a starter role-play at that level
            assert level.starter_scenario in cur.scenarios, (code, level.code)
        assert all(t.id.startswith(f"{code}.") for t in cur.topics.values())
