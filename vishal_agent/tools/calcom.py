"""Book meetings on Vishal's Cal.com calendar.

Exposed to the agent as a tool. The model emits a `book_meeting` call with
name / email / start_time / topic; this module turns that into a Cal.com
booking and hands back a plain dict the model can read aloud.

The signature is fixed by the model's training: it was fine-tuned to emit
exactly these four arguments, and recall drops if they change. The function
conforms to the model, not the other way round.
"""

import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

CAL_API = "https://api.cal.com/v2/bookings"
# Mandatory. Omitting it silently selects an older endpoint shape.
CAL_API_VERSION = "2026-02-25"

USERNAME = "vishalpandey.ai"
EVENT_TYPE_SLUG = "30min"
ATTENDEE_TZ = "UTC"  # start_time is always ISO-8601 UTC; see module docstring

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def _normalise_start(value: str) -> Optional[str]:
    """Return an ISO-8601 UTC string ending in Z, or None if unparseable.

    The model usually emits `2026-09-10T14:00:00Z` but sometimes omits the Z.
    A missing timezone is treated as UTC rather than rejected — refusing a
    booking over a trailing character would be a poor trade.
    """
    text = (value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def book_meeting(
    name: str,
    email: str,
    start_time: str,
    topic: str = "",
    _transport: Any = None,
) -> dict:
    """Book a meeting with Vishal.

    Args:
        name: The visitor's full name.
        email: The visitor's email address; the invite goes here.
        start_time: Start time in ISO 8601 UTC, e.g. "2026-09-10T14:00:00Z".
        topic: Optional short description of what they want to discuss.

    Returns:
        On success: {"ok": True, "uid": ..., "starts_at": ..., "status": ...}
        On failure: {"ok": False, "reason": <a sentence the agent can say>}
    """
    api_key = os.environ.get("CALCOM_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "reason": "Booking is not configured right now."}

    if not name or not name.strip():
        return {"ok": False, "reason": "I need your name to book that."}
    if not _EMAIL.match((email or "").strip()):
        return {"ok": False, "reason": "That email doesn't look right - can you check it?"}

    start = _normalise_start(start_time)
    if start is None:
        return {"ok": False, "reason": "I couldn't read that time - which date and time did you want?"}

    payload = {
        "start": start,
        "eventTypeSlug": EVENT_TYPE_SLUG,
        "username": USERNAME,
        "attendee": {"name": name.strip(), "email": email.strip(), "timeZone": ATTENDEE_TZ},
    }
    if topic and topic.strip():
        payload["metadata"] = {"topic": topic.strip()[:400]}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "cal-api-version": CAL_API_VERSION,
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=20.0, transport=_transport) as client:
            r = client.post(CAL_API, json=payload, headers=headers)
    except httpx.HTTPError:
        return {"ok": False, "reason": "I couldn't reach the calendar just then - try again in a moment?"}

    if r.status_code in (200, 201):
        data = (r.json() or {}).get("data") or {}
        return {
            "ok": True,
            "uid": data.get("uid"),
            "status": data.get("status", "accepted"),
            "starts_at": data.get("start", start),
        }

    detail = ""
    try:
        body = r.json()
        detail = str(body.get("error", {}).get("message") or body.get("message") or "")
    except Exception:
        detail = r.text[:200]

    low = detail.lower()
    if r.status_code in (400, 409) or "available" in low or "busy" in low or "slot" in low:
        return {"ok": False, "reason": "That slot isn't free - want to try another time?"}
    if r.status_code in (401, 403):
        return {"ok": False, "reason": "Booking is not configured right now."}
    return {"ok": False, "reason": "The calendar wouldn't take that booking - try another time?"}
