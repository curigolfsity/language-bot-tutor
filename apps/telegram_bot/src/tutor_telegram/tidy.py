"""Daily chat tidy: remember which messages may be deleted later. Display state only.

Every message in a private chat (the learner's and the bot's) is recorded in `chat_data`
with its time and the language the chat was learning, so the nightly tidy can delete one
language's messages from before today. Day cards are never recorded, so they stay. The
conversation itself is kept by the API; this only cleans the Telegram screen.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from telegram import Message, ReplyKeyboardMarkup
from telegram.ext import ExtBot

# Telegram lets a bot delete messages for 48 hours. Leave a margin for slow tidies.
DELETABLE_SECONDS = 47 * 3600
TRACKED_MAX = 3000  # per chat; a very busy day still fits
DELETE_BATCH = 100  # deleteMessages takes at most 100 ids

Tracked = dict[int, list[Any]]  # message_id -> [unix time, lang]


def _store(chat_data: dict[str, Any]) -> Tracked:
    return chat_data.setdefault("sent", {})


def track(
    chat_data: dict[str, Any], message_id: int, at: float, lang: str, menu: bool = False
) -> None:
    """`menu`: the message carries the persistent menu keyboard. The newest such message is
    never deleted, because some Telegram apps hide the keyboard along with its message."""
    if menu:
        chat_data["menu_message"] = message_id
    store = _store(chat_data)
    store.setdefault(message_id, [at, lang])
    while len(store) > TRACKED_MAX:
        store.pop(next(iter(store)))


def untrack(chat_data: dict[str, Any], message_id: int) -> None:
    _store(chat_data).pop(message_id, None)


def take_deletable(chat_data: dict[str, Any], lang: str, before: float, now: float) -> list[int]:
    """Ids of `lang` messages sent before `before` that Telegram still lets us delete. They
    are forgotten, along with any message (of any language) too old to delete anyway."""
    store = _store(chat_data)
    keep = chat_data.get("menu_message")
    out: list[int] = []
    for message_id, (at, msg_lang) in list(store.items()):
        if message_id == keep:
            continue
        too_old = now - at > DELETABLE_SECONDS
        if too_old or (msg_lang == lang and at < before):
            del store[message_id]
            if not too_old:
                out.append(message_id)
    return sorted(out)


def batches(ids: list[int]) -> list[list[int]]:
    return [ids[i : i + DELETE_BATCH] for i in range(0, len(ids), DELETE_BATCH)]


class TrackingBot(ExtBot):  # type: ignore[type-arg]
    """An ExtBot that reports every new message it sends (edits are not new messages)."""

    _on_sent: Callable[[Message, bool], None] | None = None

    def set_on_sent(self, callback: Callable[[Message, bool], None]) -> None:
        """`callback(message, has_menu_keyboard)` runs after every new message is sent."""
        self._on_sent = callback  # private name: bots are frozen for public attributes

    async def _send_message(self, *args: Any, **kwargs: Any) -> Any:
        result = await super()._send_message(*args, **kwargs)
        if isinstance(result, Message) and result.edit_date is None and self._on_sent:
            markup = kwargs.get("reply_markup")
            self._on_sent(result, isinstance(markup, ReplyKeyboardMarkup))
        return result
