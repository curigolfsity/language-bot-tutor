from datetime import UTC, datetime
from uuid import uuid4

from tutor_contracts import (
    AskOut,
    Correction,
    DailyProgressOut,
    HelpOut,
    LearnerProfileOut,
    LevelOut,
    MistakeCount,
    MistakeOut,
    NewVocab,
    ReminderOut,
    ReviewAnswerOut,
    ReviewCardOut,
    ReviewQueueOut,
    SessionOut,
    SessionSummary,
    SkillLevelOut,
    TopicRef,
    TurnProgress,
    TurnResponse,
)
from tutor_telegram import formatting
from tutor_telegram import keyboards as kb

LEVELS = [
    LevelOut(code="A1", rank=1, label="Total beginner", can_do="few words", starter_scenario="x"),
    LevelOut(code="A2", rank=2, label="Beginner", can_do="", starter_scenario=None),
]


def turn(**kw) -> TurnResponse:
    base = dict(reply="Bien", corrections=[], new_vocab=[], grammar_tags=[], turn_id=7)
    return TurnResponse(**{**base, **kw})


def test_format_turn_escapes_and_lists_corrections():
    r = turn(
        reply="¡Hola <amigo>!",
        corrections=[
            Correction(
                wrong="soy en",
                right="estoy en",
                rule_tag="t",
                explanation="loc <x>",
                severity="major",
            )
        ],
        new_vocab=[NewVocab(lemma="la playa", translation="beach", pos="noun")],
    )
    out = formatting.format_turn(r)
    assert "&lt;amigo&gt;" in out
    assert "1 quick fix</b>" in out
    assert "<s>soy en</s> → <b>estoy en</b>" in out
    assert "<blockquote expandable>" in out and "loc &lt;x&gt;" in out
    assert "<b>la playa</b> = beach" in out


def test_format_turn_praise():
    out = formatting.format_turn(turn(well_done=[TopicRef(id="t", title="Ser & estar")]))
    assert "✅ Nice use of: Ser &amp; estar" in out


def test_format_turn_plain():
    assert formatting.format_turn(turn()) == "Bien"


def test_session_start_and_summary():
    s = SessionOut(
        id=uuid4(),
        profile_id=uuid4(),
        mode="roleplay",
        scenario_id="x",
        scenario_title="Café",
        level_at_start="A1",
        started_at=datetime.now(UTC),
        ended_at=None,
        opening_line="¡Hola!",
        opening_turn_id=3,
    )
    assert "Café" in formatting.format_session_start(s)
    assert "💡 Hint" in formatting.format_session_start(s, first_time=True)
    summ = SessionSummary(
        session_id=uuid4(),
        turn_count=3,
        top_mistakes=[MistakeCount(rule_tag="es.a1.x", title="Ser vs estar", count=2)],
        new_vocab=[],
    )
    out = formatting.format_summary(summ)
    assert "3 message(s)" in out and "Ser vs estar (×2)" in out and "es.a1.x" not in out
    empty = SessionSummary(session_id=uuid4(), turn_count=0, top_mistakes=[], new_vocab=[])
    assert "closed" in formatting.format_summary(empty)


def test_progress_and_mistakes():
    profile = LearnerProfileOut(
        id=uuid4(),
        user_id=uuid4(),
        target_lang="es",
        native_lang="en",
        cefr_level="A1",
        explanation_lang_override=None,
        created_at=datetime.now(UTC),
        skills=[SkillLevelOut(skill="grammar", cefr_level="A1", score=0.42)],
        timezone="UTC",
        daily_goal=10,
    )
    m = MistakeOut(
        id=1,
        wrong="a",
        right="b",
        rule_tag="es.a1.x",
        rule_title="Title",
        explanation="e",
        severity="minor",
        created_at=datetime.now(UTC),
    )
    out = formatting.format_progress(profile, LEVELS, 12, [m])
    assert "Total beginner (A1)" in out and "Words met: <b>12</b>" in out
    assert "42%" in out and "▰▰▰▰▱" in out and "Title" in out
    assert "No mistakes" in formatting.format_mistakes([])


def test_help_formatting():
    assert formatting.format_help(HelpOut(kind="hint", text="a <b>")).startswith("💡 <b>Hint</b>")
    assert "a &lt;b&gt;" in formatting.format_help(HelpOut(kind="hint", text="a <b>"))


def test_keyboards_callback_data_fits_telegram_limit():
    markups = [
        kb.help_buttons(2**62, has_corrections=True),
        kb.level_keyboard(LEVELS, onboarding=True),
        kb.native_keyboard([("en", "English"), ("th", "ไทย")], "th", onboarding=True),
        kb.next_step_keyboard(),
        kb.settings_keyboard(),
        kb.settings_keyboard(reminders_enabled=False),
        kb.goal_keyboard(10),
        kb.reminder_keyboard(),
        kb.reminder_keyboard(reviews_due=12),
        kb.review_next_keyboard(3),
    ]
    for markup in markups:
        assert markup is not None
        for row in markup.inline_keyboard:
            for button in row:
                assert len(button.callback_data.encode()) <= 64, button.callback_data


def test_help_buttons():
    assert kb.help_buttons(None) is None
    rows = kb.help_buttons(5).inline_keyboard
    assert [b.callback_data for b in rows[0]] == ["h:hint:5", "h:translate:5", "h:suggest:5"]
    assert len(kb.help_buttons(5, has_corrections=True).inline_keyboard) == 2


def test_native_keyboard_puts_detected_first():
    rows = kb.native_keyboard([("en", "English"), ("th", "ไทย")], "th", onboarding=False)
    first = rows.inline_keyboard[0][0]
    assert first.text.startswith("✓") and first.callback_data == "nat:th:s"


def test_menu_labels_are_unique_and_all_shown():
    shown = [b.text for row in kb.main_menu().keyboard for b in row]
    assert len(shown) == len(set(shown)) == len(kb.MENU_LABELS) == 8
    assert set(shown) == kb.MENU_LABELS


def progress(**kw) -> TurnProgress:
    base = dict(
        streak=3, best_streak=5, today=1, goal=10, goal_met=False,
        first_today=False, goal_just_met=False,
    )  # fmt: skip
    return TurnProgress(**{**base, **kw})


def test_milestones_only_on_first_message_or_goal():
    assert "🔥" not in formatting.format_turn(turn(progress=progress()))
    assert formatting.format_milestone(None) == ""
    text = formatting.format_turn(turn(progress=progress(first_today=True)))
    assert "3-day streak" in text and "1/10" in text
    assert "Day 1" in formatting.format_milestone(progress(first_today=True, streak=1))
    goal = formatting.format_milestone(progress(goal_just_met=True, today=10, goal_met=True))
    assert "Daily goal reached" in goal and "10/10" in goal


def test_progress_shows_streak_and_today():
    daily = DailyProgressOut(streak=1, best_streak=4, today=10, goal=10, goal_met=True)
    lines = formatting.format_streak(daily)
    assert "1 day</b>" in lines[0] and "best 4 days" in lines[0]
    assert "10/10 ✅" in lines[1]


def test_reminder_text():
    r = ReminderOut(profile_id=uuid4(), external_id="1", streak=4, goal=10)
    assert "4 days" in formatting.format_reminder(r)
    assert "🔥" not in formatting.format_reminder(r.model_copy(update={"streak": 0}))


def test_goal_keyboard_marks_current():
    labels = [b.text for b in kb.goal_keyboard(10).inline_keyboard[0]]
    assert "✓ 10 / day" in labels


def test_card_snippet_highlights_and_trims():
    assert formatting.card_snippet("Yo soy en la playa.", "SOY EN") == (
        "Yo <b><u>soy en</u></b> la playa."
    )
    long = "a" * 200 + " soy en " + "b" * 200
    snip = formatting.card_snippet(long, "soy en")
    assert snip.startswith("…") and snip.endswith("…") and "<b><u>soy en</u></b>" in snip
    assert formatting.card_snippet("<x> & y", "zzz") == "&lt;x&gt; &amp; y"  # not found: escaped


def test_card_prompt_round_trip():
    q = ReviewQueueOut(
        card=ReviewCardOut(
            id=42,
            source_text="Yo soy en casa",
            wrong="soy en",
            rule_tag="t",
            rule_title="Ser",
            box=0,
        ),
        due=3,
        total=5,
        next_due_at=None,
    )
    html = formatting.format_card(q)
    assert "3 to go" in html and "<i>Ser</i>" in html
    # Telegram gives the bot the replied-to message as plain text (HTML tags removed).
    plain = html.replace("<b>", "").replace("</b>", "")
    assert formatting.parse_card_id(plain) == 42
    assert formatting.parse_card_id("hello") is None and formatting.parse_card_id(None) is None


def test_queue_empty_and_results():
    now = datetime(2026, 11, 20, 12, tzinfo=UTC)
    empty = ReviewQueueOut(card=None, due=0, total=0, next_due_at=None)
    assert "No mistakes to practise yet" in formatting.format_queue_empty(empty)
    later = empty.model_copy(
        update={"total": 4, "next_due_at": datetime(2026, 11, 21, 12, tzinfo=UTC)}
    )
    assert "in 1 day" in formatting.format_queue_empty(later, now)

    base = dict(
        wrong="soy en", right="estoy en", explanation="Location uses estar.",
        next_review_in_days=3.0, due=2, progress=progress(),
    )  # fmt: skip
    ok = formatting.format_review_result(ReviewAnswerOut(correct=True, feedback=None, **base))
    assert "Correct" in ok and "<s>soy en</s> → <b>estoy en</b>" in ok and "in 3 days" in ok
    bad = formatting.format_review_result(
        ReviewAnswerOut(**{**base, "correct": False, "feedback": "Use estar.", "due": 0})
    )
    assert "Not quite" in bad and "Use estar." in bad and "That's all for now" in bad


def test_answer_and_reminder_with_reviews():
    a = formatting.format_answer(
        AskOut(question="ser <> estar?", answer="Ser = what; estar = how.")
    )
    assert "ser &lt;&gt; estar?" in a and "estar = how" in a
    r = ReminderOut(profile_id=uuid4(), external_id="1", streak=0, goal=10, reviews_due=3)
    assert "3 mistakes to practise" in formatting.format_reminder_with_reviews(r)
    assert "practise." not in formatting.format_reminder_with_reviews(
        r.model_copy(update={"reviews_due": 0})
    )
