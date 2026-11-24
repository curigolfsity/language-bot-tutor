"""Pure scoring for the correction eval. No I/O, no LLM. Unit-tested in tests/test_scoring.py.

A predicted correction matches an expected one when:
  - their `wrong` spans overlap in the learner's text, and
  - the normalised `right` texts match (either one contains the other, so a slightly longer or
    shorter corrected span still counts). `also_right` lists other acceptable corrections.
The rule tag counts as correct if it is `rule_tag` or one of `also_tags` (for errors that two
catalogue topics describe equally well).
Matching is one-to-one and greedy in expected order.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Expected:
    wrong: str
    right: str
    rule_tag: str
    also_right: Sequence[str] = ()
    also_tags: Sequence[str] = ()

    def accepts_right(self, pred: str) -> bool:
        return any(rights_match(pred, r) for r in (self.right, *self.also_right))

    def accepts_tag(self, tag: str) -> bool:
        return tag == self.rule_tag or tag in self.also_tags


@dataclass(frozen=True)
class Predicted:
    wrong: str
    right: str
    rule_tag: str


@dataclass
class CaseScore:
    expected: int
    predicted: int
    matched: int
    tag_correct: int
    must_not_flag_hits: list[str] = field(default_factory=list)
    unmatched_expected: list[str] = field(default_factory=list)
    unmatched_predicted: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    """Lowercase, NFC, drop punctuation, collapse whitespace. Accents are significant."""
    text = unicodedata.normalize("NFC", text).casefold()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_span(text: str, fragment: str) -> tuple[int, int] | None:
    """Case-insensitive location of `fragment` in `text`, or None."""
    if not fragment.strip():
        return None
    hay = unicodedata.normalize("NFC", text).casefold()
    needle = unicodedata.normalize("NFC", fragment.strip()).casefold()
    i = hay.find(needle)
    if i < 0:
        # Retry ignoring trailing punctuation the model may have kept or dropped.
        needle = needle.strip(" .,;:!?¡¿\"'")
        i = hay.find(needle) if needle else -1
    return (i, i + len(needle)) if i >= 0 else None


def spans_overlap(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    return a is not None and b is not None and a[0] < b[1] and b[0] < a[1]


def rights_match(pred: str, exp: str) -> bool:
    p, e = normalize(pred), normalize(exp)
    return bool(p) and bool(e) and (p == e or f" {e} " in f" {p} " or f" {p} " in f" {e} ")


def _wrong_overlap(text: str, pred: str, exp: str) -> bool:
    ps, es = find_span(text, pred), find_span(text, exp)
    if ps is not None and es is not None:
        return spans_overlap(ps, es)
    # The model did not quote the text verbatim: fall back to normalised containment.
    p, e = normalize(pred), normalize(exp)
    return bool(p) and bool(e) and (f" {e} " in f" {p} " or f" {p} " in f" {e} ")


def score_case(
    text: str,
    expected: Sequence[Expected],
    predicted: Sequence[Predicted],
    must_not_flag: Sequence[str] = (),
) -> CaseScore:
    used: set[int] = set()
    matched = tag_correct = 0
    unmatched_expected: list[str] = []
    for exp in expected:
        hit = next(
            (
                i
                for i, p in enumerate(predicted)
                if i not in used
                and _wrong_overlap(text, p.wrong, exp.wrong)
                and exp.accepts_right(p.right)
            ),
            None,
        )
        if hit is None:
            unmatched_expected.append(f"{exp.wrong} -> {exp.right}")
            continue
        used.add(hit)
        matched += 1
        if exp.accepts_tag(predicted[hit].rule_tag):
            tag_correct += 1

    unmatched_predicted = [
        f"{p.wrong} -> {p.right} [{p.rule_tag}]" for i, p in enumerate(predicted) if i not in used
    ]
    mnf_spans = [(phrase, find_span(text, phrase)) for phrase in must_not_flag]
    mnf_hits = [
        f"{p.wrong} (protected: {phrase})"
        for i, p in enumerate(predicted)
        if i not in used
        for phrase, span in mnf_spans
        if spans_overlap(find_span(text, p.wrong), span)
    ]
    return CaseScore(
        expected=len(expected),
        predicted=len(predicted),
        matched=matched,
        tag_correct=tag_correct,
        must_not_flag_hits=mnf_hits,
        unmatched_expected=unmatched_expected,
        unmatched_predicted=unmatched_predicted,
    )


@dataclass
class LevelMetrics:
    cases: int
    recall: float | None
    precision: float | None
    rule_tag_accuracy: float | None
    must_not_flag_false_positives: int
    policy_violations: int
    refusals: int


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def aggregate(
    scores: Sequence[CaseScore], policy_violations: int = 0, refusals: int = 0
) -> LevelMetrics:
    exp = sum(s.expected for s in scores)
    pred = sum(s.predicted for s in scores)
    matched = sum(s.matched for s in scores)
    return LevelMetrics(
        cases=len(scores),
        recall=_ratio(matched, exp),
        precision=_ratio(matched, pred),
        rule_tag_accuracy=_ratio(sum(s.tag_correct for s in scores), matched),
        must_not_flag_false_positives=sum(len(s.must_not_flag_hits) for s in scores),
        policy_violations=policy_violations,
        refusals=refusals,
    )
