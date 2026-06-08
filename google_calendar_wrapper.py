"""Google Calendar wrapper — OAuth 2.0 (Desktop app flow) + Calendar API.

First run opens a browser to authenticate; subsequent runs use the saved
token.json refresh token automatically.

Setup:
  1. Google Cloud Console → enable Calendar API → create OAuth 2.0 credentials
     (type: Desktop app) → download as credentials.json in this directory.
  2. python google_calendar_wrapper.py  (completes browser auth, saves token.json)
  3. Optionally set GOOGLE_CALENDAR_ID in .env to a comma-separated list of
     calendar IDs to limit which calendars are read. Leave blank (or omit) to
     automatically use ALL calendars in your Google account.
  4. Set GOOGLE_WRITE_CALENDAR_ID to the calendar new events should be added to
     (defaults to "primary" — your main Google calendar).
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]

_BASE = Path(__file__).parent
_CREDS_FILE = _BASE / "credentials.json"
_TOKEN_FILE = _BASE / "token.json"


def _get_service():
    """Return an authenticated Calendar service, refreshing credentials as needed."""
    creds = None
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not _CREDS_FILE.exists():
                raise RuntimeError(
                    "credentials.json not found. Download it from Google Cloud Console "
                    "(APIs & Services → Credentials → your OAuth 2.0 Desktop app)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(_CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        _TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return build("calendar", "v3", credentials=creds)


def _parse_event_time(e: dict, key: str) -> str:
    t = e[key]
    return t.get("dateTime", t.get("date", ""))


def list_calendar_ids() -> list[str]:
    """Return IDs of all calendars visible to the authenticated user."""
    result = _get_service().calendarList().list().execute()
    return [c["id"] for c in result.get("items", [])]


def list_calendars() -> list[dict]:
    """Return all calendars as {id, name} dicts."""
    result = _get_service().calendarList().list().execute()
    return [{"id": c["id"], "name": c.get("summary", c["id"])} for c in result.get("items", [])]


def resolve_calendar_id(name: str) -> str:
    """Resolve a calendar name to its ID. Falls back to the name itself if no match."""
    if not name:
        return os.environ.get("GOOGLE_WRITE_CALENDAR_ID", "primary")
    name_lower = name.lower().strip()
    for cal in list_calendars():
        if name_lower in cal["name"].lower():
            return cal["id"]
    return name  # assume it's already an ID


def _resolve_calendar_ids() -> list[str]:
    """Return the calendars to query: env-configured list, or all of them."""
    configured = os.environ.get("GOOGLE_CALENDAR_ID", "").strip()
    if configured:
        return [c.strip() for c in configured.split(",") if c.strip()]
    return list_calendar_ids()


def get_events(days_ahead: int = 7) -> list[dict]:
    """Return upcoming events across all configured calendars, sorted by start."""
    tz = ZoneInfo(os.environ.get("TIMEZONE", "Europe/London"))
    now = datetime.datetime.now(tz)
    end = now + datetime.timedelta(days=days_ahead)
    service = _get_service()

    all_events: list[dict] = []
    for cal_id in _resolve_calendar_ids():
        result = (
            service.events()
            .list(
                calendarId=cal_id,
                timeMin=now.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        cal_name = cal_id  # fallback label
        for e in result.get("items", []):
            all_events.append(
                {
                    "title": e.get("summary", "(no title)"),
                    "start": _parse_event_time(e, "start"),
                    "end": _parse_event_time(e, "end"),
                    "description": e.get("description", ""),
                    "location": e.get("location", ""),
                    "calendar": e.get("organizer", {}).get("displayName", cal_id),
                }
            )

    all_events.sort(key=lambda e: e["start"])
    return all_events


def create_event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    location: str = "",
    calendar_id: str | None = None,
    calendar_name: str | None = None,
) -> str:
    """Create an event. start/end are ISO 8601 date ('2026-06-10') or datetime
    ('2026-06-10T15:00:00'). Returns the event's HTML link."""
    tz_name = os.environ.get("TIMEZONE", "Europe/London")
    if calendar_name:
        calendar_id = resolve_calendar_id(calendar_name)
    elif calendar_id is None:
        calendar_id = os.environ.get("GOOGLE_WRITE_CALENDAR_ID", "primary")

    def _slot(val: str) -> dict:
        if "T" in val:
            return {"dateTime": val, "timeZone": tz_name}
        return {"date": val}

    # Google Calendar all-day event end dates are exclusive (day after last day).
    # If start and end are the same date, bump end forward by one day.
    if "T" not in start and "T" not in end and start >= end:
        end_date = datetime.date.fromisoformat(start) + datetime.timedelta(days=1)
        end = end_date.isoformat()

    body = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": _slot(start),
        "end": _slot(end),
    }
    event = (
        _get_service()
        .events()
        .insert(calendarId=calendar_id, body=body)
        .execute()
    )
    return event.get("htmlLink", "")


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    print("Calendars found:", list_calendar_ids())
    print("\nUpcoming events (14 days):")
    for ev in get_events(days_ahead=14):
        print(f"  {ev['start']}  [{ev['calendar']}]  {ev['title']}")
