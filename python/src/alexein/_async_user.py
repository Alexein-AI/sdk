"""`AsyncUser`: `User` for asyncio, the same methods awaited. Kept beside `_user.py` line for
line, so the two read alike."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any

from alexein import _calls
from alexein._errors import AlexeinError
from alexein._http import AsyncTransport, ride_out
from alexein._memories import Fact, Memories, Opened, SearchResult
from alexein._results import (
    ExportPage,
    FactsPage,
    History,
    ItemsPage,
    OpenItems,
    Sources,
    StoredItem,
    Summary,
)
from alexein._types import Author, Item, Json, Kinds
from alexein._writes import (
    AddResult,
    Correction,
    Deleted,
    Forgotten,
    Statuses,
    Versions,
    merged,
)


class AsyncUser:
    """`User`, for asyncio: the same methods, awaited; `iter_*` are async generators."""

    def __init__(self, transport: AsyncTransport, user_id: str, *, fail_open: bool = False) -> None:
        self._transport = transport
        self.id = user_id
        self.fail_open = fail_open

    def __repr__(self) -> str:
        return f"AsyncUser({self.id!r})"

    async def _send(self, call: _calls.Call[Any]) -> Any:
        return await self._transport.send(call, self.id)

    async def add(
        self,
        items: str | Item | Sequence[str | Item],
        *,
        wait: bool = False,
        redact: bool = False,
        kind: str | None = None,
        session: str | None = None,
        role: str | None = None,
        author: str | Author | None = None,
        title: str | None = None,
        about: Sequence[str] | None = None,
        expires: str | None = None,
        at: str | None = None,
        metadata: Json | None = None,
    ) -> AddResult:
        """Remember text: a string, an item dict, or a list of either. The keyword fields fill
        every item that does not set its own. With `wait`, returns once they are searchable;
        with `redact`, phone numbers, cards, keys and the like are replaced before memory keeps
        any copy. More than 500 items go in batches; a retry never saves an item twice."""
        defaults: Json = {
            "kind": kind, "session": session, "role": role, "author": author, "title": title,
            "about": list(about) if about is not None else None, "expires": expires, "at": at,
            "metadata": metadata,
        }  # fmt: skip
        calls = _calls.add(items, wait=wait, redact=redact, defaults=defaults)
        if not calls:
            return AddResult(items=[])
        try:
            return merged([await self._send(c) for c in calls])
        except AlexeinError as error:
            ride_out(error, self.fail_open, "add", self.id)
            return AddResult(items=[], waiting=0, failed=True)

    async def search(
        self,
        query: str,
        *,
        before: str | None = None,
        after: str | None = None,
        filters: Json | None = None,
        provider: str | None = None,
        source: str | None = None,
        kind: Kinds | None = None,
        fast: bool = False,
    ) -> SearchResult:
        """What memory holds for a question. `fast` answers sooner, a little less precisely, and
        free. `before` and `after` are ISO dates; `filters`, `provider`, `source` and `kind`
        narrow it to the facts and excerpts that match."""
        call = _calls.search(
            query, before=before, after=after, filters=filters, provider=provider,
            source=source, kind=kind, fast=fast or None,
        )  # fmt: skip
        try:
            return await self._send(call)
        except AlexeinError as error:
            ride_out(error, self.fail_open, "search", self.id)
            return SearchResult.unavailable(query)

    async def grep(
        self,
        pattern: str,
        *,
        limit: int | None = None,
        provider: str | None = None,
        source: str | None = None,
        kind: Kinds | None = None,
    ) -> Memories:
        """Excerpts holding an exact phrase, ignoring case."""
        call = _calls.grep(pattern, limit=limit, provider=provider, source=source, kind=kind)
        return await self._send(call)

    async def latest(
        self,
        *,
        k: int | None = None,
        place: str | None = None,
        after: str | None = None,
        before: str | None = None,
        filters: Json | None = None,
        provider: str | None = None,
        source: str | None = None,
        kind: Kinds | None = None,
    ) -> Memories:
        """The most recent excerpts, newest first (10 by default): everywhere or in one `place`,
        or everything between `after` and `before`."""
        call = _calls.latest(
            k=k, place=place, after=after, before=before, filters=filters, provider=provider,
            source=source, kind=kind,
        )  # fmt: skip
        return await self._send(call)

    async def around(self, ref: str, *, width: int | None = None) -> Memories:
        """The excerpts just before and after one, from the same conversation, in order."""
        return await self._send(_calls.around(ref, width=width))

    async def open(self, ref: str) -> Opened:
        """One memory by its ref, whole: an excerpt in full, or a fact with the excerpts it was
        learned from."""
        return await self._send(_calls.open(ref))

    async def history(self, subject: str, *, attribute: str | None = None) -> History:
        """Every value a subject was stated to have, and since when."""
        return await self._send(_calls.history(subject, attribute=attribute))

    async def summary(self) -> Summary:
        """What this memory holds, in brief."""
        return await self._send(_calls.summary())

    async def facts(self, *, limit: int | None = None, cursor: str | None = None) -> FactsPage:
        """A page of the facts memory learned, newest first (20 by default)."""
        return await self._send(_calls.facts(limit=limit, cursor=cursor))

    async def iter_facts(self, *, limit: int | None = None) -> AsyncIterator[Fact]:
        """Every fact memory learned, newest first, page after page."""
        cursor: str | None = None
        while True:
            page = await self.facts(limit=limit, cursor=cursor)
            for each in page.facts:
                yield each
            if not page.next:
                return
            cursor = page.next

    async def open_items(
        self,
        *,
        kind: Kinds | None = None,
        provider: str | None = None,
        place: str | None = None,
        mine: bool | None = None,
        within_days: int | None = None,
        limit: int | None = None,
    ) -> OpenItems:
        """Issues and pull requests still open, newest first - by default the person's own -
        and follow-ups nobody answered."""
        call = _calls.open_items(
            kind=kind, provider=provider, place=place, mine=mine, within_days=within_days,
            limit=limit,
        )  # fmt: skip
        return await self._send(call)

    async def sources(self) -> Sources:
        """What each connected app delivered to this memory."""
        return await self._send(_calls.sources())

    async def items(
        self, *, limit: int | None = None, cursor: str | None = None, filters: Json | None = None
    ) -> ItemsPage:
        """A page of the items added to this memory, newest first, as they were given."""
        return await self._send(_calls.items(limit=limit, cursor=cursor, filters=filters))

    async def iter_items(
        self, *, limit: int | None = None, filters: Json | None = None
    ) -> AsyncIterator[StoredItem]:
        """Every item added to this memory, newest first, page after page."""
        cursor: str | None = None
        while True:
            page = await self.items(limit=limit, cursor=cursor, filters=filters)
            for each in page.items:
                yield each
            if not page.next:
                return
            cursor = page.next

    async def item(self, item_id: str) -> StoredItem | None:
        """One added item by its id, whole; None for an id memory does not hold."""
        return await self._send(_calls.item(item_id))

    async def status(self, ids: Sequence[str]) -> Statuses:
        """How far each item has got: queued, stored, processed or unknown."""
        return await self._send(_calls.status(ids))

    async def forget(
        self,
        *,
        items: Sequence[str] | None = None,
        sessions: Sequence[str] | None = None,
        refs: Sequence[str] | None = None,
    ) -> Forgotten:
        """Erase what is named - items by id, whole sessions, memories by ref - with every copy
        and everything learned from it, for good. Needs a key that writes."""
        return await self._send(_calls.forget(items=items, sessions=sessions, refs=refs))

    async def correct(self, ref: str, replacement: str | None = None) -> Correction:
        """Retract one fact by its ref, and optionally say what is true instead."""
        return await self._send(_calls.correct(ref, replacement))

    async def versions(self, item_id: str) -> Versions:
        """Every version of one added item, and when and why it went. Needs a key that writes."""
        return await self._send(_calls.versions(item_id))

    async def export(self, *, limit: int | None = None, cursor: str | None = None) -> ExportPage:
        """A page of everything memory holds for this app user, for a person who asks for theirs."""
        return await self._send(_calls.export(limit=limit, cursor=cursor))

    async def iter_export(self, *, limit: int | None = None) -> AsyncIterator[Json]:
        """Every record of the export, page after page."""
        cursor: str | None = None
        while True:
            page = await self.export(limit=limit, cursor=cursor)
            for each in page.records:
                yield each
            if not page.next:
                return
            cursor = page.next

    async def delete(self) -> Deleted:
        """Erase this app user whole: every item, fact and version. Not undone; their next add
        starts a new memory. Needs a key that writes."""
        return await self._send(_calls.delete())
