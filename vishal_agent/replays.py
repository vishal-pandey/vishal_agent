"""Session replay for vishalpandey.ai on our own storage, with rrweb (replaces LogRocket, whose quota ran out).
Same design as cordane's app/replays.py.

Browser (portfolio-website/replay.js): once the page has loaded and stayed on screen for 2 s, the self-hosted
rrweb recorder records the page as DOM changes, clicks, touches and scrolls. Mouse movement is not recorded and
everything typed into a field is masked. Events go in gzip batches every 5 s and when the page is hidden, to
POST /v1/rec. One recording id per tab visit (sessionStorage, new after 30 min idle). The chat sends that id with
each question (RunRequest.replay), so the WhatsApp alert carries a link to /replay/<id>?k=<signature>.

There is no admin login here, so the link itself is the key: k is an HMAC of the id (REPLAY_SECRET). Without it
the page and its events answer 404.

Storage: Cloudflare R2, one object per batch at rec/<yyyymmdd>/<id>/<page>-<seq>.json.gz. Recordings older than
KEEP_DAYS are deleted by a daily job. Off while any R2_* setting is empty.

Env: R2_ACCOUNT_ID, R2_BUCKET, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, REPLAY_SECRET,
     PUBLIC_URL (this API's address, default https://vishal-agent.codeshare.co.in)
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import hmac
import io
import json
import logging
import os
import random
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

log = logging.getLogger("vishal_agent.replays")

RID = re.compile(r"^(\d{8})[a-f0-9]{16}$")
KEEP_DAYS = 30
MAX_BATCH = 512 * 1024  # compressed bytes in one upload
MAX_RECORDING = 60 * 1024 * 1024  # decompressed bytes the replay page will load
MAX_SEQ = 5000
MAX_PAGE = 300
PER_MINUTE = 120  # uploads per client IP per worker
STATIC = Path(__file__).parent / "static"

router = APIRouter(include_in_schema=False)


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def enabled() -> bool:
    return all(_env(n) for n in ("R2_ACCOUNT_ID", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "REPLAY_SECRET"))


def sign(rid: str) -> str:
    return hmac.new(_env("REPLAY_SECRET").encode(), rid.encode(), hashlib.sha256).hexdigest()[:24]


def valid(rid: str, k: str) -> bool:
    return bool(enabled() and RID.match(rid or "") and k and hmac.compare_digest(sign(rid), k))


def link(rid: str) -> str:
    """Signed link to one recording, or "" when replay is off or the id is not one of ours."""
    if not enabled() or not RID.match(rid or ""):
        return ""
    return f"{_env('PUBLIC_URL', 'https://vishal-agent.codeshare.co.in').rstrip('/')}/replay/{rid}?k={sign(rid)}"


# ------------------------------------------------------------------ R2 (S3 API, SigV4)
class R2:
    """The few S3 calls we need, signed by hand (no boto3 in the image for four requests)."""

    def __init__(self, account: str, bucket: str, key_id: str, secret: str):
        self.host, self.bucket, self.key_id, self.secret = f"{account}.r2.cloudflarestorage.com", bucket, key_id, secret

    def _headers(self, method: str, key: str, query: dict[str, str], body: bytes) -> tuple[str, dict]:
        now = datetime.now(timezone.utc)
        amz, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
        scope = f"{day}/auto/s3/aws4_request"
        uri = f"/{self.bucket}" + (f"/{quote(key, safe='/~')}" if key else "")
        qs = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(query.items()))
        h = {"host": self.host, "x-amz-content-sha256": hashlib.sha256(body).hexdigest(), "x-amz-date": amz}
        signed = ";".join(sorted(h))
        canonical = "\n".join([method, uri, qs, "".join(f"{k}:{h[k]}\n" for k in sorted(h)), signed,
                               h["x-amz-content-sha256"]])
        k = f"AWS4{self.secret}".encode()
        for part in (day, "auto", "s3", "aws4_request"):
            k = hmac.new(k, part.encode(), hashlib.sha256).digest()
        to_sign = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(canonical.encode()).hexdigest()])
        sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
        h["Authorization"] = f"AWS4-HMAC-SHA256 Credential={self.key_id}/{scope}, SignedHeaders={signed}, Signature={sig}"
        del h["host"]
        return f"https://{self.host}{uri}" + (f"?{qs}" if qs else ""), h

    async def _call(self, c: httpx.AsyncClient, method: str, key: str = "", query: dict | None = None,
                    body: bytes = b"") -> httpx.Response:
        url, h = self._headers(method, key, query or {}, body)
        r = await c.request(method, url, headers=h, content=body or None)
        if r.status_code >= 300 and not (method == "GET" and r.status_code == 404):
            raise RuntimeError(f"R2 {method} {r.status_code}: {r.text[:200]}")
        return r

    async def put(self, key: str, body: bytes) -> None:
        async with httpx.AsyncClient(timeout=20) as c:
            await self._call(c, "PUT", key, body=body)

    async def keys(self, prefix: str, limit: int = 10000) -> list[str]:
        out, token = [], ""
        async with httpx.AsyncClient(timeout=20) as c:
            while len(out) < limit:
                q = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
                if token:
                    q["continuation-token"] = token
                root = ET.fromstring((await self._call(c, "GET", query=q)).content)
                ns = {"s": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {"s": ""}
                p = "s:" if ns["s"] else ""
                out += [e.text for e in root.iterfind(f"{p}Contents/{p}Key", ns) if e.text]
                token = (root.findtext(f"{p}NextContinuationToken", default="", namespaces=ns) or "")
                if (root.findtext(f"{p}IsTruncated", default="false", namespaces=ns) or "").lower() != "true" or not token:
                    break
        return out[:limit]

    async def get_many(self, keys: list[str]) -> list[bytes]:
        sem = asyncio.Semaphore(16)
        async with httpx.AsyncClient(timeout=30) as c:
            async def one(k):
                async with sem:
                    r = await self._call(c, "GET", k)
                    return r.content if r.status_code == 200 else b""
            return list(await asyncio.gather(*(one(k) for k in keys)))

    async def delete(self, keys: list[str]) -> None:
        sem = asyncio.Semaphore(16)
        async with httpx.AsyncClient(timeout=20) as c:
            async def one(k):
                async with sem:
                    await self._call(c, "DELETE", k)
            await asyncio.gather(*(one(k) for k in keys))


_store = None


def store():
    """The R2 bucket (tests swap in a dict-backed one)."""
    global _store
    if _store is None:
        _store = R2(_env("R2_ACCOUNT_ID"), _env("R2_BUCKET"), _env("R2_ACCESS_KEY_ID"), _env("R2_SECRET_ACCESS_KEY"))
    return _store


def prefix(rid: str) -> str:
    return f"rec/{rid[:8]}/{rid}/"


# ------------------------------------------------------------------ upload from the browser
_hits: dict[str, deque] = defaultdict(deque)


def _limited(ip: str, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= PER_MINUTE:
        return True
    q.append(now)
    if len(_hits) > 5000:  # forget idle clients
        for k in [k for k, v in _hits.items() if not v]:
            _hits.pop(k, None)
    return False


def _client(request: Request) -> str:
    return (request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "") or "?")


@router.post("/v1/rec", status_code=204)
async def upload(request: Request, rid: str = "", p: int = 0, s: int = 0, z: int = 0):
    nothing = Response(status_code=204)  # never an error in the visitor's console
    if not enabled() or not RID.match(rid) or not (0 <= p < MAX_PAGE and 0 <= s < MAX_SEQ):
        return nothing
    if _limited(_client(request)):
        return nothing
    day = datetime.strptime(rid[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
    if abs((datetime.now(timezone.utc) - day).days) > 2:
        return nothing  # an id from days ago: a stale tab
    body = await request.body()
    if not body or len(body) > MAX_BATCH:
        return nothing
    if z:
        if body[:2] != b"\x1f\x8b":
            return nothing
        stored = body
    else:
        if body[:1] != b"[":
            return nothing
        stored = gzip.compress(body, 6)
    try:
        await store().put(f"{prefix(rid)}{p:03d}-{s:05d}.json.gz", stored)
    except Exception as exc:  # noqa: BLE001
        log.warning("replay upload failed: %s", exc)
    return nothing


# ------------------------------------------------------------------ watching
async def events(rid: str) -> list[dict]:
    """Every event of one recording, in time order."""
    keys = sorted(await store().keys(prefix(rid), limit=MAX_SEQ))
    out, total = [], 0
    for blob in await store().get_many(keys):
        try:
            d = gzip.GzipFile(fileobj=io.BytesIO(blob)).read(MAX_RECORDING - total + 1)
        except Exception:  # noqa: BLE001  a torn upload: skip it, keep the rest
            continue
        total += len(d)
        if total > MAX_RECORDING:
            break
        try:
            batch = json.loads(d)
        except ValueError:
            continue
        out += [e for e in batch if isinstance(e, dict) and isinstance(e.get("timestamp"), (int, float))]
    out.sort(key=lambda e: e["timestamp"])
    return out


PRIVATE = {"cache-control": "no-store", "x-robots-tag": "noindex", "referrer-policy": "no-referrer"}


@router.get("/replay/{rid}")
async def replay_page(rid: str, k: str = ""):
    if not valid(rid, k):
        raise HTTPException(404)
    html = (STATIC / "replay.html").read_text().replace("{{RID}}", rid).replace("{{K}}", k)
    return HTMLResponse(html, headers=PRIVATE)


@router.get("/replay/{rid}/events")
async def replay_events(rid: str, k: str = ""):
    if not valid(rid, k):
        raise HTTPException(404)
    ev = await events(rid)
    return Response(gzip.compress(json.dumps(ev, separators=(",", ":")).encode(), 5),
                    media_type="application/json", headers={"content-encoding": "gzip", **PRIVATE})


@router.get("/replay-static/{name}")
async def replay_static(name: str):
    files = {"rrweb-player-2.2.2.min.js": "application/javascript", "rrweb-player-2.2.2.min.css": "text/css"}
    if name not in files:
        raise HTTPException(404)
    return Response((STATIC / name).read_bytes(), media_type=files[name],
                    headers={"cache-control": "public, max-age=31536000, immutable"})


# ------------------------------------------------------------------ 30-day cleanup
async def cleanup(today: datetime | None = None) -> int:
    """Delete the recordings of the days just past KEEP_DAYS (looks back a further 10 days in case a run was missed)."""
    if not enabled():
        return 0
    today = today or datetime.now(timezone.utc)
    n = 0
    for back in range(KEEP_DAYS + 1, KEEP_DAYS + 11):
        keys = await store().keys(f"rec/{(today - timedelta(days=back)).strftime('%Y%m%d')}/")
        if keys:
            await store().delete(keys)
            n += len(keys)
    return n


async def cleanup_forever() -> None:
    await asyncio.sleep(300 + random.random() * 600)  # several workers: don't all start at once
    while True:
        try:
            n = await cleanup()
            if n:
                log.info("old replay batches deleted: %s", n)
        except Exception as exc:  # noqa: BLE001
            log.warning("replay cleanup failed: %s", exc)
        await asyncio.sleep(24 * 3600)
