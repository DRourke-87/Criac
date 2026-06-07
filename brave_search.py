"""Brave Search API wrapper for real-time web search.

Hits the Brave Web Search endpoint and returns a clean list of results.
Requires BRAVE_API_KEY in the environment (get a free key at
https://brave.com/search/api/). If the key is missing, returns a single
result explaining that search is unavailable so the agent can tell the user.
"""

from __future__ import annotations

import logging

import httpx

import config

_log = logging.getLogger(__name__)
_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def search(query: str, count: int = 5) -> list[dict]:
    """Search the web and return up to `count` results as [{title, url, description}].

    `count` is capped at 10 (Brave API limit per call on the free plan).
    """
    if not config.BRAVE_API_KEY:
        return [
            {
                "title": "Web search unavailable",
                "url": "",
                "description": "BRAVE_API_KEY is not configured. Add it to .env to enable search.",
            }
        ]
    try:
        resp = httpx.get(
            _ENDPOINT,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": config.BRAVE_API_KEY,
            },
            params={"q": query, "count": min(count, 10)},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        _log.warning("Brave search failed for %r: %s", query, exc)
        return [{"title": "Search error", "url": "", "description": str(exc)}]

    results: list[dict] = []
    for item in data.get("web", {}).get("results", []):
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "description": item.get("description", ""),
        })
    return results
