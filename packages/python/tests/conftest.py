"""A client whose every request is answered by a function, and the requests it was sent."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from twinmemory import AsyncMemory, Memory

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
