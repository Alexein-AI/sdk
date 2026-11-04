"""The two modes through a real `AgentSession`: "auto" recalls before every reply and saves every
turn, "tools" leaves both to the model."""

from __future__ import annotations

from typing import Any

import pytest
from fakes import FakeLLM, MemoryService
from livekit.agents import AgentSession, llm

from alexein_livekit import AlexeinMemory, AlexeinMemoryAgent
from alexein_livekit._tools import GUIDE

# An excerpt as search returns one: the caller's words, and the agent's reply after them.
LOCKER = (
    "Context: messages (memory), 2 Oct 2026. user and assistant, in “gym”. "
    "**user** 18:02 · My locker code at the Alfama gym is 4417. "
    "**assistant** 18:02 · Got it, your locker code is 4417."
)


def _memory(service: MemoryService, **kwargs: Any) -> AlexeinMemory:
    return AlexeinMemory("dana", client=service.client(), session_id="call-2", **kwargs)


def _tool_then_text(name: str, arguments: str) -> FakeLLM:
    def reply(chat_ctx: llm.ChatContext) -> str | list[llm.FunctionToolCall]:
        if any(i.type == "function_call_output" for i in chat_ctx.items):
            return "Done."
        return [llm.FunctionToolCall(name=name, arguments=arguments, call_id="call_1")]

    return FakeLLM(reply_fn=reply)


def _names(agent: AlexeinMemoryAgent) -> list[str]:
    return sorted(t.info.name for t in agent.tools if isinstance(t, llm.FunctionTool))


async def test_auto_recalls_what_was_said_and_lends_only_read_tools() -> None:
    service = MemoryService(hits=[LOCKER])
    memory, fake = _memory(service), FakeLLM()
    agent = AlexeinMemoryAgent(memory, instructions="Be brief.")
    assert _names(agent) == ["memory_open", "memory_search"]
    async with AgentSession(llm=fake) as session:
        await session.start(agent)
        await session.run(user_input="What is my locker code at the gym?")
        assert await memory.flush(5) == 0
    shown = next(t for r, t in fake.calls[-1] if r == "assistant" and "<memory>" in t)
    assert "2 Oct 2026 18:02, they said: My locker code at the Alfama gym is 4417." in shown
    assert "2 Oct 2026 18:02, you said: Got it, your locker code is 4417." in shown
    assert [role for role, _ in service.texts()] == ["user", "assistant"]
    await memory.aclose()


async def test_recall_and_memory_search_work_in_any_script() -> None:
    urdu = (
        "Context: messages (memory), 2 Oct 2026. user and assistant, in “x”. "
        "**user** 18:02 · میرا لاکر کوڈ 4417 ہے **assistant** 18:02 · ٹھیک ہے"
    )
    service = MemoryService(hits=[urdu])
    memory, fake = _memory(service), FakeLLM()
    async with AgentSession(llm=fake) as session:
        await session.start(AlexeinMemoryAgent(memory, instructions="x", memory_tools=False))
        await session.run(user_input="میرا لاکر کوڈ کیا ہے؟")
    shown = next(t for r, t in fake.calls[-1] if r == "assistant" and "<memory>" in t)
    assert "they said: میرا لاکر کوڈ 4417 ہے" in shown
    search, _open = memory.tools()
    assert "میرا لاکر کوڈ 4417 ہے" in await search("لاکر کوڈ")
    await memory.aclose()


async def test_the_last_call_is_recalled_even_where_words_do_not_match() -> None:
    # "suggest a dinner" shares no word with "I'm vegetarian": a search by words finds nothing,
    # and the call before this one says it.
    diet = (
        "Context: messages (memory), 2 Oct 2026. user and assistant, in “diet”. "
        "**user** 19:00 · By the way, I'm vegetarian. **assistant** 19:00 · Noted!"
    )
    service = MemoryService(recent=[diet])
    memory, fake = _memory(service), FakeLLM()
    async with AgentSession(llm=fake) as session:
        await session.start(AlexeinMemoryAgent(memory, instructions="x", memory_tools=False))
        await session.run(user_input="Can you suggest a dinner for me tonight?")
    shown = next(t for r, t in fake.calls[-1] if r == "assistant" and "<memory>" in t)
    assert "they said: By the way, I'm vegetarian." in shown
    # Once for the call, and earlier calls only: this call's own words are not handed back.
    assert len(service.latests) == 1 and service.latests[0]["filters"] == {
        "NOT": {"mentions": "session:call-2"}
    }
    await memory.aclose()


async def test_auto_can_leave_out_the_agents_own_words() -> None:
    service = MemoryService(hits=[LOCKER])
    memory, fake = _memory(service, recall_agent_turns=False), FakeLLM()
    async with AgentSession(llm=fake) as session:
        await session.start(AlexeinMemoryAgent(memory, instructions="x", memory_tools=False))
        await session.run(user_input="What is my locker code at the gym?")
    shown = next(t for r, t in fake.calls[-1] if r == "assistant" and "<memory>" in t)
    assert "they said: My locker code" in shown and "Got it" not in shown
    await memory.aclose()


async def test_tools_does_nothing_by_itself() -> None:
    service = MemoryService(hits=[LOCKER])
    memory, fake = _memory(service, mode="tools"), FakeLLM(reply="Hello.")
    agent = AlexeinMemoryAgent(memory, instructions="Be brief.")
    assert _names(agent) == ["memory_add", "memory_open", "memory_search"]
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
    fake = _tool_then_text("memory_add", '{"text": "Their favourite colour is teal."}')
    async with AgentSession(llm=fake) as session:
        await session.start(AlexeinMemoryAgent(memory, instructions="x"))
        await session.run(user_input="My favourite colour is teal.")
        assert await memory.flush(5) == 0
    # The agent's own line in the call, so it keeps its time: "lives in Berlin" and, a call
    # later, "moved to Lisbon" are then told apart by when, not shown as equally recent.
    assert [(i["kind"], i["role"], i["text"]) for i in service.added] == [
        ("message", "assistant", "Noted: Their favourite colour is teal.")
    ]
    assert service.added[0]["at"] and service.added[0]["session"] == "call-2"
    assert (
        "author" not in service.added[0]
    )  # the agent wrote it down; the service refuses a bare self
    await memory.aclose()


async def test_tools_finds_what_the_model_asks_for() -> None:
    service = MemoryService(hits=[LOCKER])
    memory = _memory(service, mode="tools")
    fake = _tool_then_text("memory_search", '{"query": "locker code"}')
    async with AgentSession(llm=fake) as session:
        await session.start(AlexeinMemoryAgent(memory, instructions="x"))
        await session.run(user_input="What is my locker code at the gym?")
    output = next(i for i in session.history.items if i.type == "function_call_output")
    assert "they said: My locker code at the Alfama gym is 4417." in output.output  # pyright: ignore[reportAttributeAccessIssue]
    assert "To read one whole, memory_open:\n- p0" in output.output  # pyright: ignore[reportAttributeAccessIssue]
    await memory.aclose()


async def test_memory_open_reads_whole_what_memory_search_found() -> None:
    service = MemoryService(hits=[LOCKER])
    memory = _memory(service, mode="tools")
    search, open_, _add = memory.tools()
    assert "To read one whole, memory_open:\n- p0" in await search("locker code")
    assert await open_("p0") == LOCKER
    assert service.opens == [{"ref": "p0"}]
    assert await open_("mem_made_up") == "Nothing remembered about that."
    await memory.aclose()


async def test_a_refused_fact_is_never_reported_saved() -> None:
    service = MemoryService(reject="teal")
    memory = _memory(service, mode="tools")
    _search, _open, add = memory.tools()
    assert await add("Their favourite colour is teal.") == "I couldn't save that just now."
    assert memory.noted == []  # nor kept as noted
    assert await add("They train on Tuesdays.") == "Saved."
    assert memory.noted == ["They train on Tuesdays."]
    assert [i["text"] for i in service.added] == ["Noted: They train on Tuesdays."]
    await memory.aclose()


async def test_a_fact_memory_is_too_slow_for_is_saved_behind_the_reply() -> None:
    service = MemoryService(delay=3.0)
    memory = _memory(service, mode="tools")
    _search, _open, add = memory.tools()
    assert await add("They train on Tuesdays.") == "Saved."  # within the 2 s it may wait
    service.delay = 0
    assert await memory.flush(10) == 0
    assert [i["text"] for i in service.added].count("Noted: They train on Tuesdays.") >= 1
    await memory.aclose()


async def test_a_card_number_never_reaches_memory_in_either_mode() -> None:
    for mode in ("auto", "tools"):
        service = MemoryService()
        memory = _memory(service, mode=mode)
        fake = _tool_then_text("memory_add", '{"text": "My card number is 4111 1111 1111 1111"}')
        async with AgentSession(llm=fake if mode == "tools" else FakeLLM()) as session:
            await session.start(AlexeinMemoryAgent(memory, instructions="x"))
            await session.run(
                user_input="My card number is 4111 1111 1111 1111, window seat please."
            )
            assert await memory.flush(5) == 0
        saved = " ".join(i["text"] for i in service.added)
        assert "4111" not in saved and "[card number]" in saved, (mode, saved)
        await memory.aclose()


async def test_the_tools_wait_as_long_as_they_are_told_to() -> None:
    import time

    service = MemoryService(delay=3.0)
    memory = _memory(service, mode="tools", tool_timeout=0.3, save_timeout=0.3)
    search, open_, add = memory.tools()
    for tool, argument in ((search, "locker code"), (open_, "p0")):
        started = time.monotonic()
        assert await tool(argument) == "I couldn't reach my memory just now."
        assert time.monotonic() - started < 1.0
    started = time.monotonic()
    assert await add("Prefers aisle seats.") == "Saved."  # left to the writer, which retries
    assert time.monotonic() - started < 1.0
    service.delay = 0
    assert await memory.flush(10) == 0
    with pytest.raises(ValueError, match="shutdown"):
        _memory(service, flush_timeout=12)
    await memory.aclose()


def test_a_mode_is_one_of_two_and_tools_mode_needs_its_tools() -> None:
    with pytest.raises(ValueError, match="auto"):
        AlexeinMemory("dana", mode="always")  # pyright: ignore[reportArgumentType]
    memory = AlexeinMemory("dana", client=MemoryService().client(), mode="tools")
    with pytest.raises(ValueError, match="nothing to do"):
        AlexeinMemoryAgent(memory, instructions="x", memory_tools=False)
