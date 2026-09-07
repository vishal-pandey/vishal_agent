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
    assert "available" in out["reason"].lower() or "free" in out["reason"].lower()


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
