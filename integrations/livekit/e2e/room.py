"""twinmemory-livekit in a real LiveKit room, against the real twin memory API.

    cd packages/livekit && uv run python e2e/room.py

Needs: the LiveKit dev server on ws://localhost:7880 (devkey/secret), twin memory on
TWIN_MEMORY_BASE_URL, TWIN_MEMORY_API_KEY (from the environment, or E2E_ENV, a KEY=VALUE file), and
MEMORY_CONTROL_SECRET to delete the users it made (from the environment, or E2E_CONTROL_ENV, by
default the .env of a twin-memory-frontend checkout beside this repository, as memory-up.sh lays
them out). Exit 0 only if every check holds. The key and the secret are never printed.

Three calls, one end user `e2e-<hex>`, each in a new room and so a new job:
  1. identity = the user, no metadata -> bound from the participant. Two turns with a fact.
     Then the driver polls twin memory until a search finds the fact.
  2. same identity, new room. Turn 1 says a call-2 marker; the driver waits until that has landed
     in memory, then asks for the fact: the model must be shown it inside <memory>, and none of
     call 2's own turns.
  3. a different participant identity (`kiosk-<hex>`) and dispatch metadata
     {"twinmemory_user_id": user}: the user must come from the metadata, recall must work for
     them, and nothing may be saved under the kiosk identity.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from livekit import api, rtc
from twinmemory import AsyncMemory, NotFoundError

from twinmemory_livekit import participant_id

warnings.filterwarnings("ignore", message="The HMAC key")  # the 6-byte dev secret
HERE = Path(__file__).resolve().parent
LK_URL = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
LK_KEY = os.environ.get("LIVEKIT_API_KEY", "devkey")
LK_SECRET = os.environ.get("LIVEKIT_API_SECRET", "secret")
AGENT_NAME = "twinmemory-e2e"
ENV_FILE = os.environ.get("E2E_ENV", "")
CONTROL_ENV = os.environ.get(
    "E2E_CONTROL_ENV", str(HERE.parents[3] / "twin-memory-frontend" / ".env")
)
# The organisation and project the key belongs to, asked of memory at the start.
CONTROL_ORG, CONTROL_PROJECT = "", ""

FACT = "My locker code at the Alfama gym is 4417."
FACT_TOKEN = "4417"
CALL1_TURN2 = "I usually train there on Tuesday evenings."
CALL2_MARKER = "Call two note: my favourite colour is ultramarine."
CALL2_TOKEN = "ultramarine"
QUESTION = "What is my locker code at the gym?"

FAILURES: list[str] = []


def say(msg: str) -> None:
    print(f"[e2e {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def check(ok: bool, what: str) -> None:
    say(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        FAILURES.append(what)


def read_env(path: str, *names: str) -> dict[str, str]:
    found: dict[str, str] = {}
    try:
        for line in (Path(path).read_text() if path else "").splitlines():
            m = re.match(r"\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
            if m and m.group(1) in names:
                found[m.group(1)] = m.group(2).strip().strip("'\"")
    except FileNotFoundError:
        pass
    return found


# ------------------------------------------------------------------------- the user's side --


class Call:
    """One participant in one room: dispatches the agent, joins, says things, reads replies."""

    def __init__(self, room: str, identity: str, metadata: dict[str, str] | None = None) -> None:
        self.room_name, self.identity, self.metadata = room, identity, metadata
        self.room = rtc.Room()
        self.replies: asyncio.Queue[tuple[str, float]] = asyncio.Queue()
        self.agent: str | None = None
        self.ready = asyncio.Event()
        self.turns: list[dict[str, Any]] = []
        self._tasks: set[asyncio.Task[None]] = set()

    def _agent_state(self, p: rtc.RemoteParticipant) -> None:
        if p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
            self.agent = p.identity
            (
                self.ready.set
                if p.attributes.get("lk.agent.state") == "listening"
                else self.ready.clear
            )()

    async def __aenter__(self) -> Call:
        lk = api.LiveKitAPI(
            url=LK_URL.replace("ws", "http", 1), api_key=LK_KEY, api_secret=LK_SECRET
        )
        try:
            # departure_timeout 5 s: the job ends soon after we leave (server default is 20 s)
            await lk.room.create_room(
                api.CreateRoomRequest(name=self.room_name, empty_timeout=30, departure_timeout=5)
            )
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=AGENT_NAME,
                    room=self.room_name,
                    metadata=json.dumps(self.metadata) if self.metadata else "",
                )
            )
        finally:
            await lk.aclose()
        token = (
            api.AccessToken(LK_KEY, LK_SECRET)
            .with_identity(self.identity)
            .with_grants(api.VideoGrants(room_join=True, room=self.room_name))
            .to_jwt()
        )
        self.room.on("participant_connected", self._agent_state)
        self.room.on("participant_attributes_changed", lambda _c, p: self._agent_state(p))

        def on_text(reader: rtc.TextStreamReader, sender: str) -> None:
            if sender != self.agent:
                return

            async def read() -> None:
                text = await reader.read_all()
                if text.strip():
                    self.replies.put_nowait((text, time.perf_counter()))

            t = asyncio.create_task(read())
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

        self.room.register_text_stream_handler("lk.transcription", on_text)
        t0 = time.perf_counter()
        await self.room.connect(LK_URL, token)
        for p in self.room.remote_participants.values():
            self._agent_state(p)
        await asyncio.wait_for(self.ready.wait(), 20)
        self.ready_ms = (time.perf_counter() - t0) * 1000
        return self

    async def say(self, text: str, timeout: float = 15) -> str:
        await asyncio.wait_for(self.ready.wait(), timeout)
        sent = time.perf_counter()
        await self.room.local_participant.send_text(text, topic="lk.chat")
        reply, at = await asyncio.wait_for(self.replies.get(), timeout)
        self.turns.append(
            {
                "said": text,
                "reply": reply,
                "rtt_ms": round((at - sent) * 1000, 1),
                "sent_at": time.time() - (time.perf_counter() - sent),
            }
        )
        self.ready.clear()
        if self.agent in self.room.remote_participants:
            self._agent_state(self.room.remote_participants[self.agent])
        return reply

    async def __aexit__(self, *_: object) -> None:
        self.left_at = time.time()
        await self.room.disconnect()


# ------------------------------------------------------------------------ the agent's side --


class Events:
    def __init__(self, path: Path) -> None:
        self.path = path

    def all(self, room: str | None = None, ev: str | None = None) -> list[dict[str, Any]]:
        out = []
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                e = json.loads(line)
                if (room is None or e.get("room") == room) and (ev is None or e["ev"] == ev):
                    out.append(e)
        return out

    async def wait(self, pred: Callable[[], Any], timeout: float, what: str) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = pred()
            if asyncio.iscoroutine(r):
                r = await r
            if r:
                return r
            await asyncio.sleep(0.1)
        raise AssertionError(f"timed out after {timeout}s waiting for {what}")


async def found_in_memory(
    memory: AsyncMemory, user: str, query: str, token: str, timeout: float = 15.0
) -> float | None:
    """Seconds until a search for `query` returns a passage holding `token`; None if never."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        try:
            r = await memory.user(user).search(query, fast=True)
            if any(token in h.text for h in r.hits) or any(token in k for k in r.known):
                return time.monotonic() - t0
        except NotFoundError:
            pass
        await asyncio.sleep(0.25)
    return None


def memory_text(block: str) -> str:
    m = re.search(r"<memory>\n(.*)\n</memory>", block, re.S)
    return m.group(1) if m else ""


# ------------------------------------------------------------------------------- the test --


async def scenario(ev: Events, memory: AsyncMemory, user: str, kiosk: str) -> dict[str, Any]:
    # Bound by participant, a caller's memory is its own namespace (participant_id), apart from
    # the ids a backend writes; call 3's backend names that same id in the job's metadata.
    uid, kiosk_id = participant_id(user), participant_id(kiosk)
    timings: dict[str, Any] = {}
    tag = uuid.uuid4().hex[:6]

    # ---- call 1: a new user, bound from the participant, says a fact
    r1 = f"e2e-call1-{tag}"
    say(f"call 1: room {r1}, identity {user}, no metadata")
    async with Call(r1, user) as c1:
        a = await c1.say(FACT)
        b = await c1.say(CALL1_TURN2)
    timings["call1"] = c1.turns
    check(
        [a, b] == ["MEMORY-SEEN:no", "MEMORY-SEEN:no"],
        f"call 1 replies say no memory (got {[a, b]})",
    )
    bound = ev.all(r1, "bound")
    check(
        bool(bound) and bound[0]["user_id"] == uid and bound[0]["via"] == "participant",
        f"call 1 bound to participant_id({user}) = {uid} ({bound[:1]})",
    )
    check(ev.all(r1, "job_start")[0]["user_from_metadata"] is None, "call 1 metadata named no user")
    flushed = await ev.wait(lambda: ev.all(r1, "flushed"), 15, "call 1 flush on session close")
    check(
        flushed[0]["unsaved"] == 0,
        f"call 1 flushed on close, unsaved={flushed[0]['unsaved']} in {flushed[0]['ms']} ms",
    )
    landed = await found_in_memory(memory, uid, "locker code at the Alfama gym", FACT_TOKEN)
    since_said = time.time() - c1.turns[0]["sent_at"]
    check(
        landed is not None,
        f"fact searchable in twin memory after call 1 (by {since_said:.2f} s "
        "after it was said; polling starts once the session has closed)",
    )
    timings["fact_searchable_s"] = round(since_said, 2)

    # ---- call 2: same identity, new room and job; recall shows call 1, never call 2
    r2 = f"e2e-call2-{tag}"
    say(f"call 2: room {r2}, identity {user}, no metadata")
    async with Call(r2, user) as c2:
        await c2.say(CALL2_MARKER)
        # let call 2's own turn land in memory first, so leaving it out is the package's doing
        marker = await found_in_memory(memory, uid, "favourite colour", CALL2_TOKEN)
        check(
            marker is not None,
            "call 2's own turn landed in memory before the question "
            f"({marker and round(marker, 2)} s after it was said)",
        )
        timings["call2_turn_searchable_s"] = marker and round(marker, 2)
        ans = await c2.say(QUESTION)
    timings["call2"] = c2.turns
    check(ans == "MEMORY-SEEN:yes", f"call 2 question reply says memory seen (got {ans!r})")
    calls = [
        e for e in ev.all(r2, "llm_call") if e["context"] and e["context"][-1] == ["user", QUESTION]
    ]
    check(len(calls) >= 1, f"LLM called for the call-2 question ({len(calls)} calls)")
    if calls:
        ctx = calls[-1]["context"]
        blocks = calls[-1]["memory_blocks"]
        check(
            len(blocks) == 1,
            f"exactly one <memory> block in the question's context ({len(blocks)})",
        )
        block = memory_text(blocks[0]) if blocks else ""
        check(FACT_TOKEN in block, "the <memory> block holds the call-1 fact (4417)")
        check(
            CALL2_TOKEN not in block and QUESTION not in block,
            "the <memory> block holds none of call 2's own turns",
        )
        check(
            len(ctx) >= 2 and ctx[-2][0] == "assistant" and "<memory>" in ctx[-2][1],
            "memory sits just before the user's question",
        )
        check(
            not any(t == FACT for _, t in ctx if "<memory>" not in t),
            "the fact reached call 2 only through memory, not as a turn of the call",
        )
    # assert that what is saved for call 2 is the call's turns and not the recalled block
    # (checked below via the call-1/2 searches; memory text is marked and skipped by capture)

    # ---- call 3: the metadata path; the participant is someone else's device
    r3 = f"e2e-call3-{tag}"
    say(f"call 3: room {r3}, identity {kiosk}, metadata twinmemory_user_id={uid}")
    async with Call(r3, kiosk, {"twinmemory_user_id": uid}) as c3:
        ans3 = await c3.say(QUESTION)
    timings["call3"] = c3.turns
    start3 = ev.all(r3, "job_start")
    from_metadata = start3[0]["user_from_metadata"] if start3 else None
    check(
        from_metadata == uid,
        f"call 3 user came from job metadata before connect ({from_metadata})",
    )
    bound3 = ev.all(r3, "bound")
    check(
        bool(bound3) and bound3[0]["user_id"] == uid and bound3[0]["via"] == "metadata",
        "call 3 bound via metadata, not the kiosk participant",
    )
    check(ans3 == "MEMORY-SEEN:yes", f"call 3 reply says memory seen (got {ans3!r})")
    q3 = [
        e for e in ev.all(r3, "llm_call") if e["context"] and e["context"][-1] == ["user", QUESTION]
    ]
    check(
        bool(q3) and FACT_TOKEN in memory_text((q3[-1]["memory_blocks"] or [""])[0]),
        "call 3 <memory> holds the fact",
    )
    await ev.wait(lambda: ev.all(r3, "flushed"), 15, "call 3 flush on session close")
    try:
        await memory.user(kiosk_id).search("locker", fast=True)
        kiosk_empty = False
    except NotFoundError:
        kiosk_empty = True
    check(kiosk_empty, f"nothing saved under the kiosk identity {kiosk}")

    # ---- what was saved: one thread per call, the turns as said, never what recall added
    async def saved() -> Any:
        u = memory.user(uid)
        try:
            threads = {h.thread for h in (await u.latest(k=20)).passages}
            asked = (await u.grep(QUESTION)).total
        except NotFoundError:
            return None
        return (threads, asked) if len(threads) >= 3 and asked >= 2 else None

    try:
        threads, asked = await ev.wait(saved, 15, "all three calls' turns searchable")
        check(
            len(threads) == 3,
            f"twin memory holds 3 threads for {user}, one per call ({len(threads)})",
        )
        check(asked == 2, f"call 2's and call 3's question both saved under {user} ({asked})")
    except AssertionError as e:
        check(False, str(e))
    u = memory.user(uid)
    recalled = (await u.grep("Quoted records from earlier conversations")).total
    check(
        recalled == 0 and (await u.grep("<memory>")).total == 0,
        f"no recalled <memory> block was saved as a turn ({recalled})",
    )
    check((await u.grep(FACT_TOKEN)).total == 1, "the fact is saved once, from call 1 only")

    # ---- every job shut down with memory closed (from_job registers memory.aclose)
    rooms = [r1, r2, r3]
    shut = await ev.wait(
        lambda: (lambda s: s if len(s) == 3 else None)(
            [e for e in ev.all(ev="shutdown") if e["room"] in rooms]
        ),
        30,
        "3 job shutdowns",
    )
    check(
        all(e["closed"] for e in shut),
        f"memory.aclose ran before each job ended ({[e['reason'] for e in shut]})",
    )
    timings["recall"] = [
        {"room": e["room"].split("-")[1], "said": e["context"][-1][1][:40], **(e["recall"] or {})}
        for e in ev.all(ev="llm_call")
        if e["room"] in rooms
    ]
    return timings


async def cleanup(users: list[str], secret: str | None) -> None:
    if not secret:
        say("  no MEMORY_CONTROL_SECRET: e2e users left in memory: " + ", ".join(users))
        return
    async with httpx.AsyncClient(timeout=10) as http:
        for u in users:
            r = await http.delete(
                "http://localhost:8210/v1/control/accounts",
                params={"org": CONTROL_ORG, "project": CONTROL_PROJECT, "user": u},
                headers={"Authorization": f"Bearer {secret}"},
            )
            say(f"cleanup: DELETE user {u} -> {r.status_code}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-users", action="store_true", help="skip deleting the e2e users")
    args = ap.parse_args()

    env = dict(os.environ)
    for k, v in read_env(ENV_FILE, "TWIN_MEMORY_BASE_URL", "TWIN_MEMORY_API_KEY").items():
        env.setdefault(k, v)
    if not env.get("TWIN_MEMORY_API_KEY"):
        say(f"FAIL: no TWIN_MEMORY_API_KEY in the environment or {ENV_FILE}")
        return 1
    os.environ.update(
        {k: env[k] for k in ("TWIN_MEMORY_BASE_URL", "TWIN_MEMORY_API_KEY") if k in env}
    )
    secret = os.environ.get("MEMORY_CONTROL_SECRET") or read_env(
        CONTROL_ENV, "MEMORY_CONTROL_SECRET"
    ).get("MEMORY_CONTROL_SECRET")

    try:
        httpx.get(LK_URL.replace("ws", "http", 1), timeout=3).raise_for_status()
    except Exception as e:
        say(f"FAIL: LiveKit server not reachable at {LK_URL} ({e}); start twin-livekit-dev")
        return 1

    out = Path(tempfile.mkdtemp(prefix="twinmemory-livekit-e2e-"))
    worker_log = open(out / "worker.log", "w")  # noqa: SIM115 - the worker outlives any block
    events = out / "events.jsonl"
    env.update(
        {
            "E2E_EVENTS": str(events),
            "E2E_AGENT_NAME": AGENT_NAME,
            "PYTHONWARNINGS": "ignore",
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )  # no .pyc into tests/ from importing fakes
    say(f"logs in {out}")
    t0 = time.perf_counter()
    worker = subprocess.Popen(
        [
            sys.executable,
            str(HERE / "worker.py"),
            "start",
            "--url",
            LK_URL,
            "--api-key",
            LK_KEY,
            "--api-secret",
            LK_SECRET,
            "--log-level",
            "info",
        ],
        stdout=worker_log,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )

    tag = uuid.uuid4().hex[:10]
    user, kiosk = f"e2e-{tag}", f"kiosk-{tag}"
    timings: dict[str, Any] = {}

    async def run() -> None:
        nonlocal timings
        ev = Events(events)
        deadline = time.monotonic() + 120  # a first run after install can take ~80 s to import
        while "registered worker" not in (out / "worker.log").read_text(errors="replace"):
            if worker.poll() is not None or time.monotonic() > deadline:
                raise AssertionError(
                    f"worker did not register (exit {worker.poll()}), see {out}/worker.log"
                )
            await asyncio.sleep(0.2)
        say(f"worker registered in {(time.perf_counter() - t0) * 1000:.0f} ms")
        memory = AsyncMemory(integration="livekit")
        global CONTROL_ORG, CONTROL_PROJECT
        key = await memory.me()
        CONTROL_ORG, CONTROL_PROJECT = key.org, key.project or ""
        try:
            timings = await scenario(ev, memory, user, kiosk)
        finally:
            await memory.close()
            if not args.keep_users:
                await cleanup([participant_id(user), participant_id(kiosk), user, kiosk], secret)

    try:
        asyncio.run(run())
    except Exception as e:  # any failure is a FAIL with a reason, never a bare traceback
        FAILURES.append(f"{type(e).__name__}: {e}")
        say(f"FAIL: {type(e).__name__}: {e}")
    finally:
        worker.send_signal(signal.SIGINT)
        try:
            code = worker.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(worker.pid, signal.SIGKILL)
            code = worker.wait()
            FAILURES.append("worker did not stop on SIGINT within 30 s")
        say(f"worker stopped (exit {code})")

    if timings:
        for k in ("call1", "call2", "call3"):
            say(
                f"{k} turns: "
                + "; ".join(
                    f"{t['said'][:28]!r} -> {t['reply']} {t['rtt_ms']} ms"
                    for t in timings.get(k, [])
                )
            )
        say(
            f"call 1 fact searchable within {timings.get('fact_searchable_s')} s of being said; "
            f"call 2 marker searchable {timings.get('call2_turn_searchable_s')} s after being said"
        )
        for r in timings.get("recall", []):
            say(
                f"recall [{r['room']}] {r['said']!r}: {r.get('ms')} ms, {r.get('chars')} chars,"
                f" timed_out={r.get('timed_out')} reused={r.get('reused')}"
            )
    say(
        "RESULT: "
        + ("PASS" if not FAILURES else f"FAIL ({len(FAILURES)}): " + " | ".join(FAILURES))
    )
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # skip interpreter teardown: livekit.rtc's FfiHandle.__del__ asserts noisily (and harmlessly)
    # when Room handles are collected after the FFI server has gone
    os._exit(rc)
