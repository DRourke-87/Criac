"""Environment variable loading and validation.

Fails fast with a clear message naming the first missing variable so the bot
never starts half-configured.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# Claude model used by the agent. Sonnet 4.6 — balanced quality/cost, supports
# adaptive thinking.
MODEL = "claude-sonnet-4-6"

_REQUIRED = (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_USER_ID",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "NOTION_API_KEY",
    "NOTION_NOTES_DB_ID",
    "NOTION_TASKS_DB_ID",
    "NOTION_DRAFTS_DB_ID",
)


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


def validate() -> None:
    """Check every required variable is present. Call once at startup."""
    for name in _REQUIRED:
        _require(name)
    # Surface a bad user id immediately rather than at first message.
    int(_require("TELEGRAM_ALLOWED_USER_ID"))


# Eagerly-resolved settings. Importing this module does not raise; call
# validate() (from main.py) to fail fast before the bot starts.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_USER_ID = int(os.environ.get("TELEGRAM_ALLOWED_USER_ID", "0") or "0")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_NOTES_DB_ID = os.environ.get("NOTION_NOTES_DB_ID", "")
NOTION_TASKS_DB_ID = os.environ.get("NOTION_TASKS_DB_ID", "")
NOTION_DRAFTS_DB_ID = os.environ.get("NOTION_DRAFTS_DB_ID", "")
