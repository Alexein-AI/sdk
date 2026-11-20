"""What the routes about people and things answer: one subject whole, what a memory links to, how
the person works, and the lessons they taught assistants. Each keeps its JSON in `raw`."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from alexein._memories import Fact
from alexein._results import Value
from alexein._types import Json, listed


@dataclass(frozen=True)
class Link:
    """How one person or thing relates to another, in words (`link`): the day it was said, the
    ref of the fact that says it, and the ref of the excerpt that fact was learned from (None
    when unknown, and on `subject()` links)."""

    link: str
    ref: str
    date: str | None = None
    source: str | None = None

    @classmethod
    def parse(cls, raw: Json) -> Link:
        return cls(raw.get("link", ""), raw.get("ref", ""), raw.get("date"), raw.get("source"))


@dataclass(frozen=True)
class Line:
    """A line for a model, with the refs of the facts it rests on: a subject's `about`, and a
    conversation about it (whose one ref is an excerpt of that conversation)."""

    text: str
    refs: list[str] = field(default_factory=list[str])
    date: str | None = None


@dataclass(frozen=True)
class Subject:
    """One person or thing by name, whole: `about`, a few lines on how it went; `values`, each
    property's newest value; `timeline`, its facts oldest first; `conversations` about it;
    `links` to other people and things. `facts` is 0 when memory holds nothing by that name,
    and then `suggestions` names the nearest it does."""

    name: str
    facts: int
    about: list[Line]
    values: list[Value]
    timeline: list[Fact]
    conversations: list[Line]
    links: list[Link]
    suggestions: list[str] | None = None
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Subject:
        return cls(
            name=raw.get("name", ""),
            facts=int(raw.get("facts") or 0),
            about=[Line(a.get("text", ""), listed(a, "refs")) for a in listed(raw, "about")],
            values=[
                Value(v.get("attribute", ""), v.get("value", ""), v.get("since"))
                for v in listed(raw, "values")
            ],
            timeline=[Fact.parse(f) for f in listed(raw, "timeline")],
            conversations=[
                Line(c.get("text", ""), [c["ref"]] if c.get("ref") else [], c.get("date"))
                for c in listed(raw, "conversations")
            ],
            links=[Link.parse(link) for link in listed(raw, "links")],
            suggestions=raw.get("suggestions"),
            raw=raw,
        )


@dataclass(frozen=True)
class Related:
    """What the people and things one memory names link to, newest said first. Iterable."""

    links: list[Link]
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Related:
        return cls([Link.parse(link) for link in listed(raw, "links")], raw)

    def __iter__(self) -> Iterator[Link]:
        return iter(self.links)

    def __len__(self) -> int:
        return len(self.links)


@dataclass(frozen=True)
class Card:
    """A plain line for a model, and the refs of the facts it cites. `kind` says what it is:
    `routine` or `style` from `how_they_work()` (`surface` names where a style is for), `lesson`
    from `lessons()` (`from_` says what it came from: `correction`, `feedback` or `said`), or
    `strategy`, `failure` or `workflow` among a `Lessons`' `lessons`. The counts a card rests on
    are in its `raw`."""

    kind: str
    text: str
    refs: list[str] = field(default_factory=list[str])
    surface: str | None = None
    from_: list[str] = field(default_factory=list[str])
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Card:
        return cls(
            kind=raw.get("kind", ""),
            text=raw.get("text", ""),
            refs=listed(raw, "refs"),
            surface=raw.get("surface"),
            from_=listed(raw, "from"),
            raw=raw,
        )


@dataclass(frozen=True)
class Ways:
    """How someone works: `cards`, each a routine or a writing style; `procedures`, each
    routine's counts written out for a model; `voice`, how they write, or None when memory has
    too few of their messages to say."""

    who: str
    cards: list[Card]
    procedures: list[str]
    voice: str | None = None
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Ways:
        return cls(
            who=raw.get("who", ""),
            cards=[Card.parse(c) for c in listed(raw, "cards")],
            procedures=listed(raw, "procedures"),
            voice=raw.get("voice"),
            raw=raw,
        )


@dataclass(frozen=True)
class Lessons:
    """What an assistant should know before a task like `task`: `cards`, the lessons the person
    taught, most like it first; `lessons`, what earlier attempts at similar tasks taught."""

    task: str
    cards: list[Card]
    lessons: list[Card]
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Lessons:
        return cls(
            task=raw.get("task", ""),
            cards=[Card.parse(c) for c in listed(raw, "cards")],
            lessons=[Card.parse(c) for c in listed(raw, "lessons")],
            raw=raw,
        )
