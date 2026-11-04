"""Talk to the memory voice agent yourself, in the browser.

    cd integrations/livekit && uv run --with "livekit-plugins-openai~=1.8" \
        --with "livekit-plugins-silero~=1.8" python e2e/talk.py --identity dana --mode auto

then open http://localhost:8765 and press Start call. Each call is a new room and a new job, so
hanging up and calling again is "call 2": what you said before is in memory for the same identity.
`--mode tools` lets the model decide when to search and save; `--mode off` is a plain agent.

It starts e2e/voice_worker.py (the same worker e2e/voice.py tests), and serves talk.html with a
fresh room, dispatch and token per call from /call. Needs what voice.py needs: the LiveKit dev
server, ALEXEIN_API_KEY (or $E2E_ENV), and OPENAI_API_KEY or OPENROUTER_API_KEY (or
$VOICE_ENV). What the agent heard and said, its tool calls and its recall are printed here as they
happen.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from aiohttp import web
from livekit import api
from voice import (  # e2e/voice.py, beside this file
    LK_KEY,
    LK_SECRET,
    LK_URL,
    environment,
    registered,
    start_worker,
    stop_worker,
)

HERE = Path(__file__).resolve().parent
AGENT_NAME = "alexein-voice-talk"


def show(line: str) -> None:
    print(f"[talk {time.strftime('%H:%M:%S')}] {line}", flush=True)


async def follow(events: Path) -> None:
    """Print what the worker logs that a person talking to it wants to see."""
    seen = 0
    while True:
        if events.exists():
            lines = events.read_text().splitlines()
            for raw in lines[seen:]:
                e = json.loads(raw)
                ev = e["ev"]
                if ev == "bound":
                    show(f"call {e['room']}: memory user {e['user_id']} ({e['mode']})")
                elif ev == "stt":
                    show(f"  you:   {e['text']}")
                elif ev == "item" and e.get("role") == "assistant":
                    show(f"  agent: {e['text']}")
                elif ev == "tools":
                    show(f"  tools: {[(c['name'], c['arguments']) for c in e['calls']]}")
                elif ev == "llm_call" and e.get("recall"):
                    r = e["recall"]
                    n = len(e["memory_blocks"])
                    show(f"  recall: {r['ms']} ms, {r['chars']} chars, {n} <memory> block")
                elif ev == "error":
                    show(f"  error: {e['error'][:160]}")
            seen = len(lines)
        await asyncio.sleep(0.3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--identity", default="talk-demo", help="your participant identity = user id")
    ap.add_argument("--mode", choices=["auto", "tools", "off"], default="auto")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    env = environment()
    for k in ("ALEXEIN_API_KEY", "VOICE_API_KEY"):
        if not env.get(k):
            show(f"no {k} in the environment or its file; see e2e/README.md")
            return 1
    out = Path(tempfile.mkdtemp(prefix="alexein-livekit-talk-"))
    events = out / "events.jsonl"
    env.update({"E2E_EVENTS": str(events), "E2E_AGENT_NAME": AGENT_NAME,
                "VOICE_MODE": args.mode, "PYTHONWARNINGS": "ignore"})  # fmt: skip
    show(f"worker log and events in {out}")
    worker = start_worker(env, out)

    async def call(_req: web.Request) -> web.Response:
        """A new call: a room, the agent dispatched to it, and a token for you."""
        room = f"talk-{uuid.uuid4().hex[:8]}"
        lk = api.LiveKitAPI(
            url=LK_URL.replace("ws", "http", 1), api_key=LK_KEY, api_secret=LK_SECRET
        )
        try:
            await lk.room.create_room(
                api.CreateRoomRequest(name=room, empty_timeout=60, departure_timeout=5)
            )
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=AGENT_NAME, room=room, metadata=json.dumps({"mode": args.mode})
                )
            )
        finally:
            await lk.aclose()
        token = (
            api.AccessToken(LK_KEY, LK_SECRET)
            .with_identity(args.identity)
            .with_name(args.identity)
            .with_grants(api.VideoGrants(room_join=True, room=room))
            .to_jwt()
        )
        show(f"call: room {room} for {args.identity}")
        body: dict[str, Any] = {
            "url": LK_URL, "token": token, "room": room,
            "identity": args.identity, "mode": args.mode,
        }  # fmt: skip
        return web.json_response(body)

    async def page(_req: web.Request) -> web.FileResponse:
        return web.FileResponse(HERE / "talk.html")

    async def go() -> None:
        await registered(worker, out)
        show("worker registered")
        app = web.Application()
        app.router.add_get("/", page)
        app.router.add_post("/call", call)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "localhost", args.port).start()
        show(f"open http://localhost:{args.port}  (identity {args.identity}, mode {args.mode})")
        stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):  # Ctrl-C ends the demo, and the worker with it
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        printer = asyncio.create_task(follow(events))
        await stop.wait()
        printer.cancel()
        await runner.shutdown()
        await runner.cleanup()

    try:
        asyncio.run(go())
    except Exception as e:
        show(f"stopped: {type(e).__name__}: {e}")
    finally:
        # one Ctrl-C often arrives twice (from the terminal and forwarded by `uv run`): the
        # first stops the server, and the worker is stopped whatever comes after
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        show(f"worker stopped (exit {stop_worker(worker)})")
    return 0


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    os._exit(rc)  # skip teardown: livekit.rtc's FfiHandle.__del__ asserts after the FFI is gone
