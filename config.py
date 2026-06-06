"""Environment variable loading and validation.

Fails fast with a clear message naming the first missing variable so the bot
never starts half-configured.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# Transcription via Groq's free Whisper API (OpenAI-compatible endpoint).
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
TRANSCRIBE_MODEL = "whisper-large-v3-turbo"

_REQUIRED = (
    "DISCORD_BOT_TOKEN",
    "DISCORD_ALLOWED_USER_ID",
    "GROQ_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
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
    int(_require("DISCORD_ALLOWED_USER_ID"))


# Eagerly-resolved settings. Importing this module does not raise; call
# validate() (from main.py) to fail fast before the bot starts.
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_ALLOWED_USER_ID = int(os.environ.get("DISCORD_ALLOWED_USER_ID", "0") or "0")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
# Subscription auth for the Claude Agent SDK — from `claude setup-token` (a
# Claude Pro/Max login). The SDK reads this env var directly; we surface it here
# only so validate() can fail fast if it's missing.
CLAUDE_CODE_OAUTH_TOKEN = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_NOTES_DB_ID = os.environ.get("NOTION_NOTES_DB_ID", "")
NOTION_TASKS_DB_ID = os.environ.get("NOTION_TASKS_DB_ID", "")
NOTION_DRAFTS_DB_ID = os.environ.get("NOTION_DRAFTS_DB_ID", "")
