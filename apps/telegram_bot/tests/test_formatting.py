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
    assert [b.callback_data for b in rows[1]] == ["ask:5"]


def test_native_keyboard_puts_detected_first():
    rows = kb.native_keyboard([("en", "English"), ("th", "ไทย")], "th", onboarding=False)
    first = rows.inline_keyboard[0][0]
    assert first.text.startswith("✓") and first.callback_data == "nat:th:s"


def test_menu_labels_are_unique_and_all_shown():
    shown = [b.text for row in kb.main_menu().keyboard for b in row]
    assert len(shown) == len(set(shown)) == len(kb.MENU_LABELS) == 9
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


def test_voice_turn_shows_transcript_first():
    text = formatting.format_turn(turn(transcript="Yo soy <en> casa"))
    assert text.startswith("🎤 <i>I heard: “Yo soy &lt;en&gt; casa”</i>")
    assert "I heard" not in formatting.format_turn(turn())


def test_fold_toggle_and_explain_button():
    folded = kb.help_buttons(5, True, "✏️ 2 fixes", expanded=False).inline_keyboard
    assert [(b.text, b.callback_data) for b in folded[1]] == [
        ("🙋 Ask", "ask:5"),
        ("▾ ✏️ 2 fixes", "fb:5"),
    ]
    assert len(folded) == 2  # "Explain my mistakes" waits until the fixes are visible
    unfolded = kb.help_buttons(5, True, "✏️ 2 fixes", expanded=True).inline_keyboard
    assert unfolded[1][1].text == "▴ Hide feedback"
    assert [b.callback_data for b in unfolded[2]] == ["h:explain:5"]
    # Corrections but nothing to fold (unforeseen): Explain stays reachable.
    assert kb.help_buttons(5, True).inline_keyboard[2][0].callback_data == "h:explain:5"


def test_turn_split_into_body_and_feedback():
    t = turn(
        reply="¡Hola!",
        corrections=[
            Correction(wrong="soy", right="estoy", rule_tag="x", explanation="e", severity="major")
        ],
        new_vocab=[NewVocab(lemma="la playa", translation="beach", pos="noun")],
        well_done=[TopicRef(id="t", title="Ser")],
    )
    body, feedback = formatting.turn_body(t), formatting.turn_feedback(t)
    assert body == "¡Hola!"  # only the reply is visible by default
    assert "Nice use of" in feedback and "<s>soy</s>" in feedback and "la playa" in feedback
    assert formatting.feedback_label(t) == "✏️ 1 fix · 📚 1 word"
    assert formatting.feedback_label(turn(well_done=[TopicRef(id="t", title="Ser")])) == (
        "✅ Well done"
    )
    assert formatting.feedback_label(turn()) is None and formatting.turn_feedback(turn()) == ""
    # Milestones stay visible.
    assert "🔥" in formatting.turn_body(turn(progress=progress(first_today=True)))


def test_views_fold_and_extras():
    from tutor_telegram import views

    t = turn(
        reply="¡Hola!",
        corrections=[
            Correction(wrong="soy", right="estoy", rule_tag="x", explanation="e", severity="major")
        ],
    )
    v = views.from_turn(t)
    assert views.render(v) == "¡Hola!"
    assert views.markup(v).inline_keyboard[1][1].callback_data == "fb:7"
    v["expanded"] = True
    assert "<s>soy</s>" in views.render(v)
    v["extras"].append(["translate", formatting.help_block("translate", "Hello!")])
    assert views.has_extra(v, "translate") and not views.has_extra(v, "hint")
    assert views.render(v).endswith("🌐 <b>Translation</b>\nHello!</blockquote>")
    assert views.fits(v)
    v["extras"].append(["ask", formatting.inline_answer_block("q", "x" * 5000)])
    assert not views.fits(v)

    # A plain view (no feedback) has no fold button.
    plain = views.new_view(9, "Opening line")
    assert [b.callback_data for b in views.markup(plain).inline_keyboard[1]] == ["ask:9"]


def test_views_memory_is_bounded():
    from tutor_telegram import views

    chat_data: dict = {}
    for i in range(views.VIEWS_KEPT + 5):
        views.remember(chat_data, i, views.new_view(i, "x"))
    assert views.lookup(chat_data, 0) is None
    assert views.lookup(chat_data, views.VIEWS_KEPT + 4) is not None
    assert views.lookup(None, 1) is None


def test_ask_prompt_link_round_trip():
    html = formatting.ask_about_prompt(123, 4567, "golf_tutor_bot")
    url = html.split('href="')[1].split('"')[0]
    assert formatting.parse_ask_link(["https://example.com", url]) == (123, 4567)
    assert formatting.parse_ask_link([]) is None
    assert formatting.parse_ask_link(["https://t.me/x?start=other"]) is None


def test_inline_answer_block_and_length():
    block = formatting.inline_answer_block("¿<qué>?", "It means 'what'.")
    assert block.startswith("\n\n<blockquote expandable>🙋 <b>¿&lt;qué&gt;?</b>")
    assert block.endswith("It means &#x27;what&#x27;.</blockquote>")
    assert formatting.visible_length("<b>a&amp;b</b>") == 3


def _topic(reason=None, mastery=None, id_="es.c1.subjunctive_sequence_of_tenses"):
    from tutor_contracts import LessonTopicOut

    return LessonTopicOut(id=id_, title="Ser & estar", level="A1", mastery=mastery, reason=reason)


def test_lesson_menu_and_buttons():
    from tutor_contracts import LessonSuggestionsOut

    s = LessonSuggestionsOut(
        suggested=[_topic("weak", 0.2), _topic("next")], level_topics=[_topic(mastery=0.8)]
    )
    menu = formatting.format_lesson_menu(s)
    assert "🎯 Ser &amp; estar · ▰▱▱▱▱ 20%" in menu and "🆕 Ser &amp; estar · new" in menu
    rows = kb.lesson_topics_keyboard(s.suggested, browse=True).inline_keyboard
    assert rows[0][0].callback_data == "ls:es.c1.subjunctive_sequence_of_tenses"
    assert rows[-1][0].callback_data == "lb"
    for row in rows + kb.lesson_done_keyboard().inline_keyboard:
        for b in row:
            assert len(b.callback_data.encode()) <= 64
    assert "80%" in formatting.format_level_topics(s.level_topics)


def test_exercise_round_trip_and_results():
    from tutor_contracts import ExerciseOut, LessonAnswerOut

    ex = ExerciseOut(index=1, total=5, kind="fill_blank", instruction="Fill", prompt="Yo ___.")
    html = formatting.format_exercise(42, ex)
    plain = html.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
    assert "📝 Lesson #42 · 2/5" in plain
    assert formatting.parse_exercise(plain) == (42, 1)
    assert formatting.parse_exercise("🧠 Practice #3") is None

    base = dict(
        expected="estoy", why="Location uses estar.", feedback=None, score=2, answered=2,
        total=5, mastery=0.4, progress=progress(),
    )  # fmt: skip
    nxt = ExerciseOut(index=2, total=5, kind="fix", instruction="Fix", prompt="Ella es en casa.")
    ok = formatting.format_lesson_answer(42, LessonAnswerOut(correct=True, next=nxt, **base))
    assert ok.startswith("✅") and "📝 Lesson #42 · 3/5" in ok
    # The next question is inside the same message, so a reply to it routes correctly.
    assert formatting.parse_exercise(ok.replace("<b>", "").replace("</b>", "")) == (42, 2)
    done = formatting.format_lesson_answer(
        42,
        LessonAnswerOut(
            **{**base, "correct": False, "feedback": "Use estar.", "score": 5}, next=None
        ),
    )
    assert "Answer: <b>estoy</b>" in done and "Lesson done: 5/5" in done and "🌟" in done


def _langs():
    from tutor_contracts import LanguageOut

    return [
        LanguageOut(code="es", name="Spanish", native_name="Español", flag="🇪🇸", levels=[]),
        LanguageOut(code="ja", name="Japanese", native_name="日本語", flag="🇯🇵", levels=[]),
    ]


def test_language_keyboard():
    rows = kb.language_keyboard(_langs(), "ja", onboarding=True).inline_keyboard
    assert [(r[0].text, r[0].callback_data) for r in rows] == [
        ("🇪🇸 Spanish · Español", "tl:es:o"),
        ("✓ 🇯🇵 Japanese · 日本語", "tl:ja:o"),
    ]
    assert (
        kb.language_keyboard(_langs(), None, onboarding=False).inline_keyboard[0][0].callback_data
        == "tl:es:s"
    )


def test_settings_and_reminders_carry_language():
    rows = kb.settings_keyboard(True, "🇯🇵 Japanese").inline_keyboard
    assert rows[0][0].callback_data == "menu:settings_lang" and "Japanese" in rows[0][0].text
    assert kb.settings_keyboard(True).inline_keyboard[0][0].callback_data == "menu:settings_level"
    rem = kb.reminder_keyboard(3, "zh").inline_keyboard
    assert [r[0].callback_data for r in rem] == ["go:zh:resume", "go:zh:review", "rem:off"]
    assert kb.reminder_keyboard().inline_keyboard[0][0].callback_data == "menu:resume"


def test_lesson_layout_with_parts_and_fallback():
    from tutor_contracts import (
        LessonExampleOut,
        LessonFormOut,
        LessonOut,
        LessonPartsOut,
        LessonWatchOutOut,
    )

    parts = LessonPartsOut(
        summary="Past habits & descriptions.",
        forms=[LessonFormOut(label="-ar (hablar)", forms="hablaba · hablabas")],
        usage=["Habits: siempre, cada día"],
        examples=[
            LessonExampleOut(sentence="Vivía en <Madrid>.", translation="I lived in Madrid.")
        ],
        watch_out=LessonWatchOutOut(
            wrong="Jugué cada día.", right="Jugaba cada día.", note="Habit."
        ),
    )
    lesson = LessonOut(id=1, topic=_topic(), explanation="plain", parts=parts, exercise=None)
    html = formatting.format_lesson(lesson)
    assert html.startswith("📖 <b>Ser &amp; estar</b>\n\n<i>Past habits &amp; descriptions.</i>")
    assert "<b>📐 Forms</b>\n<b>-ar (hablar)</b>\n<code>hablaba · hablabas</code>" in html
    assert "▸ <b>Vivía en &lt;Madrid&gt;.</b>\n   <i>I lived in Madrid.</i>" in html
    assert "❌ <s>Jugué cada día.</s>\n✅ <b>Jugaba cada día.</b>" in html
    assert formatting.format_lesson(lesson.model_copy(update={"parts": None})).endswith("plain")
