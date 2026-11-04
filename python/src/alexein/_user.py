"""`User`: one app user's memory, every route that names them. What each method sends is in
`_calls.py`; here is what it takes and what it answers."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from alexein import _calls
from alexein._errors import AlexeinError
from alexein._http import Transport, ride_out
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


class User:
    """One app user's memory. Every call sends their id as `X-Alexein-User`.

    Arguments left as None are not sent, so the API's defaults apply."""

    def __init__(self, transport: Transport, user_id: str, *, fail_open: bool = False) -> None:
        self._transport = transport
        self.id = user_id
        self.fail_open = fail_open

    def __repr__(self) -> str:
        return f"User({self.id!r})"

    def _send(self, call: _calls.Call[Any]) -> Any:
        return self._transport.send(call, self.id)

    def add(
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
            return merged([self._send(c) for c in calls])
        except AlexeinError as error:
            ride_out(error, self.fail_open, "add", self.id)
            return AddResult(items=[], waiting=0, failed=True)

    def search(
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
            return self._send(call)
        except AlexeinError as error:
            ride_out(error, self.fail_open, "search", self.id)
            return SearchResult.unavailable(query)

    def grep(
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
        return self._send(call)

    def latest(
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
        return self._send(call)

    def around(self, ref: str, *, width: int | None = None) -> Memories:
        """The excerpts just before and after one, from the same conversation, in order."""
        return self._send(_calls.around(ref, width=width))

    def open(self, ref: str) -> Opened:
        """One memory by its ref, whole: an excerpt in full, or a fact with the excerpts it was
        learned from."""
        return self._send(_calls.open(ref))

    def history(self, subject: str, *, attribute: str | None = None) -> History:
        """Every value a subject was stated to have, and since when."""
        return self._send(_calls.history(subject, attribute=attribute))

    def summary(self) -> Summary:
        """What this memory holds, in brief."""
        return self._send(_calls.summary())

    def facts(self, *, limit: int | None = None, cursor: str | None = None) -> FactsPage:
        """A page of the facts memory learned, newest first (20 by default)."""
        return self._send(_calls.facts(limit=limit, cursor=cursor))

    def iter_facts(self, *, limit: int | None = None) -> Iterator[Fact]:
        """Every fact memory learned, newest first, page after page."""
        cursor: str | None = None
        while True:
            page = self.facts(limit=limit, cursor=cursor)
            yield from page.facts
            if not page.next:
                return
            cursor = page.next

    def open_items(
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
        return self._send(call)

    def sources(self) -> Sources:
        """What each connected app delivered to this memory."""
        return self._send(_calls.sources())

    def items(
        self, *, limit: int | None = None, cursor: str | None = None, filters: Json | None = None
    ) -> ItemsPage:
        """A page of the items added to this memory, newest first, as they were given."""
        return self._send(_calls.items(limit=limit, cursor=cursor, filters=filters))

    def iter_items(
        self, *, limit: int | None = None, filters: Json | None = None
    ) -> Iterator[StoredItem]:
        """Every item added to this memory, newest first, page after page."""
        cursor: str | None = None
        while True:
            page = self.items(limit=limit, cursor=cursor, filters=filters)
            yield from page.items
            if not page.next:
                return
            cursor = page.next

    def item(self, item_id: str) -> StoredItem | None:
        """One added item by its id, whole; None for an id memory does not hold."""
        return self._send(_calls.item(item_id))

    def status(self, ids: Sequence[str]) -> Statuses:
        """How far each item has got: queued, stored, processed or unknown."""
        return self._send(_calls.status(ids))

    def forget(
        self,
        *,
        items: Sequence[str] | None = None,
        sessions: Sequence[str] | None = None,
        refs: Sequence[str] | None = None,
    ) -> Forgotten:
        """Erase what is named - items by id, whole sessions, memories by ref - with every copy
        and everything learned from it, for good. Needs a key that writes."""
        return self._send(_calls.forget(items=items, sessions=sessions, refs=refs))

    def correct(self, ref: str, replacement: str | None = None) -> Correction:
        """Retract one fact by its ref, and optionally say what is true instead."""
        return self._send(_calls.correct(ref, replacement))

    def versions(self, item_id: str) -> Versions:
        """Every version of one added item, and when and why it went. Needs a key that writes."""
        return self._send(_calls.versions(item_id))

    def export(self, *, limit: int | None = None, cursor: str | None = None) -> ExportPage:
        """A page of everything memory holds for this app user, for a person who asks for theirs."""
        return self._send(_calls.export(limit=limit, cursor=cursor))

    def iter_export(self, *, limit: int | None = None) -> Iterator[Json]:
        """Every record of the export, page after page."""
        cursor: str | None = None
        while True:
            page = self.export(limit=limit, cursor=cursor)
            yield from page.records
            if not page.next:
                return
            cursor = page.next

    def delete(self) -> Deleted:
        """Erase this app user whole: every item, fact and version. Not undone; their next add
        starts a new memory. Needs a key that writes."""
        return self._send(_calls.delete())
