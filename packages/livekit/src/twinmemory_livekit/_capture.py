"""Capture: every turn of a call saved to the user's memory, in the order it was said.

It listens to the session's `conversation_item_added`, which LiveKit emits once a message is in the
history, typed or spoken, from whichever agent is speaking; an interrupted reply holds only what was
actually said. One writer drains one queue, so turns land in order, and each item's id is the call
and LiveKit's id for the message, so a retry or a second delivery replaces rather than duplicates.

Not a transcript store: handoffs, tool calls, empty messages and what recall added are skipped.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

from livekit.agents import llm
from twinmemory import AsyncUser, Author, Item, TwinMemoryError

from twinmemory_livekit._recall import MARK

log = logging.getLogger("twinmemory.livekit")

# Turns wait here while memory is down or the user is not yet known; past this the oldest go, with
# a warning, so a long outage cannot grow a call's memory use without bound.
MAX_BUFFER = 500
_BATCH = 20
# A write that takes longer than this is tried again; ids make the second attempt replace the first.
_WRITE_SECONDS = 5.0
_BACKOFF = (0.5, 1.0, 2.0, 4.0, 8.0)


def item(message: llm.ChatMessage, *, session: str, room: str | None) -> Item | None:
    """`message` as an item of the call `session`; None for what is not a turn worth keeping."""
    text = (message.text_content or "").strip()
    if message.role not in ("user", "assistant") or not text or MARK in message.extra:
        return None
    metadata: dict[str, object] = {"livekit_item": message.id}
    if message.interrupted:
        metadata["interrupted"] = True
    if room:
        metadata["room"] = room
    at = datetime.fromtimestamp(message.created_at, tz=timezone.utc)
    turn = Item(
        id=f"lk:{session}:{message.id}",
        kind="message",
        role=message.role,
        text=text,
        session=session,
        at=at.isoformat(timespec="milliseconds"),
        metadata=metadata,
    )
    if message.role == "user":
        # The person whose memory this is: what lets memory say "you" and not "a user".
        turn["author"] = Author(self=True)
    return turn


class Writer:
    """One queue of a call's turns and the one task that saves them."""

    def __init__(self) -> None:
        self._waiting: list[Item] = []
        self._user: AsyncUser | None = None
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: asyncio.Task[None] | None = None
        self._refused = False
        self.dropped = 0

    def put(self, turn: Item) -> None:
        if len(self._waiting) >= MAX_BUFFER:
            self._waiting.pop(0)
            self.dropped += 1
            if self.dropped == 1:
                log.warning("twin memory unreachable for %d turns: dropping the oldest", MAX_BUFFER)
        self._waiting.append(turn)
        self._idle.clear()
        self._wake.set()

    def start(self, user: AsyncUser) -> None:
        """Save to `user` from now on, the turns that waited for them first."""
        self._user = user
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="twinmemory.capture")
        self._wake.set()

    async def flush(self, timeout: float) -> int:
        """Wait up to `timeout` seconds for every queued turn to be saved; how many were not."""
        if self._user is not None:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._idle.wait(), timeout)
        return len(self._waiting)

    async def aclose(self, timeout: float) -> None:
        left = await self.flush(timeout)
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if left:
            log.warning("twin memory: %d turns of this call were not saved", left)

    async def _run(self) -> None:
        failures = 0
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._waiting and self._user is not None:
                batch = self._waiting[:_BATCH]
                if await self._save(self._user, batch):
                    del self._waiting[: len(batch)]
                    failures = 0
                    continue
                await asyncio.sleep(_BACKOFF[min(failures, len(_BACKOFF) - 1)])
                failures += 1
            if not self._waiting:
                self._idle.set()

    async def _save(self, user: AsyncUser, batch: list[Item]) -> bool:
        """True once `batch` is saved or can never be; False to try it again later."""
        try:
            result = await asyncio.wait_for(user.add(batch), _WRITE_SECONDS)
        except asyncio.TimeoutError:
            return False
        except TwinMemoryError as error:
            if error.outage:
                return False
            # A wrong key, or a key that cannot write: trying again cannot help.
            if not self._refused:
                self._refused = True
                log.error("twin memory refused this call's turns, they are not saved: %s", error)
            return True
        return not result.failed
