"""Entry point — validate config and start the Discord bot (gateway connection)."""

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
    logging.getLogger(__name__).info("Starting Discord bot…")
    bot.run()


if __name__ == "__main__":
    main()
