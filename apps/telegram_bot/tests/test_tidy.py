"""Daily chat tidy (message tracking) and past-day views. No network."""

from datetime import UTC, date, datetime

from telegram import Chat, Message
from telegram.ext import ExtBot
from tutor_contracts import DayOut, DayTranscriptOut, TranscriptFix, TranscriptLine, WeeklyTopicOut
from tutor_telegram import formatting, tidy
from tutor_telegram import keyboards as kb

NOW = 1_800_000_000.0
HOUR = 3600.0
D = date(2026, 11, 25)


def test_take_deletable_by_language_and_time():
    data: dict = {}
    tidy.track(data, 1, NOW - 20 * HOUR, "es")  # yesterday, Spanish
    tidy.track(data, 2, NOW - 20 * HOUR, "zh")  # yesterday, Chinese
    tidy.track(data, 3, NOW - 1 * HOUR, "es")  # today
    tidy.track(data, 4, NOW - 50 * HOUR, "zh")  # too old to delete: forgotten
    tidy.track(data, 1, NOW, "zh")  # re-tracking keeps the first record
    before = NOW - 2 * HOUR

    assert tidy.take_deletable(data, "es", before, NOW) == [1]
    assert set(data["sent"]) == {2, 3}
    assert tidy.take_deletable(data, "es", before, NOW) == []  # once only
    assert tidy.take_deletable(data, "zh", before, NOW) == [2]


def test_newest_menu_message_is_kept():
    data: dict = {}
    tidy.track(data, 1, NOW - 20 * HOUR, "es", menu=True)
    tidy.track(data, 2, NOW - 19 * HOUR, "es")
    assert tidy.take_deletable(data, "es", NOW, NOW) == [2]  # the menu keyboard stays
    tidy.track(data, 3, NOW - 18 * HOUR, "es", menu=True)  # a newer menu message
    assert tidy.take_deletable(data, "es", NOW, NOW) == [1]


def test_untrack_and_cap():
    data: dict = {}
    for i in range(tidy.TRACKED_MAX + 5):
        tidy.track(data, i, NOW, "es")
    assert len(data["sent"]) == tidy.TRACKED_MAX and 0 not in data["sent"]
    tidy.untrack(data, 10)
    tidy.untrack(data, 10)
    assert 10 not in data["sent"]


def test_batches():
    assert tidy.batches([]) == []
    assert [len(b) for b in tidy.batches(list(range(250)))] == [100, 100, 50]


def _message(edited: bool = False) -> Message:
    return Message(
        message_id=7,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        edit_date=datetime.now(UTC) if edited else None,
    )


async def test_tracking_bot_reports_new_messages_only(monkeypatch):
    seen: list[int] = []
    results = iter([_message(), _message(edited=True), True])

    async def fake_send(self, *args, **kwargs):
        return next(results)

    monkeypatch.setattr(ExtBot, "_send_message", fake_send)
    bot = tidy.TrackingBot(token="123:abc")
    bot.set_on_sent(lambda m, menu: seen.append((m.message_id, menu)))
    await bot._send_message("sendMessage", {}, reply_markup=kb.main_menu())
    await bot._send_message("editMessageText", {})  # an edit: not a new message
    await bot._send_message("pinChatMessage", {})  # not a message
    assert seen == [(7, True)]


def _day(**kw) -> DayOut:
    base = dict(day=D, messages=12, corrections=3, new_words=1, lessons=0, top_mistakes=[])
    return DayOut(**(base | kw))


def test_day_card():
    card = formatting.format_day_card(
        _day(top_mistakes=[WeeklyTopicOut(id="x", title="Ser <vs> estar", count=2)]), "🇪🇸 Spanish"
    )
    assert card.splitlines()[0] == "📅 <b>Wed 25 Nov</b> · 🇪🇸 Spanish"
    assert "12 messages · ✏️ 3 fixes · 📚 1 new word" in card
    assert "📖" not in card  # no lessons that day
    assert "Ser &lt;vs&gt; estar" in card
    one = formatting.format_day_card(_day(messages=1, corrections=1, new_words=0, lessons=2))
    assert "1 message ·" in one and "1 fix ·" in one and "2 lessons" in one


def _line(role: str, text: str, **kw) -> TranscriptLine:
    return TranscriptLine(role=role, text=text, at=datetime(2026, 11, 25, 10, tzinfo=UTC), **kw)  # type: ignore[arg-type]


def test_day_pages_split_and_fit():
    lines = [_line("tutor", "¡Hola!", scenario_title="At the café")]
    for i in range(80):
        lines.append(
            _line(
                "learner",
                f"Yo soy cansado {i} " + "x" * 60,
                fixes=[TranscriptFix(wrong="soy", right="estoy", explanation="a state")],
            )
        )
        lines.append(_line("tutor", "¿Por qué? " + "y" * 80))
    t = DayTranscriptOut(day=_day(), lines=lines)
    pages = formatting.day_pages(t)
    assert len(pages) > 1
    assert pages[0].startswith("<b>— At the café —</b>")
    assert "✏️ <s>soy</s> → <b>estoy</b> <i>(a state)</i>" in pages[0]
    for n, _ in enumerate(pages, start=1):
        page = formatting.format_day_page(t, n, len(pages))
        assert formatting.visible_length(page) <= formatting.TELEGRAM_TEXT_LIMIT
        assert f"page {n}/{len(pages)}" in page
    joined = "".join(pages)
    assert joined.count("🧑") == 80 and joined.count("🎓") == 81  # nothing lost between pages


def test_day_pages_long_line_and_empty():
    t = DayTranscriptOut(day=_day(), lines=[_line("tutor", "z" * 9000)])
    page = formatting.format_day_page(t, 1, 1)
    assert formatting.visible_length(page) <= formatting.TELEGRAM_TEXT_LIMIT
    assert "page" not in page  # single page: no counter
    empty = formatting.day_pages(DayTranscriptOut(day=_day(), lines=[]))
    assert len(empty) == 1 and "No conversation" in empty[0]


def _data(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_day_buttons_round_trip():
    assert _data(kb.day_card_keyboard("es", D)) == ["dy:es:20261125:1"]
    assert kb.parse_day("es:20261125:3") == ("es", D, 3)
    assert kb.parse_day("es:2026-11-25:3") is None
    assert kb.parse_day("es:20261125") is None
    assert kb.parse_day("es:20261399:1") is None

    assert _data(kb.day_page_keyboard("es", D, 1, 1)) == ["dy:es:20261125:0", "dl:es"]
    assert _data(kb.day_page_keyboard("es", D, 2, 3)) == [
        "dy:es:20261125:1",
        "dy:es:20261125:3",
        "dy:es:20261125:0",
        "dl:es",
    ]
    days = kb.day_list_keyboard("ja", [D, date(2026, 11, 24), date(2026, 11, 20)], [4, 1, 9])
    assert [len(r) for r in days.inline_keyboard] == [2, 1]
    assert days.inline_keyboard[0][0].text == "Wed 25 Nov · 4 msg"
    for data in _data(days) + _data(kb.day_page_keyboard("ja", D, 2, 3)):
        assert len(data.encode()) <= 64


def test_settings_keyboard_tidy_toggle():
    assert "tidy:off" in _data(kb.settings_keyboard(tidy_chat=True))
    assert "tidy:on" in _data(kb.settings_keyboard(tidy_chat=False))
    assert "dl:" in _data(kb.settings_keyboard())
