"""A client whose every request is answered by a function, the requests it was sent, and what the
v2 API answers each route with (the service's `api/public.py`, `v2.py`, `v2_writes.py`)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from alexein import AsyncMemory, Memory

Answer = Callable[[httpx.Request], httpx.Response]


class Recorded:
    def __init__(self, answer: Answer) -> None:
        self.answer = answer
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.answer(request)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def body(self, at: int = -1) -> Any:
        return json.loads(self.requests[at].content or b"null")

    def routes(self) -> list[str]:
        return [route(r) for r in self.requests]

    def bodies(self, name: str) -> list[Any]:
        return [json.loads(r.content) for r in self.requests if route(r) == name]


def route(request: httpx.Request) -> str:
    """`search` for `/v2/memory/search`, `users/delete`, `me`."""
    return request.url.path.removeprefix("/v2/").removeprefix("memory/")


def ok(body: Any = None, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, json={} if body is None else body, headers=headers)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Retries record their pauses instead of sleeping them."""
    slept: list[float] = []

    async def asleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("alexein._http.time.sleep", slept.append)
    monkeypatch.setattr("alexein._http.asyncio.sleep", asleep)
    return slept


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALEXEIN_API_KEY", raising=False)
    monkeypatch.delenv("ALEXEIN_API_URL", raising=False)


def memory(answer: Answer, **kwargs: Any) -> tuple[Memory, Recorded]:
    recorded = Recorded(answer)
    http = httpx.Client(transport=httpx.MockTransport(recorded))
    return Memory("tm_test", http_client=http, **kwargs), recorded


def async_memory(answer: Answer, **kwargs: Any) -> tuple[AsyncMemory, Recorded]:
    recorded = Recorded(answer)
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorded))
    return AsyncMemory("tm_test", http_client=http, **kwargs), recorded


# ---------------------------------------------------------------- what the API answers --

EXCERPT = {
    "type": "excerpt",
    "ref": "mem_e1",
    "text": "Dana: I moved to Lisbon for the job at Acme.",
    "date": "2026-10-01T09:30:00Z",
    "added_at": "2026-10-01T09:30:02Z",
    "session": "onboarding",
    "roles": ["user"],
}
FACT = {
    "type": "fact",
    "ref": "mem_f1",
    "text": "Dana moved to Lisbon for a job at Acme.",
    "source": "mem_e1",
}
SEARCHED = {
    "query": "Where does Dana live?",
    "answerable": True,
    "notes": ["Prefer the newest of two values."],
    "memories": [{"type": "known", "text": "Dana lives in Lisbon."}, FACT, EXCERPT],
}
EMPTY_SEARCH = {"query": "q", "answerable": None, "notes": [], "memories": []}
GREPPED = {"pattern": "Lisbon", "total": 3, "memories": [EXCERPT]}
LATEST = {"memories": [EXCERPT], "places": ["slack", "items"]}
OPENED_FACT = {"memory": FACT, "sources": [EXCERPT]}
OPENED_EXCERPT = {"memory": EXCERPT}
HISTORY = {
    "subject": "Dana",
    "values": [
        {"attribute": "city", "value": "Porto", "since": "2025-01-01", "negated": False},
        {"attribute": "city", "value": "Lisbon", "since": "2026-10-01", "negated": False},
    ],
}
HISTORY_UNKNOWN = {"subject": "Dna", "values": [], "suggestions": ["Dana"]}
SOURCE = {
    "provider": "github",
    "source": "items",
    "connection": "conn_1",
    "items": 12,
    "ended": 2,
    "newest": "2026-10-30T08:00:00Z",
}
SUMMARY = {
    "items": 14,
    "first": "2025-01-01T00:00:00Z",
    "last": "2026-10-30T08:00:00Z",
    "sources": [SOURCE],
    "known": ["Dana lives in Lisbon."],
}
FACTS_PAGE = {"facts": [{**FACT, "date": "2026-10-01T09:30:00Z"}], "next": "cur_2"}
STORED = {
    "id": "diet",
    "kind": "note",
    "text": "Vegetarian, allergic to peanuts.",
    "author": {"name": "Dana", "self": True},
    "about": ["topic:food"],
    "metadata": {"source": "crm"},
    "status": "stored",
}
ITEMS_PAGE = {
    "items": [STORED, {"id": "q1", "text": "x" * 2000, "truncated": True, "status": "queued"}],
    "next": None,
}
ITEM = {"found": True, "item": STORED}
NO_ITEM = {"found": False}
USERS_PAGE = {
    "users": [{"user": "dana", "items": 14, "facts": 6, "last_write": "2026-10-30T08:00:00Z"}],
    "next": "dana",
}
EXPORT_PAGE = {
    "user": "dana",
    "exported_at": "2026-11-04T10:00:00+00:00",
    "records": [
        {"type": "item", "id": "diet", "text": "Vegetarian.", "status": "stored"},
        {
            "type": "fact",
            "ref": "mem_f1",
            "text": "Dana is vegetarian.",
            "date": "2026-10-01",
            "from": "2026-10-01",
            "until": None,
        },
    ],
    "next": None,
    "withheld": ["version"],
}
OPEN_ITEMS = {
    "items": [
        {
            "ref": "mem_e2",
            "text": "PR #12: Fix the login page",
            "date": "2026-10-28",
            "added_at": "2026-10-28T10:00:00Z",
            "age_days": 7,
        },
    ],
    "follow_ups": [{"title": "Send the deck", "who": "sam", "date": "2026-10-20", "age_days": 15}],
}
SOURCES = {"sources": [SOURCE]}
ADDED = {
    "items": [
        {"id": "diet", "status": "stored", "redacted": {"PHONE": 1}},
        {"id": "k:1", "status": "queued"},
    ],
    "waiting": 1,
}
STATUSES = {
    "items": [
        {"id": "diet", "status": "processed", "reason": None},
        {"id": "nope", "status": "unknown", "reason": "Memory holds nothing by this id."},
    ]
}
FORGOTTEN = {
    "erased": {"items": 2, "facts": 3, "versions": 1, "waiting": 0, "relearning": 1},
    "complete": True,
}
CORRECTED = {"retracted": "mem_f1", "text": "Dana lives in Porto.", "replacement": "corr_1"}
VERSIONS = {
    "id": "diet",
    "state": "live",
    "history": [{"event": "version", "at": "2026-10-01T09:30:00Z", "item": {"text": "Veg."}}],
}
ME = {
    "kind": "key",
    "org": "o7k2m9qx4ab",
    "project": "production",
    "key_id": "key_3f9a1c2b7d4e",
    "writes": True,
    "label": "backend",
    "created": "2026-09-01T00:00:00Z",
    "created_by": "dana@example.com",
    "org_name": "Acme",
    "project_name": "Production",
    "space": "project",
}
DELETED = {"user": "dana", "deleted": True}

BY_ROUTE: dict[str, Any] = {
    "me": ME,
    "users": USERS_PAGE,
    "users/delete": DELETED,
    "search": SEARCHED,
    "grep": GREPPED,
    "latest": LATEST,
    "around": {"memories": [EXCERPT]},
    "open": OPENED_FACT,
    "history": HISTORY,
    "summary": SUMMARY,
    "facts": FACTS_PAGE,
    "open_items": OPEN_ITEMS,
    "sources": SOURCES,
    "items": ITEMS_PAGE,
    "item": ITEM,
    "status": STATUSES,
    "forget": FORGOTTEN,
    "correct": CORRECTED,
    "versions": VERSIONS,
    "export": EXPORT_PAGE,
    "add": ADDED,
}


def answer(request: httpx.Request) -> httpx.Response:
    """Each route's answer, as the v2 API gives it."""
    name = route(request)
    status = 202 if name == "add" else 200
    return ok(BY_ROUTE[name], status=status)
