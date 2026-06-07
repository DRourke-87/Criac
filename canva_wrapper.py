"""Canva Connect API wrapper — creates presentation designs and returns edit URLs."""

from __future__ import annotations

import httpx

import config

_BASE = "https://api.canva.com/rest/v1"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.CANVA_API_KEY}",
        "Content-Type": "application/json",
    }


def create_presentation(title: str) -> str:
    """Create a new blank Canva presentation and return its edit URL."""
    r = httpx.post(
        f"{_BASE}/designs",
        json={"design_type": {"type": "presentation"}, "title": title},
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["design"]["urls"]["edit_url"]
