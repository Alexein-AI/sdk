"""What the other read routes answer: the key, a subject's history, a summary, pages of facts,
items, app users and an export, and open work. Each keeps its JSON in `raw`."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from alexein._memories import Fact
from alexein._types import Json, listed


@dataclass(frozen=True)
class Me:
    """What a key is: `kind` is "key" for an API key; `writes` whether it may add, forget and
    correct. The names are the console's, None when unknown. `space` is "project" for a key
    whose app users are a project's, "personal" for a member's own space."""

    kind: str
    writes: bool
    org: str | None = None
    project: str | None = None
    key_id: str | None = None
    label: str | None = None
    created: str | None = None
    created_by: str | None = None
    org_name: str | None = None
    project_name: str | None = None
    space: str | None = None
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Me:
        named = ("org", "project", "key_id", "label", "created", "created_by", "org_name")
        return cls(
            kind=raw.get("kind", ""),
            writes=bool(raw.get("writes")),
            project_name=raw.get("project_name"),
            space=raw.get("space"),
            raw=raw,
            **{k: raw.get(k) for k in named},
        )


@dataclass(frozen=True)
class Value:
    """One value a subject was stated to have, and since when; `negated` when it was said not to
    be so."""

    attribute: str
    value: str
    since: str | None = None
    negated: bool = False


@dataclass(frozen=True)
class History:
    """Every value a subject was stated to have, by attribute, oldest first. When memory does
    not know the subject, `suggestions` names subjects close to it."""

    subject: str
    values: list[Value]
    suggestions: list[str] | None = None
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> History:
        values = [
            Value(
                attribute=v.get("attribute", ""),
                value=v.get("value", ""),
                since=v.get("since"),
                negated=bool(v.get("negated")),
            )
            for v in listed(raw, "values")
        ]
        return cls(raw.get("subject", ""), values, raw.get("suggestions"), raw)


@dataclass(frozen=True)
class Source:
    """What one connected app delivered through one connection: how many items, how many of them
    ended, and the date of the newest."""

    provider: str
    source: str
    connection: str | None = None
    items: int = 0
    ended: int = 0
    newest: str | None = None

    @classmethod
    def parse(cls, raw: Json) -> Source:
        return cls(
            provider=raw.get("provider", ""),
            source=raw.get("source", ""),
            connection=raw.get("connection"),
            items=int(raw.get("items") or 0),
            ended=int(raw.get("ended") or 0),
            newest=raw.get("newest"),
        )


@dataclass(frozen=True)
class Sources:
    """`sources()`: what each connected app delivered to this memory. Iterable."""

    sources: list[Source]
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Sources:
        return cls([Source.parse(s) for s in listed(raw, "sources")], raw)

    def __iter__(self) -> Iterator[Source]:
        return iter(self.sources)

    def __len__(self) -> int:
        return len(self.sources)


@dataclass(frozen=True)
class Summary:
    """What this memory holds, in brief: how many items, the dates of the oldest and newest, the
    connected apps, and the known lines."""

    items: int
    first: str | None
    last: str | None
    sources: list[Source]
    known: list[str]
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> Summary:
        return cls(
            items=int(raw.get("items") or 0),
            first=raw.get("first"),
            last=raw.get("last"),
            sources=[Source.parse(s) for s in listed(raw, "sources")],
            known=listed(raw, "known"),
            raw=raw,
        )


@dataclass(frozen=True)
class FactsPage:
    """A page of the facts memory learned, newest first; `next` is the cursor of the page after,
    None on the last."""

    facts: list[Fact]
    next: str | None = None
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> FactsPage:
        return cls([Fact.parse(f) for f in listed(raw, "facts")], raw.get("next"), raw)


@dataclass(frozen=True)
class StoredItem:
    """An item as it was added, and its `status`: "queued" while it waits to be stored, then
    "stored". `truncated` when a page cut its text; `item(id)` returns it whole."""

    id: str
    text: str
    status: str
    kind: str | None = None
    title: str | None = None
    at: str | None = None
    author: str | Json | None = None
    role: str | None = None
    session: str | None = None
    about: list[str] | None = None
    metadata: Json | None = None
    expires: str | None = None
    truncated: bool = False
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> StoredItem:
        named = ("kind", "title", "at", "author", "role", "session", "about", "metadata")
        return cls(
            id=raw.get("id", ""),
            text=raw.get("text", ""),
            status=raw.get("status", ""),
            expires=raw.get("expires"),
            truncated=bool(raw.get("truncated")),
            raw=raw,
            **{k: raw.get(k) for k in named},
        )


@dataclass(frozen=True)
class ItemsPage:
    """A page of the items added to this memory, newest first; `next` as on `FactsPage`."""

    items: list[StoredItem]
    next: str | None = None
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> ItemsPage:
        return cls([StoredItem.parse(i) for i in listed(raw, "items")], raw.get("next"), raw)


@dataclass(frozen=True)
class AppUser:
    """One app user with memory: how many items and facts it holds, and when memory last took
    something for it (None when unknown)."""

    user: str
    items: int = 0
    facts: int = 0
    last_write: str | None = None


@dataclass(frozen=True)
class UsersPage:
    """A page of this key's project's app users, in id order; `next` as on `FactsPage`."""

    users: list[AppUser]
    next: str | None = None
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> UsersPage:
        users = [
            AppUser(
                user=u.get("user", ""),
                items=int(u.get("items") or 0),
                facts=int(u.get("facts") or 0),
                last_write=u.get("last_write"),
            )
            for u in listed(raw, "users")
        ]
        return cls(users, raw.get("next"), raw)


@dataclass(frozen=True)
class ExportPage:
    """A page of everything memory holds for one app user. Each record is a dict with a `type`
    (item, version, event, fact). `withheld` names what a read key went without."""

    user: str
    exported_at: str
    records: list[Json]
    next: str | None = None
    withheld: list[str] = field(default_factory=list[str])
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> ExportPage:
        return cls(
            user=raw.get("user", ""),
            exported_at=raw.get("exported_at", ""),
            records=listed(raw, "records"),
            next=raw.get("next"),
            withheld=listed(raw, "withheld"),
            raw=raw,
        )


@dataclass(frozen=True)
class OpenItem:
    """An issue or pull request still open: its excerpt's ref, its line, and its age."""

    ref: str
    text: str
    date: str | None = None
    added_at: str | None = None
    age_days: int | None = None


@dataclass(frozen=True)
class FollowUp:
    """An ask nobody answered: what, who, when."""

    title: str | None = None
    who: str | None = None
    date: str | None = None
    age_days: int | None = None


@dataclass(frozen=True)
class OpenItems:
    """Work still open, newest first, and the follow-ups nobody answered."""

    items: list[OpenItem]
    follow_ups: list[FollowUp]
    raw: Json = field(default_factory=dict[str, Any], repr=False, compare=False)

    @classmethod
    def parse(cls, raw: Json) -> OpenItems:
        items = [
            OpenItem(i.get("ref", ""), i.get("text", ""), i.get("date"), i.get("added_at"),
                     i.get("age_days"))
            for i in listed(raw, "items")
        ]  # fmt: skip
        follow_ups = [
            FollowUp(f.get("title"), f.get("who"), f.get("date"), f.get("age_days"))
            for f in listed(raw, "follow_ups")
        ]
        return cls(items, follow_ups, raw)
