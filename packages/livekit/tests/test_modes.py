"""The two modes through a real `AgentSession`: "auto" recalls before every reply and saves every
turn, "tools" leaves both to the model."""

from __future__ import annotations

from typing import Any

import pytest
from fakes import FakeLLM, MemoryService
from livekit.agents import AgentSession, llm

from twinmemory_livekit import TwinMemory, TwinMemoryAgent
from twinmemory_livekit._tools import GUIDE

# A passage as the engine writes one: the caller's words, and the agent's reply after them.
LOCKER = (
    "Context: messages (memory), 2 Oct 2026. user and assistant, in “gym”. Turns 1-2. "
    "**user** 18:02 · My locker code at the Alfama gym is 4417. "
    "**assistant** 18:02 · Got it, your locker code is 4417."
)


def _memory(service: MemoryService, **kwargs: Any) -> TwinMemory:
    return TwinMemory("dana", client=service.client(), session_id="call-2", **kwargs)


def _tool_then_text(name: str, arguments: str) -> FakeLLM:
    def reply(chat_ctx: llm.ChatContext) -> str | list[llm.FunctionToolCall]:
        if any(i.type == "function_call_output" for i in chat_ctx.items):
            return "Done."
        return [llm.FunctionToolCall(name=name, arguments=arguments, call_id="call_1")]

    return FakeLLM(reply_fn=reply)


def _names(agent: TwinMemoryAgent) -> list[str]:
    return sorted(t.info.name for t in agent.tools if isinstance(t, llm.FunctionTool))


async def test_auto_recalls_what_was_said_and_lends_only_read_tools() -> None:
    service = MemoryService(hits=[LOCKER])
    memory, fake = _memory(service), FakeLLM()
    agent = TwinMemoryAgent(memory, instructions="Be brief.")
    assert _names(agent) == ["memory_read", "memory_search"]
    async with AgentSession(llm=fake) as session:
        await session.start(agent)
        await session.run(user_input="What is my locker code at the gym?")
        assert await memory.flush(5) == 0
    shown = next(t for r, t in fake.calls[-1] if r == "assistant" and "<memory>" in t)
    assert "2 Oct 2026 18:02, they said: My locker code at the Alfama gym is 4417." in shown
    assert "2 Oct 2026 18:02, you said: Got it, your locker code is 4417." in shown
    assert [role for role, _ in service.texts()] == ["user", "assistant"]
    await memory.aclose()


async def test_the_last_call_is_recalled_even_where_words_do_not_match() -> None:
    # "suggest a dinner" shares no word with "I'm vegetarian": a search by words finds nothing,
    # and the call before this one says it.
    diet = (
        "Context: messages (memory), 2 Oct 2026. user and assistant, in “diet”. Turns 1-2. "
        "**user** 19:00 · By the way, I'm vegetarian. **assistant** 19:00 · Noted!"
    )
    service = MemoryService(recent=[diet])
    memory, fake = _memory(service), FakeLLM()
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="x", memory_tools=False))
        await session.run(user_input="Can you suggest a dinner for me tonight?")
    shown = next(t for r, t in fake.calls[-1] if r == "assistant" and "<memory>" in t)
    assert "they said: By the way, I'm vegetarian." in shown
    # Once for the call, and earlier calls only: this call's own words are not handed back.
    assert len(service.latests) == 1 and service.latests[0]["before"] == memory.since
    await memory.aclose()


async def test_auto_can_leave_out_the_agents_own_words() -> None:
    service = MemoryService(hits=[LOCKER])
    memory, fake = _memory(service, recall_agent_turns=False), FakeLLM()
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="x", memory_tools=False))
        await session.run(user_input="What is my locker code at the gym?")
    shown = next(t for r, t in fake.calls[-1] if r == "assistant" and "<memory>" in t)
    assert "they said: My locker code" in shown and "Got it" not in shown
    await memory.aclose()


async def test_tools_does_nothing_by_itself() -> None:
    service = MemoryService(hits=[LOCKER])
    memory, fake = _memory(service, mode="tools"), FakeLLM(reply="Hello.")
    agent = TwinMemoryAgent(memory, instructions="Be brief.")
    assert _names(agent) == ["memory_add", "memory_read", "memory_search"]
    assert str(agent.instructions).endswith(GUIDE)  # the model is told when to search and save
    async with AgentSession(llm=fake) as session:
        await session.start(agent)
        await session.run(user_input="What is my locker code at the gym?")
        assert await memory.flush(5) == 0
    # No recall and no turn saved: only the one look, at bind, at what is known about them.
    assert [s["query"] for s in service.searches] == ["What should I know about this person?"]
    assert service.added == []
    assert not any("<memory>" in t for _, t in fake.calls[-1])
    await memory.aclose()


async def test_tools_saves_what_the_model_decides_to() -> None:
    service = MemoryService()
    memory = _memory(service, mode="tools")
    fake = _tool_then_text("memory_add", '{"fact": "Their favourite colour is teal."}')
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="x"))
        await session.run(user_input="My favourite colour is teal.")
        assert await memory.flush(5) == 0
    assert [(i["kind"], i["text"]) for i in service.added] == [
        ("note", "Their favourite colour is teal.")
    ]
    assert (
        "author" not in service.added[0]
    )  # the agent wrote it down; the service refuses a bare self
    await memory.aclose()


async def test_tools_finds_what_the_model_asks_for() -> None:
    service = MemoryService(hits=[LOCKER])
    memory = _memory(service, mode="tools")
    fake = _tool_then_text("memory_search", '{"query": "locker code"}')
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="x"))
        await session.run(user_input="What is my locker code at the gym?")
    output = next(i for i in session.history.items if i.type == "function_call_output")
    assert "they said: My locker code at the Alfama gym is 4417." in output.output  # pyright: ignore[reportAttributeAccessIssue]
    assert "Sources:" in output.output  # pyright: ignore[reportAttributeAccessIssue]
    await memory.aclose()


async def test_a_refused_fact_is_never_reported_saved() -> None:
    service = MemoryService(reject="teal")
    memory = _memory(service, mode="tools")
    _search, _read, add = memory.tools()
    assert await add("Their favourite colour is teal.") == "I couldn't save that just now."
    assert await add("They train on Tuesdays.") == "Saved."
    assert [i["text"] for i in service.added] == ["They train on Tuesdays."]
    await memory.aclose()


async def test_a_fact_memory_is_too_slow_for_is_saved_behind_the_reply() -> None:
    service = MemoryService(delay=3.0)
    memory = _memory(service, mode="tools")
    _search, _read, add = memory.tools()
    assert await add("They train on Tuesdays.") == "Saved."  # within the 2 s it may wait
    service.delay = 0
    assert await memory.flush(10) == 0
    assert [i["text"] for i in service.added].count("They train on Tuesdays.") >= 1
    await memory.aclose()


def test_a_mode_is_one_of_two_and_tools_mode_needs_its_tools() -> None:
    with pytest.raises(ValueError, match="auto"):
        TwinMemory("dana", mode="always")  # pyright: ignore[reportArgumentType]
    memory = TwinMemory("dana", client=MemoryService().client(), mode="tools")
    with pytest.raises(ValueError, match="nothing to do"):
        TwinMemoryAgent(memory, instructions="x", memory_tools=False)
