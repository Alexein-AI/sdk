"""Every setting changes what it says it does, through a real `AgentSession`, and a setting that
makes no sense is refused when the memory is made."""

from __future__ import annotations

from typing import Any

import pytest
from fakes import FakeLLM, MemoryService
from livekit.agents import AgentSession, llm

from twinmemory_livekit import Settings, TwinMemory, TwinMemoryAgent

LOCKER = (
    "Context: messages (memory), 2 Oct 2026. user and assistant, in “gym”. Turns 1-2. "
    "**user** 18:02 · My locker code at the Alfama gym is 4417. "
    "**assistant** 18:02 · Got it, your locker code is 4417."
)


def _memory(service: MemoryService, **kwargs: Any) -> TwinMemory:
    return TwinMemory("dana", client=service.client(), session_id="call-2", **kwargs)


async def _turn(memory: TwinMemory, said: str, **agent: Any) -> FakeLLM:
    fake = FakeLLM(reply="Noted.")
    async with AgentSession(llm=fake) as session:
        await session.start(TwinMemoryAgent(memory, instructions="Be brief.", **agent))
        await session.run(user_input=said)
        await memory.flush(5)
    return fake


def _shown(fake: FakeLLM) -> str:
    return next((t for r, t in fake.calls[-1] if r == "assistant" and "<memory>" in t), "")


async def test_recall_fast_and_tool_fast_are_apart() -> None:
    service = MemoryService(hits=[LOCKER])
    memory = _memory(service, recall_fast=False, tool_fast=True)
    await _turn(memory, "What is my locker code at the gym?", memory_tools=False)
    recall = next(s for s in service.searches if s["query"].startswith("What is my locker"))
    assert recall["fast"] is False  # memory's model filter judges this one
    search, _read = memory.tools()
    await search("locker code")
    assert service.searches[-1]["fast"] is True
    await memory.aclose()


async def test_search_current_call_lifts_the_earlier_calls_only_rule() -> None:
    service = MemoryService(hits=[LOCKER], recent=[LOCKER])
    memory = _memory(service, search_current_call=True)
    await _turn(memory, "What is my locker code at the gym?", memory_tools=False)
    recall = next(s for s in service.searches if s["query"].startswith("What is my locker"))
    assert "scope" not in recall and "before" not in recall
    assert service.latests[0].get("before") is None
    await memory.aclose()


async def test_recent_and_known_can_be_left_out() -> None:
    service = MemoryService(hits=[LOCKER], recent=[LOCKER])
    memory = _memory(service, recall_recent=0, recall_known=False)
    await _turn(memory, "What is my locker code at the gym?", memory_tools=False)
    assert service.latests == []
    assert not any(s["query"] == "What should I know about this person?" for s in service.searches)
    await memory.aclose()


async def test_small_talk_can_be_searched_and_the_header_is_yours() -> None:
    service = MemoryService(hits=[LOCKER])
    memory = _memory(service, recall_skip_small_talk=False, recall_header="From your notebook:")
    fake = await _turn(memory, "Thanks!", memory_tools=False)
    assert any(s["query"] == "Thanks!" for s in service.searches)
    assert _shown(fake).startswith("From your notebook:\n<memory>")
    await memory.aclose()


async def test_the_size_of_what_is_shown_and_saved() -> None:
    service = MemoryService(hits=[LOCKER])
    memory = _memory(service, recall_max_chars=100, capture_max_chars=10)
    fake = await _turn(memory, "What is my locker code at the gym?", memory_tools=False)
    inside = _shown(fake).split("<memory>\n", 1)[1].split("\n</memory>", 1)[0]
    assert "they said: My locker code" in inside and "you said" not in inside  # one line fits
    assert len(inside) <= 100
    assert all(len(i["text"]) <= 10 for i in service.added)
    await memory.aclose()


async def test_the_agents_replies_need_not_be_saved() -> None:
    service = MemoryService()
    memory = _memory(service, capture_agent_turns=False)
    await _turn(memory, "I'm flying to Porto on Friday.", memory_tools=False)
    assert [i["role"] for i in service.added] == ["user"]
    await memory.aclose()


async def test_card_masking_can_be_turned_off() -> None:
    service = MemoryService()
    memory = _memory(service, mask_cards=False)
    await _turn(memory, "My card is 4111 1111 1111 1111.", memory_tools=False)
    assert "4111 1111 1111 1111" in service.added[0]["text"]
    await memory.aclose()


async def test_the_guide_is_yours_to_word_or_leave_out() -> None:
    service = MemoryService()
    for guide, ends in (("Use memory sparingly.", "Use memory sparingly."), ("", "Be brief.")):
        memory = _memory(service, mode="tools", tool_guide=guide)
        agent = TwinMemoryAgent(memory, instructions="Be brief.")
        assert str(agent.instructions).rstrip().endswith(ends)
        await memory.aclose()


async def test_a_note_is_cut_where_you_say() -> None:
    service = MemoryService()
    memory = _memory(service, mode="tools", note_max_chars=12)
    _search, _read, add = memory.tools()
    assert await add("Prefers a window seat on long flights.") == "Saved."
    assert service.added[-1]["text"] == "Noted: Prefers a wi"  # the fact cut at 12 characters
    await memory.aclose()


@pytest.mark.parametrize(
    "bad",
    [
        {"mode": "always"},
        {"recall_timeout": 0},
        {"tool_timeout": -1},
        {"recall_max_chars": 0},
        {"recall_recent": -1},
        {"flush_timeout": 10},
        {"capture_buffer": 0},
    ],
)
def test_a_setting_that_makes_no_sense_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        TwinMemory("dana", client=MemoryService().client(), **bad)


def test_the_settings_are_kept_to_read() -> None:
    memory = TwinMemory("dana", client=MemoryService().client(), recall_timeout=0.8)
    assert isinstance(memory.settings, Settings) and memory.settings.recall_timeout == 0.8
    with pytest.raises(AttributeError):
        memory.settings.recall_timeout = 2  # pyright: ignore[reportAttributeAccessIssue]
    assert isinstance(memory.tools()[0], llm.FunctionTool)
