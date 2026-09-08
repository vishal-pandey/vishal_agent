"""Tests for the Cal.com booking tool. All HTTP is mocked — no live bookings."""

import json

import httpx
import pytest

from vishal_agent.tools.calcom import book_meeting

GOOD = dict(
    name="Priya Sharma",
    email="priya@acme.io",
    start_time="2026-09-10T14:00:00Z",
    topic="a consulting project",
)


def _patch(monkeypatch, handler):
    """Point the tool at a mock transport without touching its signature."""
    from vishal_agent.tools import calcom
    monkeypatch.setattr(
        calcom, "_make_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0),
    )


def test_successful_booking_returns_ok_and_uid(monkeypatch):
    def handler(request):
        return httpx.Response(201, json={"data": {"uid": "abc123", "status": "accepted",
                                                  "start": "2026-09-10T14:00:00Z"}})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**GOOD)
    assert out["ok"] is True
    assert out["uid"] == "abc123"
    assert "2026-09-10T14:00:00Z" in out["starts_at"]


def test_sends_required_headers_and_body(monkeypatch):
    """cal-api-version is mandatory; omitting it silently selects an older API."""
    seen = {}

    def handler(request):
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"data": {"uid": "u", "status": "accepted",
                                                  "start": GOOD["start_time"]}})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    book_meeting(**GOOD)

    assert seen["headers"]["authorization"] == "Bearer cal_live_test"
    assert seen["headers"]["cal-api-version"] == "2026-02-25"
    body = seen["body"]
    assert body["start"] == "2026-09-10T14:00:00Z"
    assert body["eventTypeSlug"] == "30min"
    assert body["username"] == "vishalpandey.ai"
    assert body["attendee"] == {"name": "Priya Sharma", "email": "priya@acme.io",
                                "timeZone": "UTC"}


def test_slot_unavailable_is_conversational_not_an_exception(monkeypatch):
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "no_available_users_found_error"}})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**GOOD)
    assert out["ok"] is False
    r = out["reason"].lower()
    # names the real constraint rather than a dead-end "not free"
    assert "book" in r or "taken" in r
    assert "09:00-17:00" in out["reason"]


def test_bad_email_rejected_before_any_http_call(monkeypatch):
    def handler(request):
        raise AssertionError("must not reach the API with an invalid email")
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**{**GOOD, "email": "not-an-email"})
    assert out["ok"] is False
    assert "email" in out["reason"].lower()


def test_bad_start_time_rejected_before_any_http_call(monkeypatch):
    def handler(request):
        raise AssertionError("must not reach the API with an unparseable time")
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**{**GOOD, "start_time": "next tuesday-ish"})
    assert out["ok"] is False
    assert "time" in out["reason"].lower()


def test_missing_api_key_fails_clearly(monkeypatch):
    monkeypatch.delenv("CALCOM_API_KEY", raising=False)
    out = book_meeting(**GOOD)
    assert out["ok"] is False
    assert "not configured" in out["reason"].lower()


def test_network_failure_does_not_raise(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("boom")
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**GOOD)
    assert out["ok"] is False
    assert "reach" in out["reason"].lower() or "try" in out["reason"].lower()


def test_topic_is_optional(monkeypatch):
    def handler(request):
        return httpx.Response(201, json={"data": {"uid": "u", "status": "accepted",
                                                  "start": GOOD["start_time"]}})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(name="A B", email="a@b.co", start_time="2026-09-10T14:00:00Z")
    assert out["ok"] is True


def test_naive_iso_time_is_treated_as_utc(monkeypatch):
    """The model sometimes omits the Z. Don't reject a booking over it."""
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"data": {"uid": "u", "status": "accepted",
                                                  "start": "2026-09-10T14:00:00Z"}})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**{**GOOD, "start_time": "2026-09-10T14:00:00"})
    assert out["ok"] is True
    assert seen["body"]["start"].endswith("Z")


def test_pending_status_is_reported_as_awaiting_confirmation(monkeypatch):
    """If the event type requires confirmation, say so rather than claiming it's booked."""
    def handler(request):
        return httpx.Response(201, json={"data": {"uid": "p1", "status": "pending",
                                                  "start": GOOD["start_time"]}})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**GOOD)
    assert out["ok"] is True
    assert out["status"] == "pending"


def test_tool_schema_builds_under_adk():
    """Regression: ADK introspects book_meeting to build the tool schema.

    A parameter annotated `Any` (added once for test injection) raised
    "typing.Any cannot be used with isinstance()" at REQUEST time, not import
    time -- so unit tests calling the function directly all passed while
    production returned 500 on every message. This exercises the path ADK
    actually takes.
    """
    from google.adk.tools import FunctionTool

    tool = FunctionTool(book_meeting)
    decl = tool._get_declaration()
    assert decl is not None, "ADK could not build a declaration for book_meeting"
    assert decl.name == "book_meeting"
    props = decl.parameters.properties
    assert set(props) == {"name", "email", "start_time", "topic"}, (
        f"tool schema must match the trained contract, got {sorted(props)}"
    )


def test_agent_exposes_the_tool_and_its_schema():
    """The whole chain: agent -> registered tool -> usable declaration."""
    from vishal_agent.agent import root_agent

    names = [getattr(t, "name", None) for t in (root_agent.tools or [])]
    assert "book_meeting" in names
    tool = next(t for t in root_agent.tools if getattr(t, "name", None) == "book_meeting")
    assert tool._get_declaration() is not None


# --- availability lookup on the failure path -------------------------------

def test_unavailable_booking_offers_real_alternatives(monkeypatch):
    """A dead-end rejection is useless; offer times that are actually free."""
    def handler(request):
        if request.url.path.endswith("/bookings"):
            return httpx.Response(400, json={"error": {"message": "no_available_users_found_error"}})
        return httpx.Response(200, json={"data": {"2026-09-10": [
            {"start": "2026-09-10T03:30:00.000Z"},
            {"start": "2026-09-10T08:30:00.000Z"},
            {"start": "2026-09-10T09:00:00.000Z"},
        ]}})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**GOOD)
    assert out["ok"] is False
    assert out["alternatives"], "must offer concrete free slots"
    utcs = [a["utc"] for a in out["alternatives"]]
    assert "2026-09-10T08:30:00Z" in utcs
    locals_ = [a["local"] for a in out["alternatives"]]
    assert "2pm IST" in locals_, f"expected a human IST label, got {locals_}"
    assert len(out["alternatives"]) <= 4, "keep the list short enough to say aloud"


def test_alternatives_lookup_failure_is_not_fatal(monkeypatch):
    """If the slots call fails, still return a usable rejection."""
    def handler(request):
        if request.url.path.endswith("/bookings"):
            return httpx.Response(400, json={"error": {"message": "unavailable"}})
        raise httpx.ConnectError("slots down")
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**GOOD)
    assert out["ok"] is False
    assert out.get("alternatives") == []


def test_slots_request_uses_its_own_api_version(monkeypatch):
    """/slots and /bookings require DIFFERENT cal-api-version values."""
    seen = {}

    def handler(request):
        if request.url.path.endswith("/bookings"):
            return httpx.Response(400, json={"error": {"message": "unavailable"}})
        seen["version"] = request.headers.get("cal-api-version")
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {}})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    book_meeting(**GOOD)
    assert seen["version"] == "2024-09-04"
    assert seen["params"]["eventTypeSlug"] == "30min"
    assert seen["params"]["username"] == "vishalpandey.ai"


def test_successful_booking_does_not_look_up_slots(monkeypatch):
    """Don't spend an API call on the happy path."""
    calls = {"slots": 0}

    def handler(request):
        if request.url.path.endswith("/bookings"):
            return httpx.Response(201, json={"data": {"uid": "u", "status": "accepted",
                                                      "start": GOOD["start_time"]}})
        calls["slots"] += 1
        return httpx.Response(200, json={"data": {}})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    assert book_meeting(**GOOD)["ok"] is True
    assert calls["slots"] == 0


def test_alternatives_span_the_day_not_just_the_morning(monkeypatch):
    """Offering the first four slots always meant 'morning', so an afternoon
    request was never shown an afternoon option."""
    slots = [{"start": f"2026-09-10T{h:02d}:{m:02d}:00.000Z"}
             for h in range(3, 12) for m in (0, 30)]

    def handler(request):
        if request.url.path.endswith("/bookings"):
            return httpx.Response(400, json={"error": {"message": "unavailable"}})
        return httpx.Response(200, json={"data": {"2026-09-10": slots}})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    alts = book_meeting(**GOOD)["alternatives"]
    hours = sorted(int(a["utc"][11:13]) for a in alts)
    assert hours[0] <= 4 and hours[-1] >= 10, f"should span the day, got {hours}"


# --- duplicate guard ---------------------------------------------------------

def test_repeat_confirmation_does_not_create_a_second_booking(monkeypatch):
    """A visitor who says "yes" after it is already booked must not be double-booked.

    Seen in the multi-turn eval: the model books correctly, the tool succeeds,
    and the next "yes book it" makes a SECOND call -- which would put two events
    on the calendar for one meeting.
    """
    posts = []

    def handler(request):
        if request.url.path.endswith("/bookings") and request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(201, json={"data": {"uid": "new", "status": "accepted",
                                                      "start": GOOD["start_time"]}})
        return httpx.Response(200, json={"data": [
            {"uid": "already", "status": "accepted", "start": "2026-09-10T14:00:00.000Z",
             "attendees": [{"email": "priya@acme.io"}]}]})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**GOOD)
    assert out["ok"] is True
    assert out["uid"] == "already", "must return the existing booking, not create one"
    assert out.get("already_booked") is True
    assert posts == [], "must not POST a duplicate booking"


def test_a_different_time_same_day_reschedules_the_existing_booking(monkeypatch):
    """Same visitor, same day, different time = they changed their mind.

    Two real cases: "tomorrow 4pm" booked, then "actually make it 10am"; and
    the model booking a guessed slot before the visitor named one, then
    calling again with the right time. Refusing the second call froze the
    wrong time on the calendar. Rescheduling makes both self-correct.
    """
    posts, reschedules = [], []

    def handler(request):
        if request.url.path.endswith("/bookings") and request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(201, json={"data": {"uid": "new", "status": "accepted",
                                                      "start": "2026-09-10T09:00:00Z"}})
        if request.url.path.endswith("/reschedule"):
            reschedules.append((request.url.path, json.loads(request.content)))
            return httpx.Response(201, json={"data": {"uid": "moved", "status": "accepted",
                                                      "start": "2026-09-10T09:00:00Z"}})
        return httpx.Response(200, json={"data": [
            {"uid": "already", "status": "accepted", "start": "2026-09-10T14:00:00.000Z",
             "attendees": [{"email": "priya@acme.io"}]}]})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**{**GOOD, "start_time": "2026-09-10T09:00:00Z"})
    assert out["ok"] is True
    assert out.get("rescheduled") is True
    assert out["uid"] == "moved"
    assert out["starts_at"] == "2026-09-10T09:00:00Z"
    assert out["booking_url"] == "https://cal.com/booking/moved"
    assert "2:30pm IST" in out["reason"] and "7:30pm IST" in out["reason"], out["reason"]
    assert posts == [], "must not create a second booking"
    assert reschedules and reschedules[0][0].endswith("/bookings/already/reschedule")
    assert reschedules[0][1]["start"] == "2026-09-10T09:00:00Z"


def test_reschedule_failure_falls_back_to_reporting_the_existing_booking(monkeypatch):
    """If Cal.com refuses the move, say what IS booked rather than double-book."""
    posts = []

    def handler(request):
        if request.url.path.endswith("/bookings") and request.method == "POST":
            posts.append(1)
            return httpx.Response(201, json={"data": {"uid": "new", "status": "accepted",
                                                      "start": "2026-09-10T09:00:00Z"}})
        if request.url.path.endswith("/reschedule"):
            return httpx.Response(400, json={"error": {"message": "slot unavailable"}})
        return httpx.Response(200, json={"data": [
            {"uid": "already", "status": "accepted", "start": "2026-09-10T14:00:00.000Z",
             "attendees": [{"email": "priya@acme.io"}]}]})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**{**GOOD, "start_time": "2026-09-10T09:00:00Z"})
    assert out["ok"] is True
    assert out.get("already_booked") is True
    assert out["uid"] == "already"
    assert posts == []


def test_a_different_day_books_normally(monkeypatch):
    """The guard must not block someone booking a genuine second meeting later."""
    posts = []

    def handler(request):
        if request.url.path.endswith("/bookings") and request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(201, json={"data": {"uid": "new", "status": "accepted",
                                                      "start": "2026-09-17T08:30:00Z"}})
        return httpx.Response(200, json={"data": [
            {"uid": "already", "status": "accepted", "start": "2026-09-10T14:00:00.000Z",
             "attendees": [{"email": "priya@acme.io"}]}]})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**{**GOOD, "start_time": "2026-09-17T08:30:00Z"})
    assert out["ok"] is True
    assert out["uid"] == "new"
    assert not out.get("already_booked")
    assert len(posts) == 1


def test_a_different_visitor_is_unaffected(monkeypatch):
    """The guard keys on the attendee's email, not on the day being busy."""
    posts = []

    def handler(request):
        if request.url.path.endswith("/bookings") and request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(201, json={"data": {"uid": "new", "status": "accepted",
                                                      "start": GOOD["start_time"]}})
        return httpx.Response(200, json={"data": [
            {"uid": "someone-else", "status": "accepted", "start": "2026-09-10T14:00:00.000Z",
             "attendees": [{"email": "other@person.io"}]}]})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**{**GOOD, "email": "priya@acme.io"})
    assert out["ok"] is True
    assert out["uid"] == "new"
    assert len(posts) == 1


def test_duplicate_lookup_failure_does_not_block_the_booking(monkeypatch):
    """If the lookup fails, book anyway -- a missed booking is worse than a rare dup."""
    posts = []

    def handler(request):
        if request.url.path.endswith("/bookings") and request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(201, json={"data": {"uid": "new", "status": "accepted",
                                                      "start": GOOD["start_time"]}})
        raise httpx.ConnectError("lookup down")
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**GOOD)
    assert out["ok"] is True
    assert len(posts) == 1


def test_success_returns_a_real_booking_url(monkeypatch):
    """Without one the model invents a link.

    A live booking produced "https://vishal-agent.codesshare.co.in/bookings/<uid>"
    -- a hostname that does not exist, with the domain misspelled. Handing it
    the real URL is the same fix as handing it the date: remove the guess.
    """
    def handler(request):
        if request.url.path.endswith("/bookings") and request.method == "POST":
            return httpx.Response(201, json={"data": {"uid": "abc123", "status": "accepted",
                                                      "start": GOOD["start_time"]}})
        return httpx.Response(200, json={"data": []})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**GOOD)
    assert out["booking_url"] == "https://cal.com/booking/abc123"


def test_already_booked_also_carries_the_url(monkeypatch):
    def handler(request):
        if request.url.path.endswith("/bookings") and request.method == "POST":
            raise AssertionError("must not book a duplicate")
        return httpx.Response(200, json={"data": [
            {"uid": "already", "status": "accepted", "start": "2026-09-10T14:00:00.000Z",
             "attendees": [{"email": "priya@acme.io"}]}]})
    _patch(monkeypatch, handler)
    monkeypatch.setenv("CALCOM_API_KEY", "cal_live_test")
    out = book_meeting(**GOOD)
    assert out["booking_url"] == "https://cal.com/booking/already"
