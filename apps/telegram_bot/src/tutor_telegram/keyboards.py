"""Telegram keyboards. Presentation only.

Callback data (max 64 bytes) is self-describing, so the bot stays stateless:
  h:<kind>:<turn_id>     help on a tutor message (hint | translate | suggest | explain)
  ask:<turn_id>          ask a question about a tutor message (answer goes inside that message)
  fb:<turn_id>           fold / unfold the feedback (fixes, praise, new words) of a tutor message
  tl:<code>:<o|s>        choose the language to learn (o = onboarding, s = switch)
  go:<code>:<action>     from a reminder: switch to that language, then resume | review
  nat:<code>:<o|s>       set native language (o = onboarding step, s = from settings)
  lvl:<code>:<o|s>       set level
  play:<scenario_id>     start a role-play
  goal:<n>               set the daily goal (messages per day)
  rem:<on|off>           practice reminders on / off
  rv:<next|done>         practise-my-mistakes: next card / stop
  ls:<topic_id>          start a grammar lesson on that topic
  lb                     browse every grammar topic at the learner's level
  sp:<turn_id>           read a tutor message aloud (voice message)
  av:<on|off>            voice replies after every tutor message on / off
  wd:<show|y|n|say>:<id> word flashcard: reveal / knew it / didn't / say it; wd:next
  pl:start[:o|s]         placement test: start (o = during onboarding)
  pl:keep | pl:pick      after the test: keep my level / pick a level myself
  pl:<run>:<choice>:<q>  placement test: answer question <q> with option <choice>
  lf:<topic_id>          the same lesson with a newly written explanation
  sw:<turn_id>           save words from a tutor message as word cards
  pr:go                  start a mixed practice round (mistakes + words)
  menu:<action>          free | roleplay | resume | review | lessons | settings_level |
                         settings_native | settings_goal | settings_lang
"""

from __future__ import annotations

from telegram import (
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from tutor_contracts import LanguageOut, LessonTopicOut, LevelOut, ScenarioOut

# Persistent menu under the text box. Pressing one sends its label as a message.
MENU_CHAT = "💬 Free chat"
MENU_ROLEPLAY = "🎭 Role-play"
MENU_PROGRESS = "📊 My progress"
MENU_FINISH = "🏁 Finish session"
MENU_SETTINGS = "⚙️ Settings"
MENU_HELP = "❓ How it works"
MENU_REVIEW = "🧠 Practise mistakes"
MENU_ASK = "🙋 Ask a question"
MENU_LESSONS = "📖 Grammar lessons"
MENU_WORDS = "🃏 Word cards"
# The compact menu (5 buttons). The labels above stay recognised: phones keep showing an old
# menu until the bot sends the new one.
MENU_CHAT_SHORT = "💬 Chat"
MENU_PRACTICE = "🧠 Practice"
MENU_LESSONS_SHORT = "📖 Lessons"
MENU_MORE = "☰ More"
MENU_LABELS = {MENU_CHAT_SHORT, MENU_ROLEPLAY, MENU_PRACTICE, MENU_LESSONS_SHORT, MENU_MORE}
LEGACY_MENU_LABELS = {
    MENU_CHAT,
    MENU_REVIEW,
    MENU_ASK,
    MENU_LESSONS,
    MENU_PROGRESS,
    MENU_FINISH,
    MENU_SETTINGS,
    MENU_HELP,
    MENU_WORDS,
}

# Headers of messages the learner answers with Telegram's "reply". The bot recognises the
# reply by the quoted header, so it needs no memory of what it asked.
ASK_PROMPT_HEADER = "🙋 Ask me anything"
REVIEW_HEADER = "🧠 Practice #"  # followed by the card id
SAVE_HEADER = "➕ Save words #"  # followed by the tutor turn id
LESSON_HEADER = "📝 Lesson #"  # followed by "<lesson id> · <n>/<total>"

LEVEL_ICONS = ["🌱", "🌿", "🌳", "🏔️", "🚀", "👑"]
GOAL_CHOICES = (5, 10, 20, 30)  # messages per day offered as buttons


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(MENU_CHAT_SHORT), KeyboardButton(MENU_ROLEPLAY)],
            [KeyboardButton(MENU_PRACTICE), KeyboardButton(MENU_LESSONS_SHORT)],
            [KeyboardButton(MENU_MORE)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Write your message…",
    )


def help_buttons(
    turn_id: int | None,
    has_corrections: bool = False,
    feedback_label: str | None = None,
    expanded: bool = False,
) -> InlineKeyboardMarkup | None:
    """Buttons under a tutor message. `feedback_label` (e.g. "✏️ 2 fixes") adds the fold
    toggle; "Explain my mistakes" shows only while the feedback is unfolded."""
    if turn_id is None:
        return None
    rows = [
        [
            InlineKeyboardButton("💡 Hint", callback_data=f"h:hint:{turn_id}"),
            InlineKeyboardButton("🌐 Translate", callback_data=f"h:translate:{turn_id}"),
            InlineKeyboardButton("✍️ Suggest", callback_data=f"h:suggest:{turn_id}"),
        ]
    ]
    second = [
        InlineKeyboardButton("🔊", callback_data=f"sp:{turn_id}"),
        InlineKeyboardButton("🙋 Ask", callback_data=f"ask:{turn_id}"),
        InlineKeyboardButton("➕ Word", callback_data=f"sw:{turn_id}"),
    ]
    if feedback_label:
        toggle = "▴ Hide feedback" if expanded else f"▾ {feedback_label}"
        second.append(InlineKeyboardButton(toggle, callback_data=f"fb:{turn_id}"))
    rows.append(second)
    if has_corrections and (expanded or not feedback_label):
        rows.append(
            [InlineKeyboardButton("❓ Explain my mistakes", callback_data=f"h:explain:{turn_id}")]
        )
    return InlineKeyboardMarkup(rows)


def level_icon(rank: int) -> str:
    return LEVEL_ICONS[min(rank, len(LEVEL_ICONS)) - 1] if rank >= 1 else "•"


def level_keyboard(levels: list[LevelOut], onboarding: bool) -> InlineKeyboardMarkup:
    flag = "o" if onboarding else "s"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{level_icon(lv.rank)} {lv.label}" + (f" · {lv.can_do}" if lv.can_do else ""),
                    callback_data=f"lvl:{lv.code}:{flag}",
                )
            ]
            for lv in levels
        ]
        + [
            [
                InlineKeyboardButton(
                    "🧭 Not sure? Take a 2-minute test", callback_data=f"pl:start:{flag}"
                )
            ]
        ]
    )


def native_keyboard(
    choices: list[tuple[str, str]], detected: str | None, onboarding: bool
) -> InlineKeyboardMarkup:
    flag = "o" if onboarding else "s"
    ordered = sorted(choices, key=lambda c: 0 if c[0] == detected else 1)
    buttons = [
        InlineKeyboardButton(
            ("✓ " if code == detected else "") + label, callback_data=f"nat:{code}:{flag}"
        )
        for code, label in ordered
    ]
    return InlineKeyboardMarkup([buttons[i : i + 2] for i in range(0, len(buttons), 2)])


def scenario_keyboard(scenarios: list[ScenarioOut]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"[{s.level}] {s.title}", callback_data=f"play:{s.id}")]
            for s in scenarios
        ]
    )


def next_step_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎭 New role-play", callback_data="menu:roleplay"),
                InlineKeyboardButton("💬 Free chat", callback_data="menu:free"),
            ]
        ]
    )


def language_keyboard(
    languages: list[LanguageOut], current: str | None, onboarding: bool
) -> InlineKeyboardMarkup:
    flag = "o" if onboarding else "s"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    ("✓ " if lang.code == current else "")
                    + f"{lang.flag} {lang.name} · {lang.native_name}",
                    callback_data=f"tl:{lang.code}:{flag}",
                )
            ]
            for lang in languages
        ]
    )


def settings_keyboard(
    reminders_enabled: bool = True, language_label: str | None = None, voice: bool = False
) -> InlineKeyboardMarkup:
    reminder = (
        InlineKeyboardButton("🔕 Turn reminders off", callback_data="rem:off")
        if reminders_enabled
        else InlineKeyboardButton("🔔 Turn reminders on", callback_data="rem:on")
    )
    language = (
        [
            [
                InlineKeyboardButton(
                    f"🌍 Learning {language_label}: switch", callback_data="menu:settings_lang"
                )
            ]
        ]
        if language_label
        else []
    )
    return InlineKeyboardMarkup(
        [
            *language,
            [InlineKeyboardButton("📶 Change my level", callback_data="menu:settings_level")],
            [InlineKeyboardButton("🧭 Find my level (quick test)", callback_data="pl:start")],
            [
                InlineKeyboardButton(
                    "🗣️ Change explanation language", callback_data="menu:settings_native"
                )
            ],
            [InlineKeyboardButton("🎯 Change daily goal", callback_data="menu:settings_goal")],
            [reminder],
            [
                InlineKeyboardButton("🔇 Turn voice replies off", callback_data="av:off")
                if voice
                else InlineKeyboardButton("🔊 Turn voice replies on", callback_data="av:on")
            ],
        ]
    )


def goal_keyboard(current: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    ("✓ " if n == current else "") + f"{n} / day", callback_data=f"goal:{n}"
                )
                for n in GOAL_CHOICES
            ]
        ]
    )


def reminder_keyboard(reviews_due: int = 0, lang: str | None = None) -> InlineKeyboardMarkup:
    """With `lang`, the buttons switch the chat to that language first (multi-language bots)."""
    resume = f"go:{lang}:resume" if lang else "menu:resume"
    review = f"go:{lang}:review" if lang else "menu:review"
    rows = [[InlineKeyboardButton("▶️ Practise now", callback_data=resume)]]
    if reviews_due:
        rows.append(
            [InlineKeyboardButton(f"🧠 Review {reviews_due} mistakes", callback_data=review)]
        )
    rows.append([InlineKeyboardButton("🔕 Stop reminders", callback_data="rem:off")])
    return InlineKeyboardMarkup(rows)


def reply_prompt(placeholder: str) -> ForceReply:
    """Opens the reply box on the prompt, so the answer quotes it."""
    return ForceReply(selective=True, input_field_placeholder=placeholder)


def review_next_keyboard(due: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"▶️ Next ({due} left)", callback_data="rv:next"),
                InlineKeyboardButton("🏁 Stop", callback_data="rv:done"),
            ]
        ]
    )


TOPIC_ICONS = {"weak": "🎯", "next": "🆕", "refresh": "🔁"}


def lesson_topics_keyboard(topics: list[LessonTopicOut], browse: bool) -> InlineKeyboardMarkup:
    """One button per topic; `browse` adds "all topics at my level"."""
    rows = [
        [
            InlineKeyboardButton(
                f"{TOPIC_ICONS.get(t.reason or '', '📖')} {t.title}", callback_data=f"ls:{t.id}"
            )
        ]
        for t in topics
    ]
    if browse:
        rows.append([InlineKeyboardButton("📚 All topics at my level", callback_data="lb")])
    return InlineKeyboardMarkup(rows)


def lesson_done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💬 Use it in a conversation", callback_data="menu:free")],
            [
                InlineKeyboardButton("📖 Another lesson", callback_data="menu:lessons"),
                InlineKeyboardButton("🧠 My mistakes", callback_data="menu:review"),
            ],
        ]
    )


def word_front_keyboard(word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👀 Show meaning", callback_data=f"wd:show:{word_id}"),
                InlineKeyboardButton("🔊", callback_data=f"wd:say:{word_id}"),
            ]
        ]
    )


def word_back_keyboard(word_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ I knew it", callback_data=f"wd:y:{word_id}"),
                InlineKeyboardButton("❌ Not yet", callback_data=f"wd:n:{word_id}"),
            ],
            [InlineKeyboardButton("🔊", callback_data=f"wd:say:{word_id}")],
        ]
    )


def word_next_keyboard(due: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(f"▶️ Next ({due} left)", callback_data="wd:next"),
                InlineKeyboardButton("🏁 Stop", callback_data="rv:done"),
            ]
        ]
    )


def placement_keyboard(run_id: int, question_id: str, options: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(o, callback_data=f"pl:{run_id}:{i}:{question_id}")
        for i, o in enumerate(options)
    ]
    return InlineKeyboardMarkup([buttons[i : i + 2] for i in range(0, len(buttons), 2)])


def placement_result_keyboard(
    suggested: str, current: str, suggested_label: str, onboarding: bool = False
) -> InlineKeyboardMarkup:
    if onboarding:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        f"✅ Start at {suggested_label}", callback_data=f"lvl:{suggested}:o"
                    )
                ],
                [InlineKeyboardButton("📶 Choose a level myself", callback_data="pl:pick")],
            ]
        )
    rows = []
    if suggested != current:
        rows.append(
            [
                InlineKeyboardButton(
                    f"✅ Switch to {suggested_label}", callback_data=f"lvl:{suggested}:s"
                )
            ]
        )
        rows.append([InlineKeyboardButton(f"Keep my level ({current})", callback_data="pl:keep")])
    rows.append(
        [InlineKeyboardButton("📶 Choose a level myself", callback_data="menu:settings_level")]
    )
    return InlineKeyboardMarkup(rows)


def lesson_fresh_keyboard(topic_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Explain it differently", callback_data=f"lf:{topic_id}")]]
    )


def weekly_keyboard(
    lesson_id: str | None, reviews_due: int, words_due: int, lang: str | None = None
) -> InlineKeyboardMarkup:
    rows = []
    if lesson_id:
        rows.append([InlineKeyboardButton("📖 Suggested lesson", callback_data=f"ls:{lesson_id}")])
    if reviews_due:
        review = f"go:{lang}:review" if lang else "menu:review"
        rows.append(
            [InlineKeyboardButton(f"🧠 Review {reviews_due} mistakes", callback_data=review)]
        )
    if words_due:
        rows.append([InlineKeyboardButton(f"🃏 {words_due} word cards", callback_data="wd:next")])
    rows.append([InlineKeyboardButton("💬 Chat now", callback_data="menu:free")])
    return InlineKeyboardMarkup(rows)


def more_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📊 Progress", callback_data="menu:progress"),
                InlineKeyboardButton("📅 My week", callback_data="menu:week"),
            ],
            [
                InlineKeyboardButton("🙋 Ask a question", callback_data="menu:ask"),
                InlineKeyboardButton("🏁 Finish session", callback_data="menu:finish"),
            ],
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
                InlineKeyboardButton("❓ How it works", callback_data="menu:help"),
            ],
        ]
    )


def practice_keyboard(mistakes_due: int, words_due: int) -> InlineKeyboardMarkup:
    rows = []
    if mistakes_due + words_due:
        rows.append(
            [
                InlineKeyboardButton(
                    f"▶️ Practise now ({mistakes_due + words_due} due)", callback_data="pr:go"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(f"🧠 Mistakes ({mistakes_due})", callback_data="menu:review"),
            InlineKeyboardButton(f"🃏 Words ({words_due})", callback_data="wd:next"),
        ]
    )
    return InlineKeyboardMarkup(rows)
