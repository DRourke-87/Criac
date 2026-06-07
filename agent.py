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
import google_calendar_wrapper as gcal
import pptx_wrapper as pptx

_SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")

# Serialises run() calls and holds the current message's state for the tools.
_lock = asyncio.Lock()
_state: dict = {"source": "voice", "urls": [], "used": False, "files": []}


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


@tool(
    "get_upcoming_events",
    "Check what is on the family Google Calendar. Use when the user asks what's "
    "coming up, what's on this week, whether a date is free, or anything about "
    "upcoming plans or family events.",
    {
        "type": "object",
        "properties": {
            "days_ahead": {
                "type": "integer",
                "description": "How many days ahead to look (default 7, max 180)",
            },
        },
        "required": [],
    },
)
async def get_upcoming_events(args: dict[str, Any]) -> dict[str, Any]:
    _state["used"] = True
    days = min(int(args.get("days_ahead", 7)), 180)
    events = gcal.get_events(days_ahead=days)
    if not events:
        text = "No events found in that window."
    else:
        lines = [f"- {e['start']}: {e['title']}" + (f" @ {e['location']}" if e['location'] else "") for e in events]
        text = "\n".join(lines)
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "create_calendar_event",
    "Add an event to the family Google Calendar. Use when the user says they want "
    "to add, schedule, or put something on the calendar. Always infer a sensible "
    "end time (default 1 hour after start) if not stated.",
    {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Event title"},
            "start": {
                "type": "string",
                "description": "ISO 8601 date ('2026-06-10') or datetime ('2026-06-10T15:00:00')",
            },
            "end": {
                "type": "string",
                "description": "ISO 8601 date or datetime. For timed events default to start + 1 hour.",
            },
            "description": {"type": "string", "description": "Optional notes or details"},
            "location": {"type": "string", "description": "Optional location"},
        },
        "required": ["summary", "start", "end"],
    },
)
async def create_calendar_event(args: dict[str, Any]) -> dict[str, Any]:
    _state["used"] = True
    link = gcal.create_event(
        summary=args["summary"],
        start=args["start"],
        end=args["end"],
        description=args.get("description", ""),
        location=args.get("location", ""),
    )
    _state["urls"].append(link)
    return {"content": [{"type": "text", "text": f"Event created. Calendar link: {link}"}]}


@tool(
    "create_presentation",
    "Create a slide deck on a topic via Canva and return an edit link. Use when "
    "the user asks for a presentation, slide deck, or slides on a topic. Write "
    "the full slide content — headings and bullets for every slide. Maximum 7 "
    "content slides (plus the title slide handled by the title field).",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Presentation title"},
            "slides": {
                "type": "array",
                "description": "Ordered list of up to 7 content slides",
                "maxItems": 7,
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string", "description": "Slide title"},
                        "bullets": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "3-5 bullet points for this slide",
                        },
                    },
                    "required": ["heading", "bullets"],
                },
            },
            "brief": {"type": "string", "description": "Original user request"},
        },
        "required": ["title", "slides", "brief"],
    },
)
async def create_presentation(args: dict[str, Any]) -> dict[str, Any]:
    _state["used"] = True
    file_path = await asyncio.to_thread(
        pptx.create_presentation, args["title"], args["slides"]
    )
    slide_lines = []
    for i, s in enumerate(args["slides"], 1):
        slide_lines.append(f"Slide {i}: {s['heading']}")
        slide_lines.extend(f"  - {b}" for b in s["bullets"])
    notion_url = notion.upload_presentation_to_notion(
        title=f"Presentation: {args['title']}",
        content=f"Brief: {args['brief']}\n\n" + "\n".join(slide_lines),
        file_path=file_path,
        source=_state["source"],
    )
    _state["files"].append(file_path)
    _state["urls"].append(notion_url)
    return {
        "content": [
            {
                "type": "text",
                "text": f"File: {file_path}  Notion URL: {notion_url}  Slides: {len(args['slides'])}",
            }
        ]
    }


_server = create_sdk_mcp_server(
    name="notion",
    version="1.0.0",
    tools=[create_note, create_task, create_draft, search_notion,
           get_upcoming_events, create_calendar_event, create_presentation],
)

_ALLOWED_TOOLS = [
    "mcp__notion__create_note",
    "mcp__notion__create_task",
    "mcp__notion__create_draft",
    "mcp__notion__search_notion",
    "mcp__notion__get_upcoming_events",
    "mcp__notion__create_calendar_event",
    "mcp__notion__create_presentation",
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
        _state.update(source=source, urls=[], used=False, files=[])

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
        file_path = _state["files"][-1] if _state["files"] else None
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

    return {"reply": reply, "notion_url": notion_url, "file_path": file_path}


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
