"""`fail_open`: memory being down costs a search its answer and an add its save, not the caller
its turn. A wrong key or a wrong request still raises. And `integration`, in the User-Agent."""

from __future__ import annotations

import logging

import httpx
import pytest
from conftest import Answer, async_memory, memory, ok

from twinmemory import (
    AuthenticationError,
    InvalidRequestError,
    Memory,
    ServiceUnavailableError,
    __version__,
)

OUTAGES = [
    pytest.param(lambda r: ok({"detail": "rebuilding"}, status=503), id="503"),
    pytest.param(lambda r: ok({"detail": "busy"}, status=429), id="429"),
    pytest.param(lambda r: ok({"detail": "boom"}, status=500), id="500"),
    pytest.param(lambda r: ok({"detail": "bad gateway"}, status=502), id="502"),
]


def unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def timed_out(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


@pytest.mark.parametrize(
    "answer",
    [*OUTAGES, pytest.param(unreachable, id="unreachable"), pytest.param(timed_out, id="timeout")],
)
def test_an_outage_answers_empty_and_logs(answer: Answer, caplog: pytest.LogCaptureFixture) -> None:
    client, recorded = memory(answer, fail_open=True)
    dana = client.user("dana")

    with caplog.at_level(logging.WARNING, logger="twinmemory"):
        found = dana.search("Where does Dana live?")
        saved = dana.add("I moved to Lisbon.")

    assert found.failed and found.found == 0 and found.context() == ""
    assert found.query == "Where does Dana live?"
    assert saved.failed and saved.items == []
    assert {r.url.path for r in recorded.requests} == {"/v1/memory/search", "/v1/memory/add"}
    assert [r.message for r in caplog.records if "unavailable" in r.message] != []


@pytest.mark.parametrize(
    ("status", "kind"), [(401, AuthenticationError), (400, InvalidRequestError)]
)
def test_a_mistake_still_raises(status: int, kind: type[Exception]) -> None:
    client, _ = memory(lambda r: ok({"detail": "no"}, status=status), fail_open=True)
    with pytest.raises(kind):
        client.user("dana").search("q")
    with pytest.raises(kind):
        client.user("dana").add("x")


def test_off_by_default() -> None:
    client, _ = memory(lambda r: ok({"detail": "rebuilding"}, status=503))
    with pytest.raises(ServiceUnavailableError):
        client.user("dana").search("q")


def test_429_and_503_are_retried_before_failing_open() -> None:
    client, recorded = memory(lambda r: ok({"detail": "busy"}, status=503), fail_open=True)
    assert client.user("dana").search("q").failed
    assert len(recorded.requests) == 1 + client.max_retries


def test_a_success_is_not_failed() -> None:
    client, _ = memory(lambda r: ok({"query": "q", "found": 0}), fail_open=True)
    assert client.user("dana").search("q").failed is False


@pytest.mark.anyio
async def test_async_fails_open_too() -> None:
    client, _ = async_memory(lambda r: ok({"detail": "rebuilding"}, status=503), fail_open=True)
    dana = client.user("dana")
    assert (await dana.search("q")).failed
    assert (await dana.add("x")).failed


def test_integration_names_itself_in_the_user_agent() -> None:
    client, recorded = memory(lambda r: ok({"query": "q"}), integration="langgraph")
    client.user("dana").search("q")
    assert recorded.last.headers["User-Agent"] == f"twinmemory-python/{__version__} langgraph"


def test_without_integration_the_user_agent_is_unchanged() -> None:
    client, recorded = memory(lambda r: ok({"query": "q"}))
    client.user("dana").search("q")
    assert recorded.last.headers["User-Agent"] == f"twinmemory-python/{__version__}"


@pytest.mark.parametrize("bad", ["Lang Graph", "", "x" * 40, "a/b"])
def test_an_integration_is_one_short_word(bad: str) -> None:
    with pytest.raises(ValueError, match="integration"):
        Memory("tm_test", integration=bad)


def test_outage_is_public_on_every_error() -> None:
    client, _ = memory(unreachable)
    with pytest.raises(Exception) as raised:
        client.user("dana").search("q")
    assert getattr(raised.value, "outage", None) is True
    client, _ = memory(lambda r: ok({"detail": "no"}, status=401))
    with pytest.raises(AuthenticationError) as denied:
        client.user("dana").search("q")
    assert denied.value.outage is False
