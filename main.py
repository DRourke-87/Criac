"""Entry point — validate config and start the Telegram bot (long polling)."""

from __future__ import annotations

import logging

import bot
import config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config.validate()
    application = bot.build_application()
    logging.getLogger(__name__).info("Starting bot (long polling)…")
    application.run_polling()


if __name__ == "__main__":
    main()
