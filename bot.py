"""Telegram bot — receives voice/text, routes to the agent, replies."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

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


async def _process(text: str, source: str, update: Update,
                   context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run the agent on text and reply, mapping failures to user messages."""
    if not text:
        await update.message.reply_text("⚠️ Didn't catch anything — was that empty?")
        return
    try:
        async def _progress(msg: str) -> None:
            if msg.startswith("PLAN:"):
                display = "🗂 Planning: " + msg[5:].strip()
            elif msg.startswith("STEP_DONE:"):
                display = "✔ " + msg[10:].strip()
            else:
                display = msg
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=display,
            )

        result = await agent.run(text, source, progress_callback=_progress)
        files = result.get("files") or ([result["file_path"]] if result.get("file_path") else [])
        if files:
            for i, fp in enumerate(files):
                with open(fp, "rb") as f:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=f,
                        caption=result["reply"] if i == 0 else None,
                    )
                Path(fp).unlink(missing_ok=True)
        else:
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

    await _process(transcript, "voice", update, context)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _authorized(update):
        return
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    await _process((update.message.text or "").strip(), "text", update, context)


def build_application() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app
