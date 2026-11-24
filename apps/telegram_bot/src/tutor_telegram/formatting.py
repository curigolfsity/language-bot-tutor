"""Pure presentation helpers: contract DTOs -> Telegram HTML. No business logic."""

from __future__ import annotations

from html import escape

from tutor_contracts import (
    HelpOut,
    LearnerProfileOut,
    LevelOut,
    MistakeOut,
    ScenarioOut,
    SessionOut,
    SessionSummary,
    TurnResponse,
)

from tutor_telegram.keyboards import (
    MENU_CHAT,
    MENU_FINISH,
    MENU_PROGRESS,
    MENU_ROLEPLAY,
    MENU_SETTINGS,
    level_icon,
)

HOW_IT_WORKS = (
    "<b>How it works</b>\n"
    "Just write to me in the language you're learning, even if it's imperfect. "
    "I'll reply like a real person and point out a few mistakes along the way.\n\n"
    "Under each of my messages:\n"
    "💡 <b>Hint</b>: get unstuck without seeing the answer\n"
    "🌐 <b>Translate</b>: see what I said in your language\n"
    "✍️ <b>Suggest</b>: an example answer you could send\n"
    "❓ <b>Explain</b>: more detail about your mistakes\n\n"
    f"{MENU_CHAT}: talk about anything\n"
    f"{MENU_ROLEPLAY}: practise a real situation (café, doctor, job interview…)\n"
    f"{MENU_PROGRESS}: your scores and recent mistakes\n"
    f"{MENU_FINISH}: wrap up and see what you learned\n"
    f"{MENU_SETTINGS}: change your level or explanation language"
)

HELP_TITLES = {
    "hint": "💡 <b>Hint</b>",
    "translate": "🌐 <b>Translation</b>",
    "suggest": "✍️ <b>You could say</b>",
    "explain": "❓ <b>About your mistakes</b>",
}


def _topic(title: str | None, fallback: str) -> str:
    return escape(title or fallback)


def format_turn(result: TurnResponse) -> str:
    parts = [escape(result.reply)]
    if result.well_done:
        parts.append("\n✅ Nice use of: " + ", ".join(escape(t.title) for t in result.well_done))
    if result.corrections:
        n = len(result.corrections)
        lines = [f"\n✏️ <b>{n} quick fix{'es' if n > 1 else ''}</b>"]
        lines.extend(
            f"• <s>{escape(c.wrong)}</s> → <b>{escape(c.right)}</b>" for c in result.corrections
        )
        why = "\n".join(f"• {escape(c.explanation)}" for c in result.corrections)
        lines.append(f"<blockquote expandable>Why:\n{why}</blockquote>")
        parts.append("\n".join(lines))
    if result.new_vocab:
        vocab = ", ".join(
            f"<b>{escape(v.lemma)}</b> = {escape(v.translation)}" for v in result.new_vocab
        )
        parts.append(f"\n📚 {vocab}")
    return "\n".join(parts)


def format_help(help_: HelpOut) -> str:
    return f"{HELP_TITLES.get(help_.kind, '💡')}\n{escape(help_.text)}"


def format_session_start(session: SessionOut, first_time: bool = False) -> str:
    if session.scenario_title:
        header = f"🎭 <b>{escape(session.scenario_title)}</b>"
    else:
        header = "💬 <b>Free conversation</b>"
    tip = (
        "\n\n<i>Reply in the language you're learning. Stuck? Tap 💡 Hint or ✍️ Suggest.</i>"
        if first_time
        else ""
    )
    return f"{header}\n\n{escape(session.opening_line)}{tip}"


def format_summary(summary: SessionSummary) -> str:
    if summary.turn_count == 0:
        return "🏁 Session closed. Come back any time!"
    lines = [f"🏁 <b>Great work!</b> You sent {summary.turn_count} message(s)."]
    if summary.new_vocab:
        lines.append("\n📚 <b>New words</b>")
        lines.extend(f"• {escape(v.lemma)} = {escape(v.translation)}" for v in summary.new_vocab)
    if summary.top_mistakes:
        lines.append("\n🎯 <b>To practise next</b>")
        lines.extend(f"• {_topic(m.title, m.rule_tag)} (×{m.count})" for m in summary.top_mistakes)
    lines.append("\nWhat next?")
    return "\n".join(lines)


def format_mistakes(mistakes: list[MistakeOut]) -> str:
    if not mistakes:
        return "No mistakes recorded yet. 🎉"
    lines = ["<b>Recent mistakes</b>"]
    lines.extend(
        f"• <s>{escape(m.wrong)}</s> → <b>{escape(m.right)}</b>\n"
        f"  <i>{_topic(m.rule_title, m.rule_tag)}</i>"
        for m in mistakes
    )
    return "\n".join(lines)


def _bar(score: float, width: int = 10) -> str:
    filled = max(0, min(width, round(score * width)))
    return "▰" * filled + "▱" * (width - filled)


def _level_text(cefr_level: str, levels: list[LevelOut] | None) -> str:
    level = next((lv for lv in levels or [] if lv.code == cefr_level), None)
    if level is None:
        return escape(cefr_level)
    return f"{level_icon(level.rank)} {escape(level.label)} ({escape(level.code)})"


def format_progress(
    profile: LearnerProfileOut,
    levels: list[LevelOut],
    word_count: int,
    mistakes: list[MistakeOut],
) -> str:
    skills = {s.skill: s.score for s in profile.skills}
    grammar, vocab = skills.get("grammar", 0.0), skills.get("vocab", 0.0)
    lines = [
        "📊 <b>Your progress</b>",
        f"Level: {_level_text(profile.cefr_level, levels)}",
        f"Words met: <b>{word_count}</b>",
        "",
        f"Grammar {_bar(grammar)} {round(grammar * 100)}%",
        f"Vocab   {_bar(vocab)} {round(vocab * 100)}%",
        "<i>Scores update when you finish a session.</i>",
    ]
    if mistakes:
        lines += ["", format_mistakes(mistakes)]
    return "\n".join(lines)


def format_scenarios(scenarios: list[ScenarioOut]) -> str:
    if not scenarios:
        return "No role-plays for your level yet. Try 💬 Free chat!"
    return "🎭 <b>Pick a situation to practise</b>"


def format_profile(p: LearnerProfileOut, levels: list[LevelOut] | None = None) -> str:
    return (
        f"Level: <b>{_level_text(p.cefr_level, levels)}</b> · "
        f"explanations in: <b>{escape(p.native_lang)}</b>"
    )
