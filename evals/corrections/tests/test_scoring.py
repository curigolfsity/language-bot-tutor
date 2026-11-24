from pathlib import Path

import yaml
from scoring import Expected, Predicted, aggregate, find_span, rights_match, score_case
from tutor_api.config import REPO_ROOT
from tutor_api.curriculum import load_curriculum

TEXT = "Yo soy en la playa con mi amigos."
EXP = [
    Expected("soy en", "estoy en", "es.a1.ser_vs_estar_basic"),
    Expected("mi amigos", "mis amigos", "es.a1.possessive_agreement"),
]


def test_find_span_case_insensitive():
    assert find_span(TEXT, "SOY EN") == (3, 9)
    assert find_span(TEXT, "nada") is None
    assert find_span(TEXT, "amigos.") is not None


def test_rights_match():
    assert rights_match("Estoy en", "estoy en")
    assert rights_match("Yo estoy en la playa", "estoy en")  # longer span is fine
    assert not rights_match("estoy", "estás")


def test_perfect_score():
    pred = [
        Predicted("Yo soy en", "Yo estoy en", "es.a1.ser_vs_estar_basic"),
        Predicted("mi amigos", "mis amigos", "es.a1.possessive_agreement"),
    ]
    s = score_case(TEXT, EXP, pred, ["la playa"])
    assert (s.matched, s.tag_correct, s.must_not_flag_hits) == (2, 2, [])


def test_wrong_tag_and_false_positive():
    pred = [
        Predicted("soy en", "estoy en", "es.a1.gender_agreement"),
        Predicted("la playa", "el playa", "es.a1.gender_agreement"),
    ]
    s = score_case(TEXT, EXP, pred, ["la playa"])
    assert s.matched == 1 and s.tag_correct == 0
    assert len(s.must_not_flag_hits) == 1
    assert s.unmatched_expected == ["mi amigos -> mis amigos"]


def test_one_to_one_matching():
    pred = [Predicted("soy en", "estoy en", "x")]
    exp = [Expected("soy en", "estoy en", "x"), Expected("soy", "estoy en", "x")]
    assert score_case(TEXT, exp, pred).matched == 1


def test_alternatives():
    exp = [
        Expected(
            "soy en",
            "estoy en",
            "es.a1.ser_vs_estar_basic",
            also_right=["me encuentro en"],
            also_tags=["es.a1.estar_present"],
        )
    ]
    pred = [Predicted("soy en", "me encuentro en", "es.a1.estar_present")]
    s = score_case(TEXT, exp, pred)
    assert (s.matched, s.tag_correct) == (1, 1)
    assert score_case(TEXT, exp, [Predicted("soy en", "era en", "x")]).matched == 0


def test_aggregate():
    a = score_case(TEXT, EXP, [Predicted("soy en", "estoy en", "es.a1.ser_vs_estar_basic")])
    b = score_case("Hola.", [], [])
    m = aggregate([a, b], policy_violations=1)
    assert (m.recall, m.precision, m.rule_tag_accuracy) == (0.5, 1.0, 1.0)
    assert m.cases == 2 and m.policy_violations == 1
    assert aggregate([b]).recall is None


def test_cases_reference_real_topics():
    """Every expected rule_tag in the eval set must exist in the curriculum."""
    es = load_curriculum(REPO_ROOT / "curriculum" / "es")
    cases_dir = Path(__file__).resolve().parents[1] / "cases"
    count = 0
    for path in cases_dir.glob("*.yaml"):
        for case in yaml.safe_load(path.read_text(encoding="utf-8")):
            count += 1
            assert es.has_level(case["level"]), case["id"]
            for exp in case["expected"]:
                for tag in [exp["rule_tag"], *exp.get("also_tags", [])]:
                    assert tag in es.topics, f"{case['id']}: {tag}"
                assert find_span(case["text"], exp["wrong"]), f"{case['id']}: {exp['wrong']}"
            for phrase in case.get("must_not_flag") or []:
                assert find_span(case["text"], phrase), f"{case['id']}: {phrase}"
    assert count >= 30
