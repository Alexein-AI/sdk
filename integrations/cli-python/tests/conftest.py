"""A memory API that answers as the v2 one does, the requests it was sent, and a memory file as
`init` writes it, imported with its own client - made as the file makes it, from its own
settings - sending to that API."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import alexein._client
import httpx
import pytest

from alexein_cli.render import render

Answer = Callable[[httpx.Request], httpx.Response]


class Recorded:
    """Every request sent, and the timeout each client was made with."""

    def __init__(self, answer: Answer) -> None:
        self.answer = answer
        self.requests: list[httpx.Request] = []
        self.timeouts: list[float | None] = []

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

    def users(self) -> set[str]:
        return {r.headers.get("x-alexein-user", "") for r in self.requests if route(r) != "me"}


def route(request: httpx.Request) -> str:
    """`search` for `/v2/memory/search`, `me` for `/v2/me`."""
    return request.url.path.removeprefix("/v2/").removeprefix("memory/")


def ok(body: Any = None, status: int = 200, **headers: str) -> httpx.Response:
    return httpx.Response(status, json={} if body is None else body, headers=headers)


def down(request: httpx.Request) -> httpx.Response:
    return ok({"detail": "rebuilding"}, status=503)


def wrong_key(request: httpx.Request) -> httpx.Response:
    return ok({"detail": "bad key"}, status=401)


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


# ---------------------------------------------------------------- what the API answers --

EXCERPT = {
    "type": "excerpt",
    "ref": "mem_e1",
    "text": "Dana: I moved to Lisbon.",
    "date": "2026-10-01T09:30:00Z",
    "added_at": "2026-10-01T09:30:02Z",
    "session": "onboarding",
    "roles": ["user"],
}
FACT = {"type": "fact", "ref": "mem_f1", "text": "Dana moved to Lisbon.", "source": "mem_e1"}
SEARCHED = {
    "query": "q",
    "answerable": True,
    "notes": [],
    "memories": [{"type": "known", "text": "Dana lives in Lisbon."}, FACT, EXCERPT],
}
ME = {"kind": "key", "org": "o", "project": "p", "writes": True}


def answer(request: httpx.Request) -> httpx.Response:
    """Each route's answer, as the v2 API gives it."""
    name = route(request)
    if name == "me":
        return ok(ME)
    if name == "search":
        return ok(SEARCHED)
    if name == "open":
        return ok({"memory": EXCERPT})
    if name == "add":
        items = json.loads(request.content)["items"]
        added = [{"id": i.get("id") or f"i{n}", "status": "queued"} for n, i in enumerate(items)]
        return ok({"items": added, "waiting": len(items)}, status=202)
    return ok()


def wire(monkeypatch: pytest.MonkeyPatch, answer: Answer) -> Recorded:
    """Every client made from here on - the memory file's own - sends to `answer`."""
    recorded = Recorded(answer)

    def client(timeout: float | None = None, **_: Any) -> httpx.Client:
        recorded.timeouts.append(timeout)
        return httpx.Client(transport=httpx.MockTransport(recorded))

    def async_client(timeout: float | None = None, **_: Any) -> httpx.AsyncClient:
        recorded.timeouts.append(timeout)
        return httpx.AsyncClient(transport=httpx.MockTransport(recorded))

    made = SimpleNamespace(Client=client, AsyncClient=async_client)
    monkeypatch.setattr(alexein._client, "httpx", made)
    return recorded


def load_memory_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    framework: str,
    answer: Answer = answer,
    *,
    fast: bool = False,
    edits: dict[str, str] | None = None,
    key: str | None = "tm_test",
) -> tuple[ModuleType, Recorded]:
    """The file as `init` writes it - with `edits` made to it, as its developer would - imported
    with `key` set (or none), the client it makes on first use sending to `answer`."""
    text = render(f"{framework.replace('-', '_')}/memory.py.tmpl", (), written(fast))
    for old, new in (edits or {}).items():
        assert old in text, old
        text = text.replace(old, new)
    path = tmp_path / "memory.py"
    path.write_text(text)
    if key is None:
        monkeypatch.delenv("ALEXEIN_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ALEXEIN_API_KEY", key)
    monkeypatch.delenv("ALEXEIN_API_URL", raising=False)
    recorded = wire(monkeypatch, answer)
    name = f"generated_{framework.replace('-', '_')}_{abs(hash(tmp_path))}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module, recorded


def written(fast: bool = False) -> dict[str, str]:
    """The values `init` fills a memory template with."""
    return {"version": "test", "fast": str(fast)}


STRICT = {"STRICT = False": "STRICT = True"}
