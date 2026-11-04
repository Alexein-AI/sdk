"""`AsyncMemory` sends what `Memory` sends, method for method."""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from conftest import answer, async_memory, memory
from test_requests import CASES

from alexein import AsyncMemory, AsyncUser, Memory, NotFoundError, User

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(("call", "name", "body"), CASES)
async def test_each_method_sends_the_same_request(call: Any, name: str, body: Any):
    client, recorded = async_memory(answer)
    result = await call(client.user("dana"))
    sync_client, _ = memory(answer)
    assert result == call(sync_client.user("dana"))
    (request,) = recorded.requests
    assert request.url.path == f"/v2/memory/{name}" and recorded.body() == body
    assert request.headers["x-alexein-user"] == "dana"


async def test_me_users_and_close():
    client, recorded = async_memory(answer)
    async with client:
        assert (await client.me()).writes
        assert (await client.users(limit=5)).next == "dana"
    assert [r.url.path for r in recorded.requests] == ["/v2/me", "/v2/memory/users"]


async def test_errors_and_retries_are_the_same(no_waiting: list[float]):
    from conftest import ok

    answers = iter([ok({}, 503), ok({"detail": "no memory for app user 'x' yet"}, 404)])
    client, recorded = async_memory(lambda r: next(answers))
    with pytest.raises(NotFoundError):
        await client.user("x").summary()
    assert len(recorded.requests) == 2 and len(no_waiting) == 1


def test_both_clients_have_the_same_methods():
    def public(kind: type) -> dict[str, inspect.Signature]:
        return {
            name: inspect.signature(fn)
            for name, fn in vars(kind).items()
            if callable(fn) and not name.startswith("_")
        }

    for sync, asynchronous in ((Memory, AsyncMemory), (User, AsyncUser)):
        ours, theirs = public(sync), public(asynchronous)
        assert set(ours) == set(theirs)
        for name in ours:
            assert list(ours[name].parameters) == list(theirs[name].parameters), name


def test_every_route_has_a_method_on_both():
    names = {
        "add",
        "search",
        "grep",
        "latest",
        "around",
        "open",
        "history",
        "summary",
        "facts",
        "iter_facts",
        "open_items",
        "sources",
        "items",
        "iter_items",
        "item",
        "status",
        "forget",
        "correct",
        "versions",
        "export",
        "iter_export",
        "delete",
    }
    assert names <= set(vars(User)) and names <= set(vars(AsyncUser))
    assert {"me", "user", "users", "iter_users", "close"} <= set(vars(Memory))
