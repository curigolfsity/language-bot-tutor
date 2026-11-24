"""Prompt assembly. Pure functions only.

Order (for prompt caching):
  1. system: tutor instructions + level policy + topic catalogue   (stable per lang/level -> cached)
  2. scenario
  3. learner summary
  4. recent turns
  5. the new message
Items 2-5 go in the single user message, after the cached system prompt.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from xml.sax.saxutils import escape

from tutor_api.curriculum.models import Curriculum, GrammarTopic, Scenario
from tutor_api.domain.policy import Policy

UNKNOWN_TAG = "unknown"

_EXPLANATION_RULES = {
    "native": "Write every `explanation` in the learner's native language "
    "(given in <learner>). Keep it to one short, plain sentence.",
    "mixed": "Write every `explanation` in simple {target} with a short gloss in the learner's "
    "native language (given in <learner>) in parentheses for the key term.",
    "target": "Write every `explanation` entirely in {target}, concisely, as a teacher would.",
}

_CORRECTION_SCOPE = {
    "at_or_below_level": "Only correct errors whose topic is in the catalogue below (topics at or "
    "below the learner's level). Ignore errors that belong to more advanced grammar; do not "
    "flag them at all.",
    "all": "Correct any grammatical, spelling or agreement error.",
    "all_plus_style": "Correct any grammatical error, and also flag unnatural phrasing, wrong "
    "register or weak collocations as `minor`.",
}


@dataclass(frozen=True)
class PriorTurn:
    role: str  # "learner" | "tutor"
    text: str


def catalogue_for(curriculum: Curriculum, policy: Policy) -> list[GrammarTopic]:
    if policy.correct_topics == "at_or_below_level":
        topics = curriculum.topics_up_to(policy.level)
    else:
        topics = curriculum.active_topics()
    return sorted(topics, key=lambda t: (curriculum.rank(t.level), t.id))


def build_system_prompt(curriculum: Curriculum, policy: Policy) -> str:
    """Stable, cacheable part. Must not contain per-learner or per-turn data."""
    target = policy.target_lang_name
    catalogue = "\n".join(
        f"- {t.id} [{t.level}] {t.title}" for t in catalogue_for(curriculum, policy)
    )
    language_notes = ""
    if curriculum.lang.prompt_notes:
        notes = "\n".join(f"- {n}" for n in curriculum.lang.prompt_notes)
        language_notes = f"## Notes for {target}\n{notes}\n\n"
    explanation_rule = _EXPLANATION_RULES[policy.explanation_language].format(target=target)
    return f"""You are a warm, encouraging {target} tutor having a conversation with a learner.
You do two jobs at once on every turn:
1. Stay in the conversation: reply naturally, in character when a scenario is given.
2. Silently review the learner's LATEST message and report corrections in structured form.

# Learner level: {policy.level}
## Your reply (`reply`)
- Write only in {target}. At most {policy.max_sentences} sentences.
- Vocabulary no harder than CEFR {policy.vocab_ceiling}. Style: {policy.speed_note or "natural"}.
- Keep the conversation going: end with a question or prompt the learner can answer.
- Never put corrections or grammar lessons inside `reply`; at most, naturally recast the
  corrected form in your answer.
- If the learner writes in another language, answer briefly in {target} and encourage them
  to try in {target}.

## Corrections (`corrections`)
- {_CORRECTION_SCOPE[policy.correct_topics]}
- Report at most {policy.max_corrections_per_turn} corrections, most important first.
  If there are no errors, return an empty list. Never invent errors.
- `wrong` is copied verbatim from the learner's latest message (the smallest span that shows
  the error). `right` is the corrected span.
- `rule_tag` is the id of the catalogue topic the error violates, or "{UNKNOWN_TAG}" if none fits.
  Use only ids that appear in the catalogue.
- `severity`: "major" if it obscures meaning or is a core rule at this level, otherwise "minor".
- {explanation_rule}
- Do not correct the learner's earlier messages or proper names.

## Grammar tags (`grammar_tags`)
- List catalogue ids for topics the learner's latest message exercised, whether used correctly
  or not. Include correct uses: they show progress. Use only catalogue ids.

## New vocabulary (`new_vocab`)
- 0 to 3 words or expressions from YOUR reply that a {policy.level} learner probably does not
  know yet. Translate them into the learner's native language.

{language_notes}# Topic catalogue ({target})
{catalogue}
"""


def build_learner_summary(
    weak_topics: Sequence[tuple[str, float]],
    recent_mistakes: Sequence[tuple[str, str, str]],
) -> str:
    """weak_topics: (topic_id, mastery). recent_mistakes: (wrong, right, rule_tag)."""
    lines: list[str] = []
    if weak_topics:
        lines.append(
            "Weak topics (mastery 0-1): " + ", ".join(f"{tid} ({m:.2f})" for tid, m in weak_topics)
        )
    if recent_mistakes:
        lines.append("Recent mistakes:")
        lines.extend(f"- {w} → {r} [{tag}]" for w, r, tag in recent_mistakes)
    return "\n".join(lines) if lines else "No history yet."


def build_user_content(
    policy: Policy,
    scenario: Scenario | None,
    learner_summary: str,
    recent_turns: Sequence[PriorTurn],
    new_message: str,
) -> str:
    """Per-learner and per-turn context, in cache-friendly order (after the system prompt)."""
    parts: list[str] = []
    if scenario is not None:
        goals = "; ".join(scenario.goals)
        vocab = ", ".join(scenario.key_vocab)
        focus = ", ".join(scenario.target_topics)
        parts.append(
            "<scenario>\n"
            f"Title: {escape(scenario.title)}\n"
            f"Setting: {escape(scenario.setting)}\n"
            f"Your role: {escape(scenario.bot_role)}\n"
            f"Learner goals: {escape(goals)}\n"
            f"Useful vocabulary: {escape(vocab)}\n"
            f"Focus topics: {focus}\n"
            "</scenario>"
        )
    else:
        parts.append(
            "<scenario>Free conversation. Be a friendly conversation partner and follow the "
            "learner's interests.</scenario>"
        )
    parts.append(
        "<learner>\n"
        f"Native language (ISO 639-1): {escape(policy.native_lang)}\n"
        f"Explanation mode: {policy.explanation_language}\n"
        f"{escape(learner_summary)}\n"
        "</learner>"
    )
    if recent_turns:
        convo = "\n".join(f"{t.role}: {escape(t.text)}" for t in recent_turns)
        parts.append(f"<conversation>\n{convo}\n</conversation>")
    parts.append(
        "<latest_learner_message>\n"
        f"{escape(new_message)}\n"
        "</latest_learner_message>\n"
        "Reply to the latest learner message and review it, following your instructions."
    )
    return "\n\n".join(parts)


# ----------------------------------------------------------------------------- learner help

HelpKind = str  # "hint" | "translate" | "suggest" | "explain" (validated by the contract)

_HELP_TASKS = {
    "hint": (
        "The learner is stuck and does not know how to answer the tutor's message. Give a short "
        "hint in {native}: what the tutor is asking, and 2-3 useful {target} words or a sentence "
        "starter. Do NOT write the full answer for them."
    ),
    "translate": (
        "Translate the tutor's message into {native}. Keep it natural. If one or two words are "
        "worth learning, add them after the translation as '{target} word = meaning'."
    ),
    "suggest": (
        "Write ONE example answer the learner could send, in simple {target} at level {level} "
        "(no harder vocabulary than {ceiling}). Put its {native} translation on the next line "
        "in parentheses. Keep it short and natural."
    ),
    "explain": (
        "Explain the corrections below in more depth for this learner: why each was wrong, the "
        "rule in plain words, and one extra correct example for each. Write the explanation in "
        "{explain_lang}. Be warm and brief: a few lines per correction."
    ),
}

_EXPLAIN_LANG = {
    "native": "{native}",
    "mixed": "simple {target}, with {native} glosses for key terms",
    "target": "{target}",
}


def build_help_prompt(
    policy: Policy,
    kind: HelpKind,
    scenario: Scenario | None,
    recent_turns: Sequence[PriorTurn],
    tutor_message: str,
    corrections: Sequence[tuple[str, str, str]] = (),
) -> tuple[str, str]:
    """(system, user) for a one-off help request about a tutor message.

    corrections: (wrong, right, short explanation) from the learner message the tutor answered.
    `native` is an ISO 639-1 code; the model resolves it to the language.
    """
    native = f"the learner's native language (ISO 639-1 code '{policy.native_lang}')"
    fmt = {
        "native": native,
        "target": policy.target_lang_name,
        "level": policy.level,
        "ceiling": policy.vocab_ceiling,
        "explain_lang": _EXPLAIN_LANG[policy.explanation_language].format(
            native=native, target=policy.target_lang_name
        ),
    }
    system = (
        f"You help a {policy.target_lang_name} learner (level {policy.level}) who is practising "
        "conversation with a tutor. Answer in plain text (no Markdown), in at most 5 short "
        "lines. Be encouraging.\n\nTask: " + _HELP_TASKS[kind].format(**fmt)
    )
    parts: list[str] = []
    if scenario is not None:
        parts.append(f"<scenario>{escape(scenario.title)}: {escape(scenario.setting)}</scenario>")
    if recent_turns:
        convo = "\n".join(f"{t.role}: {escape(t.text)}" for t in recent_turns)
        parts.append(f"<conversation>\n{convo}\n</conversation>")
    parts.append(f"<tutor_message>\n{escape(tutor_message)}\n</tutor_message>")
    if kind == "explain":
        if corrections:
            lines = "\n".join(
                f"- {escape(w)} → {escape(r)} ({escape(e)})" for w, r, e in corrections
            )
            parts.append(f"<corrections>\n{lines}\n</corrections>")
        else:
            parts.append(
                "<corrections>none: the learner's message had no corrections</corrections>"
            )
    return system, "\n\n".join(parts)
