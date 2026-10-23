"""`TwinMemoryAgent`: a LiveKit `Agent` that recalls before each reply and saves every turn.

Not the only way in. An agent of your own gets the same by calling `memory.enrich(chat_ctx)` at the
top of its `llm_node` and `memory.attach(self.session)` in its `on_enter`; this class is those two
lines and the memory tools.
"""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Any

from livekit.agents import Agent, ModelSettings, llm

from twinmemory_livekit._memory import TwinMemory


class TwinMemoryAgent(Agent):
    """An `Agent` with long-term memory. Every keyword an `Agent` takes is passed on;
    `memory_tools=False` leaves out `search_memory` and `remember`.

    If you override `llm_node`, `on_user_turn_completed` or `on_enter`, call `super()`.
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
        super().__init__(instructions=instructions, tools=tools, **kwargs)
        self.memory = memory

    async def on_enter(self) -> None:
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

    async def on_user_turn_completed(
        self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage
    ) -> None:
        # A realtime model has no llm_node; this hook is where its turn can still be given memory.
        # (With server-side turn detection it is skipped too, and only capture applies.)
        if isinstance(self.llm, llm.RealtimeModel) or isinstance(
            self.session.llm, llm.RealtimeModel
        ):
            turn_ctx.insert(new_message)
            await self.memory.enrich(turn_ctx)
            turn_ctx.items.remove(new_message)
