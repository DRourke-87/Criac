"""Discord bot — receives voice/text DMs, routes to the agent, replies.

Gated to a single user (config.DISCORD_ALLOWED_USER_ID). Voice messages and
plain audio attachments are transcribed via Groq Whisper; text is used as-is.
The bot connects outbound over Discord's gateway — no public URL or open port.

Requires the **Message Content** privileged intent, enabled both here and in the
Discord Developer Portal (Bot → Privileged Gateway Intents).
"""

from __future__ import annotations

import asyncio
import logging
import tempfile

import discord

import agent
import config
import transcriber

logger = logging.getLogger(__name__)


def _authorized(message: discord.Message) -> bool:
    return (
        message.author.id == config.DISCORD_ALLOWED_USER_ID
        and not message.author.bot
    )


def _audio_attachment(message: discord.Message) -> discord.Attachment | None:
    """Return the first voice message / audio attachment, if any."""
    for att in message.attachments:
        if (att.content_type or "").startswith("audio") or att.is_voice_message():
            return att
    return None


async def _process(text: str, source: str, message: discord.Message) -> None:
    """Run the agent on text and reply, mapping failures to user messages."""
    if not text:
        await message.reply("⚠️ Didn't catch anything — was that empty?")
        return
    try:
        result = await agent.run(text, source)
        await message.reply(result["reply"])
    except Exception:  # noqa: BLE001 — surface a friendly message, log the rest
        logger.exception("Agent failed")
        await message.reply("⚠️ Agent error — try again")


async def _handle_voice(att: discord.Attachment, message: discord.Message) -> None:
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        ogg_path = tmp.name
    await att.save(ogg_path)

    try:
        transcript = await asyncio.to_thread(transcriber.transcribe, ogg_path)
    except Exception:  # noqa: BLE001
        logger.exception("Transcription failed")
        await message.reply("⚠️ Couldn't transcribe that — try again or send as text")
        return

    await _process(transcript, "voice", message)


def build_client() -> discord.Client:
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        logger.info("Logged in as %s", client.user)

    @client.event
    async def on_message(message: discord.Message) -> None:
        if not _authorized(message):
            return
        async with message.channel.typing():
            att = _audio_attachment(message)
            if att is not None:
                await _handle_voice(att, message)
            else:
                await _process((message.content or "").strip(), "text", message)

    return client


def run() -> None:
    build_client().run(config.DISCORD_BOT_TOKEN, log_handler=None)
