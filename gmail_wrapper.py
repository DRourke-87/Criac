"""Gmail wrapper — OAuth 2.0 (Desktop app flow) + Gmail API, read-only.

Polls for new mail from a hard-coded sender allowlist only; the Gmail API
query itself is restricted to GMAIL_ALLOWED_SENDERS, so no other mail is
ever fetched.

Setup:
  1. Google Cloud Console → enable the Gmail API (same project as Calendar).
  2. Set GMAIL_ALLOWED_SENDERS in .env to a comma-separated list of sender
     addresses to monitor.
  3. python gmail_wrapper.py  (completes browser auth, saves token_gmail.json)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

_BASE = Path(__file__).parent
_CREDS_FILE = _BASE / "credentials.json"
_TOKEN_FILE = _BASE / "token_gmail.json"
_SEEN_FILE = _BASE / "gmail_seen.json"
_SEEN_CAP = 1000


def _get_service():
    """Return an authenticated Gmail service, refreshing credentials as needed."""
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
    return build("gmail", "v1", credentials=creds)


def _allowed_senders() -> list[str]:
    raw = os.environ.get("GMAIL_ALLOWED_SENDERS", "").strip()
    return [s.strip() for s in raw.split(",") if s.strip()]


def _build_query(senders: list[str]) -> str:
    return "(" + " OR ".join(f"from:{addr}" for addr in senders) + ")"


def _load_seen() -> set[str] | None:
    """Return the seen-message-id set, or None if this is the first ever run."""
    if not _SEEN_FILE.exists():
        return None
    return set(json.loads(_SEEN_FILE.read_text(encoding="utf-8")))


def _save_seen(seen: set[str]) -> None:
    trimmed = list(seen)[-_SEEN_CAP:]
    _SEEN_FILE.write_text(json.dumps(trimmed), encoding="utf-8")


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def get_new_emails(max_results: int = 50) -> list[dict]:
    """Return new emails from allowed senders since the last check.

    First call ever establishes a baseline (marks current matching mail as
    seen) and returns nothing, so startup doesn't dump the whole inbox.
    """
    senders = _allowed_senders()
    if not senders:
        return []

    service = _get_service()
    query = _build_query(senders)
    result = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    ids = [m["id"] for m in result.get("messages", [])]

    seen = _load_seen()
    if seen is None:
        _save_seen(set(ids))
        return []

    new_ids = [i for i in ids if i not in seen]
    if not new_ids:
        return []

    emails = []
    for msg_id in new_ids:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="metadata",
                 metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        emails.append({
            "id": msg_id,
            "from": _header(headers, "From"),
            "subject": _header(headers, "Subject") or "(no subject)",
            "snippet": msg.get("snippet", ""),
        })

    seen.update(ids)
    _save_seen(seen)
    emails.reverse()  # oldest-new-first, so notifications arrive in order
    return emails


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    print("Allowed senders:", _allowed_senders())
    print("New emails:", get_new_emails())
