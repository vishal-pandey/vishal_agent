"""Session replay: uploads, signed links, playback, cleanup. R2 is a dict: nothing leaves the machine."""

import asyncio
import gzip
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vishal_agent import notify, replays


class FakeStore:
    def __init__(self):
        self.d = {}

    async def put(self, key, body):
        self.d[key] = body

    async def keys(self, prefix, limit=10000):
        return sorted(k for k in self.d if k.startswith(prefix))[:limit]

    async def get_many(self, keys):
        return [self.d.get(k, b"") for k in keys]

    async def delete(self, keys):
        for k in keys:
            self.d.pop(k, None)


@pytest.fixture
def store(monkeypatch):
    for k, v in {"R2_ACCOUNT_ID": "acc", "R2_BUCKET": "b", "R2_ACCESS_KEY_ID": "id",
                 "R2_SECRET_ACCESS_KEY": "s", "REPLAY_SECRET": "test-secret",
                 "PUBLIC_URL": "https://agent.test"}.items():
        monkeypatch.setenv(k, v)
    fake = FakeStore()
    monkeypatch.setattr(replays, "_store", fake)
    replays._hits.clear()
    return fake


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(replays.router)
    return TestClient(app)


def rid_today(tail="0123456789abcdef"):
    return datetime.now(timezone.utc).strftime("%Y%m%d") + tail


def test_link_is_signed_and_checked(store):
    rid = rid_today()
    url = replays.link(rid)
    assert url.startswith(f"https://agent.test/replay/{rid}?k=")
    k = url.split("k=")[1]
    assert replays.valid(rid, k)
    assert not replays.valid(rid, "0" * 24)
    assert not replays.valid(rid_today("fedcba9876543210"), k)  # a signature is for one recording only
    assert replays.link("not-an-id") == ""


def test_off_without_storage(monkeypatch):
    monkeypatch.delenv("R2_BUCKET", raising=False)
    assert not replays.enabled()
    assert replays.link(rid_today()) == ""


def test_upload_gzip_and_plain_then_play(store, client):
    rid = rid_today()
    first = [{"type": 4, "data": {"href": "https://vishalpandey.ai/"}, "timestamp": 1000},
             {"type": 2, "data": {}, "timestamp": 1001}]
    second = [{"type": 3, "data": {}, "timestamp": 1500}]
    r = client.post(f"/v1/rec?rid={rid}&p=0&s=0&z=1", content=gzip.compress(json.dumps(first).encode()),
                    headers={"content-type": "text/plain"})
    assert r.status_code == 204
    assert client.post(f"/v1/rec?rid={rid}&p=0&s=1", content=json.dumps(second)).status_code == 204
    assert sorted(store.d) == [f"rec/{rid[:8]}/{rid}/000-00000.json.gz", f"rec/{rid[:8]}/{rid}/000-00001.json.gz"]

    k = replays.sign(rid)
    page = client.get(f"/replay/{rid}?k={k}")
    assert page.status_code == 200 and rid in page.text and "rrwebPlayer" in page.text
    assert page.headers["cache-control"] == "no-store"
    ev = client.get(f"/replay/{rid}/events?k={k}").json()
    assert [e["timestamp"] for e in ev] == [1000, 1001, 1500]


def test_no_key_no_replay(store, client):
    rid = rid_today()
    assert client.get(f"/replay/{rid}").status_code == 404
    assert client.get(f"/replay/{rid}?k=nope").status_code == 404
    assert client.get(f"/replay/{rid}/events?k=nope").status_code == 404


def test_rejects_junk_quietly(store, client):
    old = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y%m%d") + "0123456789abcdef"
    for url, body in [("/v1/rec?rid=bad&p=0&s=0", b"[]"),                       # not an id
                      (f"/v1/rec?rid={old}&p=0&s=0", b"[]"),                    # stale tab
                      (f"/v1/rec?rid={rid_today()}&p=0&s=0&z=1", b"[]"),        # says gzip, isn't
                      (f"/v1/rec?rid={rid_today()}&p=0&s=0", b"<html>"),        # not JSON
                      (f"/v1/rec?rid={rid_today()}&p=0&s=0", b"[" + b" " * (600 * 1024) + b"]")]:  # too big
        assert client.post(url, content=body).status_code == 204
    assert store.d == {}


def test_rate_limit_per_client(store, client, monkeypatch):
    monkeypatch.setattr(replays, "PER_MINUTE", 3)
    rid = rid_today()
    for s in range(5):
        client.post(f"/v1/rec?rid={rid}&p=0&s={s}", content=b"[]")
    assert len(store.d) == 3


def test_static_player_only_known_files(client):
    assert client.get("/replay-static/rrweb-player-2.2.2.min.js").status_code == 200
    assert client.get("/replay-static/..%2Fserver.py").status_code == 404


def test_cleanup_deletes_only_old_days(store):
    today = datetime(2026, 11, 21, tzinfo=timezone.utc)
    old = (today - timedelta(days=31)).strftime("%Y%m%d")
    new = (today - timedelta(days=29)).strftime("%Y%m%d")
    store.d = {f"rec/{old}/{old}aaaaaaaaaaaaaaaa/000-00000.json.gz": b"x",
               f"rec/{new}/{new}bbbbbbbbbbbbbbbb/000-00000.json.gz": b"y"}
    assert asyncio.run(replays.cleanup(today)) == 1
    assert list(store.d) == [f"rec/{new}/{new}bbbbbbbbbbbbbbbb/000-00000.json.gz"]


def test_whatsapp_alert_carries_the_link():
    text = notify.format_turn("What does Vishal do?", "He leads engineering.", "s1", 1, "IN",
                              replay="https://agent.test/replay/x?k=y")
    assert text.endswith("\n▶️ Watch the visit: https://agent.test/replay/x?k=y")
    assert "Watch" not in notify.format_turn("q", "a", "s1", 1)
