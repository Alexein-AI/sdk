"""Recall: what memory holds for the user's latest words, placed just before them in the prompt.

It runs in `llm_node`, not in `on_user_turn_completed`. LiveKit starts a reply before it is sure
the user has finished (preemptive generation, on by default), from a copy of the context, and
throws that reply away if `on_user_turn_completed` changes the turn; `llm_node` runs inside the
early reply as well, so recall there starts early instead of cancelling the head start, and it
runs for typed turns too, which that hook never sees. One lookup per question is shared by the
early reply, the confirmed one and the model calls after a tool runs, and its time limit is the
reply's, not each call's: a turn whose lookup is late goes ahead without memory.

What it searches is earlier calls only, unless `search_current_call`: the model already has this
one, and memory would hand its own turns back, so every lookup leaves out this call's session.
Not a cache of memory: a lookup is reused for `recall_reuse_seconds`, one turn. Every choice it
makes is a field of `Settings`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from alexein import AlexeinError, AsyncUser, Excerpt, NotFoundError, SearchResult
from livekit.agents import llm

from alexein_livekit._lines import SHORT, asks, said, small_talk, words
from alexein_livekit._settings import HEADER, Settings

log = logging.getLogger("alexein.livekit")

# A short reply is searched with the agent's words before it (`_lines.SHORT`).
_ASKED_CHARS = 300
_QUERY_CHARS = 1000

# Lookups held at once: one turn's question, and a few preemptive tries at it.
_REUSED = 8

_ABOUT = "What should I know about this person?"
# The last excerpts (`recall_recent`), newest first, are shown after what the search matched: the
# call before this one often holds what a question needs without naming it, such as the "I'm
# vegetarian" behind "suggest a dinner", or an appointment that moved. Fetched once a call, so no
# turn waits.

# The marker on what recall adds to a prompt, so capture never saves it as something said.
MARK = "alexein"


@dataclass(frozen=True)
class RecallInfo:
    """How the last recall went, for your metrics: `ms` it took this turn, the `chars` it added,
    whether it `timed_out` or `failed`, and whether it was `reused` from earlier in the turn."""

    ms: float
    chars: int
    timed_out: bool = False
    failed: bool = False
    reused: bool = False


def question(
    chat_ctx: llm.ChatContext, *, skip_small_talk: bool = True
) -> tuple[llm.ChatMessage, str] | None:
    """The user's latest message and what to search for it; None before the user has spoken, or
    when what they said holds nothing to look up."""
    messages = chat_ctx.messages()
    for i in range(len(messages) - 1, -1, -1):
        said = messages[i]
        if said.role != "user":
            continue
        text = " ".join((said.text_content or "").split())
        heard = words(text)
        asked = next((m for m in reversed(messages[:i]) if m.role == "assistant"), None)
        asked_text = " ".join((asked.text_content or "").split()) if asked else ""
        if not heard or (skip_small_talk and small_talk(heard) and not asks(asked_text)):
            return None
        if len(heard) < SHORT and asked_text:
            text = asked_text[-_ASKED_CHARS:] + " " + text
        return said, text[:_QUERY_CHARS]
    return None


# Every character a model may read as an angle bracket, and the ampersand that starts an entity:
# with none of them left, no tag and no `&lt;` can be spelled, however it is hidden, and the rest
# of the text (m², 10⁶, an emoji, a Persian word) is left exactly as it was said.
_MARKUP = str.maketrans(
    {c: "‹" for c in "<＜﹤〈⟨"} | {c: "›" for c in ">＞﹥〉⟩"} | {"&": "＆"}  # noqa: RUF001
)


def _inert(text: str) -> str:
    """`text` as it cannot be read as markup."""
    return text.translate(_MARKUP)


def wrap(context: str, header: str = HEADER) -> str:
    """Memory as the model reads it: inside `<memory>`, which nothing remembered can close."""
    return f"{header}\n<memory>\n{_inert(context)}\n</memory>"


def place(chat_ctx: llm.ChatContext, said: llm.ChatMessage, text: str) -> None:
    """Put `text` just before `said`, once: a tool's follow-up call sees the same context."""
    items = chat_ctx.items
    ident = f"{MARK}_{said.id}"
    if said not in items or any(item.id == ident for item in items):
        return
    # By place, not by time: LiveKit 1.5 stamps the instructions within a millisecond of the
    # user's words, and inserting by time put memory ahead of the system prompt. The time given
    # keeps the list in order for whatever sorts it later.
    at = items.index(said)
    floor = items[at - 1].created_at if at else said.created_at - 1e-3
    # As the assistant, as LiveKit's own retrieval example does: on several providers a system
    # message after the first reaches the model as user-written <instructions>.
    recalled = llm.ChatMessage(
        id=ident,
        role="assistant",
        content=[text],
        created_at=max(floor, said.created_at - 1e-3),
        extra={MARK: "recall"},
    )
    items.insert(at, recalled)


@dataclass
class Recall:
    """Lookups for one call. A lookup is started once per question and its answer waited for until
    `recall_timeout` seconds after it started, by every model call of the turn together."""

    settings: Settings = field(default_factory=Settings)
    # The call's session: what is saved under it is this call's, and left out of every lookup.
    session: str = ""
    last: RecallInfo | None = None
    _known: list[str] = field(default_factory=list[str])
    _recent: list[Excerpt] = field(default_factory=list[Excerpt])
    _about_task: asyncio.Task[None] | None = None
    _about_for: AsyncUser | None = None
    _lookups: dict[str, tuple[float, asyncio.Task[str | None]]] = field(
        default_factory=dict[str, tuple[float, "asyncio.Task[str | None]"]]
    )
    _tasks: set[asyncio.Task[None]] = field(default_factory=set[asyncio.Task[None]])
    _warned: set[str] = field(default_factory=set[str])

    @property
    def known(self) -> list[str]:
        return self._known

    @property
    def recent(self) -> list[Excerpt]:
        return self._recent

    async def ready(self, timeout: float) -> None:
        """Wait up to `timeout` for what is known and recent to arrive, if it is on its way."""
        if self._about_task is not None and not self._about_task.done():
            await asyncio.wait({self._about_task}, timeout=timeout)

    def prime(self, user: AsyncUser) -> None:
        """Look up what is known about `user`, for every reply of the call to lead with: in the
        background, once there is an event loop, so the greeting does not wait for it."""
        self._about_for = user
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # started by the first recall instead
        self._start_about()

    async def context(self, user: AsyncUser, query: str) -> str:
        """Memory for `query`, wrapped for the prompt; empty when memory has nothing, is down, or
        is late. Never raises but for the caller's own cancellation."""
        self._start_about()
        now = time.monotonic()
        started, lookup, reused = self._lookup(user, query, now)
        try:
            left = max(0.0, started + self.settings.recall_timeout - now)
            found = await asyncio.wait_for(asyncio.shield(lookup), left)
        except asyncio.TimeoutError:
            # The lookup goes on: a preemptive retry or a tool's follow-up may still use it.
            self._done(now, 0, timed_out=True, reused=reused)
            return ""
        except asyncio.CancelledError:
            current = asyncio.current_task()
            cancelling = getattr(current, "cancelling", lambda: 0)()  # Python 3.11 and newer
            if cancelling or not lookup.cancelled():
                raise  # the reply itself was cancelled
            return ""  # the call is closing, and took the lookup with it
        text = wrap(found, self.settings.recall_header) if found else ""
        self._done(now, len(text), failed=found is None, reused=reused)
        return text

    def _start_about(self) -> None:
        user, self._about_for = self._about_for, None
        if user is None or not (self.settings.recall_known or self.settings.recall_recent):
            return
        task = asyncio.create_task(self._about(user), name="alexein.about")
        self._about_task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _lookup(
        self, user: AsyncUser, query: str, now: float
    ) -> tuple[float, asyncio.Task[str | None], bool]:
        key = f"{user.id}\n{query}"
        held = self._lookups.get(key)
        reuse = self.settings.recall_reuse_seconds
        if held is not None and now - held[0] < reuse:
            return held[0], held[1], True
        for stale in [k for k, (at, _) in self._lookups.items() if now - at >= reuse]:
            del self._lookups[stale]
        while len(self._lookups) >= _REUSED:
            del self._lookups[next(iter(self._lookups))]
        task = asyncio.create_task(self._search(user, query), name="alexein.recall")
        self._lookups[key] = (now, task)
        return now, task, False

    def where(self) -> dict[str, Any]:
        """Earlier calls only - everything said outside this call's session - unless
        `search_current_call`; for recall, the last calls and `memory_search` alike."""
        if self.settings.search_current_call or not self.session:
            return {}
        return {"filters": {"NOT": {"mentions": f"session:{self.session}"}}}

    async def _search(self, user: AsyncUser, query: str) -> str | None:
        """What memory holds, or None when it could not be asked."""
        s = self.settings
        found = await self._ask(user, query, fast=s.recall_fast, **self.where())
        if found is None:
            return None
        await self.ready(s.recall_timeout / 2)
        lines = said(
            self._known,
            [*found.excerpts, *self._recent],
            query,
            agent=s.recall_agent_turns,
            max_chars=s.recall_max_chars,
            skip_small_talk=s.recall_skip_small_talk,
        )
        return "\n".join(f"- {line}" for line in lines)

    async def _about(self, user: AsyncUser) -> None:
        known = self.settings.recall_known
        about = self._ask(user, _ABOUT, fast=self.settings.recall_fast) if known else _nothing()
        found, recent = await asyncio.gather(about, self._latest(user))
        if found is not None:
            self._known = [line.text for line in found.known]
        self._recent = recent

    async def _latest(self, user: AsyncUser) -> list[Excerpt]:
        if not self.settings.recall_recent:
            return []
        try:
            return (await user.latest(k=self.settings.recall_recent, **self.where())).memories
        except NotFoundError:
            return []
        except Exception as error:
            self._warn(error)
            return []

    async def _ask(
        self, user: AsyncUser, query: str, *, fast: bool, **where: Any
    ) -> SearchResult | None:
        """Never raises: a call goes on however memory fails, a proxy's HTML page included."""
        try:
            found = await user.search(query, fast=fast, **where)
        except NotFoundError:  # nothing has been saved for this user yet (an older service)
            return SearchResult.parse({"query": query})
        except Exception as error:
            self._warn(error)
            return None
        return None if found.failed else found

    def _warn(self, error: Exception) -> None:
        # Once per kind of failure: an outage would otherwise log every turn of every call. The
        # service's own words are left out, since they name the app user.
        kind = type(error).__name__
        if kind in self._warned:
            return
        self._warned.add(kind)
        level = logging.ERROR if isinstance(error, AlexeinError) and not error.outage else 0
        log.log(level or logging.WARNING, "Alexein recall failed (%s), replies go on", how(error))

    def _done(self, started: float, chars: int, **how: bool) -> None:
        ms = (time.monotonic() - started) * 1000
        self.last = RecallInfo(ms, chars, **how)
        log.debug("recall %.0f ms, %d chars, %s", ms, chars, how)

    def cancel(self) -> None:
        for _, task in self._lookups.values():
            task.cancel()
        for task in self._tasks:
            task.cancel()
        self._lookups.clear()


async def _nothing() -> None:
    return None


def how(error: Exception) -> str:
    """An error as a log line can carry it: its kind, status and request id, never its text."""
    if isinstance(error, AlexeinError):
        return f"{type(error).__name__}, status {error.status}, request {error.request_id}"
    return type(error).__name__
