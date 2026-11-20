"""WhatsApp alerts when someone uses the chatbot on vishalpandey.ai.

Each chat turn (visitor question + the agent's answer) is posted to a WhatsApp group
through the WAHA server in the homelab cluster (namespace waha), the same way
cordane's app/notify.py sends its shop alerts.

Fire-and-forget: a WhatsApp outage never slows or breaks a chat; failures are only
logged. Off unless WA_CHAT_ID is set (a group id like 1203...@g.us).

Env:
  WAHA_URL           default http://waha.waha.svc.cluster.local
  WAHA_API_KEY       WAHA's X-Api-Key
  WAHA_SESSION       the WAHA session (logged-in WhatsApp number) that posts
  WA_CHAT_ID         the group to post into; empty = alerts off
  WA_CHAT_PER_HOUR   cap per worker process, so a bot can't flood the group (default 40)
"""

import asyncio
import logging
import os
import time
from collections import deque

import httpx

log = logging.getLogger("vishal_agent.notify")
_tasks: set[asyncio.Task] = set()  # keep references so tasks aren't garbage-collected mid-flight
_recent: deque[float] = deque()

QUESTION_MAX = 500
ANSWER_MAX = 700


def _cfg() -> dict:
    return {
        "url": os.environ.get("WAHA_URL", "http://waha.waha.svc.cluster.local"),
        "key": os.environ.get("WAHA_API_KEY", ""),
        "session": os.environ.get("WAHA_SESSION", "cordane"),
        "chat": os.environ.get("WA_CHAT_ID", ""),
        "per_hour": int(os.environ.get("WA_CHAT_PER_HOUR", "40")),
    }


def enabled() -> bool:
    c = _cfg()
    return bool(c["chat"] and c["url"])


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())  # one line: WhatsApp alerts stay scannable
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def format_turn(question: str, answer: str, session_id: str, turn: int,
                country: str = "", finished: bool = True) -> str:
    """The group message for one chat turn."""
    head = "💬 *New chat on vishalpandey.ai*" if turn <= 1 else f"💬 *Chat continued* · message {turn}"
    if answer:
        reply = _clip(answer, ANSWER_MAX) + ("" if finished else " (visitor left mid-answer)")
    else:
        reply = "_no answer: the visitor left or the model errored_"
    meta = " · ".join(x for x in (f"🌍 {country}" if country else "", f"🧵 {session_id}") if x)
    return f"{head}\n❓ {_clip(question, QUESTION_MAX)}\n🤖 {reply}\n{meta}"


def allow(now: float | None = None) -> bool:
    """Hourly cap per process. Returns False (and drops the alert) when over it."""
    now = time.monotonic() if now is None else now
    while _recent and now - _recent[0] > 3600:
        _recent.popleft()
    if len(_recent) >= _cfg()["per_hour"]:
        return False
    _recent.append(now)
    return True


def _make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10)


async def _deliver(text: str) -> None:
    c = _cfg()
    headers = {"X-Api-Key": c["key"]} if c["key"] else {}
    async with _make_client() as client:
        r = await client.post(f"{c['url'].rstrip('/')}/api/sendText", headers=headers,
                              json={"session": c["session"], "chatId": c["chat"], "text": text,
                                    "linkPreview": False})
        r.raise_for_status()


async def _safe(text: str) -> None:
    try:
        await _deliver(text)
    except Exception as exc:  # noqa: BLE001  alerts must never take the chat down
        log.warning("whatsapp alert failed: %s", exc)


def chat_turn(question: str, answer: str, session_id: str, turn: int,
              country: str = "", finished: bool = True) -> bool:
    """Post one chat turn to the group. Returns True if an alert was queued."""
    if not enabled() or not (question or "").strip() or not allow():
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    t = loop.create_task(_safe(format_turn(question, answer, session_id, turn, country, finished)))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return True
