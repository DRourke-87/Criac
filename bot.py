"""Telegram bot — receives voice/text, routes to the agent, replies."""

from __future__ import annotations

import asyncio
import logging
import tempfile

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

import agent
import config
import transcriber

logger = logging.getLogger(__name__)


def _authorized(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == config.TELEGRAM_ALLOWED_USER_ID


async def _process(text: str, source: str, update: Update) -> None:
    """Run the agent on text and reply, mapping failures to user messages."""
    if not text:
        await update.message.reply_text("⚠️ Didn't catch anything — was that empty?")
        return
    try:
        result = await asyncio.to_thread(agent.run, text, source)
        await update.message.reply_text(result["reply"])
    except Exception:  # noqa: BLE001 — surface a friendly message, log the rest
        logger.exception("Agent failed")
        await update.message.reply_text("⚠️ Agent error — try again")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        ogg_path = tmp.name
    tg_file = await update.message.voice.get_file()
    await tg_file.download_to_drive(ogg_path)

    try:
        transcript = await asyncio.to_thread(transcriber.transcribe, ogg_path)
    except Exception:  # noqa: BLE001
        logger.exception("Transcription failed")
        await update.message.reply_text(
            "⚠️ Couldn't transcribe that — try again or send as text"
        )
        return

    await _process(transcript, "voice", update)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    await _process((update.message.text or "").strip(), "text", update)


def build_application() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app
