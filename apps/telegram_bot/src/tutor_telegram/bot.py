"""Telegram handlers. Thin: every decision is made by the API; this file only drives the UI.

New learner flow (stateless; each step's choice travels in the button's callback data):
  /start -> "explain in which language?" -> "how much do you know?" -> starter role-play
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from datetime import date

from telegram import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardMarkup,
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
    TypeHandler,
    filters,
)
from tutor_contracts import (
    LanguageOut,
    LearnerPatch,
    LearnerProfileOut,
    LevelOut,
    PlacementStepOut,
    ResolveUserRequest,
    ReviewQueueOut,
    SessionOut,
    WordCardOut,
    WordQueueOut,
)

from tutor_telegram import formatting, tidy, views
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
    BotCommand("words", "Word flashcards from our chats"),
    BotCommand("save", "Save words as flashcards: /save palabra"),
    BotCommand("week", "Your week in numbers"),
    BotCommand("history", "Read the conversations of past days"),
    BotCommand("placement", "Quick test to find your level"),
    BotCommand("ask", "Ask a question without interrupting the conversation"),
    BotCommand("progress", "Your progress and recent mistakes"),
    BotCommand("end", "Finish the session and see a summary"),
    BotCommand("language", "Switch language (Spanish, Chinese, Japanese)"),
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


def _lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    """The language this chat is learning: picked in onboarding or settings, else the default.
    Everything learned (level, mistakes, streak) lives per language in the API."""
    settings = _settings(context)
    chosen = (context.chat_data or {}).get("lang")
    return chosen if chosen in settings.languages() else settings.target_lang


def _has_chosen_lang(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool((context.chat_data or {}).get("lang")) or len(_settings(context).languages()) < 2


async def _languages(context: ContextTypes.DEFAULT_TYPE) -> list[LanguageOut]:
    """Offered languages with names and flags (fetched once, then cached)."""
    cached = context.application.bot_data.get("languages")
    if cached is None:
        api = _api(context)
        cached = [await api.language(code) for code in _settings(context).languages()]
        context.application.bot_data["languages"] = cached
    return cached


async def _lang_info(context: ContextTypes.DEFAULT_TYPE, code: str | None = None) -> LanguageOut:
    code = code or _lang(context)
    for lang in await _languages(context):
        if lang.code == code:
            return lang
    return await _api(context).language(code)


async def _resolve(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    native_lang: str | None = None,
    target_lang: str | None = None,
) -> tuple[LearnerProfileOut, bool]:
    user = update.effective_user
    assert user is not None
    settings = _settings(context)
    res = await _api(context).resolve_user(
        ResolveUserRequest(
            provider=PROVIDER,
            external_id=str(user.id),
            display_name=user.full_name or "",
            target_lang=target_lang or _lang(context),
            native_lang=native_lang or _detected_lang(update) or settings.default_native_lang,
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
    return (await _lang_info(context)).levels


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
    if not _has_chosen_lang(context):
        await _send(
            update,
            "👋 <b>Hi!</b> I'm your language conversation tutor.\n"
            "We'll chat, I'll gently fix your mistakes, and you'll pick up words as you go.\n\n"
            "First, <b>which language do you want to learn?</b>",
            reply_markup=kb.language_keyboard(await _languages(context), None, onboarding=True),
        )
        return
    await _start_in_language(update, context)


async def _start_in_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Onboarding for a new profile in the current language, or "welcome back"."""
    profile, created = await _resolve(update, context)
    lang = await _lang_info(context)
    if created:
        await _send(
            update,
            f"{lang.flag} Great, let's learn <b>{lang.name}</b>!\n\n"
            "<b>Which language should I explain things in?</b>",
            reply_markup=kb.native_keyboard(
                _settings(context).native_choices(), _detected_lang(update), onboarding=True
            ),
        )
        return
    await _send(
        update,
        f"👋 Welcome back! {lang.flag} <b>{lang.name}</b> · "
        + formatting.format_profile(profile, lang.levels),
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
    lang = await _lang_info(context)
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
    lang = await _lang_info(context)
    multi = len(_settings(context).languages()) > 1
    await _send(
        update,
        f"{lang.flag} <b>{lang.name}</b>\n" + formatting.format_settings(profile, lang.levels),
        reply_markup=kb.settings_keyboard(
            profile.reminders_enabled,
            f"{lang.flag} {lang.name}" if multi else None,
            voice=_voice_on(context),
            tidy_chat=profile.tidy_chat,
        ),
    )


async def do_choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(
        update,
        "🌍 <b>Which language do you want to practise?</b>\n"
        "<i>Each language keeps its own level, progress and streak.</i>",
        reply_markup=kb.language_keyboard(
            await _languages(context), _lang(context), onboarding=False
        ),
    )


async def switch_language(
    update: Update, context: ContextTypes.DEFAULT_TYPE, code: str, onboarding: bool
) -> None:
    """Make `code` this chat's language. A new language gets a level question and a starter
    role-play (the explanation language carries over); a known one just continues."""
    if code not in _settings(context).languages():
        return
    assert context.chat_data is not None
    native = None
    if not onboarding and context.chat_data.get("lang"):
        current, _ = await _resolve(update, context)
        native = current.native_lang
    context.chat_data["lang"] = code
    if onboarding:
        await _start_in_language(update, context)
        return
    profile, created = await _resolve(update, context, native_lang=native)
    lang = await _lang_info(context, code)
    if created:
        await _send(update, f"{lang.flag} Great, let's learn <b>{lang.name}</b>!")
        await _ask_level(update, context, onboarding=True)
        return
    await _send(
        update,
        f"✅ Switched to {lang.flag} <b>{lang.name}</b> · "
        + formatting.format_profile(profile, lang.levels),
        reply_markup=kb.main_menu(),
    )
    await _send(update, "What would you like to do?", reply_markup=kb.next_step_keyboard())


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
    if _tally(context, result.correct, result.progress.streak):
        await msg.reply_text(formatting.format_review_result(result), parse_mode=ParseMode.HTML)
        await next_in_round(update, context)
        return
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


async def start_lesson(
    update: Update, context: ContextTypes.DEFAULT_TYPE, topic_id: str, fresh: bool = False
) -> None:
    """Generate the lesson, show the explanation, then the first exercise as a reply prompt."""
    profile, _ = await _resolve(update, context)
    waiting = await _send(update, "📖 <i>Preparing your lesson…</i>")
    async with _typing(update, context):
        lesson = await _api(context).start_lesson(profile.id, topic_id, fresh=fresh)
    html = formatting.format_lesson(lesson)
    markup = kb.lesson_fresh_keyboard(topic_id) if lesson.reused else None
    try:  # the lesson replaces the "preparing" note
        await waiting.edit_text(html, parse_mode=ParseMode.HTML, reply_markup=markup)
    except TelegramError:
        await _send(update, html, reply_markup=markup)
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


# ----------------------------------------------------------------------------- voice replies


def _voice_on(context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(context.chat_data and context.chat_data.get("voice"))


async def send_speech(update: Update, audio: bytes, mime: str, reply_to: int) -> None:
    chat = update.effective_chat
    assert chat is not None
    params = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)
    if mime == "audio/ogg":
        await chat.send_voice(audio, reply_parameters=params)
    else:
        await chat.send_audio(audio, filename="reply.mp3", reply_parameters=params)


async def speak_turn(
    update: Update, context: ContextTypes.DEFAULT_TYPE, turn_id: int, reply_to: int
) -> None:
    chat = update.effective_chat
    assert chat is not None
    await chat.send_chat_action(ChatAction.RECORD_VOICE)
    audio, mime = await _api(context).turn_speech(turn_id)
    await send_speech(update, audio, mime, reply_to)


# ----------------------------------------------------------------------------- word cards


async def do_words(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile, _ = await _resolve(update, context)
    queue = await _api(context).next_word(profile.id)
    if queue.card is None:
        await _send(
            update, formatting.format_words_empty(queue), reply_markup=kb.next_step_keyboard()
        )
        return
    if context.chat_data is not None:  # the back of the card, shown on "Show meaning"
        context.chat_data.setdefault("word_cards", {})[queue.card.id] = queue.card.model_dump()
    await _send(
        update,
        formatting.format_word_front(queue),
        reply_markup=kb.word_front_keyboard(queue.card.id),
    )


async def on_word_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE, action: str, word_id: int
) -> None:
    query = update.callback_query
    assert query is not None and query.message is not None
    if action == "say":
        await _ack(query)
        audio, mime = await _api(context).word_speech(word_id)
        await send_speech(update, audio, mime, query.message.message_id)
        return
    cards: dict[int, dict] = (context.chat_data or {}).get("word_cards", {})
    raw = cards.get(word_id)
    if raw is None:
        await _ack(query, "This card has expired. Here's the next one.")
        await do_words(update, context)
        return
    card = WordCardOut.model_validate(raw)
    await _ack(query)
    if action == "show":
        with contextlib.suppress(TelegramError):
            await query.edit_message_text(
                formatting.format_word_back(card),
                parse_mode=ParseMode.HTML,
                reply_markup=kb.word_back_keyboard(word_id),
            )
        return
    result = await _api(context).answer_word(word_id, knew=action == "y")
    cards.pop(word_id, None)
    with contextlib.suppress(TelegramError):
        await query.edit_message_text(
            formatting.format_word_result(card.word, result), parse_mode=ParseMode.HTML
        )
    if _tally(context, result.knew, result.progress.streak):
        await next_in_round(update, context)
    elif result.due:
        await do_words(update, context)
    else:
        await _send(update, "🎉 All words done for now!", reply_markup=kb.next_step_keyboard())


# ----------------------------------------------------------------------------- placement test


async def do_placement(
    update: Update, context: ContextTypes.DEFAULT_TYPE, onboarding: bool = False
) -> None:
    profile, _ = await _resolve(update, context)
    step = await _api(context).start_placement(profile.id)
    if context.chat_data is not None:
        context.chat_data["pl_onboarding"] = onboarding
    await _send(
        update,
        "🧭 <b>Quick level test</b>\nAbout 2 minutes, multiple choice. It gets harder as you "
        "go and stops when it gets too hard, so don't worry about wrong answers.",
    )
    await _show_placement_step(update, context, step)


async def _show_placement_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE, step: PlacementStepOut, edit: bool = False
) -> None:
    query = update.callback_query
    if step.question is not None:
        text = formatting.format_placement_question(step)
        markup = kb.placement_keyboard(step.run_id, step.question.id, step.question.options)
    else:
        assert step.result is not None
        r = step.result
        text = formatting.format_placement_result(step)
        onboarding = bool((context.chat_data or {}).get("pl_onboarding"))
        markup = kb.placement_result_keyboard(r.level, r.current_level, r.label, onboarding)
    if edit and query is not None:
        try:
            await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return
        except TelegramError as e:
            log.info("could not edit placement message: %s", e)
    await _send(update, text, reply_markup=markup)


async def on_placement_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE, rest: str
) -> None:
    query = update.callback_query
    assert query is not None
    if rest.startswith("start"):
        await _ack(query)
        await do_placement(update, context, onboarding=rest.endswith(":o"))
        return
    if rest == "keep":
        await _ack(query, "Keeping your level 👍")
        with contextlib.suppress(TelegramError):
            await query.edit_message_reply_markup(None)
        await _send(update, "👍 Level unchanged. What next?", reply_markup=kb.next_step_keyboard())
        return
    if rest == "pick":
        await _ack(query)
        await _ask_level(update, context, onboarding=True)
        return
    run_id, _, tail = rest.partition(":")
    choice, _, question_id = tail.partition(":")
    if not (run_id.isdigit() and choice.isdigit() and question_id):
        await _ack(query)
        return
    try:
        step = await _api(context).answer_placement(int(run_id), question_id, int(choice))
    except ApiError as e:
        if e.status_code in (400, 409):
            await _ack(query, "Already answered ✔")
            return
        raise
    await _ack(query)
    await _show_placement_step(update, context, step, edit=True)


# ----------------------------------------------------------------------------- practice rounds

ROUND_SIZE = 10  # items per "Practise now" round


def _round(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    return (context.chat_data or {}).get("round")


async def do_practice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🧠 Practice: what's due, and a button to practise both kinds together."""
    profile, _ = await _resolve(update, context)
    item = await _api(context).practice_next(profile.id)
    await _send(
        update,
        formatting.format_practice_menu(item),
        reply_markup=kb.practice_keyboard(item.mistakes_due, item.words_due),
    )


async def start_round(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.chat_data is not None:
        context.chat_data["round"] = {"done": 0, "right": 0, "streak": None}
    await next_in_round(update, context)


async def next_in_round(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rnd = _round(context)
    if rnd is None:
        return
    profile, _ = await _resolve(update, context)
    item = None if rnd["done"] >= ROUND_SIZE else await _api(context).practice_next(profile.id)
    if item is None or item.kind is None:
        assert context.chat_data is not None
        context.chat_data.pop("round", None)
        await _send(
            update,
            formatting.format_round_summary(rnd["done"], rnd["right"], rnd["streak"]),
            reply_markup=kb.next_step_keyboard(),
        )
        return
    step = f"\n\n<i>Round {rnd['done'] + 1}/{ROUND_SIZE}</i>"
    if item.kind == "mistake":
        assert item.mistake is not None
        queue = ReviewQueueOut(
            card=item.mistake, due=item.mistakes_due, total=item.mistakes_due, next_due_at=None
        )
        await _send(
            update, formatting.format_card(queue) + step, reply_markup=kb.reply_prompt("Your fix…")
        )
    else:
        assert item.word is not None and context.chat_data is not None
        context.chat_data.setdefault("word_cards", {})[item.word.id] = item.word.model_dump()
        queue_w = WordQueueOut(card=item.word, due=item.words_due, total=item.words_due)
        await _send(
            update,
            formatting.format_word_front(queue_w) + step,
            reply_markup=kb.word_front_keyboard(item.word.id),
        )


def _tally(context: ContextTypes.DEFAULT_TYPE, right: bool, streak: int) -> bool:
    """Count an answer in the current round. False if no round is running."""
    rnd = _round(context)
    if rnd is None:
        return False
    rnd["done"] += 1
    rnd["right"] += int(right)
    rnd["streak"] = streak
    return True


# ----------------------------------------------------------------------------- save words


async def ask_save_words(
    update: Update, turn_id: int, tutor_message: MaybeInaccessibleMessage | None
) -> None:
    params = (
        ReplyParameters(message_id=tutor_message.message_id, allow_sending_without_reply=True)
        if isinstance(tutor_message, Message)
        else None
    )
    await _send(
        update,
        formatting.save_words_prompt(turn_id),
        reply_markup=kb.reply_prompt("e.g. perro, bonito"),
        reply_parameters=params,
    )


async def save_words(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, turn_id: int | None
) -> None:
    msg = update.effective_message
    assert msg is not None
    profile, _ = await _resolve(update, context)
    async with _typing(update, context):
        out = await _api(context).save_words(profile.id, text, turn_id)
    await msg.reply_text(formatting.format_saved_words(out), parse_mode=ParseMode.HTML)


async def cmd_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args or []).strip()
    if text:
        await save_words(update, context, text, None)
    else:
        await _send(update, "Usage: <code>/save palabra, otra palabra</code>")


async def do_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send(update, "☰ <b>More</b>", reply_markup=kb.more_keyboard())


# ----------------------------------------------------------------------------- weekly summary


async def do_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile, _ = await _resolve(update, context)
    w = await _api(context).weekly(profile.id)
    lesson = w.suggested_lesson.id if w.suggested_lesson else None
    await _send(
        update,
        formatting.format_weekly(w),
        reply_markup=kb.weekly_keyboard(lesson, w.reviews_due, w.words_due),
    )


# ----------------------------------------------------------------------------- past days


async def _lang_tag(context: ContextTypes.DEFAULT_TYPE, code: str) -> str:
    """Flag and name of the language, shown only when the bot offers several."""
    if len(_settings(context).languages()) < 2:
        return ""
    lang = await _lang_info(context, code)
    return f"{lang.flag} {lang.name}"


async def _edit_or_send(update: Update, text: str, markup: InlineKeyboardMarkup | None) -> None:
    """Show `text` in the tapped message (past days open in place), else as a new message."""
    query = update.callback_query
    if query is not None:
        try:
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
                link_preview_options=NO_PREVIEW,
            )
            return
        except BadRequest as e:
            if "not modified" in str(e):
                return
            log.info("could not edit day message: %s", e)
    await _send(update, text, reply_markup=markup, link_preview_options=NO_PREVIEW)


async def do_history(
    update: Update, context: ContextTypes.DEFAULT_TYPE, code: str | None = None
) -> None:
    code = code if code in _settings(context).languages() else _lang(context)
    profile, _ = await _resolve(update, context, target_lang=code)
    days = (await _api(context).days(profile.id, limit=14)).days
    await _edit_or_send(
        update,
        formatting.format_day_list(days, await _lang_tag(context, code)),
        kb.day_list_keyboard(code, [d.day for d in days], [d.messages for d in days])
        if days
        else None,
    )


async def show_day(
    update: Update, context: ContextTypes.DEFAULT_TYPE, code: str, day: date, page: int
) -> None:
    """A past day in place: page 0 is its card, 1.. are pages of its conversation."""
    if code not in _settings(context).languages():
        return
    profile, _ = await _resolve(update, context, target_lang=code)
    t = await _api(context).day(profile.id, day)
    tag = await _lang_tag(context, code)
    if page == 0:
        text = formatting.format_day_card(t.day, tag)
        await _edit_or_send(update, text, kb.day_card_keyboard(code, day))
        return
    total = len(formatting.day_pages(t))
    page = min(page, total)
    await _edit_or_send(
        update,
        formatting.format_day_page(t, page, total, tag),
        kb.day_page_keyboard(code, day, page, total),
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
    kb.MENU_WORDS: do_words,
    kb.MENU_CHAT_SHORT: do_free_chat,
    kb.MENU_PRACTICE: do_practice,
    kb.MENU_LESSONS_SHORT: do_lessons,
    kb.MENU_MORE: do_more,
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

    if kind == "sp" and rest.isdigit():  # read a tutor message aloud
        await _ack(query, "🔊 One moment…")
        assert query.message is not None
        await speak_turn(update, context, int(rest), query.message.message_id)
        return

    if kind == "wd":  # word flashcards
        action, _, word_id = rest.partition(":")
        if action == "next":
            await _ack(query)
            with contextlib.suppress(TelegramError):
                await query.edit_message_reply_markup(None)
            await do_words(update, context)
        elif action in ("show", "y", "n", "say") and word_id.isdigit():
            await on_word_button(update, context, action, int(word_id))
        else:
            await _ack(query)
        return

    if kind == "pr":  # mixed practice round
        await _ack(query)
        with contextlib.suppress(TelegramError):
            await query.edit_message_reply_markup(None)
        await start_round(update, context)
        return

    if kind == "sw" and rest.isdigit():  # save words from a tutor message
        await _ack(query)
        await ask_save_words(update, int(rest), query.message)
        return

    if kind == "pl":  # placement test
        await on_placement_button(update, context, rest)
        return

    if kind == "tl":  # choose the language to learn
        await _ack(query)
        code, _, flag = rest.partition(":")
        with contextlib.suppress(Exception):
            await query.edit_message_reply_markup(None)
        await switch_language(update, context, code, onboarding=flag == "o")
        return

    if kind == "go":  # from a reminder: switch to that language, then resume / review
        await _ack(query)
        code, _, action = rest.partition(":")
        if code in _settings(context).languages() and context.chat_data is not None:
            context.chat_data["lang"] = code
        await (do_review if action == "review" else do_resume)(update, context)
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
    elif kind == "lf" and rest:
        with contextlib.suppress(Exception):
            await query.edit_message_reply_markup(None)
        await start_lesson(update, context, rest, fresh=True)
    elif kind == "av" and rest in ("on", "off") and context.chat_data is not None:
        context.chat_data["voice"] = rest == "on"
        with contextlib.suppress(Exception):
            await query.edit_message_reply_markup(None)
        await _send(
            update,
            "🔊 Voice replies on: I'll read every reply aloud. (Tap 🔊 under any message too.)"
            if rest == "on"
            else "🔇 Voice replies off. You can still tap 🔊 under any message.",
        )
    elif kind == "lb":
        await do_browse_lessons(update, context)
    elif kind == "rv":
        with contextlib.suppress(Exception):
            await query.edit_message_reply_markup(None)
        if rest == "next":
            await do_review(update, context)
        else:
            if context.chat_data is not None:
                context.chat_data.pop("round", None)
            await _send(update, "👍 Nice work. What next?", reply_markup=kb.next_step_keyboard())
    elif kind == "tidy" and rest in ("on", "off"):
        profile, _ = await _resolve(update, context)
        await _api(context).patch_learner(profile.id, LearnerPatch(tidy_chat=rest == "on"))
        with contextlib.suppress(Exception):
            await query.edit_message_reply_markup(None)
        await _send(
            update,
            "🧹 Daily tidy on. Every night I'll replace the day's messages with a short "
            "📅 card. Tap 📖 on a card to read that day again."
            if rest == "on"
            else "🧹 Daily tidy off. I won't delete any messages. "
            "Past days are still in 📅 Past days (/history).",
        )
    elif kind == "dy":
        await _ack(query)
        parsed = kb.parse_day(rest)
        if parsed is not None:
            await show_day(update, context, *parsed)
    elif kind == "dl":
        await _ack(query)
        await do_history(update, context, rest or None)
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
        elif rest == "settings_lang":
            await do_choose_language(update, context)
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
        else:
            more = {
                "progress": do_progress,
                "week": do_week,
                "ask": do_ask,
                "finish": do_finish,
                "settings": do_settings,
                "help": do_help,
                "practice": do_practice,
            }.get(rest)
            if more is not None:
                await more(update, context)


# ----------------------------------------------------------------------------- free text


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if msg is None or not msg.text:
        return
    text = msg.text.strip()
    action = MENU_ACTIONS.get(text)
    if action is not None:
        await action(update, context)
        if text in kb.LEGACY_MENU_LABELS:  # an old menu on the phone: send the new one
            await _send(
                update,
                "✨ The menu got simpler: ☰ More has the rest.",
                reply_markup=kb.main_menu(),
            )
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
        if (save_turn := formatting.parse_save_turn(replied.text)) is not None:
            await save_words(update, context, text, save_turn)
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
    if _voice_on(context):
        await speak_turn(update, context, result.turn_id, msg.message_id)


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
    if _voice_on(context):
        await speak_turn(update, context, result.turn_id, msg.message_id)


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
    due = [
        (await api.language(code), r)
        for code in settings.languages()
        for r in await api.claim_reminders(PROVIDER, code)
    ]
    for lang, r in due:
        try:
            await app.bot.send_message(
                chat_id=int(r.external_id),
                text=f"{lang.flag} <b>{lang.name}</b>\n"
                + formatting.format_reminder_with_reviews(r),
                parse_mode=ParseMode.HTML,
                reply_markup=kb.reminder_keyboard(r.reviews_due, lang.code),
            )
            sent += 1
        except Forbidden:
            # The learner blocked the bot: stop reminding them.
            log.info("reminder: chat %s blocked the bot; disabling reminders", r.external_id)
            await api.patch_learner(r.profile_id, LearnerPatch(reminders_enabled=False))
        except TelegramError as e:
            log.warning("reminder to %s failed: %s", r.external_id, e)
    for code in settings.languages():
        lang = await api.language(code)
        for w in await api.claim_weekly(PROVIDER, code):
            if w.external_id is None:
                continue
            lesson = w.suggested_lesson.id if w.suggested_lesson else None
            try:
                await app.bot.send_message(
                    chat_id=int(w.external_id),
                    text=f"{lang.flag} <b>{lang.name}</b>\n" + formatting.format_weekly(w),
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb.weekly_keyboard(lesson, w.reviews_due, w.words_due, lang.code),
                )
                sent += 1
            except TelegramError as e:
                log.warning("weekly summary to %s failed: %s", w.external_id, e)
    return sent


async def track_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remember the learner's messages so the nightly tidy can delete them (runs first)."""
    msg = update.message
    if msg is None or msg.chat.type != "private" or context.chat_data is None:
        return
    tidy.track(context.chat_data, msg.message_id, msg.date.timestamp(), _lang(context))


def _record_sent(app: Application, msg: Message, menu: bool) -> None:
    """Remember a message the bot sent (TrackingBot calls this for every new message)."""
    if msg.chat.type != "private":
        return
    settings: BotSettings = app.bot_data["settings"]
    data = app.chat_data[msg.chat.id]  # created on first use
    lang = data.get("lang")
    tidy.track(
        data,
        msg.message_id,
        msg.date.timestamp(),
        lang if lang in settings.languages() else settings.target_lang,
        menu=menu,
    )
    app.mark_data_for_update_persistence(chat_ids=msg.chat.id)


async def _delete(app: Application, chat_id: int, ids: list[int]) -> None:
    for batch in tidy.batches(ids):
        try:
            await app.bot.delete_messages(chat_id, batch)
        except Forbidden:
            raise
        except TelegramError as e:
            log.info("tidy: batch delete in %s failed (%s); deleting one by one", chat_id, e)
            for message_id in batch:
                with contextlib.suppress(TelegramError):
                    await app.bot.delete_message(chat_id, message_id)


async def run_due_tidies(app: Application) -> int:
    """Nightly tidy: delete each due chat's messages from before today and leave one card
    per day practised. Returns how many chats were tidied."""
    api: TutorApiClient = app.bot_data["api"]
    settings: BotSettings = app.bot_data["settings"]
    multi = len(settings.languages()) > 1
    tidied = 0
    for code in settings.languages():
        due = await api.claim_tidy(PROVIDER, code)
        if not due:
            continue
        lang = await api.language(code)
        tag = f"{lang.flag} {lang.name}" if multi else ""
        for t in due:
            chat_id = int(t.external_id)
            data = app.chat_data[chat_id]
            ids = tidy.take_deletable(data, code, t.before.timestamp(), time.time())
            app.mark_data_for_update_persistence(chat_ids=chat_id)
            try:
                await _delete(app, chat_id, ids)
                for day in t.days:
                    card = await app.bot.send_message(
                        chat_id=chat_id,
                        text=formatting.format_day_card(day, tag),
                        parse_mode=ParseMode.HTML,
                        reply_markup=kb.day_card_keyboard(code, day.day),
                        disable_notification=True,
                    )
                    tidy.untrack(data, card.message_id)  # cards stay
                tidied += 1
            except Forbidden:
                log.info("tidy: chat %s blocked the bot; turning the tidy off", chat_id)
                await api.patch_learner(t.profile_id, LearnerPatch(tidy_chat=False))
            except TelegramError as e:
                log.warning("tidy of chat %s failed: %s", chat_id, e)
    return tidied


async def _reminder_loop(app: Application) -> None:
    settings: BotSettings = app.bot_data["settings"]
    while True:
        try:
            if sent := await send_due_reminders(app):
                log.info("sent %d practice reminder(s)", sent)
            if tidied := await run_due_tidies(app):
                log.info("tidied %d chat(s)", tidied)
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
        .bot(tidy.TrackingBot(token=settings.telegram_token))
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
    assert isinstance(app.bot, tidy.TrackingBot)
    app.bot.set_on_sent(lambda msg, menu: _record_sent(app, msg, menu))
    app.add_handler(TypeHandler(Update, track_incoming), group=-1)
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
    app.add_handler(CommandHandler(["language", "languages"], do_choose_language))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler(["lessons", "lesson", "grammar"], do_lessons))
    app.add_handler(CommandHandler(["review", "practise", "practice"], do_review))
    app.add_handler(CommandHandler(["words", "cards"], do_words))
    app.add_handler(CommandHandler("week", do_week))
    app.add_handler(CommandHandler(["history", "days"], do_history))
    app.add_handler(CommandHandler("save", cmd_save))
    app.add_handler(CommandHandler("practice_now", start_round))
    app.add_handler(CommandHandler(["placement", "test"], do_placement))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_error_handler(on_error)
    return app
