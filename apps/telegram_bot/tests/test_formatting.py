from datetime import UTC, datetime
from uuid import uuid4

from tutor_contracts import (
    Correction,
    HelpOut,
    LearnerProfileOut,
    LevelOut,
    MistakeCount,
    MistakeOut,
    NewVocab,
    SessionOut,
    SessionSummary,
    SkillLevelOut,
    TopicRef,
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


def test_menu_labels_are_unique():
    assert len(kb.MENU_LABELS) == 6
