"""Recall: what memory holds for the user's latest words, placed just before them in the prompt.

It runs in `llm_node`, not in `on_user_turn_completed`. LiveKit starts a reply before it is sure
the user has finished (preemptive generation, on by default), from a copy of the context, and
throws that reply away if `on_user_turn_completed` changes the turn; `llm_node` runs inside the
early reply as well, so recall there starts early instead of cancelling the head start, and it
runs for typed turns too, which that hook never sees. One lookup per question is shared by the
early reply, the confirmed one and the model calls after a tool runs; a turn whose lookup is late
goes ahead without memory rather than wait.

What it searches is earlier calls only: the model already has this one, and memory would hand
its own turns back. Not a cache of memory: a lookup is reused for half a minute, one turn.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from livekit.agents import llm
from twinmemory import AsyncUser, Hit, NotFoundError, SearchResult, TwinMemoryError

log = logging.getLogger("twinmemory.livekit")

# A reply like "yes" or "the second one" says nothing a search can find; with the agent's last
# words before it, it says what was asked.
_SHORT = 4
_ASKED_CHARS = 300
_QUERY_CHARS = 1000
# Unfiltered search returns six to eight passages for anything, "thanks" included: these turns
# would only fill the prompt with noise.
_PHATIC = frozenset(
    {"hi", "hello", "hey", "thanks", "thank", "you", "ok", "okay", "bye", "goodbye", "cheers"}
    | {"hmm", "um", "uh", "mhm", "right", "cool", "great"}
)

# One turn: a preemptive reply, the confirmed one and a tool's follow-up arrive within seconds.
_REUSE_SECONDS = 30.0
_REUSED = 8

# The ranked search over messages, which is the one whose `before` keeps time of day: earlier
# calls of the same day are kept and this call is left out (the brief's `before` is a whole day).
_EARLIER_CALLS = "passages/memory"
_ABOUT = "What should I know about this person?"

# The marker on what recall adds to a prompt, so capture never saves it as something said.
MARK = "twinmemory"

HEADER = (
    "Background from earlier conversations with this user, from memory. It may be out of date, "
    "and what they say in this conversation takes precedence. Use it where it helps; do not read "
    "it out."
)


@dataclass(frozen=True)
class RecallInfo:
    """How the last recall went, for your metrics: `ms` it took this turn, the `chars` it added,
    whether it `timed_out` or `failed`, and whether it was `reused` from earlier in the turn."""

    query: str
    ms: float
    chars: int
    timed_out: bool = False
    failed: bool = False
    reused: bool = False


def question(chat_ctx: llm.ChatContext) -> tuple[llm.ChatMessage, str] | None:
    """The user's latest message and what to search for it; None before the user has spoken, or
    when what they said holds nothing to look up."""
    messages = chat_ctx.messages()
    for i in range(len(messages) - 1, -1, -1):
        said = messages[i]
        if said.role != "user":
            continue
        text = " ".join((said.text_content or "").split())
        words = re.findall(r"[a-z']+", text.lower())
        if not words or set(words) <= _PHATIC:
            return None
        if len(words) < _SHORT:
            asked = next((m for m in reversed(messages[:i]) if m.role == "assistant"), None)
            if asked is not None and asked.text_content:
                text = " ".join(asked.text_content.split())[-_ASKED_CHARS:] + " " + text
        return said, text[:_QUERY_CHARS]
    return None


def block(known: list[str], hits: list[Hit], max_chars: int) -> str:
    """What is known, then whole passages in rank order, each kept if it fits: one long passage
    does not hide the shorter ones after it."""
    lines = [" ".join(k.split()) for k in known]
    used = sum(len(line) + 3 for line in lines)
    for hit in hits:
        text = " ".join(hit.text.split())
        if text and used + len(text) + 3 <= max_chars:
            lines.append(text)
            used += len(text) + 3
    return "\n".join(f"- {line}" for line in lines)


def wrap(context: str) -> str:
    """Memory as the model reads it: inside `<memory>`, which nothing remembered can close."""
    # A look-alike of `<`, so a remembered "</memory>" reads as text and closes nothing.
    fenced = re.sub(r"<(/?)\s*memory", r"‹\1memory", context, flags=re.IGNORECASE)  # noqa: RUF001
    return f"{HEADER}\n<memory>\n{fenced}\n</memory>"


def place(chat_ctx: llm.ChatContext, said: llm.ChatMessage, text: str) -> None:
    """Put `text` just before `said`, once: a tool's follow-up call sees the same context."""
    ident = f"{MARK}_{said.id}"
    if any(item.id == ident for item in chat_ctx.items):
        return
    # As the assistant, as LiveKit's own retrieval example does: on several providers a system
    # message after the first reaches the model as user-written <instructions>.
    chat_ctx.insert(
        llm.ChatMessage(
            id=ident,
            role="assistant",
            content=[text],
            created_at=said.created_at - 1e-3,
            extra={MARK: "recall"},
        )
    )


@dataclass
class Recall:
    """Lookups for one call, each started once and given `timeout` seconds per model call."""

    timeout: float
    max_chars: int
    fast: bool
    since: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last: RecallInfo | None = None
    _known: list[str] = field(default_factory=list[str])
    _lookups: dict[str, tuple[float, asyncio.Task[str | None]]] = field(
        default_factory=dict[str, tuple[float, "asyncio.Task[str | None]"]]
    )
    _tasks: set[asyncio.Task[None]] = field(default_factory=set[asyncio.Task[None]])
    _warned: set[str] = field(default_factory=set[str])

    def prime(self, user: AsyncUser) -> None:
        """Start looking up what is known about `user`, for every reply of the call to lead with.
        In the background: the greeting does not wait for it."""
        task = asyncio.create_task(self._about(user), name="twinmemory.about")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def context(self, user: AsyncUser, query: str) -> str:
        """Memory for `query`, wrapped for the prompt; empty when memory has nothing, is down, or
        is late."""
        started = time.monotonic()
        lookup, reused = self._lookup(user, query)
        try:
            found = await asyncio.wait_for(asyncio.shield(lookup), self.timeout)
        except asyncio.TimeoutError:
            # The lookup goes on: a preemptive retry or a tool's follow-up may still use it.
            self._done(query, started, 0, timed_out=True, reused=reused)
            return ""
        text = wrap(found) if found else ""
        self._done(query, started, len(text), failed=found is None, reused=reused)
        return text

    def _lookup(self, user: AsyncUser, query: str) -> tuple[asyncio.Task[str | None], bool]:
        now = time.monotonic()
        key = f"{user.id}\n{query}"
        held = self._lookups.get(key)
        if held is not None and now - held[0] < _REUSE_SECONDS:
            return held[1], True
        for stale in [k for k, (at, _) in self._lookups.items() if now - at >= _REUSE_SECONDS]:
            del self._lookups[stale]
        while len(self._lookups) >= _REUSED:
            del self._lookups[next(iter(self._lookups))]
        task = asyncio.create_task(self._search(user, query), name="twinmemory.recall")
        self._lookups[key] = (now, task)
        return task, False

    async def _search(self, user: AsyncUser, query: str) -> str | None:
        """What memory holds, or None when it could not be asked."""
        found = await self._ask(user, query, scope=_EARLIER_CALLS, before=self.since)
        if found is None:
            return None
        return block(self._known, found.hits, self.max_chars)

    async def _about(self, user: AsyncUser) -> None:
        found = await self._ask(user, _ABOUT)
        if found is not None:
            self._known = found.known

    async def _ask(self, user: AsyncUser, query: str, **where: str) -> SearchResult | None:
        """Never raises: a call goes on whatever memory does."""
        try:
            found = await user.search(query, fast=self.fast, **where)
        except NotFoundError:  # nothing has been saved for this user yet
            return SearchResult.parse({"query": query})
        except TwinMemoryError as error:
            self._warn(error)
            return None
        return None if found.failed else found

    def _warn(self, error: TwinMemoryError) -> None:
        # Once per kind of failure: an outage would otherwise log every turn of every call.
        kind = type(error).__name__
        if kind in self._warned:
            return
        self._warned.add(kind)
        level = logging.WARNING if error.outage else logging.ERROR
        log.log(level, "twin memory recall failed, replies go on without memory: %s", error)

    def _done(self, query: str, started: float, chars: int, **how: bool) -> None:
        ms = (time.monotonic() - started) * 1000
        self.last = RecallInfo(query, ms, chars, **how)
        log.debug("recall %.0f ms, %d chars, %s", ms, chars, how)

    def cancel(self) -> None:
        for _, task in self._lookups.values():
            task.cancel()
        for task in self._tasks:
            task.cancel()
        self._lookups.clear()
