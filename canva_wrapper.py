"""Canva Connect API wrapper — fills a brand template with slide content.

Setup (one-time, ~15 minutes in Canva):
  1. In Canva, open Brand Hub → Brand Templates → Create a brand template.
  2. Pick a presentation layout you like (any Canva presentation template).
  3. In the template editor, select each text element you want the bot to fill
     and click "Add autofill field". Name the fields EXACTLY as follows:
       - presentation_title  (title slide main heading)
       - slide1_heading … slide7_heading  (each content slide title)
       - slide1_body    … slide7_body     (each content slide bullet text)
  4. Publish the brand template.
  5. Copy the template ID from the URL:
       canva.com/brand-templates/OACxxxxxxxxxxxxxx/…  →  OACxxxxxxxxxxxxxx
  6. Add it to your .env:  CANVA_BRAND_TEMPLATE_ID=OACxxxxxxxxxxxxxx

The bot fills up to 7 content slides. Unused slide slots stay blank — design
your template so that looks intentional (e.g. hide blank slides or use a
template that looks fine with 5-7 slides of content).
"""

from __future__ import annotations

import time

import httpx

import config

_BASE = "https://api.canva.com/rest/v1"
_POLL_INTERVAL = 2   # seconds between status checks
_MAX_POLLS = 30      # 60-second timeout


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.CANVA_API_KEY}",
        "Content-Type": "application/json",
    }


def create_presentation(title: str, slides: list[dict]) -> str:
    """Autofill a Canva brand template with slide content.

    Args:
        title:  Presentation title (maps to the presentation_title autofill field).
        slides: List of dicts with keys 'heading' (str) and 'bullets' (list[str]).
                Up to 7 slides supported. Maps to slide1_heading/slide1_body … slide7_*.

    Returns:
        Canva edit URL (valid for 30 days).
    """
    data: dict = {
        "presentation_title": {"type": "text", "text": title},
    }
    for i, slide in enumerate(slides[:7], 1):
        data[f"slide{i}_heading"] = {"type": "text", "text": slide["heading"]}
        data[f"slide{i}_body"] = {
            "type": "text",
            "text": "\n".join(f"• {b}" for b in slide["bullets"]),
        }

    r = httpx.post(
        f"{_BASE}/autofills",
        json={
            "brand_template_id": config.CANVA_BRAND_TEMPLATE_ID,
            "title": title,
            "data": data,
        },
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    job_id = r.json()["job"]["id"]

    for _ in range(_MAX_POLLS):
        time.sleep(_POLL_INTERVAL)
        r = httpx.get(f"{_BASE}/autofills/{job_id}", headers=_headers(), timeout=30)
        r.raise_for_status()
        job = r.json()["job"]
        if job["status"] == "success":
            return job["result"]["design"]["urls"]["edit_url"]
        if job["status"] == "failed":
            error = job.get("error", {}).get("message", "unknown error")
            raise RuntimeError(f"Canva autofill job failed: {error}")

    raise TimeoutError("Canva autofill job did not complete within 60 seconds")
