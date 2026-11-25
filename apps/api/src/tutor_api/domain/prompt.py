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
- Report EVERY error in scope, most important first (major before minor). The app shows the
  learner only the first {policy.max_corrections_per_turn}; the rest are kept silently to track
  progress, so do not skip any. If there are no errors, return an empty list. Never invent errors.
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


# ----------------------------------------------------------------------------- side questions


# Which language a side answer is written in, by the level's explanation style. Quoting a few
# target-language words in a question doesn't make it a target-language question.
_ASK_LANGUAGE = {
    "native": "Answer in {native}, unless the whole question is written in {target}; "
    "then answer in very simple {target}.",
    "mixed": "Answer in {native} if the question is in {native}; if the whole question is in "
    "{target}, answer in simple {target} with {native} glosses for key terms.",
    "target": "Answer in {target}.",
}


def build_ask_prompt(
    policy: Policy,
    scenario: Scenario | None,
    recent_turns: Sequence[PriorTurn],
    question: str,
    about_message: str | None = None,
) -> tuple[str, str]:
    """(system, user) for a question the learner asks outside the conversation ("aside").

    The answer is not part of the conversation: it is not stored as a turn and not corrected.
    `about_message`: the tutor message the question is attached to, if any.
    """
    target = policy.target_lang_name
    native = f"the learner's native language (ISO 639-1 code '{policy.native_lang}')"
    system = (
        f"You are a friendly {target} teacher. A learner at level {policy.level} is in the "
        "middle of a practice conversation and steps aside to ask you a question (grammar, "
        "vocabulary, usage, pronunciation, culture, or something in the conversation).\n"
        "- Answer the question directly and correctly. Use the conversation only as context. "
        "If a <message_in_question> is given, the question is about that tutor message.\n"
        f"- {_ASK_LANGUAGE[policy.explanation_language].format(target=target, native=native)} "
        f"Keep {target} examples simple, suited to level {policy.level}.\n"
        f"- Give 1-2 short {target} example sentences when they help.\n"
        "- Plain text, no Markdown, at most 8 short lines. Be warm and encouraging.\n"
        "- If the question has nothing to do with learning the language, answer briefly and "
        "kindly invite them back to the conversation."
    )
    parts: list[str] = []
    if scenario is not None:
        parts.append(f"<scenario>{escape(scenario.title)}: {escape(scenario.setting)}</scenario>")
    if recent_turns:
        convo = "\n".join(f"{t.role}: {escape(t.text)}" for t in recent_turns)
        parts.append(f"<conversation>\n{convo}\n</conversation>")
    if about_message is not None:
        parts.append(f"<message_in_question>\n{escape(about_message)}\n</message_in_question>")
    parts.append(f"<question>\n{escape(question)}\n</question>")
    return system, "\n\n".join(parts)


# ----------------------------------------------------------------------------- review grading


def build_grade_prompt(
    policy: Policy,
    source_text: str,
    wrong: str,
    right: str,
    explanation: str,
    answer: str,
) -> tuple[str, str]:
    """(system, user) to grade the learner's fix of one of their past mistakes."""
    target = policy.target_lang_name
    native = f"the learner's native language (ISO 639-1 code '{policy.native_lang}')"
    feedback_lang = _EXPLAIN_LANG[policy.explanation_language].format(native=native, target=target)
    system = (
        f"You grade a {target} learner (level {policy.level}) who is practising one of their own "
        "past mistakes. They see the sentence they once wrote and must fix the error in it.\n"
        "- `correct` is true if their answer fixes that error correctly. Accept any correct, "
        "natural alternative, a full rewritten sentence, or just the fixed words. Ignore "
        "capitalisation and punctuation.\n"
        "- Missing or wrong accents, or a new error in the fixed part, make it incorrect.\n"
        f"- `feedback` in {feedback_lang}, at most 2 short sentences, warm. If correct with a "
        "different wording, say it also works. If incorrect, say what is still wrong and give "
        "the correct form."
    )
    user = (
        f"<original_sentence>{escape(source_text)}</original_sentence>\n"
        f"<error>{escape(wrong)}</error>\n"
        f"<a_correct_fix>{escape(right)}</a_correct_fix>\n"
        f"<rule>{escape(explanation)}</rule>\n"
        f"<learner_answer>{escape(answer)}</learner_answer>"
    )
    return system, user


# ----------------------------------------------------------------------------- grammar lessons

LESSON_NATIVE = "the learner's native language (given in <learner>)"


def build_lesson_prompt(
    curriculum: Curriculum,
    policy: Policy,
    topic: GrammarTopic,
    learner_mistakes: Sequence[tuple[str, str]],
    n_exercises: int,
) -> tuple[str, str]:
    """(system, user) to write a short lesson plus exercises on one grammar topic.

    The system part depends only on language, level and explanation style (cacheable); the
    learner's native language, the topic and their own mistakes go in the user part.
    learner_mistakes: (wrong, right) pairs the learner made on this topic.
    """
    target = policy.target_lang_name
    explain_in = _EXPLAIN_LANG[policy.explanation_language].format(
        native=LESSON_NATIVE, target=target
    )
    system = f"""You are an expert {target} teacher. Write a short grammar lesson with practice \
exercises for a learner at CEFR level {policy.level}.

# lesson parts (each is laid out separately, so keep every part short and plain text: no \
Markdown symbols such as *, # or backticks)
- `summary`: one or two short sentences in {explain_in}: what this grammar point is for.
- `forms`: the forms to learn, 0-4 lines. Each has a short `label` and the `forms` separated \
by " · " (for example one line per verb group). For forms that change by person, write every \
item as "person: form" with the {target} pronoun, in the usual order (for example \
"yo: hablé · tú: hablaste · él/ella/usted: habló"). Leave it empty if there is nothing to memorise.
- `usage`: 2-4 short points in {explain_in}: when to use it, typical signal words.
- `examples`: exactly 3 example sentences in {target}, each with its translation in \
{LESSON_NATIVE}.
- `watch_out`: the most common mistake as a wrong sentence, the corrected sentence, and a \
one-sentence `note` in {explain_in}. If <learner_mistakes> are given, use one of the learner's \
own mistakes.
- Vocabulary no harder than CEFR {policy.vocab_ceiling}.

{_exercise_rules(policy, n_exercises, explain_in)}{_lang_notes(curriculum, target)}
"""
    parts = _lesson_context(policy, topic, learner_mistakes)
    parts.append("Write the lesson and the exercises.")
    return system, "\n\n".join(parts)


def _lang_notes(curriculum: Curriculum, target: str) -> str:
    if not curriculum.lang.prompt_notes:
        return ""
    return f"\n# Notes for {target}\n" + "\n".join(f"- {n}" for n in curriculum.lang.prompt_notes)


def _exercise_rules(policy: Policy, n_exercises: int, explain_in: str) -> str:
    target = policy.target_lang_name
    return f"""# exercises
- Exactly {n_exercises} exercises on THIS topic only, easiest first. Mix the kinds: at least one \
fill_blank, one fix and one translate.
- `instruction` and `why` in {explain_in}. `prompt` in {target}, except for translate, whose \
prompt is a short sentence in {LESSON_NATIVE}.
- fill_blank: exactly one gap written ___ ; `answer` is only the missing word(s).
- fix: a sentence with exactly one error on this topic; `answer` is the full corrected sentence.
- translate: `answer` is a natural {target} sentence.
- Each exercise needs one clearly correct answer. Put genuinely acceptable alternatives in \
`also_accept` (for example with or without the subject pronoun).
- Vocabulary no harder than CEFR {policy.vocab_ceiling}. Check that every answer is correct \
{target}."""


def _lesson_context(
    policy: Policy, topic: GrammarTopic, learner_mistakes: Sequence[tuple[str, str]]
) -> list[str]:
    examples = "\n".join(f"- {escape(e.wrong)} → {escape(e.right)}" for e in topic.examples)
    parts = [
        f"<learner>native language: ISO 639-1 code '{policy.native_lang}'</learner>",
        "<topic>\n"
        f"id: {topic.id}\nlevel: {topic.level}\ntitle: {escape(topic.title)}\n"
        f"description: {escape(topic.description)}\n"
        + (f"examples (wrong → right):\n{examples}\n" if examples else "")
        + "</topic>",
    ]
    if learner_mistakes:
        lines = "\n".join(f"- {escape(w)} → {escape(r)}" for w, r in learner_mistakes)
        parts.append(f"<learner_mistakes>\n{lines}\n</learner_mistakes>")
    return parts


def build_exercises_prompt(
    curriculum: Curriculum,
    policy: Policy,
    topic: GrammarTopic,
    learner_mistakes: Sequence[tuple[str, str]],
    n_exercises: int,
    lesson_text: str,
) -> tuple[str, str]:
    """(system, user) to write fresh exercises for a lesson whose explanation is reused.

    lesson_text: the explanation the learner sees, so the exercises match it. The learner's
    own mistakes steer the exercises towards what they get wrong."""
    target = policy.target_lang_name
    explain_in = _EXPLAIN_LANG[policy.explanation_language].format(
        native=LESSON_NATIVE, target=target
    )
    system = f"""You are an expert {target} teacher. Write practice exercises for a learner at \
CEFR level {policy.level}, on the grammar lesson they have just read. Plain text only: no \
Markdown symbols such as *, # or backticks.

{_exercise_rules(policy, n_exercises, explain_in)}
- Use new sentences, not the lesson's examples. If <learner_mistakes> are given, base at least \
one exercise on them.{_lang_notes(curriculum, target)}
"""
    parts = _lesson_context(policy, topic, learner_mistakes)
    parts.append(f"<lesson>\n{escape(lesson_text)}\n</lesson>")
    parts.append("Write the exercises.")
    return system, "\n\n".join(parts)


def build_exercise_grade_prompt(
    policy: Policy,
    kind: str,
    instruction: str,
    prompt_text: str,
    expected: Sequence[str],
    answer: str,
) -> tuple[str, str]:
    """(system, user) to check an exercise answer that did not match the expected ones."""
    target = policy.target_lang_name
    native = f"the learner's native language (ISO 639-1 code '{policy.native_lang}')"
    feedback_lang = _EXPLAIN_LANG[policy.explanation_language].format(native=native, target=target)
    system = (
        f"You check a {target} learner's (level {policy.level}) answer to a grammar exercise.\n"
        "- `correct` is true if the answer is fully correct for the exercise. Any correct "
        "alternative counts. Ignore capitalisation and final punctuation. Accents matter.\n"
        "- For fill_blank, the answer may be just the missing words or the whole sentence.\n"
        f"- `feedback` in {feedback_lang}, at most 2 short sentences, warm. If incorrect, say "
        "what is wrong and give the correct answer."
    )
    user = (
        f"<exercise kind='{escape(kind)}'>\n"
        f"instruction: {escape(instruction)}\n"
        f"prompt: {escape(prompt_text)}\n"
        f"expected: {' | '.join(escape(x) for x in expected)}\n"
        "</exercise>\n"
        f"<learner_answer>{escape(answer)}</learner_answer>"
    )
    return system, user


def build_save_words_prompt(
    curriculum: Curriculum, policy: Policy, words: str, context: str | None
) -> tuple[str, str]:
    """(system, user) to turn words the learner typed into dictionary entries."""
    target = policy.target_lang_name
    system = f"""You write flashcard entries for a learner of {target} whose native language is \
ISO 639-1 '{policy.native_lang}'. For each word or expression in <words> (one entry each, in \
order): `lemma` is its dictionary form in {target} (fix obvious typos), `translation` is a short \
meaning in the learner's native language, as used in <context> if given, and `pos` its part of \
speech. Skip anything that is not {target}.{_lang_notes(curriculum, target)}
"""
    parts = [f"<words>{escape(words)}</words>"]
    if context:
        parts.append(f"<context>{escape(context)}</context>")
    return system, "\n\n".join(parts)
