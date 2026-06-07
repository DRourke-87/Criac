"""Notion wrapper — the four write/read operations the agent can perform.

Uses the official `notion-client` SDK directly with a static internal-integration
token (config.NOTION_API_KEY). Each create function returns the new page URL.

Module is named `notion_client_wrapper` to avoid shadowing the installed
`notion_client` package.
"""

from __future__ import annotations

import logging
import os
import sys

import httpx
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


def _normalise_id(db_id: str) -> str:
    return db_id.replace("-", "").lower()


_DB_IDS = {
    "notes": (config.NOTION_NOTES_DB_ID,),
    "tasks": (config.NOTION_TASKS_DB_ID,),
    "drafts": (config.NOTION_DRAFTS_DB_ID,),
}


def search(query: str, database: str) -> list[dict]:
    """Full-text search across the requested DB(s). Returns [{title, content, url}]."""
    if database == "all":
        wanted = {
            _normalise_id(config.NOTION_NOTES_DB_ID),
            _normalise_id(config.NOTION_TASKS_DB_ID),
            _normalise_id(config.NOTION_DRAFTS_DB_ID),
        }
    else:
        wanted = {_normalise_id(i) for i in _DB_IDS.get(database, ())}

    response = _client().search(
        query=query, filter={"property": "object", "value": "page"}
    )
    results: list[dict] = []
    for page in response.get("results", []):
        parent = page.get("parent", {})
        if parent.get("type") == "database_id" and _normalise_id(parent.get("database_id", "")) in wanted:
            results.append({
                "title": _page_title(page),
                "content": _page_text(page),
                "url": page.get("url", ""),
            })
    return results


def _page_title(page: dict) -> str:
    """Pull the title text out of whichever property is the title."""
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(part.get("plain_text", "") for part in prop.get("title", []))
    return "(untitled)"


def _page_text(page: dict) -> str:
    """Extract all plain text from rich_text properties — covers Content, Context, Brief, etc."""
    parts = []
    for name, prop in page.get("properties", {}).items():
        if prop.get("type") == "rich_text":
            text = "".join(p.get("plain_text", "") for p in prop.get("rich_text", []))
            if text:
                parts.append(text)
    return "\n".join(parts)


_log = logging.getLogger(__name__)

_NOTION_VERSION = "2022-06-28"
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _api_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {config.NOTION_API_KEY}", "Notion-Version": _NOTION_VERSION}


def _attach_file_to_page(page_id: str, file_path: str) -> None:
    """Upload file_path to Notion and append it as a file block on page_id."""
    filename = os.path.basename(file_path)
    hdrs = _api_headers()

    # Step 1 — create the upload record
    resp = httpx.post(
        "https://api.notion.com/v1/file_uploads",
        headers={**hdrs, "Content-Type": "application/json"},
        json={"name": filename},
        timeout=30,
    )
    resp.raise_for_status()
    upload_id = resp.json()["id"]

    # Step 2 — send the binary content
    with open(file_path, "rb") as fh:
        resp2 = httpx.post(
            f"https://api.notion.com/v1/file_uploads/{upload_id}/send",
            headers=hdrs,
            files={"file": (filename, fh, _PPTX_MIME)},
            timeout=60,
        )
        resp2.raise_for_status()

    # Step 3 — append a file block to the page
    _client().blocks.children.append(
        page_id,
        children=[{
            "type": "file",
            "file": {
                "type": "file_upload",
                "file_upload": {"id": upload_id},
                "name": filename,
            },
        }],
    )


def upload_presentation_to_notion(
    title: str, content: str, file_path: str, source: str
) -> str:
    """Create a Notion note page with the slide outline and attach the .pptx file.

    The file attach is best-effort — a warning is logged on failure but the
    page URL is always returned.
    """
    page = _client().pages.create(
        parent={"database_id": config.NOTION_NOTES_DB_ID},
        properties={
            "Title": {"title": _title(title)},
            "Content": {"rich_text": _rich_text(content)},
            "Tags": {"multi_select": _multi_select(["presentation"])},
            "Source": {"select": {"name": source}},
        },
    )
    page_url: str = page["url"]
    page_id: str = page["id"]

    try:
        _attach_file_to_page(page_id, file_path)
    except Exception as exc:
        _log.warning("Could not attach .pptx to Notion page %s: %s", page_id, exc)

    return page_url


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
