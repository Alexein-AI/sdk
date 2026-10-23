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
    shown = next(t for _, t in fake.calls[-1] if "<memory>" in t)
    assert "2 Oct 2026 18:02, they said: My locker code at the Alfama gym is 4417." in shown
    assert "2 Oct 2026 18:02, you said: Got it, your locker code is 4417." in shown
    assert [role for role, _ in service.texts()] == ["user", "assistant"]
    await memory.aclose()


async def test_auto_can_leave_out_the_agents_own_words() -> None:
    service = MemoryService(hits=[LOCKER])
    memory, fake = _memory(service, recall_agent_turns=False), FakeLLM()
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="x", memory_tools=False))
        await session.run(user_input="What is my locker code at the gym?")
    shown = next(t for _, t in fake.calls[-1] if "<memory>" in t)
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
    assert service.searches == [] and service.added == []  # no recall, no turn saved
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
    assert service.added[0]["author"] == {"self": True}
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


def test_a_mode_is_one_of_two_and_tools_mode_needs_its_tools() -> None:
    with pytest.raises(ValueError, match="auto"):
        TwinMemory("dana", mode="always")  # pyright: ignore[reportArgumentType]
    memory = TwinMemory("dana", client=MemoryService().client(), mode="tools")
    with pytest.raises(ValueError, match="nothing to do"):
        TwinMemoryAgent(memory, instructions="x", memory_tools=False)
