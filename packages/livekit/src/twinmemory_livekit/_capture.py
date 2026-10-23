"""Capture: every turn of a call saved to the user's memory, in the order it was said.

It listens to the session's `conversation_item_added`, which LiveKit emits once a message is in the
history, typed or spoken, from whichever agent is speaking; an interrupted reply holds only what was
actually said. One writer drains one queue, so turns land in order, and each item's id is the call
and LiveKit's id for the message, so a retry or a second delivery replaces rather than duplicates.

Not a transcript store: handoffs, tool calls, empty messages and what recall added are skipped,
and `redact` may change or drop any turn before it leaves the process.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from datetime import datetime, timezone

from livekit.agents import llm
from twinmemory import AsyncUser, Author, InvalidRequestError, Item, TwinMemoryError

from twinmemory_livekit._recall import MARK, how
from twinmemory_livekit._settings import Settings

log = logging.getLogger("twinmemory.livekit")

# Turns wait while memory is down or the user is not yet known, up to `capture_buffer`; past it
# the oldest go, with a warning, so a long outage cannot grow a call's memory use without bound.
# A turn past `capture_max_chars` (a dictated paragraph is a few hundred) is cut, not refused.
_BATCH = 20
# A write that takes longer than this is tried again; ids make the second attempt replace the first.
_WRITE_SECONDS = 5.0
_BACKOFF = (0.5, 1.0, 2.0, 4.0, 8.0)
# A card number, said over the phone: 13 to 19 digits, spaced or dashed as people read them out.
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _luhn(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def saved_text(role: str, text: str, settings: Settings) -> str:
    """`text` as the settings let it be saved - card numbers masked, then your `redact` - or
    empty for nothing."""
    text = masked(text) if settings.mask_cards else text
    if settings.redact is not None:
        text = settings.redact(role, text) or ""
    return text.strip()


def masked(text: str) -> str:
    """`text` with every card number in it - its checksum holds, so an order number or a phone
    number does not - as "[card number]". Before any `redact` of yours, in both modes: a model told
    never to save one saved one (tools mode, gpt-4.1-mini), and a transcript keeps what was said."""

    def card(found: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", found.group())
        return "[card number]" if _luhn(digits) else found.group()

    return _CARD.sub(card, text)


def item(
    message: llm.ChatMessage, *, session: str, room: str | None, settings: Settings
) -> Item | None:
    """`message` as an item of the call `session`; None for what is not a turn worth keeping."""
    roles = ("user", "assistant") if settings.capture_agent_turns else ("user",)
    if message.role not in roles or MARK in message.extra:
        return None
    text = saved_text(message.role, (message.text_content or "").strip(), settings)
    if not text:
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
        text=text[: settings.capture_max_chars],
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

    def __init__(self, max_buffer: int = 500) -> None:
        self.max_buffer = max_buffer
        self._waiting: list[Item] = []
        self._sending: list[Item] = []
        self._user: AsyncUser | None = None
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: asyncio.Task[None] | None = None
        self._refused = False
        self._closed = False
        self._failed: set[str] = set()
        self.dropped = 0

    def put(self, turn: Item) -> None:
        if len(self._waiting) >= self.max_buffer:
            # The oldest turn not on its way already: one being sent may still land.
            oldest = next((t for t in self._waiting if not _among(t, self._sending)), None)
            if oldest is not None:
                self._waiting.remove(oldest)
                self.dropped += 1
                if self.dropped == 1:
                    log.warning(
                        "twin memory unreachable for %d turns, dropping the oldest", self.max_buffer
                    )
        self._waiting.append(turn)
        self._idle.clear()
        self._wake.set()
        self._ensure()

    def start(self, user: AsyncUser) -> None:
        """Save to `user` from now on, the turns that waited for them first."""
        self._user = user
        self._wake.set()
        self._ensure()

    async def flush(self, timeout: float) -> int:
        """Wait up to `timeout` seconds for every queued turn to be saved; how many were not."""
        if self._user is not None and not self._closed:
            self._ensure()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._idle.wait(), timeout)
        return len(self._waiting)

    async def aclose(self, timeout: float) -> None:
        left = await self.flush(timeout)
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if left:
            why = "memory was unreachable" if self._user else "no user was ever bound"
            log.warning("twin memory: %d turns of this call were not saved, %s", left, why)

    def _ensure(self) -> None:
        """The writer task, started once there is a user and an event loop to run it on."""
        if self._task is not None or self._user is None or self._closed:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # no running loop yet: the first turn starts it
        self._task = asyncio.create_task(self._run(), name="twinmemory.capture")
        self._task.add_done_callback(_reported)

    async def _run(self) -> None:
        failures = 0
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._waiting and self._user is not None:
                self._sending = self._waiting[:_BATCH]
                if await self._save(self._user, self._sending):
                    self._waiting = [t for t in self._waiting if not _among(t, self._sending)]
                    failures = 0
                    continue
                await asyncio.sleep(_BACKOFF[min(failures, len(_BACKOFF) - 1)])
                failures += 1
            self._sending = []
            if not self._waiting:
                self._idle.set()

    async def _save(self, user: AsyncUser, batch: list[Item]) -> bool:
        """True once `batch` is saved or can never be; False to try it again later."""
        try:
            result = await asyncio.wait_for(user.add(batch), _WRITE_SECONDS)
        except asyncio.TimeoutError:
            return False
        except InvalidRequestError as error:
            if len(batch) > 1:  # one bad turn: save them one by one, in order, until one must wait
                for turn in batch:
                    if not await self._save(user, [turn]):
                        return False
                return True
            self._refuse(error)
            return True
        except TwinMemoryError as error:
            if error.outage:
                return False
            self._refuse(error)  # a wrong key, or one that cannot write: retrying cannot help
            return True
        except Exception as error:
            # Not the service's answer (a proxy's page, a closed client): like an outage, wait.
            if type(error).__name__ not in self._failed:
                self._failed.add(type(error).__name__)
                log.warning("twin memory save failed (%s), will retry", how(error))
            return False
        return not result.failed

    def _refuse(self, error: TwinMemoryError) -> None:
        if not self._refused:
            self._refused = True
            log.error("twin memory refused this call's turns, not saved (%s)", how(error))


def _among(turn: Item, batch: list[Item]) -> bool:
    return any(turn is sent for sent in batch)


def _reported(task: asyncio.Task[None]) -> None:
    error = None if task.cancelled() else task.exception()
    if isinstance(error, Exception):
        log.error("twin memory capture stopped (%s)", how(error))
