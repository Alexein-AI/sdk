"""What two reviews of 0.1.0 found, each as the test that failed before its fix: memory answering
nonsense, overflowing, refusing one turn, closing mid-reply; whose memory a call may reach; and
what may be saved."""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace
from typing import Any

import pytest
from alexein import Item
from fakes import FakeLLM, MemoryService
from livekit import rtc
from livekit.agents import AgentSession, llm

from alexein_livekit import AlexeinMemory, AlexeinMemoryAgent
from alexein_livekit._capture import Writer

LISBON = "user, 2 Oct 2026: I moved to Lisbon for the job at Acme."


def _memory(service: MemoryService, user: str | None = "dana", **kwargs: Any) -> AlexeinMemory:
    return AlexeinMemory(user, client=service.client(), session_id="call-2", **kwargs)


def _ctx(text: str) -> llm.ChatContext:
    ctx = llm.ChatContext()
    ctx.add_message(role="user", content=text)
    return ctx


async def test_a_page_that_is_not_memorys_answer_never_stops_a_reply_or_the_saving() -> None:
    service = MemoryService(hits=[LISBON], garbage=True)
    memory, fake = _memory(service), FakeLLM(reply="Sure.")
    async with AgentSession(llm=fake) as session:
        await session.start(AlexeinMemoryAgent(memory, instructions="x", memory_tools=False))
        result = await session.run(user_input="Where do I live now?")
        result.expect.contains_message(role="assistant")
        assert len(fake.calls) == 1
        assert await memory.flush(0.5) == 2  # waiting, not lost
        service.garbage = False
        assert await memory.flush(10) == 0
    assert [role for role, _ in service.texts()] == ["user", "assistant"]
    await memory.aclose()


async def test_a_reply_with_a_tool_call_waits_for_a_hung_memory_once_not_twice() -> None:
    service = MemoryService(hits=[LISBON], delay=30.0)
    memory = _memory(service, recall_timeout=0.4)

    def reply(chat_ctx: llm.ChatContext) -> str | list[llm.FunctionToolCall]:
        if any(i.type == "function_call_output" for i in chat_ctx.items):
            return "Done."
        return [llm.FunctionToolCall(name="lookup", arguments="{}", call_id="c1")]

    @llm.function_tool
    async def lookup() -> str:
        """Look something up."""
        return "found"

    async with AgentSession(llm=FakeLLM(reply_fn=reply)) as session:
        agent = AlexeinMemoryAgent(memory, instructions="x", tools=[lookup], memory_tools=False)
        await session.start(agent)
        started = time.monotonic()
        await session.run(user_input="Where do I live now?")
        took = time.monotonic() - started
    assert took < 0.7, took  # one 0.4 s budget for the reply, not one per model call
    service.delay = 0
    await memory.aclose()


async def test_a_full_buffer_never_drops_a_turn_on_its_way() -> None:
    service = MemoryService(delay=0.3)
    writer = Writer(max_buffer=5)
    writer.start(service.client().user("dana"))
    for n in range(5):
        writer.put(Item(id=f"t{n}", text=f"t{n}"))
    await asyncio.sleep(0.1)  # t0..t4 are being sent
    for n in range(5, 11):
        writer.put(Item(id=f"t{n}", text=f"t{n}"))
    assert await writer.flush(5) == 0
    saved = [i["id"] for i in service.added]
    # Every turn on its way landed; of those queued behind them, the newest was kept.
    assert saved == ["t0", "t1", "t2", "t3", "t4", "t10"]
    assert writer.dropped == 5
    await writer.aclose(1)


async def test_one_refused_turn_does_not_take_the_others_with_it() -> None:
    service = MemoryService(reject="BAD")
    writer = Writer()
    writer.start(service.client().user("dana"))
    for text in ("first", "BAD one", "third"):
        writer.put(Item(id=text, text=text))
    assert await writer.flush(5) == 0
    assert [i["text"] for i in service.added] == ["first", "third"]
    await writer.aclose(1)


async def test_saving_one_by_one_keeps_the_order_when_memory_falters() -> None:
    service = MemoryService(reject="BAD", flaky="t2")  # t2 meets an outage, once, alone
    writer = Writer()
    writer.start(service.client().user("dana"))
    for name in ("t1", "t2", "BAD", "t4"):
        writer.put(Item(id=name, text=name))
    assert await writer.flush(10) == 0
    saved = [i["id"] for i in service.added]
    assert saved.index("t2") < saved.index("t4")  # t4 never lands before t2
    assert set(saved) == {"t1", "t2", "t4"}
    await writer.aclose(1)


async def test_flush_after_close_returns_at_once_and_starts_nothing() -> None:
    service = MemoryService(status=503)
    writer = Writer()
    writer.start(service.client().user("dana"))
    writer.put(Item(id="t1", text="t1"))
    await writer.aclose(0.2)
    started = time.monotonic()
    assert await writer.flush(5) == 1
    assert time.monotonic() - started < 0.1
    assert writer._task is None  # pyright: ignore[reportPrivateUsage]


async def test_closing_mid_reply_lets_the_reply_go_on() -> None:
    service = MemoryService(hits=[LISBON], delay=5.0)
    memory = _memory(service, recall_timeout=2.0)
    ctx = _ctx("Where do I live now?")
    reply = asyncio.create_task(memory.enrich(ctx))
    await asyncio.sleep(0.1)
    await memory.aclose()
    await asyncio.wait_for(reply, 1)  # returns: neither raises nor hangs
    assert not reply.cancelled() and reply.exception() is None


def test_made_outside_an_event_loop_and_unusable_once_closed() -> None:
    service = MemoryService()
    memory = _memory(service)  # no running loop: nothing is started yet
    assert memory.user_id == "dana"

    async def close() -> None:
        await memory.aclose()

    asyncio.run(close())
    with pytest.raises(RuntimeError, match="closed"):
        memory.bind("dana")


async def test_a_phone_caller_leaves_the_call_unbound_instead_of_ending_it() -> None:
    memory = _memory(MemoryService(), user=None)
    sip = SimpleNamespace(
        identity="sip_+15551234567", kind=rtc.ParticipantKind.PARTICIPANT_KIND_SIP
    )
    assert memory.bind(participant=sip) is None  # pyright: ignore[reportArgumentType]
    assert memory.user_id is None
    assert memory.bind("customer-7") == "customer-7"  # the caller, looked up in your records
    await memory.aclose()


def _job(metadata: str) -> Any:
    callbacks: list[Any] = []
    job = SimpleNamespace(id="AJ_1", metadata=metadata, room=SimpleNamespace(name="room-1"))
    return SimpleNamespace(job=job, add_shutdown_callback=callbacks.append, callbacks=callbacks)


async def test_job_metadata_chooses_the_user_only_when_asked_to() -> None:
    service, metadata = MemoryService(), json.dumps({"alexein_user_id": "victim"})
    ctx = _job(metadata)
    plain = AlexeinMemory.from_job(ctx, client=service.client())
    assert plain.user_id is None and plain.session_id == "AJ_1" and plain.room == "room-1"
    assert ctx.callbacks == [plain.aclose]  # saved when the job ends
    named = AlexeinMemory.from_job(
        _job(metadata), metadata_key="alexein_user_id", client=service.client()
    )
    assert named.user_id == "victim"
    await plain.aclose()
    await named.aclose()


async def test_redact_changes_or_drops_a_turn_before_it_leaves_the_process() -> None:
    def redact(role: str, text: str) -> str | None:
        if "card" in text:
            return None
        return "".join("#" if c.isdigit() else c for c in text)

    service = MemoryService()
    memory = _memory(service, redact=redact)
    async with AgentSession(llm=FakeLLM(reply="Noted.")) as session:
        await session.start(AlexeinMemoryAgent(memory, instructions="x", memory_tools=False))
        await session.run(user_input="My card is 4111 1111 1111 1111.")
        await session.run(user_input="My flight is TP 1234 on Friday.")
        assert await memory.flush(5) == 0
    assert service.texts() == [
        ("assistant", "Noted."),
        ("user", "My flight is TP #### on Friday."),
        ("assistant", "Noted."),
    ]
    await memory.aclose()


async def test_the_memory_tools_are_free_and_a_note_is_short() -> None:
    service = MemoryService(hits=[LISBON])
    memory = _memory(service, mode="tools")
    search, _open, add = memory.tools()
    assert await search("where do I live") and service.searches[-1]["fast"] is True
    assert await add("x" * 5000) == "Saved."  # answered at once, saved by the writer
    assert await memory.flush(5) == 0
    saved = service.added[-1]
    assert saved["text"] == "Noted: " + "x" * 500  # the fact cut at 500, as the agent's line
    assert (saved["kind"], saved["role"]) == ("message", "assistant")
    await memory.aclose()
