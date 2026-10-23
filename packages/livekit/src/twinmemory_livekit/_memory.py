"""`TwinMemory`: one call's memory - whose it is, what is recalled for each reply, and every turn
saved - attached to the session rather than to an agent, so it survives handoffs.

Two modes, as LangGraph's nodes and tools are two halves. "auto" recalls before every reply and
saves every turn, and lends the model tools to look further. "tools" does nothing by itself: the
model has `memory_search`, `memory_read` and `memory_add`, and decides when to use them.

Not an agent. `TwinMemoryAgent` is the agent that uses it; an agent of your own calls `enrich` from
its `llm_node` and gives its model `tools()`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

from livekit import rtc
from livekit.agents import llm
from twinmemory import AsyncMemory, AsyncUser, Hit, Item

from twinmemory_livekit import _identity, _tools
from twinmemory_livekit._capture import Writer, item
from twinmemory_livekit._recall import Recall, RecallInfo, how, place, question
from twinmemory_livekit._settings import HEADER, Mode, Redact, Settings

if TYPE_CHECKING:
    from livekit.agents import AgentSession, JobContext
    from livekit.agents.voice.events import CloseEvent, ConversationItemAddedEvent

log = logging.getLogger("twinmemory.livekit")


class TwinMemory:
    """Long-term memory for one LiveKit call.

    ```python
    memory = TwinMemory.from_job(ctx)  # mode="tools" to let the model decide
    await ctx.connect()
    memory.bind(participant=await ctx.wait_for_participant())
    session = AgentSession(...)
    memory.attach(session)
    await session.start(room=ctx.room, agent=TwinMemoryAgent(memory, instructions="..."))
    ```

    By default the client is made from `api_key` and `base_url`, else TWIN_MEMORY_API_KEY and
    TWIN_MEMORY_BASE_URL, and closed with the call; `client` is one of your own (make it with
    `max_retries=0`). `session_id` names the call in memory. Every other keyword is a field of
    `Settings`, which says what each does and why its default is what it is; they are kept, read
    only, as `memory.settings`. Measured defaults (README, "Settings"): recall in tens of
    milliseconds, waited for at most half a second; 2,000 characters of what was said, the agent's
    words too, which held 24 of 26 answers where whole passages held 21.
    """

    def __init__(
        self,
        user_id: str | None = None,
        *,
        mode: Mode = "auto",
        client: AsyncMemory | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        session_id: str | None = None,
        recall_fast: bool = True,
        recall_timeout: float = 0.5,
        recall_max_chars: int = 2000,
        recall_agent_turns: bool = True,
        recall_recent: int = 6,
        recall_known: bool = True,
        recall_skip_small_talk: bool = True,
        recall_reuse_seconds: float = 30.0,
        recall_header: str = HEADER,
        search_current_call: bool = False,
        tool_fast: bool = True,
        tool_timeout: float = 4.0,
        save_timeout: float = 2.0,
        note_max_chars: int = 500,
        tool_guide: str | None = None,
        capture_agent_turns: bool = True,
        capture_max_chars: int = 8000,
        capture_buffer: int = 500,
        mask_cards: bool = True,
        redact: Redact | None = None,
        flush_timeout: float = 5.0,
    ) -> None:
        self.settings = Settings(
            mode=mode,
            recall_fast=recall_fast,
            recall_timeout=recall_timeout,
            recall_max_chars=recall_max_chars,
            recall_agent_turns=recall_agent_turns,
            recall_recent=recall_recent,
            recall_known=recall_known,
            recall_skip_small_talk=recall_skip_small_talk,
            recall_reuse_seconds=recall_reuse_seconds,
            recall_header=recall_header,
            search_current_call=search_current_call,
            tool_fast=tool_fast,
            tool_timeout=tool_timeout,
            save_timeout=save_timeout,
            note_max_chars=note_max_chars,
            tool_guide=tool_guide,
            capture_agent_turns=capture_agent_turns,
            capture_max_chars=capture_max_chars,
            capture_buffer=capture_buffer,
            mask_cards=mask_cards,
            redact=redact,
            flush_timeout=flush_timeout,
        )
        self._own_client = client is None
        # No retries of the client's own: its back-off would turn a dead host into seconds of
        # silence on a turn, and capture retries writes itself.
        self.client = client or AsyncMemory(
            api_key, base_url=base_url, integration="livekit", timeout=5.0, max_retries=0
        )
        self.session_id = session_id or uuid.uuid4().hex
        self.room: str | None = None
        self._recall = Recall(self.settings)
        self.noted: list[str] = []  # the facts memory_add saved in this call, in order
        self._writer = Writer(max_buffer=capture_buffer)
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
    def user(self) -> AsyncUser | None:
        """The bound user's memory, through the client; None until `bind`."""
        return self._user

    @property
    def user_id(self) -> str | None:
        return self._user.id if self._user is not None else None

    @property
    def last_recall(self) -> RecallInfo | None:
        return self._recall.last

    @property
    def mode(self) -> Mode:
        return self.settings.mode

    @property
    def guide(self) -> str:
        """What a model given `tools()` is told about its memory, after your instructions:
        `tool_guide`, else in tools mode when to search and save, in auto mode that memory is
        given to it already."""
        return self.settings.guide

    def where(self) -> dict[str, str]:
        """What a search is narrowed to: earlier calls, unless `search_current_call`."""
        return self._recall.where()

    @property
    def since(self) -> str:
        """When this call began: what is saved from then on is this call's, and not searched."""
        return self._recall.since

    @property
    def known(self) -> list[str]:
        """What memory holds as true about the user now, looked up once when they were bound."""
        return list(self._recall.known)

    @property
    def recent(self) -> list[Hit]:
        """The user's last calls' passages, newest first, looked up once when they were bound."""
        return list(self._recall.recent)

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
        """Close with `session`, and in auto mode save every turn of it. Attaching again does
        nothing."""
        if self._session is session:
            return
        if self._session is not None:
            raise ValueError("this memory is already attached to another session")
        self._session = session
        if self.mode == "auto":
            session.on("conversation_item_added", self._on_item)
        session.on("close", self._on_close)

    async def enrich(self, chat_ctx: llm.ChatContext) -> None:
        """In auto mode, add what memory holds for the user's latest words to `chat_ctx`, for this
        reply only. Call it first thing in `llm_node`; it never raises, and waits at most
        `recall_timeout`."""
        if self.mode != "auto" or self._user is None or self._closed:
            return
        asked = question(chat_ctx, skip_small_talk=self.settings.recall_skip_small_talk)
        if asked is None:
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
        """The memory tools for the model: `memory_search` and `memory_read`, and in tools mode
        `memory_add`. They act on the bound user only, and answer in a sentence that can be spoken
        when memory is down."""
        return _tools.tools(self, write=self.mode == "tools")

    def note(self, fact: Item) -> None:
        """Queue `fact` to be saved, after the turns before it."""
        self._writer.put(fact)

    async def flush(self, timeout: float | None = None) -> int:
        """Wait up to `timeout` seconds for the call's turns to be saved; how many were not."""
        wait = self.settings.flush_timeout if timeout is None else timeout
        return await self._writer.flush(wait)

    async def aclose(self) -> None:
        """Save what is left, within `flush_timeout`, and stop. Safe to call more than once: every
        caller returns once the one close is done."""
        if self._closing is None:
            self._closed = True
            self._closing = asyncio.ensure_future(self._close())
        await asyncio.shield(self._closing)

    async def _close(self) -> None:
        if self._session is None:
            if self.mode == "auto":
                log.warning("twin memory was never attached to a session: no turn was saved")
        else:
            if self.mode == "auto":
                self._session.off("conversation_item_added", self._on_item)
            self._session.off("close", self._on_close)
        self._recall.cancel()
        await self._writer.aclose(self.settings.flush_timeout)
        if self._own_client:
            await self.client.close()

    def _on_item(self, event: ConversationItemAddedEvent) -> None:
        if self._closed or not isinstance(event.item, llm.ChatMessage):
            return
        turn = item(event.item, session=self.session_id, room=self.room, settings=self.settings)
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
