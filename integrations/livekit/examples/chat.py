"""Talk to an agent with Alexein memory in your terminal: each run is one call, your typed turns go
through the same `AgentSession` and `AlexeinMemoryAgent` a LiveKit voice agent uses, and quitting
ends the call.

    uv run python examples/chat.py dana     # call 1: tell it something, then /quit
    uv run python examples/chat.py dana     # call 2, a few seconds later: ask about it

`--mode tools` is the other mode: nothing is recalled or saved by itself, and the model calls
memory_search, memory_open and memory_add when it decides to - so it needs a real model.

Needs ALEXEIN_API_KEY (a key that writes); ALEXEIN_API_URL for a server other than
https://api.alexein.ai. Without a model key the
agent's model is a stand-in that only says what memory it was shown before each reply. With
OPENAI_API_KEY or OPENROUTER_API_KEY it is a real model:

    uv run --with livekit-plugins-openai python examples/chat.py dana

Not a voice agent: no room, no audio, and nothing here is needed to use the package.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from collections.abc import AsyncIterable
from typing import Any

from livekit.agents import DEFAULT_API_CONNECT_OPTIONS, Agent, AgentSession, ModelSettings, llm

from alexein_livekit import AlexeinMemory, AlexeinMemoryAgent
from alexein_livekit._settings import Mode

INSTRUCTIONS = (
    "You are a friendly assistant on a phone line. Keep replies to one or two sentences. Use what "
    "you remember about the caller where it helps."
)


def shown(chat_ctx: llm.ChatContext) -> list[str]:
    """The lines recall put in front of the model this turn."""
    for message in chat_ctx.messages():
        text = message.text_content or ""
        if message.role == "assistant" and "<memory>" in text:
            inside = text.split("<memory>\n", 1)[1].split("\n</memory>", 1)[0]
            return [line.removeprefix("- ") for line in inside.splitlines() if line.strip()]
    return []


class StandIn(llm.LLM):
    """A model that only says how much memory it was shown; the lines are printed above it."""

    def chat(self, *, chat_ctx: llm.ChatContext, **kwargs: Any) -> llm.LLMStream:
        return _Said(self, chat_ctx=chat_ctx, tools=[], conn_options=DEFAULT_API_CONNECT_OPTIONS)


class _Said(llm.LLMStream):
    async def _run(self) -> None:
        lines = shown(self._chat_ctx)
        if lines:
            reply = f"(stand-in model) I was shown the {len(lines)} memories printed above."
        else:
            reply = "(stand-in model) I was shown no memory for this turn."
        self._event_ch.send_nowait(
            llm.ChatChunk(id="standin", delta=llm.ChoiceDelta(role="assistant", content=reply))
        )


def model() -> llm.LLM:
    if os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        from livekit.plugins import openai  # pyright: ignore[reportMissingImports]  # --with livekit-plugins-openai

        if os.environ.get("OPENROUTER_API_KEY"):
            return openai.LLM(
                model="openai/gpt-4.1-mini",
                base_url="https://openrouter.ai/api/v1",
                api_key=os.environ["OPENROUTER_API_KEY"],
            )
        return openai.LLM(model="gpt-4.1-mini")
    return StandIn()


class ChatAgent(AlexeinMemoryAgent):
    """`AlexeinMemoryAgent`, printing what recall found before each reply."""

    async def llm_node(
        self, chat_ctx: llm.ChatContext, tools: list[llm.Tool], model_settings: ModelSettings
    ) -> AsyncIterable[llm.ChatChunk | str]:
        before = self.memory.last_recall
        await self.memory.enrich(chat_ctx)
        info = self.memory.last_recall
        if self.memory.mode != "auto":
            pass  # nothing is recalled by itself; the tools say what the model looked up
        elif info is None or info is before:
            print("   [memory: not searched, nothing to look up in that]")
        elif not info.reused:
            how = "timed out" if info.timed_out else "failed" if info.failed else "ok"
            print(f"   [memory: {info.chars} chars in {info.ms:.0f} ms, {how}]")
            for n, line in enumerate(shown(chat_ctx), 1):
                print(f"   [{n}] {line}")
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            yield chunk  # pyright: ignore[reportReturnType]


async def call(user: str, mode: Mode) -> None:
    llm_ = model()
    if mode == "tools" and isinstance(llm_, StandIn):
        raise SystemExit(
            "--mode tools needs a real model: set OPENAI_API_KEY or OPENROUTER_API_KEY"
        )
    memory = AlexeinMemory(user, mode=mode, session_id=f"chat-{uuid.uuid4().hex[:8]}")
    session = AgentSession(llm=llm_)
    memory.attach(session)

    def said_by_agent(event: Any) -> None:
        if getattr(event.item, "role", "") == "assistant":
            print(f"agent> {event.item.text_content}")

    def used_a_tool(event: Any) -> None:
        for called, output in zip(event.function_calls, event.function_call_outputs, strict=False):
            answer = " ".join((output.output if output else "").split())[:160]
            print(f"   [tool {called.name}({called.arguments}) -> {answer}]")

    session.on("conversation_item_added", said_by_agent)
    session.on("function_tools_executed", used_a_tool)

    # The stand-in model cannot call tools; a real one gets them.
    tools = not isinstance(llm_, StandIn)
    await session.start(ChatAgent(memory, instructions=INSTRUCTIONS, memory_tools=tools))
    print(
        f"A call as {memory.user_id!r} in {mode} mode, session {memory.session_id}. /quit ends it."
    )
    while True:
        try:
            said = (await asyncio.to_thread(input, "you>   ")).strip()
        except EOFError:
            break
        if said in ("/quit", "/exit"):
            break
        if said:
            await session.run(user_input=said)
    left = await memory.flush()
    print(f"Call over: {'every turn saved' if left == 0 else f'{left} turns not saved'}.")
    await session.aclose()
    await memory.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("user", help="the caller's app user id, e.g. dana")
    parser.add_argument("--mode", choices=("auto", "tools"), default="auto")
    args = parser.parse_args()
    asyncio.run(call(args.user, args.mode))


if __name__ == "__main__":
    main()
