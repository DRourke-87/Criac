"""OpenAI Whisper transcription wrapper."""

from __future__ import annotations

import os

from openai import OpenAI

import config

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def transcribe(audio_path: str) -> str:
    """Send an audio file to Whisper and return the transcript.

    Deletes the temp file afterwards. Returns "" for empty/whitespace audio.
    """
    try:
        with open(audio_path, "rb") as audio_file:
            result = _get_client().audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="en",
            )
        return (result.text or "").strip()
    finally:
        try:
            os.remove(audio_path)
        except OSError:
            pass
