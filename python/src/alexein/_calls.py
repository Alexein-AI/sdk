"""Each operation as the request it is: path, body and how to read the answer. Written once here
and sent by both clients, so the sync and async methods cannot drift apart on the wire."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, cast

from alexein._memories import Memories, Opened, SearchResult
from alexein._results import (
    ExportPage,
    FactsPage,
    History,
    ItemsPage,
    Me,
    OpenItems,
    Sources,
    StoredItem,
    Summary,
    UsersPage,
)
from alexein._types import Item, Json
from alexein._writes import (
    AddResult,
    Correction,
    Deleted,
    Forgotten,
    Statuses,
    Versions,
)

T = TypeVar("T")

# The API takes at most this many items in one add; a longer list is sent in batches.
BATCH = 500
# What the API accepts as an app user id, checked here so a typo fails where it was made.
_USER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,34}")


@dataclass(frozen=True)
class Call(Generic[T]):
    """One request: `user` is whether it names an app user in `X-Alexein-User`."""

    method: str
    path: str
    parse: Callable[[Json], T]
    body: Json | None = None
    headers: dict[str, str] = field(default_factory=dict[str, str])
    user: bool = True


def checked_user(user_id: str) -> str:
    if not isinstance(user_id, str) or not _USER_ID.fullmatch(user_id):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError(
            f"not a usable app user id: {user_id!r} (1 to 35 letters, digits, '.', '_' and "
            "'-', starting with a letter or digit)"
        )
    return user_id


def _set(**fields: Any) -> Json:
    """The fields the caller set: None is not sent, so the API's defaults apply."""
    return {k: _sent(v) for k, v in fields.items() if v is not None}


def _sent(value: Any) -> Any:
    """A sequence as the JSON list it is sent as; anything else as it is."""
    if isinstance(value, Sequence) and not isinstance(value, str):
        return list(cast("Sequence[Any]", value))
    return value


def _post(route: str, parse: Callable[[Json], T], body: Json | None = None) -> Call[T]:
    return Call("POST", f"/v2/memory/{route}", parse, body or {})


def me() -> Call[Me]:
    return Call("GET", "/v2/me", Me.parse, user=False)


def users(*, limit: int | None, cursor: str | None) -> Call[UsersPage]:
    call = _post("users", UsersPage.parse, _set(limit=limit, cursor=cursor))
    return Call(call.method, call.path, call.parse, call.body, user=False)


def add(
    items: str | Item | Sequence[str | Item],
    *,
    wait: bool,
    redact: bool,
    defaults: Json,
) -> list[Call[AddResult]]:
    """One call per batch of `BATCH` items, each with an `Idempotency-Key` of one uuid4 for the
    whole add and the batch's index, so a retried batch is the same items again."""
    given: Iterable[str | Item] = [items] if isinstance(items, (str, dict)) else items
    shaped = [_item(i, _set(**defaults)) for i in given]
    key = str(uuid.uuid4())
    options = _set(wait=wait or None, redact=redact or None)
    return [
        Call(
            "POST",
            "/v2/memory/add",
            AddResult.parse,
            {"items": shaped[at : at + BATCH], **options},
            {"Idempotency-Key": f"{key}-{at // BATCH}"},
        )
        for at in range(0, len(shaped), BATCH)
    ]


def _item(given: str | Item, defaults: Json) -> Json:
    item: Json = {"text": given} if isinstance(given, str) else dict(given)
    if not isinstance(item.get("text"), str) or not item["text"]:
        raise ValueError(f"an item needs text: {given!r}")
    return defaults | item


def search(query: str, **narrowed: Any) -> Call[SearchResult]:
    return _post("search", SearchResult.parse, _set(query=query, **narrowed))


def grep(pattern: str, **narrowed: Any) -> Call[Memories]:
    return _post("grep", Memories.parse, _set(pattern=pattern, **narrowed))


def latest(**narrowed: Any) -> Call[Memories]:
    return _post("latest", Memories.parse, _set(**narrowed))


def around(ref: str, *, width: int | None) -> Call[Memories]:
    return _post("around", Memories.parse, _set(ref=ref, width=width))


def open(ref: str) -> Call[Opened]:
    return _post("open", Opened.parse, {"ref": ref})


def history(subject: str, *, attribute: str | None) -> Call[History]:
    return _post("history", History.parse, _set(subject=subject, attribute=attribute))


def summary() -> Call[Summary]:
    return _post("summary", Summary.parse)


def facts(*, limit: int | None, cursor: str | None) -> Call[FactsPage]:
    return _post("facts", FactsPage.parse, _set(limit=limit, cursor=cursor))


def open_items(**narrowed: Any) -> Call[OpenItems]:
    return _post("open_items", OpenItems.parse, _set(**narrowed))


def sources() -> Call[Sources]:
    return _post("sources", Sources.parse)


def items(*, limit: int | None, cursor: str | None, filters: Json | None) -> Call[ItemsPage]:
    return _post("items", ItemsPage.parse, _set(limit=limit, cursor=cursor, filters=filters))


def _found(raw: Json) -> StoredItem | None:
    return StoredItem.parse(raw["item"]) if raw.get("found") and raw.get("item") else None


def item(item_id: str) -> Call[StoredItem | None]:
    return _post("item", _found, {"id": item_id})


def status(ids: Sequence[str]) -> Call[Statuses]:
    return _post("status", Statuses.parse, {"items": list(ids)})


def forget(
    *, items: Sequence[str] | None, sessions: Sequence[str] | None, refs: Sequence[str] | None
) -> Call[Forgotten]:
    named = {"items": items, "sessions": sessions, "refs": refs}
    body: Json = {k: list(v) for k, v in named.items() if v}
    if not body:
        raise ValueError("forget needs at least one of items, sessions or refs")
    return _post("forget", Forgotten.parse, body)


def correct(ref: str, replacement: str | None) -> Call[Correction]:
    return _post("correct", Correction.parse, _set(ref=ref, replacement=replacement))


def versions(item_id: str) -> Call[Versions]:
    return _post("versions", Versions.parse, {"id": item_id})


def export(*, limit: int | None, cursor: str | None) -> Call[ExportPage]:
    return _post("export", ExportPage.parse, _set(limit=limit, cursor=cursor))


def delete() -> Call[Deleted]:
    return _post("users/delete", Deleted.parse)
