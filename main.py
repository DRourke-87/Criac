"""Entry point — validate config and start the Telegram bot (long polling)
alongside the Alexa skill endpoint (Flask on ALEXA_PORT, default 8080)."""

from __future__ import annotations

import asyncio
import logging
import signal
import threading

import agent
import bot
import config
import alexa_handler
import gmail_wrapper

logger = logging.getLogger(__name__)


async def _gmail_poll_loop(bot_instance, chat_id: int) -> None:
    """Poll Gmail for new mail from allowed senders, let the agent extract any
    events/reminders into the calendar or tasks, and report the outcome."""
    while True:
        try:
            emails = await asyncio.to_thread(gmail_wrapper.get_new_emails)
            for email in emails:
                prompt = (
                    f"You've received a school email from {email['from']}.\n"
                    f"Subject: {email['subject']}\n\n"
                    f"{email['body']}\n\n"
                    "Look for any events, deadlines, or reminders in this email "
                    "and add each one to the family calendar or create a task as "
                    "appropriate. If there's nothing actionable, just say so briefly."
                )
                try:
                    result = await agent.run(prompt, source="gmail")
                    reply = result["reply"]
                except Exception:
                    logger.exception("Agent failed processing school email")
                    reply = "⚠️ Couldn't process this email automatically — check it manually."
                await bot_instance.send_message(
                    chat_id=chat_id,
                    text=f"📧 Email from {email['from']} — \"{email['subject']}\"\n{reply}",
                )
        except Exception:
            logger.exception("Gmail poll failed")
        await asyncio.sleep(config.GMAIL_POLL_INTERVAL_SECONDS)


async def _run() -> None:
    config.validate()
    application = bot.build_application()

    loop = asyncio.get_running_loop()
    alexa_handler.init(application.bot, loop, config.TELEGRAM_ALLOWED_USER_ID)

    flask_thread = threading.Thread(target=alexa_handler.run_flask, daemon=True)
    flask_thread.start()

    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    async with application:
        await application.start()
        await application.updater.start_polling()
        if config.GMAIL_ALLOWED_SENDERS:
            loop.create_task(
                _gmail_poll_loop(application.bot, config.TELEGRAM_ALLOWED_USER_ID)
            )
        logging.getLogger(__name__).info(
            "Bot running — long polling + Alexa endpoint on port %s",
            __import__("os").environ.get("ALEXA_PORT", "8080"),
        )
        await stop.wait()
        await application.updater.stop()
        await application.stop()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(_run())


if __name__ == "__main__":
    main()
