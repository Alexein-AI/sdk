"""What the API answers, as typed values. Each keeps the JSON it was read from in `raw`, so a
field this version does not know yet is still reachable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

Json = dict[str, Any]


class Author(TypedDict, total=False):
    id: str
    name: str
    email: str
    handle: str
    self: bool


class Item(TypedDict, total=False):
    """One thing to remember. Only `text` is required. Send it again with the same `id` to
    replace it; set `expires` (an ISO date) for what stops being true."""

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


@dataclass(frozen=True)
class Me:
    """What a key is: `kind` is "key" for a customer's key."""

    kind: str
    writes: bool
    org: str | None = None
    project: str | None = None
    key_id: str | None = None
    raw: Json = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, raw: Json) -> Me:
        return cls(
            kind=raw.get("kind", ""),
            writes=bool(raw.get("writes")),
            org=raw.get("org"),
            project=raw.get("project"),
            key_id=raw.get("key_id"),
            raw=raw,
        )


@dataclass(frozen=True)
class AddedItem:
    id: str
    event_id: str
    # None when the service landed it as it answered (no queue); else whether it has yet.
    landed: bool | None = None
    thread_id: str | None = None
    path: str | None = None

    @classmethod
    def parse(cls, raw: Json) -> AddedItem:
        return cls(
            id=raw.get("id", ""),
            event_id=raw.get("event_id", ""),
            landed=raw.get("landed"),
            thread_id=raw.get("thread_id"),
            path=raw.get("path"),
        )


@dataclass(frozen=True)
class AddResult:
    """`pending` is how many items are accepted and not yet searchable; zero once they are.
    `failed` is True when a `fail_open` client could not reach memory and saved nothing."""

    items: list[AddedItem]
    queued: int
    pending: int
    raw: Json = field(default_factory=dict[str, Any], repr=False)
    failed: bool = False

    @classmethod
    def parse(cls, raw: Json) -> AddResult:
        return cls(
            items=[AddedItem.parse(i) for i in raw.get("items", [])],
            queued=int(raw.get("queued", 0)),
            pending=int(raw.get("pending", 0)),
            raw=raw,
        )


@dataclass(frozen=True)
class Hit:
    """A passage: what was said or written, with its address."""

    path: str
    id: str
    text: str
    thread: str | None = None

    @classmethod
    def parse(cls, raw: Json) -> Hit:
        return cls(
            path=raw.get("path", ""),
            id=raw.get("id", ""),
            text=raw.get("text", ""),
            thread=raw.get("thread"),
        )


@dataclass(frozen=True)
class Fact:
    """One dated line read from a passage; `source` is that passage."""

    text: str
    id: str
    path: str
    thread: str | None = None
    source: str | None = None

    @classmethod
    def parse(cls, raw: Json) -> Fact:
        return cls(
            text=raw.get("text", ""),
            id=raw.get("id", ""),
            path=raw.get("path", ""),
            thread=raw.get("thread"),
            source=raw.get("source"),
        )


@dataclass(frozen=True)
class SearchResult:
    """What memory holds for a question: `known` lines first, then dated `facts`, then whole
    passages (`hits`). `held` is False when memory says it does not hold the answer; `filtered`
    is whether the model filter judged what came back. `failed` is True when a `fail_open`
    client could not reach memory, and the result is empty for that reason."""

    query: str
    found: int
    hits: list[Hit]
    facts: list[Fact]
    known: list[str]
    worked_out: list[str]
    notes: list[str]
    held: bool | None
    filtered: bool
    raw: Json = field(default_factory=dict[str, Any], repr=False)
    failed: bool = False

    @classmethod
    def unavailable(cls, query: str) -> SearchResult:
        """What a `fail_open` client answers when memory could not be reached."""
        return cls(query, 0, [], [], [], [], [], None, False, failed=True)

    @classmethod
    def parse(cls, raw: Json) -> SearchResult:
        return cls(
            query=raw.get("query", ""),
            found=int(raw.get("found", 0)),
            hits=[Hit.parse(h) for h in raw.get("hits", [])],
            facts=[Fact.parse(f) for f in raw.get("facts", [])],
            known=list(raw.get("known", [])),
            worked_out=list(raw.get("worked_out", [])),
            notes=list(raw.get("notes", [])),
            held=raw.get("held"),
            filtered=bool(raw.get("filtered")),
            raw=raw,
        )

    def context(self, max_chars: int = 4000) -> str:
        """A block to paste into a prompt: known lines, dated facts, then passages, whole
        entries only, at most `max_chars` long. Empty when memory found nothing."""
        sections = [
            ("What is known", self.known),
            ("Worked out", self.worked_out),
            ("Facts", [f.text for f in self.facts]),
            ("Passages", [h.text for h in self.hits]),
        ]
        out: list[str] = []
        for title, lines in sections:
            heading = [f"{title}:"] if not out else ["", f"{title}:"]
            for line in lines:
                grown = [*out, *heading, "- " + " ".join(line.split())]
                if len("\n".join(grown)) > max_chars:
                    return "\n".join(out)
                out, heading = grown, []
        return "\n".join(out)


@dataclass(frozen=True)
class GrepResult:
    pattern: str
    total: int
    matches: list[Hit]
    raw: Json = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, raw: Json) -> GrepResult:
        return cls(
            pattern=raw.get("pattern", ""),
            total=int(raw.get("total", 0)),
            matches=[Hit.parse(m) for m in raw.get("matches", [])],
            raw=raw,
        )


@dataclass(frozen=True)
class Passages:
    """`latest` and `around`: passages in order, newest first for `latest`."""

    passages: list[Hit]
    raw: Json = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, raw: Json) -> Passages:
        return cls(passages=[Hit.parse(p) for p in raw.get("passages", [])], raw=raw)


@dataclass(frozen=True)
class File:
    """One file by path. `error` is set, with the directory's `siblings`, when there is none."""

    path: str
    text: str | None
    error: str | None = None
    siblings: list[str] = field(default_factory=list[str])
    raw: Json = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, raw: Json) -> File:
        return cls(
            path=raw.get("path", ""),
            text=raw.get("text"),
            error=raw.get("error"),
            siblings=list(raw.get("siblings", [])),
            raw=raw,
        )


@dataclass(frozen=True)
class Listing:
    path: str
    entries: list[str]
    raw: Json = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, raw: Json) -> Listing:
        return cls(path=raw.get("path", ""), entries=list(raw.get("entries", [])), raw=raw)


@dataclass(frozen=True)
class History:
    """Every dated value recorded for one subject. When nothing is, `error` says so and
    `subjects` offers the nearest names."""

    subject: str
    assertions: list[Json]
    error: str | None = None
    subjects: list[str] = field(default_factory=list[str])
    raw: Json = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, raw: Json) -> History:
        return cls(
            subject=raw.get("subject", ""),
            assertions=list(raw.get("assertions", [])),
            error=raw.get("error"),
            subjects=list(raw.get("subjects", [])),
            raw=raw,
        )


@dataclass(frozen=True)
class Versions:
    """An added item's versions, as they were sent. `state` is "live", "forgotten" or
    "expired"; once an item goes, its history is one line saying when and why."""

    id: str
    state: str
    history: list[Json]
    raw: Json = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, raw: Json) -> Versions:
        return cls(
            id=raw.get("id", ""),
            state=raw.get("state", ""),
            history=list(raw.get("history", [])),
            raw=raw,
        )


@dataclass(frozen=True)
class TableChange:
    before: int
    after: int


@dataclass(frozen=True)
class Receipt:
    """What a forget erased: each table's row count before and after."""

    events: int
    tables: dict[str, TableChange]
    raw: Json = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, raw: Json) -> Receipt:
        tables = {
            name: TableChange(int(t.get("before", 0)), int(t.get("after", 0)))
            for name, t in raw.get("tables", {}).items()
        }
        return cls(events=int(raw.get("events", 0)), tables=tables, raw=raw)


@dataclass(frozen=True)
class Correction:
    """The record retracted, its text, and the id of the note holding the replacement."""

    retracted: str
    text: str | None = None
    replacement: str | None = None
    raw: Json = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, raw: Json) -> Correction:
        return cls(
            retracted=raw.get("retracted", ""),
            text=raw.get("text"),
            replacement=raw.get("replacement"),
            raw=raw,
        )


@dataclass(frozen=True)
class Lineage:
    """What an item, event or record became - or, for a record, what it was read from."""

    of: str
    events: list[str]
    passages: list[Json]
    records: list[Json]
    raw: Json = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, raw: Json) -> Lineage:
        return cls(
            of=raw.get("of", ""),
            events=list(raw.get("events", [])),
            passages=list(raw.get("passages", [])),
            records=list(raw.get("records", [])),
            raw=raw,
        )


@dataclass(frozen=True)
class Overview:
    """The shape of this end user's memory: its directories, counts, and written index."""

    directories: list[str]
    manifest: Json
    index: str
    raw: Json = field(default_factory=dict[str, Any], repr=False)

    @classmethod
    def parse(cls, raw: Json) -> Overview:
        return cls(
            directories=list(raw.get("directories", [])),
            manifest=dict(raw.get("manifest") or {}),
            index=raw.get("index", ""),
            raw=raw,
        )
