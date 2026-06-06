"""Speech-to-text transcription via Groq's Whisper (free tier).

Groq serves OpenAI's Whisper models behind an OpenAI-compatible API, so we
reuse the `openai` SDK and just point it at Groq's endpoint. No local model
download, no OpenAI account needed.
"""

from __future__ import annotations

import os

from openai import OpenAI

import config

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=config.GROQ_API_KEY,
            base_url=config.GROQ_BASE_URL,
        )
    return _client


def transcribe(audio_path: str) -> str:
    """Send an audio file to Whisper and return the transcript.

    Deletes the temp file afterwards. Returns "" for empty/whitespace audio.
    """
    try:
        with open(audio_path, "rb") as audio_file:
            result = _get_client().audio.transcriptions.create(
                model=config.TRANSCRIBE_MODEL,
                file=audio_file,
                language="en",
            )
        return (result.text or "").strip()
    finally:
        try:
            os.remove(audio_path)
        except OSError:
            pass
