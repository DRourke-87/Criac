"""The Claude agent — classifies intent and routes to Notion tools.

Runs a manual tool-use loop: Claude picks a tool, we execute it against Notion,
feed the result back, and Claude produces the final Telegram confirmation.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import anthropic

import config
import notion_client_wrapper as notion

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text()

_MAX_TOOL_ITERATIONS = 6

TOOLS = [
    {
        "name": "create_note",
        "description": (
            "Store a note, thought, idea, or piece of information for later "
            "reference. Use when the user is capturing something they want to "
            "remember but not necessarily act on immediately."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short summary title (max 60 chars)",
                },
                "content": {
                    "type": "string",
                    "description": "Full note content, cleaned up from transcript",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Relevant topic tags",
                },
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "create_task",
        "description": (
            "Create an actionable task with optional due date. Use when the user "
            "says they need to do something, follow up on something, or remember "
            "to take an action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Clear, actionable task description",
                },
                "due_date": {
                    "type": "string",
                    "description": "ISO 8601 date string if mentioned, else null",
                },
                "priority": {"type": "string", "enum": ["High", "Medium", "Low"]},
                "context": {
                    "type": "string",
                    "description": "Any additional context or detail",
                },
            },
            "required": ["task", "priority"],
        },
    },
    {
        "name": "create_draft",
        "description": (
            "Write and store a content draft. Use when the user wants a piece of "
            "content created: LinkedIn post, email, blog post, tweet, or similar. "
            "Write the full draft, not just a plan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Descriptive title for the draft",
                },
                "type": {
                    "type": "string",
                    "enum": ["LinkedIn", "Email", "Blog", "Twitter", "Other"],
                },
                "content": {
                    "type": "string",
                    "description": "The fully written draft content",
                },
                "brief": {
                    "type": "string",
                    "description": "Original instruction from the user",
                },
            },
            "required": ["title", "type", "content", "brief"],
        },
    },
    {
        "name": "search_notion",
        "description": (
            "Search existing notes, tasks, or drafts in Notion. Use when the user "
            "asks what they have stored, wants to find something, or references "
            "previous notes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "database": {
                    "type": "string",
                    "enum": ["notes", "tasks", "drafts", "all"],
                },
            },
            "required": ["query", "database"],
        },
    },
]


def _dispatch(name: str, tool_input: dict, source: str) -> tuple[str, str | None]:
    """Execute a tool. Returns (result_text_for_claude, notion_url_or_none)."""
    if name == "create_note":
        url = notion.create_note(
            title=tool_input["title"],
            content=tool_input["content"],
            tags=tool_input.get("tags", []),
            source=source,
        )
        return f"Note created. Notion URL: {url}", url
    if name == "create_task":
        url = notion.create_task(
            task=tool_input["task"],
            priority=tool_input["priority"],
            due_date=tool_input.get("due_date"),
            context=tool_input.get("context", ""),
            source=source,
        )
        return f"Task created. Notion URL: {url}", url
    if name == "create_draft":
        url = notion.create_draft(
            title=tool_input["title"],
            type=tool_input["type"],
            content=tool_input["content"],
            brief=tool_input["brief"],
            source=source,
        )
        return f"Draft created. Notion URL: {url}", url
    if name == "search_notion":
        results = notion.search(
            query=tool_input["query"], database=tool_input["database"]
        )
        return json.dumps(results), None
    return f"Unknown tool: {name}", None


def _system_prompt() -> str:
    today = datetime.date.today().isoformat()
    return f"Today's date is {today}.\n\n{_SYSTEM_PROMPT}"


def run(transcript: str, source: str = "voice") -> dict:
    """Send the transcript to Claude and action it.

    Returns {"reply": str, "notion_url": str | None}.
    """
    messages: list[dict] = [{"role": "user", "content": transcript}]
    notion_url: str | None = None
    used_tool = False

    for _ in range(_MAX_TOOL_ITERATIONS):
        response = _get_client().messages.create(
            model=config.MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=_system_prompt(),
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            break

        used_tool = True
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result_text, url = _dispatch(block.name, block.input, source)
                if url:
                    notion_url = url
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )
        messages.append({"role": "user", "content": tool_results})

    reply = "".join(b.text for b in response.content if b.type == "text").strip()

    # Edge case (spec §7.3): Claude replied without ever calling a tool. Store
    # the raw transcript as a note so nothing is lost.
    if not used_tool:
        title = transcript[:60]
        notion_url = notion.create_note(
            title=title, content=transcript, tags=[], source=source
        )
        reply = f'✅ Note saved — "{title}" — {notion_url}'

    if not reply:
        reply = "✅ Done." + (f" — {notion_url}" if notion_url else "")

    return {"reply": reply, "notion_url": notion_url}


if __name__ == "__main__":
    config.validate()
    for sample in (
        "remind me to call the supplier tomorrow, it's fairly urgent",
        "idea: a newsletter on AI procurement for local government",
        "write a short LinkedIn post about why defence SMEs need better data hygiene",
    ):
        print(f"\n>>> {sample}")
        print(run(sample, source="text"))
