"""Alexa skill endpoint — receives transcribed voice from Alexa, runs the agent,
and delivers the result either back through Alexa (Q&A) or via Telegram (actions)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import re

from flask import Flask, jsonify, request
import telegram

import agent
import config

logger = logging.getLogger(__name__)

_bot: telegram.Bot | None = None
_loop: asyncio.AbstractEventLoop | None = None
_chat_id: int | None = None

flask_app = Flask(__name__)

# Q&A timeout — if the agent doesn't respond in time, fall back to Telegram.
_QA_TIMEOUT = 6.0


def init(bot: telegram.Bot, loop: asyncio.AbstractEventLoop, chat_id: int) -> None:
    global _bot, _loop, _chat_id
    _bot = bot
    _loop = loop
    _chat_id = chat_id


def _extract_query(data: dict) -> str | None:
    slots = data.get("request", {}).get("intent", {}).get("slots", {})
    for name in ("query", "Query", "QUERY"):
        val = slots.get(name, {}).get("value")
        if val:
            return val.strip()
    return None


def _validate_skill_id(data: dict) -> bool:
    expected = config.ALEXA_SKILL_ID
    if not expected:
        return True
    actual = data.get("session", {}).get("application", {}).get("applicationId", "")
    return actual == expected


def _classify_request(text: str) -> str:
    """Return 'qa' for questions/lookups, 'action' for create/do tasks."""
    t = text.lower()
    qa_keywords = [
        "what", "when", "where", "who", "how many", "how much",
        "do i have", "have i got", "what's on", "what is on",
        "search for", "look up", "find me", "tell me about",
        "what do i", "do you know", "what have i", "upcoming",
        "any events", "my calendar", "what's coming", "what did i",
        "show me", "list my", "any tasks", "any notes",
    ]
    for kw in qa_keywords:
        if kw in t:
            return "qa"
    return "action"


def _clean_for_speech(text: str) -> str:
    """Strip markdown, URLs, and emoji so Alexa speaks the reply cleanly."""
    # Markdown links [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Bare URLs
    text = re.sub(r'https?://\S+', '', text)
    # Markdown punctuation
    text = re.sub(r'[*_`#]', '', text)
    # Common status emoji at line start (✅ ✔ 📋 🔍 📅 🧠 🌐 ⚠️)
    text = re.sub(r'[\U0001F300-\U0001F9FF☀-➿⬀-⯿⌀-⏿]', '', text)
    # Collapse whitespace
    text = ' '.join(text.split())
    # Truncate to ~600 chars — comfortable Alexa speech length
    if len(text) > 600:
        text = text[:597] + '...'
    return text.strip()


async def _run_and_reply(text: str) -> None:
    """Run agent and send result to Telegram (action path)."""
    assert _bot and _chat_id
    try:
        result = await agent.run(text, source="alexa")
        reply = result["reply"]
    except Exception:
        logger.exception("Alexa agent run failed")
        reply = "⚠️ Something went wrong — check logs."
    await _bot.send_message(chat_id=_chat_id, text=f"🔔 Alexa: {reply}")


@flask_app.route("/alexa", methods=["POST"])
def alexa():
    data = request.get_json(force=True, silent=True) or {}

    if not _validate_skill_id(data):
        logger.warning("Rejected Alexa request: unknown skill ID")
        return jsonify({"version": "1.0", "response": {}}), 403

    req_type = data.get("request", {}).get("type", "")

    if req_type == "LaunchRequest":
        return jsonify(_speak("Hi, I'm ready. What would you like to do?", end_session=False))

    if req_type == "IntentRequest":
        text = _extract_query(data)
        if text and _loop and not _loop.is_closed():
            if _classify_request(text) == "qa":
                return _handle_qa(text)
            else:
                asyncio.run_coroutine_threadsafe(_run_and_reply(text), _loop)
                return jsonify(_speak("Got it, I'll handle that."))
        return jsonify(_speak("Sorry, I didn't catch that."))

    if req_type == "SessionEndedRequest":
        return jsonify({"version": "1.0", "response": {}})

    return jsonify(_speak("I didn't understand that request."))


def _handle_qa(text: str):
    """Run agent synchronously; speak answer via Alexa if fast enough, else Telegram."""
    answered = [False]

    def _on_done(f: concurrent.futures.Future) -> None:
        if answered[0]:
            return
        try:
            result = f.result()
            asyncio.run_coroutine_threadsafe(
                _bot.send_message(
                    chat_id=_chat_id,
                    text=f"🔔 Alexa: {result['reply']}",
                ),
                _loop,
            )
        except Exception:
            logger.exception("Deferred Alexa Q&A Telegram fallback failed")

    future = asyncio.run_coroutine_threadsafe(agent.run(text, source="alexa"), _loop)
    future.add_done_callback(_on_done)

    try:
        result = future.result(timeout=_QA_TIMEOUT)
        answered[0] = True
        speech = _clean_for_speech(result["reply"])
        return jsonify(_speak(speech))
    except concurrent.futures.TimeoutError:
        return jsonify(_speak("I'm looking into that, check Telegram for the answer."))


@flask_app.route("/health", methods=["GET"])
def health():
    return "ok", 200


def _speak(text: str, end_session: bool = True) -> dict:
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text},
            "shouldEndSession": end_session,
        },
    }


def run_flask() -> None:
    port = int(os.environ.get("ALEXA_PORT", "8080"))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
