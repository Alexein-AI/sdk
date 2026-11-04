"""What the read routes answer: memories - known lines, facts and excerpts - and the results that
hold them. Each result keeps the JSON it was read from in `raw`, so a field this version does not
know yet is still reachable."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias

from alexein._types import Json, listed


@dataclass(frozen=True)
class Known:
    """A line memory takes to be true now, as a model should read it first."""

    text: str
    type: Literal["known"] = "known"


@dataclass(frozen=True)
class Fact:
    """A dated fact learned from what was said. `source` is the ref of the excerpt it came from;
    `date` is set on `facts()` alone."""

    ref: str
    text: str
    source: str | None = None
    date: str | None = None
    type: Literal["fact"] = "fact"

    @classmethod
    def parse(cls, raw: Json) -> Fact:
        return cls(
            ref=raw.get("ref", ""),
            text=raw.get("text", ""),
            source=raw.get("source"),
            date=raw.get("date"),
        )


@dataclass(frozen=True)
class Excerpt:
    """Part of what was said or delivered: `date` is when it happened, `added_at` when memory
    took it, `roles` who spoke in it."""

    ref: str
    text: str
    date: str | None = None
    added_at: str | None = None
    session: str | None = None
    roles: list[str] = field(default_factory=list[str])
    type: Literal["excerpt"] = "excerpt"

    @classmethod
    def parse(cls, raw: Json) -> Excerpt:
        return cls(
            ref=raw.get("ref", ""),
            text=raw.get("text", ""),
            date=raw.get("date"),
            added_at=raw.get("added_at"),
            session=raw.get("session"),
            roles=listed(raw, "roles"),
        )


AnyMemory: TypeAlias = "Known | Fact | Excerpt"


def parse_memory(raw: Json) -> AnyMemory:
    kind = raw.get("type")
    if kind == "known":
        return Known(raw.get("text", ""))
    if kind == "fact":
        return Fact.parse(raw)
    return Excerpt.parse(raw)


def _memories(raw: Json) -> list[AnyMemory]:
    return [parse_memory(m) for m in listed(raw, "memories")]


def _line(memory: AnyMemory) -> str:
    """`- <text>`, or `- <YYYY-MM-DD>: <text>` for an excerpt with a date."""
    if isinstance(memory, Excerpt) and memory.date:
        return f"- {memory.date[:10]}: {memory.text}"
    return f"- {memory.text}"


@dataclass(frozen=True)
class SearchResult:
    """What memory holds for a question: `memories` in order - known lines, then facts, then
    excerpts - and `notes` for the model that reads them. `answerable` is False when memory
    does not seem to hold the answer, and None when that was not checked. `failed` is True when
    a `fail_open` client could not reach memory, and the result is empty for that reason."""

    query: str
    answerable: bool | None
    notes: list[str]
    memories: list[AnyMemory]
    sources: list[Any] | None = None
    failed: bool = False
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> SearchResult:
        return cls(
            query=raw.get("query", ""),
            answerable=raw.get("answerable"),
            notes=listed(raw, "notes"),
            memories=_memories(raw),
            sources=raw.get("sources"),
            raw=raw,
        )

    @classmethod
    def unavailable(cls, query: str) -> SearchResult:
        """What a `fail_open` client answers when memory could not be reached."""
        return cls(query=query, answerable=None, notes=[], memories=[], failed=True)

    @property
    def known(self) -> list[Known]:
        return [m for m in self.memories if isinstance(m, Known)]

    @property
    def facts(self) -> list[Fact]:
        return [m for m in self.memories if isinstance(m, Fact)]

    @property
    def excerpts(self) -> list[Excerpt]:
        return [m for m in self.memories if isinstance(m, Excerpt)]

    @property
    def refs(self) -> list[str]:
        """The ref of every fact and excerpt, in order: each opens with `open(ref)`."""
        return [m.ref for m in self.memories if not isinstance(m, Known)]

    def fitting(self, max_chars: int = 4000) -> list[AnyMemory]:
        """The memories `context(max_chars)` holds: from the first, while they fit."""
        return self._fit(max_chars)[1]

    def context(self, max_chars: int = 4000) -> str:
        """The text to paste into a prompt: the notes, then each memory on a line of its own,
        excerpts after their date. Whole memories only, at most `max_chars` long; empty when
        memory found nothing."""
        return self._fit(max_chars)[0]

    def _fit(self, max_chars: int) -> tuple[str, list[AnyMemory]]:
        # Each note on its own line, one blank line, then each memory on its own line, cut at a
        # whole memory. The TypeScript client and the n8n node write the same text.
        notes = "\n".join(self.notes)
        text, kept = "", list[AnyMemory]()
        for memory in self.memories:
            grown = f"{text}\n{_line(memory)}" if kept else _line(memory)
            if len(f"{notes}\n\n{grown}" if notes else grown) > max_chars:
                break
            text, kept = grown, [*kept, memory]
        if not kept:
            return "", []
        return (f"{notes}\n\n{text}" if notes else text), kept


@dataclass(frozen=True)
class Memories:
    """`grep`, `latest` and `around`: excerpts in order. Iterable. `pattern` and `total` are
    set by grep (`total` counts every match, not only those returned); `places` by latest when
    the API names where it looked."""

    memories: list[Excerpt]
    pattern: str | None = None
    total: int | None = None
    places: list[Any] | None = None
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Memories:
        return cls(
            memories=[Excerpt.parse(m) for m in listed(raw, "memories")],
            pattern=raw.get("pattern"),
            total=raw.get("total"),
            places=raw.get("places"),
            raw=raw,
        )

    def __iter__(self) -> Iterator[Excerpt]:
        return iter(self.memories)

    def __len__(self) -> int:
        return len(self.memories)


@dataclass(frozen=True)
class Opened:
    """One memory whole: an excerpt in full, or a fact with the excerpts it was learned from."""

    memory: Fact | Excerpt
    sources: list[Excerpt]
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Opened:
        given: Json = raw.get("memory") or {}
        memory = Fact.parse(given) if given.get("type") == "fact" else Excerpt.parse(given)
        sources = [Excerpt.parse(s) for s in listed(raw, "sources")]
        return cls(memory=memory, sources=sources, raw=raw)
