"""Two calls against a running Alexein API, end to end: what the first call said is recalled in the
second, and the second call's own words are never handed back to it. Skipped unless
ALEXEIN_LIVE=1, with ALEXEIN_API_KEY (a key that writes) and ALEXEIN_API_URL set (a local stack:
http://localhost:8210).

Free: recall is a fast search, and what was added is forgotten at the end.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid

import pytest
from alexein import AsyncMemory, NotFoundError
from fakes import FakeLLM
from livekit.agents import AgentSession

from alexein_livekit import AlexeinMemory, AlexeinMemoryAgent

pytestmark = pytest.mark.skipif(
    os.environ.get("ALEXEIN_LIVE") != "1", reason="set ALEXEIN_LIVE=1 to run"
)


async def _findable(client: AsyncMemory, user: str, words: str) -> None:
    """Wait until memory finds `words`: an add lands within the consumer's few seconds."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            found = await client.user(user).search(words, fast=True)
            if any(words in e.text for e in found.excerpts):
                return
        except NotFoundError:
            pass
        await asyncio.sleep(0.5)
    raise AssertionError(f"{words!r} never became findable")


async def _call(user: str, call: str, *said: str) -> tuple[FakeLLM, AlexeinMemory]:
    memory, fake = AlexeinMemory(user, session_id=call), FakeLLM(reply="Got it.")
    async with AgentSession(llm=fake) as session:
        await session.start(
            AlexeinMemoryAgent(memory, instructions="Be brief.", memory_tools=False)
        )
        for text in said:
            await session.run(user_input=text)
        assert await memory.flush(10) == 0
    await memory.aclose()
    return fake, memory


def _memory_for_last_turn(fake: FakeLLM) -> str:
    return next((text for _, text in reversed(fake.calls[-1]) if "<memory>" in text), "")


async def test_the_next_call_remembers_this_one_and_never_itself() -> None:
    user, code = f"lk-live-{uuid.uuid4().hex[:8]}", f"{uuid.uuid4().int % 9000 + 1000}"
    calls = [f"live-{uuid.uuid4().hex[:6]}-1", f"live-{uuid.uuid4().hex[:6]}-2"]
    client = AsyncMemory(max_retries=0)
    try:
        await _call(user, calls[0], f"My locker code at the Alfama gym is {code}.")
        await _findable(client, user, code)

        memory, fake = AlexeinMemory(user, session_id=calls[1]), FakeLLM(reply="Got it.")
        async with AgentSession(llm=fake) as session:
            agent = AlexeinMemoryAgent(memory, instructions="Be brief.", memory_tools=False)
            await session.start(agent)
            await session.run(user_input="What is my locker code at the gym?")
            shown = _memory_for_last_turn(fake)
            assert code in shown, shown
            assert memory.last_recall is not None and memory.last_recall.ms < 500

            await session.run(user_input="My favourite colour for the new locker is teal.")
            assert await memory.flush(10) == 0
            await _findable(client, user, "teal")
            await session.run(user_input="Which colour did I pick for the locker again?")
            assert "teal" not in _memory_for_last_turn(fake)  # this call is not recalled to itself
        await memory.aclose()
    finally:
        await client.user(user).forget(sessions=calls)
        await client.close()
