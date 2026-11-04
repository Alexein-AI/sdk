"""What a caller sends: an item to add and who said it."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, TypeAlias, TypedDict, cast

Json = dict[str, Any]
# A connector's kinds to narrow to: one, or several.
Kinds: TypeAlias = "str | Sequence[str]"


class Author(TypedDict, total=False):
    """Who said it. `id` is your stable id for the person, the strongest sign of who someone is;
    `email` and `handle` help memory recognise them elsewhere; `self` marks the app user whose
    memory this is."""

    id: str
    name: str
    email: str
    handle: str
    self: bool


class Item(TypedDict, total=False):
    """One thing to remember. Only `text` is required. Send it again with the same `id` to edit
    it; set `expires` (an ISO date) for what stops being true."""

    text: str
    kind: Literal["message", "document", "note"]
    id: str
    at: str
    author: str | Author
    role: str
    session: str
    title: str
    about: list[str]
    expires: str
    metadata: Json


def listed(raw: Json, key: str) -> list[Any]:
    """A list the API answered under `key`; empty when it sent none."""
    found = raw.get(key)
    return cast("list[Any]", found) if isinstance(found, list) else []
