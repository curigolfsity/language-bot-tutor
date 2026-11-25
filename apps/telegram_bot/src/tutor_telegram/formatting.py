"""Pure presentation helpers: contract DTOs -> Telegram HTML. No business logic."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html import escape

from tutor_contracts import (
    AskOut,
    DailyProgressOut,
    ExerciseOut,
    HelpOut,
    LearnerProfileOut,
    LessonAnswerOut,
    LessonOut,
    LessonSuggestionsOut,
    LessonTopicOut,
    LevelOut,
    MistakeOut,
    ReminderOut,
    ReviewAnswerOut,
    ReviewQueueOut,
    ScenarioOut,
    SessionOut,
    SessionSummary,
    TurnProgress,
    TurnResponse,
)

from tutor_telegram.keyboards import (
    ASK_PROMPT_HEADER,
    LESSON_HEADER,
    MENU_ASK,
    MENU_CHAT,
    MENU_FINISH,
    MENU_LESSONS,
    MENU_PROGRESS,
    MENU_REVIEW,
    MENU_ROLEPLAY,
    MENU_SETTINGS,
    REVIEW_HEADER,
    TOPIC_ICONS,
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
    f"{MENU_LESSONS}: short grammar lessons with practice, picked from your weak spots\n"
    f"{MENU_REVIEW}: fix your own past mistakes again until they stick\n"
    f"{MENU_ASK}: ask about grammar or a word without interrupting the conversation. "
    "Or just start any message with <b>?</b>\n"
    "🎤 You can also send <b>voice messages</b>: I'll show what I heard and reply as usual.\n"
    f"{MENU_PROGRESS}: your scores and recent mistakes\n"
    f"{MENU_FINISH}: wrap up and see what you learned\n"
    f"{MENU_SETTINGS}: level, explanation language, daily goal, reminders\n\n"
    "🔥 Practise a little every day to build a streak. Each message counts toward your daily goal."
)

HELP_TITLES = {
    "hint": "💡 <b>Hint</b>",
    "translate": "🌐 <b>Translation</b>",
    "suggest": "✍️ <b>You could say</b>",
    "explain": "❓ <b>About your mistakes</b>",
}


def _topic(title: str | None, fallback: str) -> str:
    return escape(title or fallback)


def turn_body(result: TurnResponse) -> str:
    """What is always visible: (what was heard,) the reply, and a rare streak line."""
    parts = []
    if result.transcript:
        parts.append(f"🎤 <i>I heard: “{escape(result.transcript)}”</i>\n")
    parts.append(escape(result.reply))
    if milestone := format_milestone(result.progress):
        parts.append(f"\n{milestone}")
    return "\n".join(parts)


def turn_feedback(result: TurnResponse) -> str:
    """The foldable part: praise, fixes (with reasons) and new words. Empty if none."""
    parts = []
    if result.well_done:
        parts.append("✅ Nice use of: " + ", ".join(escape(t.title) for t in result.well_done))
    if result.corrections:
        n = len(result.corrections)
        lines = [f"✏️ <b>{n} quick fix{'es' if n > 1 else ''}</b>"]
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
        parts.append(f"📚 {vocab}")
    return "\n\n".join(parts)


def feedback_label(result: TurnResponse) -> str | None:
    """Short summary for the fold button, e.g. "✏️ 2 fixes · 📚 1 word". None if no feedback."""
    bits = []
    if n := len(result.corrections):
        bits.append(f"✏️ {n} fix{'es' if n > 1 else ''}")
    elif result.well_done:
        bits.append("✅ Well done")
    if n := len(result.new_vocab):
        bits.append(f"📚 {n} word{'s' if n > 1 else ''}")
    return " · ".join(bits) or None


def help_block(kind: str, text: str) -> str:
    """A help answer folded inside the tutor message."""
    title = HELP_TITLES.get(kind, "💡")
    return f"\n\n<blockquote expandable>{title}\n{escape(text)}</blockquote>"


def format_turn(result: TurnResponse) -> str:
    """Everything unfolded (used when a message can't be folded, and in tests)."""
    feedback = turn_feedback(result)
    return turn_body(result) + (f"\n\n{feedback}" if feedback else "")


def _days(n: int) -> str:
    return f"{n} day{'s' if n != 1 else ''}"


def format_milestone(p: TurnProgress | None) -> str:
    """One celebratory line on the first message of the day or when the goal is reached;
    empty otherwise, so ordinary turns stay uncluttered."""
    if p is None:
        return ""
    if p.goal_just_met:
        return f"🎯 <b>Daily goal reached!</b> {p.today}/{p.goal} · 🔥 {_days(p.streak)}"
    if p.first_today:
        if p.streak <= 1:
            return (
                f"🔥 <b>Day 1!</b> Come back tomorrow to build a streak. Today: {p.today}/{p.goal}"
            )
        return f"🔥 <b>{p.streak}-day streak!</b> Today: {p.today}/{p.goal}"
    return ""


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


def format_streak(d: DailyProgressOut) -> list[str]:
    done = " ✅" if d.goal_met else ""
    return [
        f"🔥 Streak: <b>{_days(d.streak)}</b> (best {_days(d.best_streak)})",
        f"🎯 Today {_bar(min(1.0, d.today / d.goal))} {d.today}/{d.goal}{done}",
    ]


def format_progress(
    profile: LearnerProfileOut,
    levels: list[LevelOut],
    word_count: int,
    mistakes: list[MistakeOut],
    daily: DailyProgressOut | None = None,
) -> str:
    skills = {s.skill: s.score for s in profile.skills}
    grammar, vocab = skills.get("grammar", 0.0), skills.get("vocab", 0.0)
    lines = [
        "📊 <b>Your progress</b>",
        *(format_streak(daily) if daily else []),
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


def format_settings(p: LearnerProfileOut, levels: list[LevelOut] | None = None) -> str:
    return (
        f"⚙️ {format_profile(p, levels)}\n"
        f"🎯 Daily goal: <b>{p.daily_goal} messages</b> · "
        f"🔔 Reminders: <b>{'on' if p.reminders_enabled else 'off'}</b>"
    )


def format_reminder(r: ReminderOut) -> str:
    if r.streak > 0:
        return (
            f"🔥 Your <b>{_days(r.streak)}</b> streak ends at midnight! "
            "Send me one message to keep it going."
        )
    return "👋 Time to practise? A few messages a day is all it takes."


def format_reminder_with_reviews(r: ReminderOut) -> str:
    text = format_reminder(r)
    if r.reviews_due:
        n = r.reviews_due
        text += f"\n🧠 You also have {n} mistake{'s' if n != 1 else ''} to practise."
    return text


# ----------------------------------------------------------------------------- side questions

ASK_PROMPT = (
    f"<b>{ASK_PROMPT_HEADER}</b> about the language: grammar, a word, how to say something…\n"
    "<i>Reply to this message. Our conversation stays where it is.</i>"
)


def format_answer(a: AskOut) -> str:
    return f"🙋 <i>{escape(a.question)}</i>\n\n{escape(a.answer)}"


# Asking about one tutor message. The prompt carries the tutor turn id and Telegram message id
# in an invisible link, so the learner's reply can be routed without the bot remembering
# anything; Telegram includes the replied-to message's entities (with the link) in the update.
_ASK_LINK = re.compile(r"[?&]start=ask_(\d+)_(\d+)$")
TELEGRAM_TEXT_LIMIT = 4096


def ask_about_prompt(turn_id: int, message_id: int, bot_username: str) -> str:
    link = f"https://t.me/{bot_username}?start=ask_{turn_id}_{message_id}"
    return (
        f'<a href="{link}">​</a>🙋 <b>Ask about this message</b>\n'
        "<i>Type your question. The answer will appear inside the message above.</i>"
    )


def parse_ask_link(urls: list[str]) -> tuple[int, int] | None:
    """(turn_id, message_id) from the URLs of a replied-to ask prompt's text links."""
    for url in urls:
        if m := _ASK_LINK.search(url):
            return int(m.group(1)), int(m.group(2))
    return None


def inline_answer_block(question: str, answer: str) -> str:
    """Question + answer appended inside the tutor message, collapsed if long."""
    return f"\n\n<blockquote expandable>🙋 <b>{escape(question)}</b>\n{escape(answer)}</blockquote>"


def visible_length(html: str) -> int:
    """Characters Telegram counts toward its 4096 limit (tags removed, entities decoded)."""
    from html import unescape

    return len(unescape(re.sub(r"<[^>]+>", "", html)))


# ----------------------------------------------------------------------------- practise mistakes

SNIPPET_CONTEXT = 70  # characters of the original message shown on each side of the error


def card_snippet(source: str, wrong: str) -> str:
    """The learner's sentence with the error bold and underlined, trimmed around it. Escaped."""
    i = source.casefold().find(wrong.casefold()) if wrong else -1
    if i < 0:
        limit = 2 * SNIPPET_CONTEXT
        return escape(source if len(source) <= limit else source[:limit] + "…")
    start, end = max(0, i - SNIPPET_CONTEXT), min(len(source), i + len(wrong) + SNIPPET_CONTEXT)
    before = ("…" if start > 0 else "") + source[start:i]
    after = source[i + len(wrong) : end] + ("…" if end < len(source) else "")
    return f"{escape(before)}<b><u>{escape(source[i : i + len(wrong)])}</u></b>{escape(after)}"


def format_card(q: ReviewQueueOut) -> str:
    assert q.card is not None
    c = q.card
    topic = f"\n<i>{escape(c.rule_title)}</i>" if c.rule_title else ""
    return (
        f"<b>{REVIEW_HEADER}{c.id}</b> · {q.due} to go{topic}\n\n"
        f"Fix the underlined part:\n{card_snippet(c.source_text, c.wrong)}\n\n"
        "<i>Reply with the corrected words or the whole sentence.</i>"
    )


def parse_card_id(prompt_text: str | None) -> int | None:
    """Card id from a practice prompt the learner replied to."""
    m = re.match(re.escape(REVIEW_HEADER) + r"(\d+)", prompt_text or "")
    return int(m.group(1)) if m else None


def _when(due: datetime | None, now: datetime | None = None) -> str:
    if due is None:
        return "later"
    hours = (due - (now or datetime.now(UTC))).total_seconds() / 3600
    if hours < 1:
        return "in a few minutes"
    if hours < 24:
        h = round(hours)
        return f"in {h} hour{'s' if h != 1 else ''}"
    d = round(hours / 24)
    return f"in {d} day{'s' if d != 1 else ''}"


def format_queue_empty(q: ReviewQueueOut, now: datetime | None = None) -> str:
    if q.total == 0:
        return (
            "🧠 No mistakes to practise yet. Chat with me and I'll save your mistakes here, "
            "so you can fix them again later."
        )
    return f"🎉 <b>All caught up!</b> Your next card is due {_when(q.next_due_at, now)}."


def format_review_result(r: ReviewAnswerOut) -> str:
    right = f"<b>{escape(r.right)}</b>"
    fix = f"<s>{escape(r.wrong)}</s> → {right}"
    if r.correct:
        d = round(r.next_review_in_days)
        when = f"in {d} day{'s' if d != 1 else ''}" if r.next_review_in_days >= 1 else "soon"
        lines = ["✅ <b>Correct!</b>"]
        if r.feedback:
            lines.append(escape(r.feedback))
        lines += [fix, f"<i>I'll check it again {when}.</i>"]
    else:
        lines = ["❌ <b>Not quite.</b>"]
        if r.feedback:
            lines.append(escape(r.feedback))
        lines += [
            fix,
            f"<i>{escape(r.explanation)}</i>",
            "<i>It'll come back in a few minutes.</i>",
        ]
    if milestone := format_milestone(r.progress):
        lines.append(f"\n{milestone}")
    if r.due == 0:
        lines.append("\n🎉 That's all for now!")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- grammar lessons

_LESSON_RE = re.compile(re.escape(LESSON_HEADER) + r"(\d+) · (\d+)/(\d+)")


def _mastery_text(t: LessonTopicOut) -> str:
    if t.mastery is None:
        return "new"
    return f"{_bar(t.mastery, 5)} {round(t.mastery * 100)}%"


def format_lesson_menu(s: LessonSuggestionsOut) -> str:
    lines = [
        "📖 <b>Grammar lessons</b>",
        "A short explanation, then a few practice questions.",
        "",
        "<b>Suggested for you</b>",
    ]
    for t in s.suggested:
        lines.append(
            f"{TOPIC_ICONS.get(t.reason or '', '📖')} {escape(t.title)} · {_mastery_text(t)}"
        )
    lines += ["", "<i>🎯 you often get this wrong · 🆕 next new topic · 🔁 refresh</i>"]
    return "\n".join(lines)


def format_level_topics(topics: list[LessonTopicOut]) -> str:
    if not topics:
        return "No grammar topics for your level yet."
    lines = [f"📚 <b>All {escape(topics[0].level)} topics</b>"]
    lines += [f"• {escape(t.title)} · {_mastery_text(t)}" for t in topics]
    return "\n".join(lines)


def format_lesson(lesson: LessonOut) -> str:
    """Sections with headings and spacing; forms in monospace so they line up and copy."""
    title = f"📖 <b>{escape(lesson.topic.title)}</b>"
    p = lesson.parts
    if p is None:  # lessons stored before parts existed
        return f"{title}\n\n{escape(lesson.explanation)}"
    out = [title, f"<i>{escape(p.summary)}</i>"]
    if p.forms:
        forms = ["<b>📐 Forms</b>"]
        for f in p.forms:
            forms.append(f"<b>{escape(f.label)}</b>\n<code>{escape(f.forms)}</code>")
        out.append("\n".join(forms))
    if p.usage:
        out.append("<b>🕐 When to use it</b>\n" + "\n".join(f"• {escape(u)}" for u in p.usage))
    if p.examples:
        examples = [
            f"▸ <b>{escape(e.sentence)}</b>\n   <i>{escape(e.translation)}</i>" for e in p.examples
        ]
        out.append("<b>💬 Examples</b>\n" + "\n".join(examples))
    w = p.watch_out
    out.append(
        "<b>⚠️ Watch out</b>\n"
        f"❌ <s>{escape(w.wrong)}</s>\n"
        f"✅ <b>{escape(w.right)}</b>\n"
        f"<i>{escape(w.note)}</i>"
    )
    return "\n\n".join(out)


def format_exercise(lesson_id: int, ex: ExerciseOut) -> str:
    return (
        f"<b>{LESSON_HEADER}{lesson_id} · {ex.index + 1}/{ex.total}</b>\n"
        f"<i>{escape(ex.instruction)}</i>\n\n"
        f"<b>{escape(ex.prompt)}</b>\n\n"
        "<i>Reply to this message with your answer.</i>"
    )


def parse_exercise(prompt_text: str | None) -> tuple[int, int] | None:
    """(lesson id, 0-based exercise index) from an exercise message the learner replied to."""
    m = _LESSON_RE.search(prompt_text or "")
    return (int(m.group(1)), int(m.group(2)) - 1) if m else None


def format_lesson_answer(lesson_id: int, r: LessonAnswerOut) -> str:
    if r.correct:
        lines = ["✅ <b>Correct!</b>"]
        if r.feedback:
            lines.append(escape(r.feedback))
    else:
        lines = ["❌ <b>Not quite.</b>"]
        if r.feedback:
            lines.append(escape(r.feedback))
        lines.append(f"Answer: <b>{escape(r.expected)}</b>")
    if r.why:
        lines.append(f"<i>{escape(r.why)}</i>")
    if milestone := format_milestone(r.progress):
        lines.append(f"\n{milestone}")
    if r.next is not None:
        lines.append("\n" + format_exercise(lesson_id, r.next))
    else:
        stars = "🌟" if r.score == r.total else "👏" if r.score * 2 >= r.total else "💪"
        lines += [
            f"\n🏁 <b>Lesson done: {r.score}/{r.total}</b> {stars}",
            f"Topic mastery: {_bar(r.mastery, 5)} {round(r.mastery * 100)}%",
            "Now try it for real in a conversation, or take another lesson.",
        ]
    return "\n".join(lines)
