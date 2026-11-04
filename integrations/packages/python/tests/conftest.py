"""A client whose every request is answered by a function, and the requests it was sent; a
memory API that answers as the real one does; and a memory file as `init` writes it, imported
with such a client."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from twinmemory import AsyncMemory, Memory

from twinmemory_cli.render import render

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

    monkeypatch.setattr("twinmemory._client.time.sleep", slept.append)
    monkeypatch.setattr("twinmemory._client.asyncio.sleep", asleep)
    return slept


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWIN_MEMORY_API_KEY", raising=False)
    monkeypatch.delenv("TWIN_MEMORY_BASE_URL", raising=False)


def memory(answer: Answer, **kwargs: Any) -> tuple[Memory, Recorded]:
    recorded = Recorded(answer)
    http = httpx.Client(transport=httpx.MockTransport(recorded))
    return Memory("tm_test", http_client=http, **kwargs), recorded


def async_memory(answer: Answer, **kwargs: Any) -> tuple[AsyncMemory, Recorded]:
    recorded = Recorded(answer)
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorded))
    return AsyncMemory("tm_test", http_client=http, **kwargs), recorded


SEARCHED = {
    "query": "q",
    "found": 1,
    "known": ["Dana lives in Lisbon."],
    "facts": [],
    "hits": [{"path": "passages/p1.md", "id": "p1", "text": "Dana: I moved to Lisbon."}],
}


def answer(request: httpx.Request) -> httpx.Response:
    route = request.url.path.rsplit("/", 1)[-1]
    if route == "search":
        return ok(SEARCHED)
    if route == "read":
        return ok({"path": "passages/p1.md", "text": "Dana: I moved to Lisbon."})
    if route == "add":
        items = json.loads(request.content)["items"]
        return ok({"accepted": len(items), "items": []}, status=202)
    return ok()


def routes(recorded: Recorded) -> list[str]:
    return [r.url.path.rsplit("/", 1)[-1] for r in recorded.requests]


def load_memory_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    template: str,
    answer: Answer,
    *,
    parts: tuple[str, ...],
    integration: str,
    asynchronous: bool,
) -> tuple[ModuleType, Recorded]:
    """The file as `init` writes it, imported, its client answered by `answer` - made as the
    file makes its own, failing open unless STRICT."""
    path = tmp_path / "memory.py"
    path.write_text(render(template, parts, {"version": "test", "fast": "False"}))
    name = f"generated_{integration.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    made = async_memory if asynchronous else memory
    client, recorded = made(answer, fail_open=not module.STRICT, integration=integration)
    monkeypatch.setattr(module, "_memory", lambda: client)
    return module, recorded
