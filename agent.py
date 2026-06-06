"""The Claude agent — powered by your Claude subscription via the Claude Agent SDK.

Instead of calling the Anthropic Messages API with a billed key, this drives the
Claude Code engine (bundled with `claude-agent-sdk`), authenticated by your
Claude Pro/Max subscription through the CLAUDE_CODE_OAUTH_TOKEN env var. Claude
classifies the incoming message and calls in-process tools that write to Notion.

Runs are serialised by `_lock` so the in-process tool handlers can read the
current message's state (source + created page URLs) off a module global without
worrying about contextvar propagation into SDK-spawned tasks. For a single-user
bot this is the simplest correct approach.
"""

from __future__ import annotations

import asyncio
import datetime
import json
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    create_sdk_mcp_server,
    query,
    tool,
)

import notion_client_wrapper as notion

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text()

# Serialises run() calls and holds the current message's state for the tools.
_lock = asyncio.Lock()
_state: dict = {"source": "voice", "urls": [], "used": False}


@tool(
    "create_note",
    "Store a note, thought, idea, or piece of information for later reference. "
    "Use when the user is capturing something to remember but not act on now.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short summary title (max 60 chars)"},
            "content": {"type": "string", "description": "Full note content, cleaned up from transcript"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Relevant topic tags"},
        },
        "required": ["title", "content"],
    },
)
async def create_note(args: dict[str, Any]) -> dict[str, Any]:
    _state["used"] = True
    url = notion.create_note(
        title=args["title"],
        content=args["content"],
        tags=args.get("tags", []),
        source=_state["source"],
    )
    _state["urls"].append(url)
    return {"content": [{"type": "text", "text": f"Note created. Notion URL: {url}"}]}


@tool(
    "create_task",
    "Create an actionable task with optional due date. Use when the user says "
    "they need to do something, follow up, or remember to take an action.",
    {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Clear, actionable task description"},
            "due_date": {"type": "string", "description": "ISO 8601 date string if mentioned, else omit"},
            "priority": {"type": "string", "enum": ["High", "Medium", "Low"]},
            "context": {"type": "string", "description": "Any additional context or detail"},
        },
        "required": ["task", "priority"],
    },
)
async def create_task(args: dict[str, Any]) -> dict[str, Any]:
    _state["used"] = True
    url = notion.create_task(
        task=args["task"],
        priority=args["priority"],
        due_date=args.get("due_date"),
        context=args.get("context", ""),
        source=_state["source"],
    )
    _state["urls"].append(url)
    return {"content": [{"type": "text", "text": f"Task created. Notion URL: {url}"}]}


@tool(
    "create_draft",
    "Write and store a content draft. Use when the user wants a piece of content "
    "created: LinkedIn post, email, blog post, tweet, or similar. Write the full "
    "draft, not just a plan.",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Descriptive title for the draft"},
            "type": {"type": "string", "enum": ["LinkedIn", "Email", "Blog", "Twitter", "Other"]},
            "content": {"type": "string", "description": "The fully written draft content"},
            "brief": {"type": "string", "description": "Original instruction from the user"},
        },
        "required": ["title", "type", "content", "brief"],
    },
)
async def create_draft(args: dict[str, Any]) -> dict[str, Any]:
    _state["used"] = True
    url = notion.create_draft(
        title=args["title"],
        type=args["type"],
        content=args["content"],
        brief=args["brief"],
        source=_state["source"],
    )
    _state["urls"].append(url)
    return {"content": [{"type": "text", "text": f"Draft created. Notion URL: {url}"}]}


@tool(
    "search_notion",
    "Search existing notes, tasks, or drafts in Notion. Use when the user asks "
    "what they have stored, wants to find something, or references past notes.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "database": {"type": "string", "enum": ["notes", "tasks", "drafts", "all"]},
        },
        "required": ["query", "database"],
    },
)
async def search_notion(args: dict[str, Any]) -> dict[str, Any]:
    _state["used"] = True
    results = notion.search(query=args["query"], database=args["database"])
    return {"content": [{"type": "text", "text": json.dumps(results)}]}


_server = create_sdk_mcp_server(
    name="notion",
    version="1.0.0",
    tools=[create_note, create_task, create_draft, search_notion],
)

_ALLOWED_TOOLS = [
    "mcp__notion__create_note",
    "mcp__notion__create_task",
    "mcp__notion__create_draft",
    "mcp__notion__search_notion",
]

# Belt-and-braces: keep Claude off the host. The only capabilities it has are the
# four Notion tools above; explicitly deny the built-in filesystem/shell tools.
_DISALLOWED_TOOLS = [
    "Bash", "Read", "Write", "Edit", "Glob", "Grep",
    "WebSearch", "WebFetch", "NotebookEdit", "Task", "TodoWrite",
]


def _options() -> ClaudeAgentOptions:
    today = datetime.date.today().isoformat()
    return ClaudeAgentOptions(
        system_prompt=f"Today's date is {today}.\n\n{_SYSTEM_PROMPT}",
        mcp_servers={"notion": _server},
        allowed_tools=_ALLOWED_TOOLS,
        disallowed_tools=_DISALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        max_turns=8,
    )


async def run(transcript: str, source: str = "voice") -> dict:
    """Send the transcript to Claude and action it.

    Returns {"reply": str, "notion_url": str | None}.
    """
    async with _lock:
        _state.update(source=source, urls=[], used=False)

        result_text: str | None = None
        texts: list[str] = []
        async for message in query(prompt=transcript, options=_options()):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        texts.append(block.text)
            elif isinstance(message, ResultMessage):
                if message.result:
                    result_text = message.result

        reply = (result_text or "\n".join(texts)).strip()
        notion_url = _state["urls"][-1] if _state["urls"] else None
        used = _state["used"]

    # Edge case: Claude replied without ever calling a tool. Store the raw
    # transcript as a note so nothing is lost.
    if not used:
        title = transcript[:60]
        notion_url = notion.create_note(
            title=title, content=transcript, tags=[], source=source
        )
        reply = f'✅ Note saved — "{title}" — {notion_url}'

    if not reply:
        reply = "✅ Done." + (f" — {notion_url}" if notion_url else "")

    return {"reply": reply, "notion_url": notion_url}


if __name__ == "__main__":
    import config

    config.validate()
    for sample in (
        "remind me to call the supplier tomorrow, it's fairly urgent",
        "idea: a newsletter on AI procurement for local government",
        "write a short LinkedIn post about why defence SMEs need better data hygiene",
    ):
        print(f"\n>>> {sample}")
        print(asyncio.run(run(sample, source="text")))
