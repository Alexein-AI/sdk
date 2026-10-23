"""`TwinMemory`: one call's memory - whose it is, what is recalled for each reply, and every turn
saved - attached to the session rather than to an agent, so it survives handoffs.

Not an agent. `TwinMemoryAgent` is the agent that uses it; an agent of your own calls `enrich` from
its `llm_node`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from livekit import rtc
from livekit.agents import llm
from twinmemory import AsyncMemory, AsyncUser, NotFoundError, TwinMemoryError

from twinmemory_livekit import _identity
from twinmemory_livekit._capture import Writer, item
from twinmemory_livekit._recall import Recall, RecallInfo, place, question

if TYPE_CHECKING:
    from livekit.agents import AgentSession, JobContext
    from livekit.agents.voice.events import CloseEvent, ConversationItemAddedEvent

log = logging.getLogger("twinmemory.livekit")

# Recall shares the reply's critical path. A fast search of earlier calls took 12 ms at p50 and
# 25 ms at p95 on a local stack, with 60 to 120 ms expected hosted: half a second only ever cuts off
# an outage or a hung connection, and it overlaps the wait for the user to finish anyway.
RECALL_SECONDS = 0.5
# LiveKit gives a job's shutdown callbacks 10 s in all; the last turns get half of it.
FLUSH_SECONDS = 5.0
# About 750 tokens. Measured over 26 questions about earlier calls, unfiltered: the answer was in
# the passages kept at 3,000 characters for 25 of them, at 1,200 for 18.
CONTEXT_CHARS = 3000
# A tool call has a thinking pause around it already, so it gets longer than a turn's recall.
_TOOL_SECONDS = 4.0
UNAVAILABLE = "I couldn't reach my memory just now."


class TwinMemory:
    """Long-term memory for one LiveKit call.

    ```python
    memory = TwinMemory.from_job(ctx)  # the user from the job's metadata, if it names one
    await ctx.connect()
    if memory.user_id is None:
        memory.bind(participant=await ctx.wait_for_participant())
    session = AgentSession(...)
    await session.start(room=ctx.room, agent=TwinMemoryAgent(memory, instructions="..."))
    ```

    `memory` is a `twinmemory.AsyncMemory`; by default one is made from TWIN_MEMORY_API_KEY and
    TWIN_MEMORY_BASE_URL, and closed with the call. `session_id` names the call in memory, by
    default the job's id. `fast=False` lets memory's model filter judge each recall: more precise,
    one paid model call and a few hundred milliseconds more per reply.
    """

    def __init__(
        self,
        user_id: str | None = None,
        *,
        memory: AsyncMemory | None = None,
        session_id: str | None = None,
        recall_timeout: float = RECALL_SECONDS,
        fast: bool = True,
    ) -> None:
        self._own_client = memory is None
        # No retries of the client's own: its back-off would turn a dead host into seconds of
        # silence on a turn, and capture retries writes itself.
        self.memory = memory or AsyncMemory(integration="livekit", timeout=5.0, max_retries=0)
        self.session_id = session_id or uuid.uuid4().hex
        self.room: str | None = None
        self.recall = Recall(timeout=recall_timeout, max_chars=CONTEXT_CHARS, fast=fast)
        self._writer = Writer()
        self._user: AsyncUser | None = None
        self._session: AgentSession[Any] | None = None
        self._closed = False
        if user_id is not None:
            self.bind(user_id)

    @classmethod
    def from_job(
        cls, ctx: JobContext, *, metadata_key: str = "twinmemory_user_id", **kwargs: Any
    ) -> TwinMemory:
        """Memory for the call `ctx` runs: the user is the one the job's metadata names under
        `metadata_key` (dispatch with `metadata=json.dumps({"twinmemory_user_id": ...})`), else
        unbound until `bind`. Saves the last turns when the job shuts down."""
        kwargs.setdefault("session_id", ctx.job.id)
        memory = cls(_identity.from_metadata(ctx.job.metadata, metadata_key), **kwargs)
        memory.room = ctx.job.room.name or None
        ctx.add_shutdown_callback(memory.aclose)
        return memory

    @property
    def user_id(self) -> str | None:
        return self._user.id if self._user is not None else None

    @property
    def last_recall(self) -> RecallInfo | None:
        return self.recall.last

    def bind(
        self,
        user_id: str | None = None,
        *,
        participant: rtc.Participant | None = None,
        trust_sip: bool = False,
    ) -> None:
        """Whose memory this call is: your own id for the user, or the participant to take it from.
        Turns said before this wait and are saved under it."""
        if (user_id is None) == (participant is None):
            raise ValueError("bind takes a user_id or a participant, one of them")
        if participant is not None:
            user_id = _identity.from_participant(participant, trust_sip=trust_sip)
        assert user_id is not None
        if self._user is not None and self._user.id != user_id:
            raise ValueError(f"this call is already {self._user.id!r}'s; one call, one memory")
        if self._user is not None:
            return
        self._user = self.memory.user(user_id)
        self._writer.start(self._user)
        self.recall.prime(self._user)

    def attach(self, session: AgentSession[Any]) -> None:
        """Save every turn of `session`. Once per session: attaching again does nothing."""
        if self._session is session:
            return
        if self._session is not None:
            raise ValueError("this memory is already attached to another session")
        self._session = session
        session.on("conversation_item_added", self._on_item)
        session.on("close", self._on_close)

    async def enrich(self, chat_ctx: llm.ChatContext) -> None:
        """Add what memory holds for the user's latest words to `chat_ctx`, for this reply only.
        Call it first thing in `llm_node`; it never raises, and waits at most `recall_timeout`."""
        asked = question(chat_ctx)
        if asked is None or self._user is None or self._closed:
            return
        said, query = asked
        text = await self.recall.context(self._user, query)
        if text:
            place(chat_ctx, said, text)

    def tools(self) -> list[llm.FunctionTool]:
        """`search_memory` and `remember`, for the model to call when it decides to. Both act on
        the bound user only, and answer in a sentence that can be spoken when memory is down."""

        @llm.function_tool
        async def search_memory(query: str) -> str:
            """Look up what you remember about this user from earlier conversations: what they
            said, did and decided. Ask in plain words, for example "where do they live"."""
            if self._user is None:
                return "I don't know who I'm talking to yet, so I have no memory to search."
            try:
                found = await asyncio.wait_for(self._user.search(query), _TOOL_SECONDS)
            except NotFoundError:
                return "Nothing remembered about that."
            except (TwinMemoryError, asyncio.TimeoutError):
                return UNAVAILABLE
            text = found.context(max_chars=CONTEXT_CHARS)
            return UNAVAILABLE if found.failed else (text or "Nothing remembered about that.")

        @llm.function_tool
        async def remember(note: str) -> str:
            """Save one thing about this user to remember in later conversations, in a short
            sentence of its own, for example "Prefers a window seat"."""
            if self._user is None:
                return "I don't know who I'm talking to yet, so I can't save that."
            try:
                saved = await asyncio.wait_for(
                    self._user.add(note, kind="note", session=self.session_id), _TOOL_SECONDS
                )
            except (TwinMemoryError, asyncio.TimeoutError):
                return "I couldn't save that just now."
            return "I couldn't save that just now." if saved.failed else "Saved."

        return [search_memory, remember]

    async def flush(self, timeout: float = FLUSH_SECONDS) -> int:
        """Wait up to `timeout` seconds for the call's turns to be saved; how many were not."""
        return await self._writer.flush(timeout)

    async def aclose(self) -> None:
        """Save what is left, within `FLUSH_SECONDS`, and stop. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        if self._session is not None:
            self._session.off("conversation_item_added", self._on_item)
            self._session.off("close", self._on_close)
        self.recall.cancel()
        await self._writer.aclose(FLUSH_SECONDS)
        if self._own_client:
            await self.memory.close()

    def _on_item(self, event: ConversationItemAddedEvent) -> None:
        if self._closed or not isinstance(event.item, llm.ChatMessage):
            return
        turn = item(event.item, session=self.session_id, room=self.room)
        if turn is not None:
            self._writer.put(turn)

    def _on_close(self, event: CloseEvent) -> None:
        # The job may outlive its session by the room's departure timeout; save now, not then.
        task = asyncio.create_task(self.flush(), name="twinmemory.flush")
        task.add_done_callback(_reported)


def _reported(task: asyncio.Task[int]) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.warning("twin memory flush failed: %s", task.exception())
