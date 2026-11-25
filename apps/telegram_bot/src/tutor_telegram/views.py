"""Foldable tutor messages. Presentation only.

A tutor message is rendered from a small "view" kept per chat in `chat_data` (persisted to
disk by the application), so buttons can fold/unfold its feedback and add help answers inside
the same message by editing it. Views are plain dicts so the persisted file stays readable
across code changes. A message without a view (sent before this existed, or evicted) simply
falls back to sending help as a separate message.
"""

from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardMarkup
from tutor_contracts import TurnResponse

from tutor_telegram import formatting
from tutor_telegram import keyboards as kb

VIEWS_KEPT = 100  # most recent tutor messages remembered per chat

View = dict[str, Any]


def from_turn(result: TurnResponse) -> View:
    return new_view(
        turn_id=result.turn_id,
        body=formatting.turn_body(result),
        feedback=formatting.turn_feedback(result),
        label=formatting.feedback_label(result),
        has_corrections=bool(result.corrections),
    )


def new_view(
    turn_id: int | None,
    body: str,
    feedback: str = "",
    label: str | None = None,
    has_corrections: bool = False,
) -> View:
    return {
        "turn_id": turn_id,
        "body": body,
        "feedback": feedback,
        "label": label if feedback else None,
        "has_corrections": has_corrections,
        "expanded": False,
        "extras": [],  # [key, html]: help answers ("hint", "translate", ...) and questions ("ask")
    }


def render(view: View) -> str:
    html = view["body"]
    if view["expanded"] and view["feedback"]:
        html += "\n\n" + view["feedback"]
    for _key, block in view["extras"]:
        html += block
    return html


def markup(view: View) -> InlineKeyboardMarkup | None:
    return kb.help_buttons(
        view["turn_id"], view["has_corrections"], view["label"], view["expanded"]
    )


def fits(view: View) -> bool:
    return formatting.visible_length(render(view)) <= formatting.TELEGRAM_TEXT_LIMIT


def has_extra(view: View, key: str) -> bool:
    return any(k == key for k, _ in view["extras"])


def _store(chat_data: dict[str, Any]) -> dict[int, View]:
    return chat_data.setdefault("views", {})


def remember(chat_data: dict[str, Any], message_id: int, view: View) -> None:
    views = _store(chat_data)
    views[message_id] = view
    while len(views) > VIEWS_KEPT:
        views.pop(next(iter(views)))


def lookup(chat_data: dict[str, Any] | None, message_id: int) -> View | None:
    if chat_data is None:
        return None
    return _store(chat_data).get(message_id)
