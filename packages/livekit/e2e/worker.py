"""The agent worker that e2e/room.py runs: the package's README pattern, text in and text out, with
tests/fakes.py's FakeLLM in place of a model. Not meant to be run by hand, though it can be:

    uv run python e2e/worker.py start --url ws://localhost:7880 --api-key devkey --api-secret secret

with E2E_EVENTS=<file.jsonl> and TWIN_MEMORY_API_KEY / TWIN_MEMORY_BASE_URL set. Every event the
driver asserts on is one JSON line in E2E_EVENTS, written by the job process that saw it.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))  # for fakes.FakeLLM

from fakes import FakeLLM, seen
from livekit.agents import AgentServer, AgentSession, JobContext, cli, llm
from livekit.agents.voice import room_io

from twinmemory_livekit import TwinMemory, TwinMemoryAgent

AGENT_NAME = os.environ.get("E2E_AGENT_NAME", "twinmemory-e2e")
EVENTS = os.environ.get("E2E_EVENTS", "")
_tasks: set[asyncio.Task[None]] = set()


def emit(event: str, **fields: Any) -> None:
    line = json.dumps({"ev": event, "t": time.time(), **fields}, default=str)
    if EVENTS:
        with open(EVENTS, "a") as f:  # one short append per line; job processes share the file
            f.write(line + "\n")
    print("E2E " + line, flush=True)


def memory_blocks(context: list[tuple[str, str]]) -> list[str]:
    return [t for _, t in context if "<memory>" in t]


server = AgentServer(num_idle_processes=2, port=0)


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    room = ctx.job.room.name
    base = {"room": room, "job": ctx.job.id}

    # ---- the README pattern
    memory = TwinMemory.from_job(ctx)
    emit(
        "job_start",
        **base,
        metadata=ctx.job.metadata,
        user_from_metadata=memory.user_id,
        session_id=memory.session_id,
    )
    await ctx.connect()
    via = "metadata" if memory.user_id is not None else "participant"
    if memory.user_id is None:
        memory.bind(participant=await ctx.wait_for_participant())
    emit("bound", **base, user_id=memory.user_id, via=via)

    async def _on_shutdown(reason: str) -> None:
        # registered after from_job's memory.aclose, so this runs once memory has closed
        emit("shutdown", **base, reason=reason, closed=memory._closed)  # pyright: ignore[reportPrivateUsage]

    ctx.add_shutdown_callback(_on_shutdown)

    def reply(chat_ctx: llm.ChatContext) -> str:
        context = seen(chat_ctx)
        blocks = memory_blocks(context)
        r = memory.last_recall
        emit(
            "llm_call",
            **base,
            user_id=memory.user_id,
            context=context,
            memory_blocks=blocks,
            recall=None
            if r is None
            else {
                "ms": round(r.ms, 2),
                "chars": r.chars,
                "timed_out": r.timed_out,
                "failed": r.failed,
                "reused": r.reused,
                "query": r.query,
            },
        )
        return f"MEMORY-SEEN:{'yes' if blocks else 'no'}"

    session = AgentSession(llm=FakeLLM(reply_fn=reply))

    @session.on("conversation_item_added")
    def _item(ev: Any) -> None:
        it = ev.item
        emit(
            "item",
            **base,
            type=it.type,
            role=getattr(it, "role", None),
            text=getattr(it, "text_content", None),
        )

    @session.on("close")
    def _close(ev: Any) -> None:
        emit("session_close", **base, reason=ev.reason.value)

        async def _flushed() -> None:  # the package flushes on close too; this measures it
            t0 = time.perf_counter()
            left = await memory.flush()
            emit("flushed", **base, unsaved=left, ms=round((time.perf_counter() - t0) * 1000, 1))

        task = asyncio.create_task(_flushed())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)

    await session.start(
        room=ctx.room,
        agent=TwinMemoryAgent(memory, instructions="You are a test agent.", memory_tools=False),
        record=False,
        room_options=room_io.RoomOptions(
            text_input=True, audio_input=False, audio_output=False, text_output=True
        ),
    )
    participant = await ctx.wait_for_participant()  # only for the log; binding is done above
    emit("participant", **base, identity=participant.identity, user_id=memory.user_id)


if __name__ == "__main__":
    cli.run_app(server)
