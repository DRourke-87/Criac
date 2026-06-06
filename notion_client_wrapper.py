"""Notion wrapper — the four write/read operations the agent can perform.

Uses the official `notion-client` SDK directly with a static internal-integration
token (config.NOTION_API_KEY). Each create function returns the new page URL.

Module is named `notion_client_wrapper` to avoid shadowing the installed
`notion_client` package.
"""

from __future__ import annotations

import sys

from notion_client import Client

import config

_notion: Client | None = None


def _client() -> Client:
    global _notion
    if _notion is None:
        _notion = Client(auth=config.NOTION_API_KEY)
    return _notion

# Notion rich-text fields cap each text object at 2000 chars; split longer bodies.
_MAX_TEXT = 2000


def _rich_text(content: str) -> list[dict]:
    content = content or ""
    if not content:
        return []
    return [
        {"text": {"content": content[i : i + _MAX_TEXT]}}
        for i in range(0, len(content), _MAX_TEXT)
    ]


def _title(text: str) -> list[dict]:
    return [{"text": {"content": (text or "")[:_MAX_TEXT]}}]


def _multi_select(tags: list[str] | None) -> list[dict]:
    return [{"name": t} for t in (tags or []) if t]


def create_note(title: str, content: str, tags: list[str], source: str) -> str:
    """Create a page in the Notes DB. Returns the page URL."""
    page = _client().pages.create(
        parent={"database_id": config.NOTION_NOTES_DB_ID},
        properties={
            "Title": {"title": _title(title)},
            "Content": {"rich_text": _rich_text(content)},
            "Tags": {"multi_select": _multi_select(tags)},
            "Source": {"select": {"name": source}},
        },
    )
    return page["url"]


def create_task(
    task: str,
    priority: str,
    due_date: str | None,
    context: str,
    source: str,
) -> str:
    """Create a page in the Tasks DB. Returns the page URL."""
    properties: dict = {
        "Task": {"title": _title(task)},
        "Priority": {"select": {"name": priority}},
        "Status": {"status": {"name": "Not started"}},
        "Context": {"rich_text": _rich_text(context)},
        "Source": {"select": {"name": source}},
    }
    if due_date:
        properties["Due Date"] = {"date": {"start": due_date}}
    page = _client().pages.create(
        parent={"database_id": config.NOTION_TASKS_DB_ID},
        properties=properties,
    )
    return page["url"]


def create_draft(title: str, type: str, content: str, brief: str, source: str) -> str:
    """Create a page in the Drafts DB. Returns the page URL."""
    page = _client().pages.create(
        parent={"database_id": config.NOTION_DRAFTS_DB_ID},
        properties={
            "Title": {"title": _title(title)},
            "Type": {"select": {"name": type}},
            "Content": {"rich_text": _rich_text(content)},
            "Status": {"select": {"name": "Draft"}},
            "Brief": {"rich_text": _rich_text(brief)},
            "Source": {"select": {"name": source}},
        },
    )
    return page["url"]


_DB_IDS = {
    "notes": (config.NOTION_NOTES_DB_ID,),
    "tasks": (config.NOTION_TASKS_DB_ID,),
    "drafts": (config.NOTION_DRAFTS_DB_ID,),
}


def search(query: str, database: str) -> list[dict]:
    """Full-text search across the requested DB(s). Returns [{title, url}]."""
    if database == "all":
        wanted = {
            config.NOTION_NOTES_DB_ID,
            config.NOTION_TASKS_DB_ID,
            config.NOTION_DRAFTS_DB_ID,
        }
    else:
        wanted = set(_DB_IDS.get(database, ()))

    response = _client().search(
        query=query, filter={"property": "object", "value": "page"}
    )
    results: list[dict] = []
    for page in response.get("results", []):
        parent = page.get("parent", {})
        if parent.get("type") == "database_id" and parent.get("database_id") in wanted:
            results.append({"title": _page_title(page), "url": page.get("url", "")})
    return results


def _page_title(page: dict) -> str:
    """Pull the title text out of whichever property is the title."""
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(part.get("plain_text", "") for part in prop.get("title", []))
    return "(untitled)"


if __name__ == "__main__":
    # Smoke test: `python notion_client_wrapper.py` writes one page to each DB.
    config.validate()
    print("note  ->", create_note("Test note", "Body of the note.", ["test"], "text"))
    print(
        "task  ->",
        create_task("Test the bot", "Low", None, "Created by smoke test.", "text"),
    )
    print(
        "draft ->",
        create_draft("Test draft", "Other", "Draft body.", "make a test draft", "text"),
    )
    print("search->", search("test", "all"), file=sys.stderr)
