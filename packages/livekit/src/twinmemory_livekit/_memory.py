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
from twinmemory import AsyncMemory, AsyncUser, NotFoundError

from twinmemory_livekit import _identity
from twinmemory_livekit._capture import Redact, Writer, item
from twinmemory_livekit._recall import Recall, RecallInfo, how, place, question

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
_NOTE_CHARS = 500
UNAVAILABLE = "I couldn't reach my memory just now."
NOTHING = "Nothing remembered about that."


class TwinMemory:
    """Long-term memory for one LiveKit call.

    ```python
    memory = TwinMemory.from_job(ctx)
    await ctx.connect()
    memory.bind(participant=await ctx.wait_for_participant())
    session = AgentSession(...)
    memory.attach(session)
    await session.start(room=ctx.room, agent=TwinMemoryAgent(memory, instructions="..."))
    ```

    By default the client is made from `api_key` and `base_url`, else TWIN_MEMORY_API_KEY and
    TWIN_MEMORY_BASE_URL, and closed with the call; `client` is one of your own (make it with
    `max_retries=0`). `session_id` names the call in memory. `fast=False` lets memory's model
    filter judge each recall: more precise, one paid model call and a few hundred milliseconds more
    per reply. `redact(role, text)` sees each turn before it is saved, and returns the text to save,
    changed or not, or None to save nothing of it.
    """

    def __init__(
        self,
        user_id: str | None = None,
        *,
        client: AsyncMemory | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        session_id: str | None = None,
        recall_timeout: float = RECALL_SECONDS,
        fast: bool = True,
        redact: Redact | None = None,
    ) -> None:
        self._own_client = client is None
        # No retries of the client's own: its back-off would turn a dead host into seconds of
        # silence on a turn, and capture retries writes itself.
        self.client = client or AsyncMemory(
            api_key, base_url=base_url, integration="livekit", timeout=5.0, max_retries=0
        )
        self.session_id = session_id or uuid.uuid4().hex
        self.room: str | None = None
        self._recall = Recall(timeout=recall_timeout, max_chars=CONTEXT_CHARS, fast=fast)
        self._redact = redact
        self._writer = Writer()
        self._user: AsyncUser | None = None
        self._session: AgentSession[Any] | None = None
        self._closed = False
        self._closing: asyncio.Future[None] | None = None
        if user_id is not None:
            self.bind(user_id)

    @classmethod
    def from_job(
        cls, ctx: JobContext, *, metadata_key: str | None = None, **kwargs: Any
    ) -> TwinMemory:
        """Memory for the call `ctx` runs, named by the job's id and saved when the job ends.

        With `metadata_key`, the user is the one the job's metadata names under it - for a backend
        that dispatches with `metadata=json.dumps({"twinmemory_user_id": ...})`. Only where your
        own server writes that metadata: a token server that copies it from a client's request
        would let the caller choose whose memory they get."""
        kwargs.setdefault("session_id", ctx.job.id)
        named = _identity.from_metadata(ctx.job.metadata, metadata_key) if metadata_key else None
        memory = cls(named, **kwargs)
        memory.room = ctx.job.room.name or None
        ctx.add_shutdown_callback(memory.aclose)
        return memory

    @property
    def user_id(self) -> str | None:
        return self._user.id if self._user is not None else None

    @property
    def last_recall(self) -> RecallInfo | None:
        return self._recall.last

    def bind(
        self,
        user_id: str | None = None,
        *,
        participant: rtc.Participant | None = None,
        trust_phone: bool = False,
    ) -> str | None:
        """Whose memory this call is - your own id for the user, or the participant to take it
        from - and the id bound. Turns said before this wait, and are saved under it.

        A phone caller (SIP, or a connector such as WhatsApp) is left unbound unless `trust_phone`,
        since a number can be spoofed: the call goes on without memory, and you may bind the id you
        look the caller up by instead."""
        if self._closed:
            raise RuntimeError("this call's memory is closed")
        if (user_id is None) == (participant is None):
            raise ValueError("bind takes a user_id or a participant, one of them")
        if participant is not None:
            user_id = _identity.from_participant(participant, trust_phone=trust_phone)
            if user_id is None:
                log.warning("twin memory: participant kind %s not bound", participant.kind)
                return None
        assert user_id is not None
        if self._user is not None:
            if self._user.id != user_id:
                raise ValueError("this call already has a user; one call, one memory")
            return user_id
        self._user = self.client.user(user_id)
        self._writer.start(self._user)
        self._recall.prime(self._user)
        return user_id

    def attach(self, session: AgentSession[Any]) -> None:
        """Save every turn of `session`, and close with it. Attaching again does nothing."""
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
        try:
            text = await self._recall.context(self._user, query)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # a reply is never stopped by memory
            log.warning("twin memory recall failed (%s), reply goes on", how(error))
            return
        if text:
            place(chat_ctx, said, text)

    def tools(self) -> list[llm.FunctionTool]:
        """`memory_search` and `memory_remember`, for the model to call when it decides to. Both act
        on the bound user only, and answer in a sentence that can be spoken when memory is down."""

        @llm.function_tool
        async def memory_search(query: str) -> str:
            """Look up what you remember about this user from earlier conversations: what they
            said, did and decided. Ask in plain words, for example "where do they live"."""
            if self._user is None:
                return "I don't know who I'm talking to yet, so I have no memory to search."
            search = self._user.search(query[:1000], fast=self._recall.fast)
            try:
                found = await asyncio.wait_for(search, _TOOL_SECONDS)
            except NotFoundError:
                return NOTHING
            except Exception:
                return UNAVAILABLE
            if found.failed:
                return UNAVAILABLE
            return found.context(max_chars=CONTEXT_CHARS) or NOTHING

        @llm.function_tool
        async def memory_remember(note: str) -> str:
            """Save one thing about this user to remember in later conversations, in a short
            sentence of its own, for example "Prefers a window seat"."""
            if self._user is None:
                return "I don't know who I'm talking to yet, so I can't save that."
            add = self._user.add(note[:_NOTE_CHARS], kind="note", session=self.session_id)
            try:
                saved = await asyncio.wait_for(add, _TOOL_SECONDS)
            except Exception:
                return "I couldn't save that just now."
            return "I couldn't save that just now." if saved.failed else "Saved."

        return [memory_search, memory_remember]

    async def flush(self, timeout: float = FLUSH_SECONDS) -> int:
        """Wait up to `timeout` seconds for the call's turns to be saved; how many were not."""
        return await self._writer.flush(timeout)

    async def aclose(self) -> None:
        """Save what is left, within `FLUSH_SECONDS`, and stop. Safe to call more than once: every
        caller returns once the one close is done."""
        if self._closing is None:
            self._closed = True
            self._closing = asyncio.ensure_future(self._close())
        await asyncio.shield(self._closing)

    async def _close(self) -> None:
        if self._session is None:
            log.warning("twin memory was never attached to a session: no turn was saved")
        else:
            self._session.off("conversation_item_added", self._on_item)
            self._session.off("close", self._on_close)
        self._recall.cancel()
        await self._writer.aclose(FLUSH_SECONDS)
        if self._own_client:
            await self.client.close()

    def _on_item(self, event: ConversationItemAddedEvent) -> None:
        if self._closed or not isinstance(event.item, llm.ChatMessage):
            return
        turn = item(event.item, session=self.session_id, room=self.room, redact=self._redact)
        if turn is not None:
            self._writer.put(turn)

    def _on_close(self, event: CloseEvent) -> None:
        # The job may outlive its session by the room's departure timeout; save now, not then.
        task = asyncio.create_task(self.aclose(), name="twinmemory.close")
        task.add_done_callback(_reported)


def _reported(task: asyncio.Task[None]) -> None:
    error = None if task.cancelled() else task.exception()
    if isinstance(error, Exception):
        log.warning("twin memory close failed (%s)", how(error))
