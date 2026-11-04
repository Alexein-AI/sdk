"""What the write routes answer, and the reads that say what became of a write: add, status,
forget, correct, versions and an app user's deletion. Each keeps its JSON in `raw`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from alexein._types import Json, listed


@dataclass(frozen=True)
class AddedItem:
    """One item an add took: "stored" (searchable) or "queued" (searchable in a moment).
    `redacted` counts the placeholders `redact` put in its words, by kind; None when none."""

    id: str
    status: str
    redacted: dict[str, int] | None = None


@dataclass(frozen=True)
class AddResult:
    """What an add took. `waiting` is how many items are not searchable yet; `failed` is True
    when a `fail_open` client could not reach memory and saved nothing."""

    items: list[AddedItem]
    waiting: int = 0
    failed: bool = False
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> AddResult:
        items = [
            AddedItem(i.get("id", ""), i.get("status", ""), i.get("redacted"))
            for i in listed(raw, "items")
        ]
        return cls(items=items, waiting=int(raw.get("waiting") or 0), raw=raw)

    @property
    def ids(self) -> list[str]:
        return [i.id for i in self.items]


def merged(results: list[AddResult]) -> AddResult:
    """The answers to an add sent in batches, as one."""
    if len(results) == 1:
        return results[0]
    return AddResult(
        items=[i for r in results for i in r.items],
        waiting=sum(r.waiting for r in results),
        raw={"batches": [r.raw for r in results]},
    )


@dataclass(frozen=True)
class ItemStatus:
    """How far one item has got: "queued", "stored" (searchable), "processed" (facts learned
    from it) or "unknown"; `reason` says what holds it back, None when nothing does."""

    id: str
    status: str
    reason: str | None = None


@dataclass(frozen=True)
class Statuses:
    items: list[ItemStatus]
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Statuses:
        items = [
            ItemStatus(i.get("id", ""), i.get("status", ""), i.get("reason"))
            for i in listed(raw, "items")
        ]
        return cls(items, raw)

    @property
    def by_id(self) -> dict[str, str]:
        return {i.id: i.status for i in self.items}


@dataclass(frozen=True)
class Erased:
    """What a forget erased: items, the facts learned from them, the versions an edit kept, and
    copies on their way in (`waiting`); `relearning` counts facts of other items that stay,
    taken to be learned again from what is left."""

    items: int = 0
    facts: int = 0
    versions: int = 0
    waiting: int = 0
    relearning: int = 0


@dataclass(frozen=True)
class Forgotten:
    """A forget's receipt. `complete` is False when some copies on their way in could not be
    checked: ask again."""

    erased: Erased
    complete: bool
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Forgotten:
        counts: Json = raw.get("erased") or {}
        named = ("items", "facts", "versions", "waiting", "relearning")
        erased = Erased(**{k: int(counts.get(k) or 0) for k in named})
        return cls(erased, bool(raw.get("complete")), raw)


@dataclass(frozen=True)
class Correction:
    """The fact retracted (its ref), its text, and the id of the note holding the replacement,
    if one was given."""

    retracted: str
    text: str | None = None
    replacement: str | None = None
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Correction:
        return cls(raw.get("retracted", ""), raw.get("text"), raw.get("replacement"), raw)


@dataclass(frozen=True)
class Versions:
    """Every version of one added item, oldest first, each a dict with `event` and `at`.
    `state` is "live", "expired", "forgotten", or "unknown" for an id memory never took."""

    id: str
    state: str
    history: list[Json]
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Versions:
        return cls(raw.get("id", ""), raw.get("state", ""), listed(raw, "history"), raw)


@dataclass(frozen=True)
class Deleted:
    """An app user erased whole."""

    user: str
    deleted: bool
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Deleted:
        return cls(raw.get("user", ""), bool(raw.get("deleted")), raw)
