"""Telegram handlers. Thin: every decision is made by the API; this file only drives the UI.

New learner flow (stateless; each step's choice travels in the button's callback data):
  /start -> "explain in which language?" -> "how much do you know?" -> starter role-play
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from telegram import (
    BotCommand,
    CallbackQuery,
    LinkPreviewOptions,
    MaybeInaccessibleMessage,
    Message,
    ReplyParameters,
    Update,
)
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PersistenceInput,
    PicklePersistence,
    filters,
)
from tutor_contracts import (
    LearnerPatch,
    LearnerProfileOut,
    LevelOut,
    ResolveUserRequest,
    SessionOut,
)

from tutor_telegram import formatting, views
from tutor_telegram import keyboards as kb
from tutor_telegram.api_client import ApiError, TutorApiClient
from tutor_telegram.config import BotSettings

log = logging.getLogger(__name__)

PROVIDER = "telegram"
HELP_KINDS = {"hint", "translate", "suggest", "explain"}

COMMANDS = [
    BotCommand("start", "Start or restart"),
    BotCommand("chat", "Free conversation"),
    BotCommand("roleplay", "Practise a real-life situation"),
    BotCommand("lessons", "Grammar lessons with practice"),
    BotCommand("review", "Practise your past mistakes"),
    BotCommand("ask", "Ask a question without interrupting the conversation"),
    BotCommand("progress", "Your progress and recent mistakes"),
    BotCommand("end", "Finish the session and see a summary"),
    BotCommand("settings", "Level, language, daily goal, reminders"),
    BotCommand("help", "How it works"),
]


# ----------------------------------------------------------------------------- plumbing


def _api(context: ContextTypes.DEFAULT_TYPE) -> TutorApiClient:
    return context.application.bot_data["api"]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> BotSettings:
    return context.application.bot_data["settings"]


def _detected_lang(update: Update) -> str | None:
    user = update.effective_user
    code = (user.language_code or "").split("-")[0].lower() if user else ""
    return code if len(code) >= 2 else None


async def _resolve(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> tuple[LearnerProfileOut, bool]:
    user = update.effective_user
    assert user is not None
    settings = _settings(context)
    res = await _api(context).resolve_user(
        ResolveUserRequest(
            provider=PROVIDER,
            external_id=str(user.id),
            display_name=user.full_name or "",
            target_lang=settings.target_lang,
            native_lang=_detected_lang(update) or settings.default_native_lang,
        )
    )
    return res.profile, res.created


async def _send(update: Update, text: str, **kwargs: object) -> Message:
    chat = update.effective_chat
    assert chat is not None
    return await chat.send_message(text, parse_mode=ParseMode.HTML, **kwargs)  # type: ignore[arg-type]


@contextlib.asynccontextmanager
async def _typing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> AsyncIterator[None]:
    """Keep "typing…" visible while the tutor thinks (Telegram clears it after ~5 s)."""
    chat = update.effective_chat

    async def keep_typing() -> None:
        while chat is not None:
            with contextlib.suppress(Exception):
                await context.bot.send_chat_action(chat_id=chat.id, action=ChatAction.TYPING)
            await asyncio.sleep(4)

    task = asyncio.create_task(keep_typing())
    try:
        yield
    finally:
        task.cancel()


async def _levels(context: ContextTypes.DEFAULT_TYPE) -> list[LevelOut]:
    return (await _api(context).language(_settings(context).target_lang)).levels


async def _show_session(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: SessionOut,
    first_time: bool = False,
) -> None:
    view = views.new_view(
        session.opening_turn_id, formatting.format_session_start(session, first_time)
    )
    await _send_view(update, context, view, reply_to=None)


# ----------------------------------------------------------------------------- onboarding


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile, created = await _resolve(update, context)
    if created:
        lang = await _api(context).language(_settings(context).target_lang)
        await _send(
            update,
            f"👋 <b>Hi!</b> I'm your {lang.name} conversation tutor.\n"
            "We'll chat, I'll gently fix your mistakes, and you'll pick up words as you go.\n\n"
            "First, <b>which language should I explain things in?</b>",
            reply_markup=kb.native_keyboard(
                _settings(context).native_choices(), _detected_lang(update), onboarding=True
            ),
        )
        return
    levels = await _levels(context)
    await _send(
        update,
        "👋 Welcome back! " + formatting.format_profile(profile, levels),
        reply_markup=kb.main_menu(),
    )
    session = await _api(context).active_session(profile.id)
    if session is not None:
        await _send(
            update,
            "You have a conversation in progress. Just reply to continue, or start something new:",
            reply_markup=kb.next_step_keyboard(),
        )
    else:
        await _send(update, "What would you like to do?", reply_markup=kb.next_step_keyboard())


async def _ask_level(update: Update, context: ContextTypes.DEFAULT_TYPE, onboarding: bool) -> None:
    lang = await _api(context).language(_settings(context).target_lang)
    await _send(
        update,
        f"<b>How much {lang.name} do you know?</b>",
        reply_markup=kb.level_keyboard(lang.levels, onboarding=onboarding),
    )


async def _after_level_chosen(
    update: Update, context: ContextTypes.DEFAULT_TYPE, profile: LearnerProfileOut
) -> None:
    """Last onboarding step: show the menu and drop the learner straight into a role-play."""
    levels = await _levels(context)
    level = next((lv for lv in levels if lv.code == profile.cefr_level), None)
    await _send(
        update,
        "🎉 You're all set! Your menu is below the text box. Let's start with a short "
        "role-play. Just answer the message below.",
        reply_markup=kb.main_menu(),
    )
    starter = level.starter_scenario if level else None
    session = await _api(context).start_session(profile.id, starter)
    await _show_session(update, context, session, first_time=True)


# ----------------------------------------------------------------------------- menu actions


async def do_free_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile, _ = await _resolve(update, context)
    await _show_session(update, context, await _api(context).start_session(profile.id))


async def do_roleplay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile, _ = await _resolve(update, context)
    scenarios = await _api(context).scenarios(profile.target_lang, level=profile.cefr_level)
    await _send(
        update,
        formatting.format_scenarios(scenarios),
        reply_markup=kb.scenario_keyboard(scenarios) if scenarios else None,
    )


async def do_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile, _ = await _resolve(update, context)
    api = _api(context)
    profile = await api.get_learner(profile.id)
    levels = await _levels(context)
    words = await api.vocab(profile.id)
    mistakes = await api.mistakes(profile.id, limit=5)
    daily = await api.progress(profile.id)
    await _send(update, formatting.format_progress(profile, levels, len(words), mistakes, daily))


async def do_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile, _ = await _resolve(update, context)
    session = await _api(context).active_session(profile.id)
    if session is None:
        await _send(
            update, "No conversation in progress. Start one:", reply_markup=kb.next_step_keyboard()
        )
        return
    summary = await _api(context).end_session(session.id)
    await _send(update, formatting.format_summary(summary), reply_markup=kb.next_step_keyboard())


async def do_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile, _ = await _resolve(update, context)
    await _send(
        update,
        formatting.format_settings(profile, await _levels(context)),
        reply_markup=kb.settings_keyboard(profile.reminders_enabled),
    )


async def do_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """From a reminder: continue the open conversation, or start a free chat."""
    profile, _ = await _resolve(update, context)
    session = await _api(context).active_session(profile.id)
    if session is None:
        await do_free_chat(update, context)
        return
    await _send(
        update,
        "Let's go! Reply to my last message to continue, or start something new:",
        reply_markup=kb.next_step_keyboard(),
    )


async def do_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(update, formatting.HOW_IT_WORKS, reply_markup=kb.main_menu())


# ----------------------------------------------------------------------------- side questions


NO_PREVIEW = LinkPreviewOptions(is_disabled=True)


async def _send_view(
    update: Update, context: ContextTypes.DEFAULT_TYPE, view: views.View, reply_to: Message | None
) -> None:
    """Send a tutor message (feedback folded) and remember it so buttons can edit it later."""
    html = views.render(view)
    markup = views.markup(view)
    if reply_to is not None:
        sent = await reply_to.reply_text(
            html, parse_mode=ParseMode.HTML, reply_markup=markup, link_preview_options=NO_PREVIEW
        )
    else:
        sent = await _send(update, html, reply_markup=markup, link_preview_options=NO_PREVIEW)
    if view["turn_id"] is not None and context.chat_data is not None:
        views.remember(context.chat_data, sent.message_id, view)


async def _redraw(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, view: views.View
) -> bool:
    """Edit a tutor message to match its view. False if it is too long or Telegram refuses."""
    if not views.fits(view):
        return False
    try:
        await context.bot.edit_message_text(
            views.render(view),
            chat_id=chat_id,
            message_id=message_id,
            parse_mode=ParseMode.HTML,
            reply_markup=views.markup(view),
            link_preview_options=NO_PREVIEW,
        )
    except TelegramError as e:
        log.info("could not edit tutor message %s: %s", message_id, e)
        return False
    return True


async def _add_inside(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, key: str, block: str
) -> bool:
    """Append a block (help answer, Q&A) inside a remembered tutor message."""
    view = views.lookup(context.chat_data, message_id)
    if view is None:
        return False
    view["extras"].append([key, block])
    if await _redraw(context, chat_id, message_id, view):
        return True
    view["extras"].pop()
    return False


async def ask_about_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    turn_id: int,
    tutor_message: MaybeInaccessibleMessage | None,
) -> None:
    """🙋 Ask under a tutor message: open a reply box tied to that message."""
    if not isinstance(tutor_message, Message):
        return
    await _send(
        update,
        formatting.ask_about_prompt(turn_id, tutor_message.message_id, context.bot.username),
        reply_markup=kb.reply_prompt("Your question about this message…"),
        reply_parameters=ReplyParameters(message_id=tutor_message.message_id),
        link_preview_options=NO_PREVIEW,
    )


async def answer_inside_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    turn_id: int,
    message_id: int,
    question: str,
    prompt: Message,
) -> None:
    """Answer, then append the Q&A inside the tutor message and tidy up the prompt and the
    question. Falls back to a reply under the tutor message if it cannot be edited."""
    msg = update.effective_message
    chat = update.effective_chat
    assert msg is not None and chat is not None
    profile, _ = await _resolve(update, context)
    async with _typing(update, context):
        answer = await _api(context).ask(profile.id, question, turn_id=turn_id)

    block = formatting.inline_answer_block(question, answer.answer)
    if await _add_inside(context, chat.id, message_id, "ask", block):
        for m in (prompt, msg):  # the Q&A now lives in the tutor message
            with contextlib.suppress(TelegramError):
                await m.delete()
        return

    with contextlib.suppress(TelegramError):
        await prompt.delete()
    await chat.send_message(
        formatting.format_answer(answer),
        parse_mode=ParseMode.HTML,
        reply_parameters=ReplyParameters(message_id=message_id, allow_sending_without_reply=True),
    )


async def answer_question(
    update: Update, context: ContextTypes.DEFAULT_TYPE, question: str
) -> None:
    """Answer outside the conversation: nothing is stored as a turn or corrected."""
    msg = update.effective_message
    assert msg is not None
    profile, _ = await _resolve(update, context)
    async with _typing(update, context):
        answer = await _api(context).ask(profile.id, question)
    await msg.reply_text(formatting.format_answer(answer), parse_mode=ParseMode.HTML)


async def do_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(update, formatting.ASK_PROMPT, reply_markup=kb.reply_prompt("Your question…"))


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args or []).strip()
    if question:
        await answer_question(update, context, question)
    else:
        await do_ask(update, context)


# ----------------------------------------------------------------------------- practise mistakes


async def do_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the next due card as a reply prompt (the reply quotes the card id)."""
    profile, _ = await _resolve(update, context)
    queue = await _api(context).next_review(profile.id)
    if queue.card is None:
        await _send(
            update, formatting.format_queue_empty(queue), reply_markup=kb.next_step_keyboard()
        )
        return
    await _send(update, formatting.format_card(queue), reply_markup=kb.reply_prompt("Your fix…"))


async def answer_card(
    update: Update, context: ContextTypes.DEFAULT_TYPE, card_id: int, answer: str
) -> None:
    msg = update.effective_message
    assert msg is not None
    async with _typing(update, context):
        result = await _api(context).answer_review(card_id, answer)
    await msg.reply_text(
        formatting.format_review_result(result),
        parse_mode=ParseMode.HTML,
        reply_markup=kb.review_next_keyboard(result.due) if result.due else kb.next_step_keyboard(),
    )


# ----------------------------------------------------------------------------- grammar lessons


async def do_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile, _ = await _resolve(update, context)
    sugg = await _api(context).lessons(profile.id)
    await _send(
        update,
        formatting.format_lesson_menu(sugg),
        reply_markup=kb.lesson_topics_keyboard(sugg.suggested, browse=True),
    )


async def do_browse_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile, _ = await _resolve(update, context)
    sugg = await _api(context).lessons(profile.id)
    await _send(
        update,
        formatting.format_level_topics(sugg.level_topics),
        reply_markup=kb.lesson_topics_keyboard(sugg.level_topics, browse=False),
    )


async def start_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE, topic_id: str) -> None:
    """Generate the lesson, show the explanation, then the first exercise as a reply prompt."""
    profile, _ = await _resolve(update, context)
    await _send(update, "📖 Preparing your lesson… (about 15 seconds)")
    async with _typing(update, context):
        lesson = await _api(context).start_lesson(profile.id, topic_id)
    await _send(update, formatting.format_lesson(lesson))
    if lesson.exercise is not None:
        await _send(
            update,
            formatting.format_exercise(lesson.id, lesson.exercise),
            reply_markup=kb.reply_prompt("Your answer…"),
        )


async def answer_exercise(
    update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int, index: int, answer: str
) -> None:
    msg = update.effective_message
    assert msg is not None
    try:
        async with _typing(update, context):
            result = await _api(context).answer_lesson(lesson_id, index, answer)
    except ApiError as e:
        if e.status_code == 409:
            await msg.reply_text("You already answered that one. Reply to the newest question.")
            return
        raise
    await msg.reply_text(
        formatting.format_lesson_answer(lesson_id, result),
        parse_mode=ParseMode.HTML,
        reply_markup=kb.reply_prompt("Your answer…")
        if result.next is not None
        else kb.lesson_done_keyboard(),
    )


MENU_ACTIONS = {
    kb.MENU_CHAT: do_free_chat,
    kb.MENU_ROLEPLAY: do_roleplay,
    kb.MENU_LESSONS: do_lessons,
    kb.MENU_REVIEW: do_review,
    kb.MENU_ASK: do_ask,
    kb.MENU_PROGRESS: do_progress,
    kb.MENU_FINISH: do_finish,
    kb.MENU_SETTINGS: do_settings,
    kb.MENU_HELP: do_help,
}


# ----------------------------------------------------------------------------- commands kept
# for power users (and the "/" menu); each maps onto the same actions as the buttons.


async def cmd_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        profile, _ = await _resolve(update, context)
        updated = await _api(context).patch_learner(
            profile.id, LearnerPatch(cefr_level=context.args[0].upper())
        )
        await _send(update, "✅ " + formatting.format_profile(updated, await _levels(context)))
        return
    await _ask_level(update, context, onboarding=False)


async def cmd_native(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await _send(
            update,
            "<b>Which language should I explain things in?</b>",
            reply_markup=kb.native_keyboard(
                _settings(context).native_choices(), _detected_lang(update), onboarding=False
            ),
        )
        return
    profile, _ = await _resolve(update, context)
    updated = await _api(context).patch_learner(
        profile.id, LearnerPatch(native_lang=context.args[0].lower())
    )
    await _send(update, "✅ " + formatting.format_profile(updated, await _levels(context)))


async def cmd_play(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await do_roleplay(update, context)
        return
    profile, _ = await _resolve(update, context)
    await _show_session(
        update, context, await _api(context).start_session(profile.id, context.args[0])
    )


async def cmd_mistakes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await do_progress(update, context)


# ----------------------------------------------------------------------------- callbacks


async def _ack(query: CallbackQuery, text: str | None = None, alert: bool = False) -> None:
    """Stop the button's spinner. Taps queued while the bot was down are too old to
    acknowledge; Telegram rejects those, but the tap itself is still handled."""
    try:
        await query.answer(text, show_alert=alert)
    except BadRequest as e:
        log.debug("could not answer callback query: %s", e)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None and query.data is not None
    kind, _, rest = query.data.partition(":")

    if kind == "h":  # help on a tutor message
        help_kind, _, turn_id = rest.partition(":")
        if help_kind not in HELP_KINDS or not turn_id.isdigit():
            await _ack(query)
            return
        message = query.message
        assert message is not None
        view = views.lookup(context.chat_data, message.message_id)
        if view is not None and views.has_extra(view, help_kind):
            await _ack(query, "Already shown in the message ↑")
            return
        await _ack(query, "One moment…")
        async with _typing(update, context):
            help_ = await _api(context).help(int(turn_id), help_kind)  # type: ignore[arg-type]
        block = formatting.help_block(help_.kind, help_.text)
        if not await _add_inside(context, message.chat.id, message.message_id, help_kind, block):
            # Not foldable (older message, or too long): send it on its own.
            await _send(
                update,
                formatting.format_help(help_),
                reply_parameters=ReplyParameters(
                    message_id=message.message_id, allow_sending_without_reply=True
                ),
            )
        return

    if kind == "fb":  # fold / unfold the feedback of a tutor message
        message = query.message
        assert message is not None
        view = views.lookup(context.chat_data, message.message_id)
        if view is None:
            await _ack(query, "This older message can't be folded. New ones can.", alert=True)
            return
        view["expanded"] = not view["expanded"]
        if not await _redraw(context, message.chat.id, message.message_id, view):
            view["expanded"] = not view["expanded"]
            await _ack(query, "Sorry, I couldn't update that message.", alert=True)
            return
        await _ack(query)
        return

    await _ack(query)
    if kind == "nat":
        code, _, flag = rest.partition(":")
        profile, _ = await _resolve(update, context)
        await _api(context).patch_learner(profile.id, LearnerPatch(native_lang=code))
        with contextlib.suppress(Exception):
            await query.edit_message_reply_markup(None)
        if flag == "o":
            await _ask_level(update, context, onboarding=True)
        else:
            await _send(update, "✅ Explanations will be in that language from now on.")
    elif kind == "lvl":
        code, _, flag = rest.partition(":")
        profile, _ = await _resolve(update, context)
        updated = await _api(context).patch_learner(profile.id, LearnerPatch(cefr_level=code))
        with contextlib.suppress(Exception):
            await query.edit_message_reply_markup(None)
        if flag == "o":
            await _after_level_chosen(update, context, updated)
        else:
            await _send(
                update,
                "✅ " + formatting.format_profile(updated, await _levels(context)),
                reply_markup=kb.next_step_keyboard(),
            )
    elif kind == "play":
        profile, _ = await _resolve(update, context)
        await _show_session(update, context, await _api(context).start_session(profile.id, rest))
    elif kind == "goal" and rest.isdigit():
        profile, _ = await _resolve(update, context)
        updated = await _api(context).patch_learner(profile.id, LearnerPatch(daily_goal=int(rest)))
        with contextlib.suppress(Exception):
            await query.edit_message_reply_markup(None)
        await _send(update, f"🎯 Daily goal set to <b>{updated.daily_goal} messages</b>.")
    elif kind == "ask" and rest.isdigit():
        await ask_about_message(update, context, int(rest), query.message)
    elif kind == "ls" and rest:
        with contextlib.suppress(Exception):
            await query.edit_message_reply_markup(None)
        await start_lesson(update, context, rest)
    elif kind == "lb":
        await do_browse_lessons(update, context)
    elif kind == "rv":
        with contextlib.suppress(Exception):
            await query.edit_message_reply_markup(None)
        if rest == "next":
            await do_review(update, context)
        else:
            await _send(update, "👍 Nice work. What next?", reply_markup=kb.next_step_keyboard())
    elif kind == "rem" and rest in ("on", "off"):
        profile, _ = await _resolve(update, context)
        await _api(context).patch_learner(profile.id, LearnerPatch(reminders_enabled=rest == "on"))
        with contextlib.suppress(Exception):
            await query.edit_message_reply_markup(None)
        await _send(
            update,
            "🔔 Reminders on. I'll nudge you in the evening if you haven't practised."
            if rest == "on"
            else "🔕 Reminders off. Turn them back on any time in ⚙️ Settings.",
        )
    elif kind == "menu":
        if rest == "free":
            await do_free_chat(update, context)
        elif rest == "roleplay":
            await do_roleplay(update, context)
        elif rest == "review":
            await do_review(update, context)
        elif rest == "lessons":
            await do_lessons(update, context)
        elif rest == "resume":
            await do_resume(update, context)
        elif rest == "settings_goal":
            profile, _ = await _resolve(update, context)
            await _send(
                update,
                "<b>How many messages a day?</b> Each message you send counts.",
                reply_markup=kb.goal_keyboard(profile.daily_goal),
            )
        elif rest == "settings_level":
            await _ask_level(update, context, onboarding=False)
        elif rest == "settings_native":
            await cmd_native(update, context)


# ----------------------------------------------------------------------------- free text


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or not msg.text:
        return
    text = msg.text.strip()
    action = MENU_ACTIONS.get(text)
    if action is not None:
        await action(update, context)
        return

    # A reply to one of the bot's prompts (practice card or "ask me anything").
    replied = msg.reply_to_message
    if replied is not None and replied.from_user is not None and replied.from_user.is_bot:
        link_urls = [e.url for e in replied.entities or [] if e.url]
        if (target := formatting.parse_ask_link(link_urls)) is not None:
            await answer_inside_message(update, context, *target, text, prompt=replied)
            return
        if (exercise := formatting.parse_exercise(replied.text)) is not None:
            await answer_exercise(update, context, *exercise, text)
            return
        card_id = formatting.parse_card_id(replied.text)
        if card_id is not None:
            await answer_card(update, context, card_id, text)
            return
        if (replied.text or "").startswith(kb.ASK_PROMPT_HEADER):
            await answer_question(update, context, text)
            return

    # "?..." is a side question. Spanish questions start with "¿", so they stay in the chat.
    if text.startswith("?") and len(text) > 1:
        await answer_question(update, context, text[1:].strip())
        return

    profile, _ = await _resolve(update, context)
    api = _api(context)
    session = await api.active_session(profile.id)
    if session is None:
        session = await api.start_session(profile.id)
    async with _typing(update, context):
        result = await api.send_turn(session.id, msg.text)
    await _send_view(update, context, views.from_turn(result), reply_to=msg)


MAX_VOICE_SECONDS = 120  # keep in step with the API's STT_MAX_SECONDS
MAX_VOICE_BYTES = 20 * 1024 * 1024  # Telegram bots can download up to 20 MB


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A spoken message: the API transcribes it and answers it like a typed one."""
    msg = update.effective_message
    if msg is None:
        return
    media = msg.voice or msg.audio
    if media is None:
        return
    if (media.duration or 0) > MAX_VOICE_SECONDS:
        await msg.reply_text(
            f"🎤 That's a bit long! Please keep voice messages under {MAX_VOICE_SECONDS // 60} "
            "minutes."
        )
        return
    if (media.file_size or 0) > MAX_VOICE_BYTES:
        await msg.reply_text("🎤 That file is too big for me. Try a shorter message.")
        return

    profile, _ = await _resolve(update, context)
    api = _api(context)
    session = await api.active_session(profile.id)
    if session is None:
        session = await api.start_session(profile.id)
    async with _typing(update, context):
        file = await media.get_file()
        audio = bytes(await file.download_as_bytearray())
        result = await api.send_voice_turn(
            session.id, audio, "voice.ogg", media.mime_type or "audio/ogg"
        )
    await _send_view(update, context, views.from_turn(result), reply_to=msg)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    log.error("handler error: %s", err, exc_info=err)
    if not isinstance(update, Update) or update.effective_chat is None:
        return
    if isinstance(err, ApiError) and err.status_code == 409:
        text = "That conversation has ended. Tap 💬 Free chat or 🎭 Role-play to start a new one."
    elif isinstance(err, ApiError) and err.status_code < 500:
        text = f"⚠️ {err.detail}"
    else:
        text = "⚠️ Sorry, something went wrong on my side. Please try again in a moment."
    await update.effective_chat.send_message(text)


# ----------------------------------------------------------------------------- app


async def send_due_reminders(app: Application) -> int:
    """Ask the API who is due a reminder and message them. Returns how many were sent."""
    api: TutorApiClient = app.bot_data["api"]
    settings: BotSettings = app.bot_data["settings"]
    sent = 0
    for r in await api.claim_reminders(PROVIDER, settings.target_lang):
        try:
            await app.bot.send_message(
                chat_id=int(r.external_id),
                text=formatting.format_reminder_with_reviews(r),
                parse_mode=ParseMode.HTML,
                reply_markup=kb.reminder_keyboard(r.reviews_due),
            )
            sent += 1
        except Forbidden:
            # The learner blocked the bot: stop reminding them.
            log.info("reminder: chat %s blocked the bot; disabling reminders", r.external_id)
            await api.patch_learner(r.profile_id, LearnerPatch(reminders_enabled=False))
        except TelegramError as e:
            log.warning("reminder to %s failed: %s", r.external_id, e)
    return sent


async def _reminder_loop(app: Application) -> None:
    settings: BotSettings = app.bot_data["settings"]
    while True:
        try:
            if sent := await send_due_reminders(app):
                log.info("sent %d practice reminder(s)", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("reminder check failed; will retry")
        await asyncio.sleep(settings.reminder_poll_seconds)


def build_application(settings: BotSettings) -> Application:
    async def post_init(app: Application) -> None:
        assert settings.api_key is not None
        app.bot_data["settings"] = settings
        app.bot_data["api"] = TutorApiClient(
            settings.api_base_url, settings.api_key, settings.request_timeout_seconds
        )
        await app.bot.set_my_commands(COMMANDS)
        app.bot_data["reminders"] = asyncio.create_task(_reminder_loop(app))

    async def post_shutdown(app: Application) -> None:
        task: asyncio.Task[None] | None = app.bot_data.get("reminders")
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        api: TutorApiClient | None = app.bot_data.get("api")
        if api is not None:
            await api.aclose()

    app = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        .persistence(
            PicklePersistence(
                filepath=settings.state_file,
                store_data=PersistenceInput(
                    bot_data=False, user_data=False, chat_data=True, callback_data=False
                ),
                update_interval=10,
            )
        )
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .concurrent_updates(True)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", do_help))
    app.add_handler(CommandHandler("chat", do_free_chat))
    app.add_handler(CommandHandler(["roleplay", "scenarios"], do_roleplay))
    app.add_handler(CommandHandler("play", cmd_play))
    app.add_handler(CommandHandler(["progress", "mistakes"], cmd_mistakes))
    app.add_handler(CommandHandler("end", do_finish))
    app.add_handler(CommandHandler("settings", do_settings))
    app.add_handler(CommandHandler("level", cmd_level))
    app.add_handler(CommandHandler("native", cmd_native))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler(["lessons", "lesson", "grammar"], do_lessons))
    app.add_handler(CommandHandler(["review", "practise", "practice"], do_review))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_error_handler(on_error)
    return app
