"""Alexa skill endpoint — receives transcribed voice from Alexa, runs the agent,
and delivers the result to the user's Telegram chat."""

from __future__ import annotations

import asyncio
import logging
import os

from flask import Flask, jsonify, request
import telegram

import agent
import config

logger = logging.getLogger(__name__)

_bot: telegram.Bot | None = None
_loop: asyncio.AbstractEventLoop | None = None
_chat_id: int | None = None

flask_app = Flask(__name__)


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


async def _run_and_reply(text: str) -> None:
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
            asyncio.run_coroutine_threadsafe(_run_and_reply(text), _loop)
            return jsonify(_speak("Got it, I'll handle that."))
        return jsonify(_speak("Sorry, I didn't catch that."))

    if req_type == "SessionEndedRequest":
        return jsonify({"version": "1.0", "response": {}})

    return jsonify(_speak("I didn't understand that request."))


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
