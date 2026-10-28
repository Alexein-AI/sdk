"""Each operation as the request it is: path, body and how to read the answer. Written once here
and sent by both clients, so the sync and async methods cannot drift apart on the wire."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from twinmemory._types import (
    AddResult,
    Correction,
    File,
    GrepResult,
    History,
    Item,
    Json,
    Lineage,
    Listing,
    Me,
    Overview,
    Passages,
    Receipt,
    SearchResult,
    Versions,
)

T = TypeVar("T")

# The API takes at most this many items in one add; a longer list is sent in batches.
BATCH = 500
# What the API accepts as an end user id, checked here so a typo fails before a round trip. The
# API also bounds its length: up to 35 characters always fits, and the 400 for a longer one
# states the maximum.
_USER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


@dataclass(frozen=True)
class Call(Generic[T]):
    method: str
    path: str
    parse: Callable[[Json], T]
    body: Json | None = None
    headers: dict[str, str] = field(default_factory=dict[str, str])


def checked_user(user_id: str) -> str:
    if not _USER_ID.fullmatch(user_id):
        raise ValueError(
            f"not a usable end user id: {user_id!r} (letters, digits, '.', '_' and '-', "
            "starting with a letter or digit)"
        )
    return user_id


def _post(path: str, parse: Callable[[Json], T], body: Json) -> Call[T]:
    return Call(
        "POST", f"/v1/memory/{path}", parse, {k: v for k, v in body.items() if v is not None}
    )


def me() -> Call[Me]:
    return Call("GET", "/v1/me", Me.parse)


def add(
    items: str | Item | Sequence[str | Item],
    *,
    wait: bool,
    defaults: Json,
) -> list[Call[AddResult]]:
    """One call per batch of `BATCH` items. Each carries an `Idempotency-Key`, so a retried
    batch is the same events again, never a second copy of an item sent without an id."""
    given: Iterable[str | Item] = [items] if isinstance(items, (str, dict)) else items
    shaped = [_item(i, defaults) for i in given]
    if not shaped:
        raise ValueError("add needs at least one item")
    key = uuid.uuid4().hex
    return [
        Call(
            "POST",
            "/v1/memory/add",
            AddResult.parse,
            {"items": shaped[at : at + BATCH], "wait": wait},
            {"Idempotency-Key": f"{key}-{at // BATCH}"},
        )
        for at in range(0, len(shaped), BATCH)
    ]


def _item(given: str | Item, defaults: Json) -> Json:
    item: Json = {"text": given} if isinstance(given, str) else dict(given)
    if not item.get("text"):
        raise ValueError(f"an item needs text: {given!r}")
    return {k: v for k, v in defaults.items() if v is not None} | item


def merged(results: list[AddResult]) -> AddResult:
    """Batches' answers as one."""
    if len(results) == 1:
        return results[0]
    return AddResult(
        items=[i for r in results for i in r.items],
        queued=sum(r.queued for r in results),
        pending=sum(r.pending for r in results),
        raw={"batches": [r.raw for r in results]},
    )


def search(
    query: str, *, before: str | None, after: str | None, scope: str | None, fast: bool
) -> Call[SearchResult]:
    body = {"query": query, "before": before, "after": after, "scope": scope, "fast": fast}
    return _post("search", SearchResult.parse, body)


def grep(pattern: str, *, scope: str | None, limit: int) -> Call[GrepResult]:
    return _post("grep", GrepResult.parse, {"pattern": pattern, "scope": scope, "limit": limit})


def read(path: str) -> Call[File]:
    return _post("read", File.parse, {"path": path})


def ls(path: str) -> Call[Listing]:
    return _post("ls", Listing.parse, {"path": path})


def around(passage_id: str, *, width: int) -> Call[Passages]:
    return _post("around", Passages.parse, {"passage_id": passage_id, "width": width})


def history(subject: str, *, attribute: str | None) -> Call[History]:
    return _post("history", History.parse, {"subject": subject, "attribute": attribute})


def latest(*, k: int, place: str, after: str | None, before: str | None) -> Call[Passages]:
    body = {"k": k, "place": place, "after": after, "before": before}
    return _post("latest", Passages.parse, body)


def overview() -> Call[Overview]:
    return _post("overview", Overview.parse, {})


def forget(
    *,
    items: Sequence[str],
    sessions: Sequence[str],
    threads: Sequence[str],
    events: Sequence[str],
) -> Call[Receipt]:
    named = {"items": items, "sessions": sessions, "threads": threads, "events": events}
    body: Json = {k: list(v) for k, v in named.items() if v}
    if not body:
        raise ValueError("forget needs at least one of items, sessions, threads or events")
    return _post("forget", Receipt.parse, body)


def correct(record_id: str, replacement: str | None) -> Call[Correction]:
    body = {"record_id": record_id, "replacement": replacement}
    return _post("correct", Correction.parse, body)


def versions(item_id: str) -> Call[Versions]:
    return _post("versions", Versions.parse, {"id": item_id})


def status(ids: Sequence[str]) -> Call[dict[str, str]]:
    def phases(raw: Json) -> dict[str, str]:
        return dict(raw.get("phases", {}))

    return _post("status", phases, {"ids": list(ids)})


def lineage(ident: str) -> Call[Lineage]:
    return _post("lineage", Lineage.parse, {"id": ident})
