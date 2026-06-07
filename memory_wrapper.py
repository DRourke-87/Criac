"""Notion-backed persistent memory for the personal assistant.

Stores facts, preferences, and context across sessions in a dedicated
Memory database in Notion. Each entry has a Key (title), Value (body),
Category (select), Tags (multi-select), and an Active checkbox. Setting
Active = False marks a memory as forgotten without deleting it.
"""

from __future__ import annotations

import logging

from notion_client import Client

import config

_notion: Client | None = None
_log = logging.getLogger(__name__)
_MAX_TEXT = 2000


def _client() -> Client:
    global _notion
    if _notion is None:
        _notion = Client(auth=config.NOTION_API_KEY)
    return _notion


def _rich_text(content: str) -> list[dict]:
    content = content or ""
    return [
        {"text": {"content": content[i : i + _MAX_TEXT]}}
        for i in range(0, len(content), _MAX_TEXT)
    ] if content else []


def _title(text: str) -> list[dict]:
    return [{"text": {"content": (text or "")[:_MAX_TEXT]}}]


def _page_title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(p.get("plain_text", "") for p in prop.get("title", []))
    return "(untitled)"


def save_memory(key: str, value: str, category: str, tags: list[str] | None = None) -> str:
    """Store a new memory entry. Returns the Notion page URL."""
    if not config.NOTION_MEMORY_DB_ID:
        raise RuntimeError("NOTION_MEMORY_DB_ID is not configured.")
    page = _client().pages.create(
        parent={"database_id": config.NOTION_MEMORY_DB_ID},
        properties={
            "Key": {"title": _title(key)},
            "Value": {"rich_text": _rich_text(value)},
            "Category": {"select": {"name": category}},
            "Tags": {"multi_select": [{"name": t} for t in (tags or []) if t]},
            "Active": {"checkbox": True},
        },
    )
    return page["url"]


def _normalise_id(db_id: str) -> str:
    return db_id.replace("-", "").lower()


def search_memories(query: str, limit: int = 10) -> list[dict]:
    """Search active memories via full-text search. Returns [{id, key, value, category, url}]."""
    if not config.NOTION_MEMORY_DB_ID:
        return []
    resp = _client().search(
        query=query,
        filter={"property": "object", "value": "page"},
    )
    target_id = _normalise_id(config.NOTION_MEMORY_DB_ID)
    results: list[dict] = []
    for page in resp.get("results", []):
        parent = page.get("parent", {})
        if _normalise_id(parent.get("database_id", "")) != target_id:
            continue
        props = page.get("properties", {})
        if not props.get("Active", {}).get("checkbox", True):
            continue
        key = _page_title(page)
        value = "".join(
            p.get("plain_text", "")
            for p in props.get("Value", {}).get("rich_text", [])
        )
        category = (props.get("Category", {}).get("select") or {}).get("name", "")
        results.append({
            "id": page["id"],
            "key": key,
            "value": value,
            "category": category,
            "url": page.get("url", ""),
        })
        if len(results) >= limit:
            break
    return results


def forget_memory(page_id: str) -> bool:
    """Mark a memory as inactive (forgotten). Returns True on success."""
    try:
        _client().pages.update(page_id=page_id, properties={"Active": {"checkbox": False}})
        return True
    except Exception as exc:
        _log.warning("Could not forget memory %s: %s", page_id, exc)
        return False


def get_all_active_memories(limit: int = 30) -> list[dict]:
    """Return up to `limit` active memories ordered by most-recently-updated.

    Used at the start of each run to inject background context into the
    system prompt. Returns an empty list if NOTION_MEMORY_DB_ID is unset.
    """
    if not config.NOTION_MEMORY_DB_ID:
        return []
    try:
        resp = _client().databases.query(
            database_id=config.NOTION_MEMORY_DB_ID,
            filter={"property": "Active", "checkbox": {"equals": True}},
            sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
            page_size=limit,
        )
    except Exception as exc:
        _log.warning("Could not fetch memories: %s", exc)
        return []
    results: list[dict] = []
    for page in resp.get("results", []):
        props = page.get("properties", {})
        key = _page_title(page)
        value = "".join(
            p.get("plain_text", "")
            for p in props.get("Value", {}).get("rich_text", [])
        )
        category = (props.get("Category", {}).get("select") or {}).get("name", "")
        results.append({
            "id": page["id"],
            "key": key,
            "value": value,
            "category": category,
            "url": page.get("url", ""),
        })
    return results
