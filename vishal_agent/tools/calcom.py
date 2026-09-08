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
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

CAL_API = "https://api.cal.com/v2/bookings"
CAL_SLOTS_API = "https://api.cal.com/v2/slots"
# Mandatory, and DIFFERENT per endpoint. Omitting either silently selects an
# older shape rather than erroring.
CAL_API_VERSION = "2026-02-25"
CAL_SLOTS_API_VERSION = "2024-09-04"
CAL_LIST_API_VERSION = "2024-08-13"
# Handed back on success so the model relays a real link instead of
# inventing one -- a live booking produced a misspelled, non-existent host.
BOOKING_URL = "https://cal.com/booking/{uid}"
CAL_RESCHEDULE_API = "https://api.cal.com/v2/bookings/{uid}/reschedule"

USERNAME = "vishalpandey.ai"
EVENT_TYPE_SLUG = "30min"
ATTENDEE_TZ = "UTC"  # start_time is always ISO-8601 UTC; see module docstring

# Bookable window, from the Cal.com "Working hours" schedule. Kept here so the
# agent's instruction and this module cannot drift apart.
HOST_TZ = "Asia/Kolkata"
WORKING_HOURS_LOCAL = "09:00-17:00"
WORKING_HOURS_UTC = "03:30-11:30"
WORKING_DAYS = "Monday to Friday"

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")


def _make_client() -> httpx.Client:
    """Build the HTTP client. Tests monkeypatch this.

    Kept out of the function signature deliberately: ADK's FunctionTool
    introspects book_meeting to build the tool schema, and a parameter
    annotated `Any` raises "typing.Any cannot be used with isinstance()"
    at request time -- which import-level checks do not catch.
    """
    # Booking creation makes a video room and sends invites inside the POST;
    # 20 s was exceeded in production and a real booking was reported as a
    # failure. Connect stays short so an unreachable host fails fast.
    return httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))


def _free_slots(client: httpx.Client, api_key: str, around_iso: str, limit: int = 4) -> list:
    """Return up to `limit` genuinely free slots on the requested day.

    Called only when a booking is rejected. A bare "that slot isn't free"
    leaves the visitor guessing, and they usually guess outside the working
    window again -- the times people ask for (afternoon) fall outside
    09:00-17:00 IST once expressed in UTC.
    """
    day = around_iso[:10]
    try:
        r = client.get(
            CAL_SLOTS_API,
            params={"eventTypeSlug": EVENT_TYPE_SLUG, "username": USERNAME,
                    "start": day, "end": day, "timeZone": "UTC"},
            headers={"Authorization": f"Bearer {api_key}",
                     "cal-api-version": CAL_SLOTS_API_VERSION},
        )
        if r.status_code != 200:
            return []
        data = (r.json() or {}).get("data") or {}
    except (httpx.HTTPError, ValueError):
        return []

    out = []
    for _, slots in sorted(data.items()):
        for s in slots or []:
            start = s.get("start") if isinstance(s, dict) else s
            norm = _normalise_start(str(start))
            if norm:
                out.append({"utc": norm, "local": _to_host_local(norm)})
    if len(out) <= limit:
        return out
    # Spread across the day. Taking the first N always offered the earliest
    # morning slots, so a visitor asking for the afternoon was never shown one.
    step = (len(out) - 1) / (limit - 1)
    return [out[round(i * step)] for i in range(limit)]


def _to_host_local(iso_utc: str) -> str:
    """Render a UTC timestamp in the host's timezone, e.g. '2:00pm IST'.

    Visitors think in Vishal's local time, the API speaks UTC. Handing the
    model both removes the conversion step it gets wrong.
    """
    try:
        dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return iso_utc
    local = dt + timedelta(hours=5, minutes=30)  # Asia/Kolkata, no DST
    hour = local.hour % 12 or 12
    suffix = "am" if local.hour < 12 else "pm"
    minute = f":{local.minute:02d}" if local.minute else ""
    return f"{hour}{minute}{suffix} IST"


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


def _existing_booking(client: httpx.Client, api_key: str, email: str, start_iso: str):
    """Return this visitor's upcoming booking on the same day, if there is one.

    The model re-books when a visitor confirms a meeting that is already made
    ("yes book it" after the tool already succeeded), which would put two
    events on the calendar for one conversation. Cheaper to notice here than
    to ask the model not to.

    Returns None on any lookup failure: a missed booking is a worse outcome
    than an occasional duplicate, so this never blocks the happy path.
    """
    try:
        r = client.get(
            CAL_API,
            params={"status": "upcoming", "attendeeEmail": email},
            headers={"Authorization": f"Bearer {api_key}",
                     "cal-api-version": CAL_LIST_API_VERSION},
        )
        if r.status_code != 200:
            return None
        rows = (r.json() or {}).get("data") or []
    except (httpx.HTTPError, ValueError):
        return None

    day = start_iso[:10]
    for b in rows:
        if not isinstance(b, dict):
            continue
        # attendeeEmail is a server-side filter on some plans and a no-op on
        # others, so confirm the match here rather than trusting it.
        emails = {str((a or {}).get("email", "")).lower()
                  for a in (b.get("attendees") or [])}
        if email.lower() not in emails:
            continue
        norm = _normalise_start(str(b.get("start", "")))
        if norm and norm[:10] == day:
            return {"uid": b.get("uid"), "status": b.get("status", "accepted"), "start": norm}
    return None


def _reschedule(client: httpx.Client, api_key: str, uid: str, start_iso: str):
    """Move an existing booking to `start_iso`. Returns the new booking dict or None."""
    try:
        r = client.post(
            CAL_RESCHEDULE_API.format(uid=uid),
            json={"start": start_iso, "reschedulingReason": "Visitor changed the time in chat"},
            headers={"Authorization": f"Bearer {api_key}",
                     "cal-api-version": CAL_LIST_API_VERSION,
                     "Content-Type": "application/json"},
        )
        if r.status_code not in (200, 201):
            return None
        data = (r.json() or {}).get("data") or {}
    except (httpx.HTTPError, ValueError):
        return None
    norm = _normalise_start(str(data.get("start", start_iso))) or start_iso
    return {"uid": data.get("uid", uid), "status": data.get("status", "accepted"), "start": norm}


def book_meeting(name: str, email: str, start_time: str, topic: str = "") -> dict:
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
        with _make_client() as client:
            dup = _existing_booking(client, api_key, email.strip(), start)
            if dup is not None and dup["start"] != start:
                # Same visitor, same day, different time: they changed their
                # mind ("actually make it 10am"), or the model booked a guess
                # before they named a time and is now correcting it. Refusing
                # here froze the wrong time on the calendar. Move it instead.
                moved = _reschedule(client, api_key, dup["uid"], start)
                if moved is not None:
                    return {
                        "ok": True,
                        "uid": moved["uid"],
                        "status": moved["status"],
                        "starts_at": moved["start"],
                        "booking_url": BOOKING_URL.format(uid=moved["uid"]),
                        "rescheduled": True,
                        "reason": f"Moved your meeting from "
                                  f"{_to_host_local(dup['start'])} to "
                                  f"{_to_host_local(moved['start'])} on {moved['start'][:10]}.",
                    }
            if dup is not None:
                return {
                    "ok": True,
                    "uid": dup["uid"],
                    "status": dup["status"],
                    "starts_at": dup["start"],
                    "booking_url": BOOKING_URL.format(uid=dup["uid"]),
                    "already_booked": True,
                    "reason": f"You are already booked with Vishal at "
                              f"{_to_host_local(dup['start'])} on {dup['start'][:10]} "
                              f"- no need to book again.",
                }

            try:
                r = client.post(CAL_API, json=payload, headers=headers)
            except httpx.HTTPError:
                # The request may have committed before the response was lost.
                # Look before claiming failure: a visitor told "couldn't reach the
                # calendar" while an invite lands in their inbox books twice.
                landed = _existing_booking(client, api_key, email.strip(), start)
                if landed is not None and landed["start"] == start:
                    return {
                        "ok": True,
                        "uid": landed["uid"],
                        "status": landed["status"],
                        "starts_at": landed["start"],
                        "booking_url": BOOKING_URL.format(uid=landed["uid"]),
                        "recovered": True,
                    }
                raise

            if r.status_code in (200, 201):
                data = (r.json() or {}).get("data") or {}
                return {
                    "ok": True,
                    "uid": data.get("uid"),
                    "status": data.get("status", "accepted"),
                    "starts_at": data.get("start", start),
                    "booking_url": BOOKING_URL.format(uid=data.get("uid")),
                }

            detail = ""
            try:
                body = r.json()
                detail = str(body.get("error", {}).get("message") or body.get("message") or "")
            except ValueError:
                detail = r.text[:200]

            if r.status_code in (401, 403):
                return {"ok": False, "reason": "Booking is not configured right now."}

            low = detail.lower()
            unavailable = (
                r.status_code in (400, 409)
                or "available" in low or "busy" in low or "slot" in low
            )
            alternatives = _free_slots(client, api_key, start) if unavailable else []
            reason = (
                f"I couldn't book that time - he takes meetings "
                f"{WORKING_HOURS_LOCAL} IST, {WORKING_DAYS}, and that slot may "
                f"already be taken."
                if unavailable
                else "The calendar wouldn't take that booking."
            )
            return {"ok": False, "reason": reason, "alternatives": alternatives}
    except httpx.HTTPError:
        return {"ok": False, "reason": "I couldn't reach the calendar just then - try again in a moment?"}
