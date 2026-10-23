"""`TwinMemoryAgent`: a LiveKit `Agent` that recalls before each reply and saves every turn.

Not the only way in. An agent of your own gets the same by calling `memory.enrich(chat_ctx)` at the
top of its `llm_node`, with `memory.attach(session)` before the session starts; this class is those
lines and the memory tools. Not for a realtime (speech to speech) model, which has no `llm_node`:
its turns are saved once the memory is attached, but nothing is recalled for it.
"""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Any

from livekit.agents import Agent, ModelSettings, llm

from twinmemory_livekit._memory import TwinMemory


class TwinMemoryAgent(Agent):
    """An `Agent` with long-term memory, in the memory's mode. Every keyword an `Agent` takes is
    passed on. In auto mode `memory_tools=False` leaves out `memory_search` and `memory_read`; in
    tools mode the tools are its memory, and the model is told when to use them.

    If you override `llm_node` or `on_enter`, call `super()`.
    """

    def __init__(
        self,
        memory: TwinMemory,
        *,
        instructions: str,
        tools: list[llm.Tool | llm.Toolset] | None = None,
        memory_tools: bool = True,
        **kwargs: Any,
    ) -> None:
        if memory_tools:
            tools = [*(tools or []), *memory.tools()]
        elif memory.mode == "tools":
            raise ValueError('memory_tools=False leaves a mode="tools" memory nothing to do')
        if memory.guide:
            instructions = f"{instructions}\n\n{memory.guide}"
        super().__init__(instructions=instructions, tools=tools, **kwargs)
        self.memory = memory

    async def on_enter(self) -> None:
        # In case the entrypoint did not: saving the turns must not hang on one line of setup.
        self.memory.attach(self.session)

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings: ModelSettings,
    ) -> AsyncIterable[llm.ChatChunk | str]:
        await self.memory.enrich(chat_ctx)
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            yield chunk  # pyright: ignore[reportReturnType]
