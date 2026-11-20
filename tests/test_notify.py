"""WhatsApp chat alerts. All HTTP is mocked: no real WhatsApp messages."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from vishal_agent import notify
from vishal_agent.server import AnswerTracker, turn_number


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("WA_CHAT_ID", "120363000000000000@g.us")
    monkeypatch.setenv("WAHA_URL", "http://waha.test")
    monkeypatch.setenv("WAHA_API_KEY", "k-test")
    monkeypatch.setenv("WAHA_SESSION", "cordane")
    monkeypatch.setenv("WA_CHAT_PER_HOUR", "40")
    notify._recent.clear()


def _capture(monkeypatch, status=201):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(status, json={})
    monkeypatch.setattr(notify, "_make_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5))
    return sent


async def _drain():
    await asyncio.gather(*list(notify._tasks))


# ---------------------------------------------------------------- message text
def test_first_message_is_a_new_chat():
    msg = notify.format_turn("what does he do?", "He leads engineering.", "session-ab12", 1, "IN")
    assert msg.startswith("💬 *New chat on vishalpandey.ai*")
    assert "❓ what does he do?" in msg
    assert "🤖 He leads engineering." in msg
    assert "🌍 IN" in msg and "🧵 session-ab12" in msg


def test_follow_up_shows_message_number():
    msg = notify.format_turn("and before that?", "LimeChat.", "session-ab12", 3)
    assert msg.startswith("💬 *Chat continued* · message 3")
    assert "🌍" not in msg  # no country header, no empty flag


def test_long_text_is_clipped_to_one_line():
    msg = notify.format_turn("q\n" * 400, "a " * 1000, "s", 1)
    question = msg.split("\n")[1]
    answer = msg.split("\n")[2]
    assert len(question) <= len("❓ ") + notify.QUESTION_MAX
    assert len(answer) <= len("🤖 ") + notify.ANSWER_MAX
    assert answer.endswith("…")


def test_missing_and_unfinished_answers_say_so():
    assert "no answer" in notify.format_turn("hi", "", "s", 1)
    assert "(visitor left mid-answer)" in notify.format_turn("hi", "Vishal is", "s", 1, finished=False)


# ---------------------------------------------------------------- sending
def test_posts_to_waha_with_key_session_and_group(monkeypatch):
    sent = _capture(monkeypatch)

    async def go():
        assert notify.chat_turn("hello?", "Hi!", "session-1", 1, "IN") is True
        await _drain()
    asyncio.run(go())

    assert len(sent) == 1
    req = sent[0]
    assert str(req.url) == "http://waha.test/api/sendText"
    assert req.headers["X-Api-Key"] == "k-test"
    body = json.loads(req.content)
    assert body["session"] == "cordane"
    assert body["chatId"] == "120363000000000000@g.us"
    assert body["linkPreview"] is False
    assert "❓ hello?" in body["text"]


def test_off_without_a_group(monkeypatch):
    monkeypatch.setenv("WA_CHAT_ID", "")
    sent = _capture(monkeypatch)

    async def go():
        assert notify.chat_turn("hello?", "Hi!", "s", 1) is False
    asyncio.run(go())
    assert sent == []


def test_blank_question_is_not_sent(monkeypatch):
    sent = _capture(monkeypatch)

    async def go():
        assert notify.chat_turn("   ", "Hi!", "s", 1) is False
    asyncio.run(go())
    assert sent == []


def test_whatsapp_outage_never_raises(monkeypatch):
    sent = _capture(monkeypatch, status=500)

    async def go():
        assert notify.chat_turn("hello?", "Hi!", "s", 1) is True
        await _drain()  # the 500 is swallowed and logged
    asyncio.run(go())
    assert len(sent) == 1


def test_hourly_cap(monkeypatch):
    monkeypatch.setenv("WA_CHAT_PER_HOUR", "3")
    assert [notify.allow(now=t) for t in (0, 1, 2, 3)] == [True, True, True, False]
    assert notify.allow(now=3602) is True  # the window slides


# ---------------------------------------------------------------- server helpers
def _event(text="", author="vishal_agent", partial=False, final=False):
    parts = [SimpleNamespace(text=text)] if text else []
    return SimpleNamespace(author=author, partial=partial, content=SimpleNamespace(parts=parts),
                           is_final_response=lambda: final)


def test_tracker_prefers_the_full_text_over_deltas():
    t = AnswerTracker()
    for chunk in ("Vish", "al leads"):
        t.see(_event(chunk, partial=True))
    assert t.answer == "Vishal leads" and not t.finished
    t.see(_event("Vishal leads engineering.", final=True))
    assert t.answer == "Vishal leads engineering." and t.finished


def test_tracker_keeps_deltas_when_the_stream_is_cut():
    t = AnswerTracker()
    t.see(_event("Half an ans", partial=True))
    assert t.answer == "Half an ans" and not t.finished


def test_turn_number_counts_previous_questions():
    assert turn_number(None) == 1
    session = SimpleNamespace(events=[SimpleNamespace(author="user"), SimpleNamespace(author="vishal_agent"),
                                      SimpleNamespace(author="user")])
    assert turn_number(session) == 3
