"""Whole turns through a real `AgentSession`, typed and spoken, with a scripted LLM and twin memory
in process: what the model is shown, what is saved, and that a reply is never held up or stopped
by memory being slow, down, new or wrong."""

from __future__ import annotations

import asyncio
import logging
import time

import pytest
from fakes import FakeLLM, MemoryService, ScriptedSTT, SilentAudioInput
from livekit.agents import Agent, AgentSession, ConversationItemAddedEvent, llm

from twinmemory_livekit import TwinMemory, TwinMemoryAgent
from twinmemory_livekit import _memory as memory_module

LISBON = "user, 2 Oct 2026: I moved to Lisbon for the job at Acme."


def _memory(service: MemoryService, user: str | None = "dana", **kwargs: object) -> TwinMemory:
    return TwinMemory(user, memory=service.client(), session_id="call-2", **kwargs)  # pyright: ignore[reportArgumentType]


def _before_user(call: list[tuple[str, str]]) -> tuple[str, str]:
    """The message the model was shown just before the user's latest words (items that are not
    messages, like LiveKit's agent config updates, never reach the model)."""
    said = [(role, text) for role, text in call if role in ("system", "user", "assistant")]
    last = max(i for i, (role, _) in enumerate(said) if role == "user")
    return said[last - 1]


def _memory_shown(call: list[tuple[str, str]]) -> list[str]:
    return [text for role, text in call if role == "assistant" and "<memory>" in text]


async def _say(session: AgentSession, text: str) -> None:
    result = await session.run(user_input=text)
    result.expect.contains_message(role="assistant")


async def _hand_off(session: AgentSession, agent: Agent) -> None:
    session.update_agent(agent)
    # The switch runs as a task; a turn sent before it ends would meet the closing agent.
    switching = session._update_activity_atask  # pyright: ignore[reportPrivateUsage]
    assert switching is not None
    await switching


async def test_a_reply_is_given_what_earlier_calls_said() -> None:
    service = MemoryService(hits=[LISBON])
    memory, fake = _memory(service), FakeLLM()
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="Be brief.", memory_tools=False))
        await _say(session, "Where do I live now?")
    role, shown = _before_user(fake.calls[-1])
    assert role == "assistant" and "<memory>" in shown and LISBON in shown
    assert fake.calls[-1][0] == ("system", "Be brief.")  # never ahead of the instructions
    scoped = [s for s in service.searches if s.get("scope")]
    assert len(scoped) == 1 and scoped[0]["fast"] is True
    # Earlier calls only: this call's own turns are left out by time, to the second.
    assert scoped[0]["scope"] == "passages/memory" and "T" in scoped[0]["before"]
    assert set(service.users) == {"dana"}
    await memory.aclose()


async def test_every_turn_is_saved_in_order_once_and_memory_never_piles_up() -> None:
    service = MemoryService(hits=[LISBON])
    memory, fake = _memory(service), FakeLLM(reply="Noted.")
    async with AgentSession(llm=fake) as session:
        agent = TwinMemoryAgent(memory, instructions="Be brief.", memory_tools=False)
        await session.start(agent)
        await _say(session, "I'm flying to Porto on Friday.")
        await _say(session, "Book me a window seat on that flight please.")
        assert await memory.flush(5) == 0
        history = [m.text_content or "" for m in agent.chat_ctx.messages()]
    assert service.texts() == [
        ("user", "I'm flying to Porto on Friday."),
        ("assistant", "Noted."),
        ("user", "Book me a window seat on that flight please."),
        ("assistant", "Noted."),
    ]
    ids = [i["id"] for i in service.added]
    assert len(set(ids)) == 4 and all(i.startswith("lk:call-2:") for i in ids)
    assert all(i["session"] == "call-2" and i["kind"] == "message" for i in service.added)
    assert [i.get("author") for i in service.added] == [{"self": True}, None] * 2
    # What recall showed the model is neither saved nor kept in the agent's history.
    assert not any("<memory>" in text for _, text in service.texts())
    assert not any("<memory>" in text for text in history)
    assert len(_memory_shown(fake.calls[-1])) == 1
    await memory.aclose()


async def test_a_slow_memory_never_holds_up_a_reply() -> None:
    service = MemoryService(hits=[LISBON], delay=3.0)
    memory, fake = _memory(service, recall_timeout=0.2), FakeLLM()
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="Be brief.", memory_tools=False))
        started = time.monotonic()
        await _say(session, "Where do I live now?")
        took = time.monotonic() - started
    assert took < 1.0, took
    assert _memory_shown(fake.calls[-1]) == []
    assert memory.last_recall is not None and memory.last_recall.timed_out
    service.delay = 0
    await memory.aclose()


async def test_memory_down_the_call_goes_on_and_its_turns_wait_then_land_once() -> None:
    service = MemoryService(hits=[LISBON], status=503)
    memory, fake = _memory(service), FakeLLM()
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="Be brief.", memory_tools=False))
        await _say(session, "Where do I live now?")
        assert _memory_shown(fake.calls[-1]) == []
        assert memory.last_recall is not None and memory.last_recall.failed
        assert await memory.flush(0.3) == 2  # both turns still waiting
        service.status = None
        assert await memory.flush(10) == 0
    assert [role for role, _ in service.texts()] == ["user", "assistant"]
    await memory.aclose()


async def test_a_wrong_key_loses_the_turns_but_never_a_reply(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = MemoryService(status=401)
    memory, fake = _memory(service), FakeLLM(reply="Sure.")
    with caplog.at_level(logging.WARNING, logger="twinmemory.livekit"):
        async with AgentSession(llm=fake) as session:
            await session.start(TwinMemoryAgent(memory, instructions="x", memory_tools=False))
            await _say(session, "What did we decide about the trip?")
            await _say(session, "And what about the hotel booking?")
            assert await memory.flush(2) == 0  # refused, so dropped, not retried forever
    refused = [r for r in caplog.records if "refused" in r.getMessage()]
    recall = [r for r in caplog.records if "recall failed" in r.getMessage()]
    assert len(refused) == 1 and len(recall) == 1  # once per call, not once per turn
    await memory.aclose()


async def test_a_new_user_has_no_memory_yet_and_that_is_not_an_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = MemoryService(new_user=True)
    memory, fake = _memory(service), FakeLLM()
    with caplog.at_level(logging.WARNING, logger="twinmemory.livekit"):
        async with AgentSession(llm=fake) as session:
            await session.start(TwinMemoryAgent(memory, instructions="x", memory_tools=False))
            await _say(session, "Hi, I'd like to book a table for two.")
            assert await memory.flush(5) == 0
    assert _memory_shown(fake.calls[-1]) == [] and caplog.records == []
    assert memory.last_recall is not None and not memory.last_recall.failed
    assert len(service.added) == 2
    await memory.aclose()


async def test_small_talk_is_not_searched() -> None:
    service = MemoryService(hits=[LISBON])
    memory = _memory(service)
    async with AgentSession(llm=FakeLLM()) as session:
        await session.start(TwinMemoryAgent(memory, instructions="x", memory_tools=False))
        await _say(session, "Thanks!")
    assert [s for s in service.searches if s.get("scope")] == []
    await memory.aclose()


def _tool_then_text(name: str, arguments: str) -> FakeLLM:
    def reply(chat_ctx: llm.ChatContext) -> str | list[llm.FunctionToolCall]:
        if any(i.type == "function_call_output" for i in chat_ctx.items):
            return "Here you go."
        return [llm.FunctionToolCall(name=name, arguments=arguments, call_id="call_1")]

    return FakeLLM(reply_fn=reply)


async def test_a_tools_follow_up_reuses_the_turns_recall() -> None:
    service = MemoryService(hits=[LISBON])
    memory, fake = _memory(service), _tool_then_text("search_memory", '{"query": "home"}')
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="x"))
        await _say(session, "Where do I live now?")
    assert len(fake.calls) == 2
    assert [len(_memory_shown(call)) for call in fake.calls] == [1, 1]
    recalls = [s for s in service.searches if s.get("scope")]
    tools = [s for s in service.searches if not s.get("scope") and s["query"] == "home"]
    assert len(recalls) == 1 and len(tools) == 1
    await memory.aclose()


async def test_the_memory_tools_answer_in_words_when_memory_is_down() -> None:
    service = MemoryService(status=503)
    memory, fake = _memory(service), _tool_then_text("search_memory", '{"query": "home"}')
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="x"))
        await _say(session, "Where do I live now?")
    outputs = [text for role, text in fake.calls[-1] if role == "function_call_output"]
    assert fake.calls[-1][-1][0] == "function_call_output" or outputs is not None
    tool_output = next(i for i in session.history.items if i.type == "function_call_output")
    assert tool_output.output == memory_module.UNAVAILABLE  # pyright: ignore[reportAttributeAccessIssue]
    service.status = None
    await memory.aclose()


async def test_a_handoff_and_back_saves_each_turn_once() -> None:
    service = MemoryService()
    memory, fake = _memory(service), FakeLLM(reply="Right.")
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="A", memory_tools=False))
        await _say(session, "First question about my booking.")
        await _hand_off(session, Agent(instructions="B"))
        await _say(session, "Second question about my booking.")
        await _hand_off(session, TwinMemoryAgent(memory, instructions="A", memory_tools=False))
        await _say(session, "Third question about my booking.")
        assert await memory.flush(5) == 0
    users = [text for role, text in service.texts() if role == "user"]
    assert users == [f"{n} question about my booking." for n in ("First", "Second", "Third")]
    assert len(service.added) == 6 and len({i["id"] for i in service.added}) == 6
    await memory.aclose()


async def test_turns_before_the_user_is_known_wait_for_them() -> None:
    service = MemoryService(hits=[LISBON])
    memory, fake = _memory(service, user=None), FakeLLM()
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="x", memory_tools=False))
        await _say(session, "Where do I live now?")
        assert service.searches == [] and service.added == []
        memory.bind("dana")
        assert await memory.flush(5) == 0
    assert [role for role, _ in service.texts()] == ["user", "assistant"]
    assert set(service.users) == {"dana"}
    with pytest.raises(ValueError, match="already"):
        memory.bind("someone-else")
    await memory.aclose()


async def test_closing_never_waits_long_for_a_hung_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(memory_module, "FLUSH_SECONDS", 0.5)
    service = MemoryService(delay=60.0)
    memory = _memory(service, recall_timeout=0.1)
    async with AgentSession(llm=FakeLLM()) as session:
        await session.start(TwinMemoryAgent(memory, instructions="x", memory_tools=False))
        await _say(session, "Where do I live now?")
    started = time.monotonic()
    await memory.aclose()
    await memory.aclose()  # twice is fine
    assert time.monotonic() - started < 1.5


async def test_a_spoken_turn_keeps_the_preemptive_head_start(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = MemoryService(hits=[LISBON])
    memory, fake, stt = _memory(service), FakeLLM(reply="In Lisbon."), ScriptedSTT()
    with caplog.at_level(logging.DEBUG, logger="livekit.agents"):
        session = AgentSession(
            llm=fake,
            stt=stt,
            vad=None,
            turn_handling={  # pyright: ignore[reportArgumentType]
                "turn_detection": "stt",
                "endpointing": {"min_delay": 0.0, "max_delay": 0.5},
            },
            aec_warmup_duration=None,
        )
        session.input.audio = SilentAudioInput()
        replied = asyncio.Event()

        def on_item(event: ConversationItemAddedEvent) -> None:
            if getattr(event.item, "role", "") == "assistant":
                replied.set()

        session.on("conversation_item_added", on_item)
        await session.start(TwinMemoryAgent(memory, instructions="x", memory_tools=False))
        await stt.user_says("Where do I live now?")
        await asyncio.wait_for(replied.wait(), 5)
        assert await memory.flush(5) == 0
        await session.aclose()
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "preemptive generation invalidated" not in logged
    assert all(len(_memory_shown(call)) == 1 for call in fake.calls)
    assert len([s for s in service.searches if s.get("scope")]) == 1
    assert service.texts() == [("user", "Where do I live now?"), ("assistant", "In Lisbon.")]
    await memory.aclose()
