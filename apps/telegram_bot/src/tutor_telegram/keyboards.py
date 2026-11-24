"""Telegram keyboards. Presentation only.

Callback data (max 64 bytes) is self-describing, so the bot stays stateless:
  h:<kind>:<turn_id>     help on a tutor message (hint | translate | suggest | explain)
  nat:<code>:<o|s>       set native language (o = onboarding step, s = from settings)
  lvl:<code>:<o|s>       set level
  play:<scenario_id>     start a role-play
  menu:<action>          free | roleplay | settings_level | settings_native
"""

from __future__ import annotations

from telegram import (
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
MENU_LABELS = {MENU_CHAT, MENU_ROLEPLAY, MENU_PROGRESS, MENU_FINISH, MENU_SETTINGS, MENU_HELP}

LEVEL_ICONS = ["🌱", "🌿", "🌳", "🏔️", "🚀", "👑"]


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(MENU_CHAT), KeyboardButton(MENU_ROLEPLAY)],
            [KeyboardButton(MENU_PROGRESS), KeyboardButton(MENU_FINISH)],
            [KeyboardButton(MENU_SETTINGS), KeyboardButton(MENU_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Write your message…",
    )


def help_buttons(turn_id: int | None, has_corrections: bool = False) -> InlineKeyboardMarkup | None:
    if turn_id is None:
        return None
    rows = [
        [
            InlineKeyboardButton("💡 Hint", callback_data=f"h:hint:{turn_id}"),
            InlineKeyboardButton("🌐 Translate", callback_data=f"h:translate:{turn_id}"),
            InlineKeyboardButton("✍️ Suggest", callback_data=f"h:suggest:{turn_id}"),
        ]
    ]
    if has_corrections:
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


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📶 Change my level", callback_data="menu:settings_level")],
            [
                InlineKeyboardButton(
                    "🗣️ Change explanation language", callback_data="menu:settings_native"
                )
            ],
        ]
    )
