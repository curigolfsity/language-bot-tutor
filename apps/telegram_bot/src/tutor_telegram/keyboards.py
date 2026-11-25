"""Telegram keyboards. Presentation only.

Callback data (max 64 bytes) is self-describing, so the bot stays stateless:
  h:<kind>:<turn_id>     help on a tutor message (hint | translate | suggest | explain)
  ask:<turn_id>          ask a question about a tutor message (answer goes inside that message)
  fb:<turn_id>           fold / unfold the feedback (fixes, praise, new words) of a tutor message
  nat:<code>:<o|s>       set native language (o = onboarding step, s = from settings)
  lvl:<code>:<o|s>       set level
  play:<scenario_id>     start a role-play
  goal:<n>               set the daily goal (messages per day)
  rem:<on|off>           practice reminders on / off
  rv:<next|done>         practise-my-mistakes: next card / stop
  menu:<action>          free | roleplay | resume | settings_level | settings_native | settings_goal
"""

from __future__ import annotations

from telegram import (
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from tutor_contracts import LevelOut, ScenarioOut

# Persistent menu under the text box. Pressing one sends its label as a message.
MENU_CHAT = "💬 Free chat"
MENU_ROLEPLAY = "🎭 Role-play"
MENU_PROGRESS = "📊 My progress"
MENU_FINISH = "🏁 Finish session"
MENU_SETTINGS = "⚙️ Settings"
MENU_HELP = "❓ How it works"
MENU_REVIEW = "🧠 Practise mistakes"
MENU_ASK = "🙋 Ask a question"
MENU_LABELS = {
    MENU_CHAT,
    MENU_ROLEPLAY,
    MENU_REVIEW,
    MENU_ASK,
    MENU_PROGRESS,
    MENU_FINISH,
    MENU_SETTINGS,
    MENU_HELP,
}

# Headers of messages the learner answers with Telegram's "reply". The bot recognises the
# reply by the quoted header, so it needs no memory of what it asked.
ASK_PROMPT_HEADER = "🙋 Ask me anything"
REVIEW_HEADER = "🧠 Practice #"  # followed by the card id

LEVEL_ICONS = ["🌱", "🌿", "🌳", "🏔️", "🚀", "👑"]
GOAL_CHOICES = (5, 10, 20, 30)  # messages per day offered as buttons


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(MENU_CHAT), KeyboardButton(MENU_ROLEPLAY)],
            [KeyboardButton(MENU_REVIEW), KeyboardButton(MENU_ASK)],
            [KeyboardButton(MENU_PROGRESS), KeyboardButton(MENU_FINISH)],
            [KeyboardButton(MENU_SETTINGS), KeyboardButton(MENU_HELP)],
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
    second = [InlineKeyboardButton("🙋 Ask", callback_data=f"ask:{turn_id}")]
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


def settings_keyboard(reminders_enabled: bool = True) -> InlineKeyboardMarkup:
    reminder = (
        InlineKeyboardButton("🔕 Turn reminders off", callback_data="rem:off")
        if reminders_enabled
        else InlineKeyboardButton("🔔 Turn reminders on", callback_data="rem:on")
    )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📶 Change my level", callback_data="menu:settings_level")],
            [
                InlineKeyboardButton(
                    "🗣️ Change explanation language", callback_data="menu:settings_native"
                )
            ],
            [InlineKeyboardButton("🎯 Change daily goal", callback_data="menu:settings_goal")],
            [reminder],
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


def reminder_keyboard(reviews_due: int = 0) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("▶️ Practise now", callback_data="menu:resume")]]
    if reviews_due:
        rows.append(
            [InlineKeyboardButton(f"🧠 Review {reviews_due} mistakes", callback_data="menu:review")]
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
