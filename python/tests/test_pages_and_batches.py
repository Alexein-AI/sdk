"""Pagination iterators, and adds of more than 500 items, each batch with its own idempotency key
that a retry repeats."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest
from conftest import async_memory, memory, ok


def paged(key: str, pages: list[list[Any]]):
    """Answers page n for cursor `cur_n`, with `next` until the last."""

    def page(request: httpx.Request) -> httpx.Response:
        cursor = json.loads(request.content).get("cursor")
        at = int(cursor.removeprefix("cur_")) if cursor else 0
        later = f"cur_{at + 1}" if at + 1 < len(pages) else None
        return ok({key: pages[at], "next": later, "user": "dana", "exported_at": "t"})

    return page


def fact(n: int) -> dict[str, Any]:
    return {"type": "fact", "ref": f"mem_{n}", "text": f"fact {n}", "source": None}


def test_iter_facts_follows_next_until_it_is_null():
    client, recorded = memory(paged("facts", [[fact(1), fact(2)], [fact(3)], []]))
    refs = [f.ref for f in client.user("dana").iter_facts(limit=2)]
    assert refs == ["mem_1", "mem_2", "mem_3"]
    assert recorded.bodies("facts") == [
        {"limit": 2},
        {"limit": 2, "cursor": "cur_1"},
        {"limit": 2, "cursor": "cur_2"},
    ]


def test_iter_items_keeps_its_filters_on_every_page():
    pages = [[{"id": "a", "text": "A", "status": "stored"}], [{"id": "b", "text": "B"}]]
    client, recorded = memory(paged("items", pages))
    found = client.user("dana").iter_items(filters={"metadata": {"source": "crm"}})
    assert [i.id for i in found] == ["a", "b"]
    assert all(b["filters"] == {"metadata": {"source": "crm"}} for b in recorded.bodies("items"))


def test_iter_export_and_iter_users():
    client, _ = memory(paged("records", [[{"type": "item"}], [{"type": "fact"}]]))
    assert [r["type"] for r in client.user("dana").iter_export()] == ["item", "fact"]
    client, recorded = memory(paged("users", [[{"user": "ann"}], [{"user": "ben"}]]))
    assert [u.user for u in client.iter_users(limit=1)] == ["ann", "ben"]
    assert all("x-alexein-user" not in r.headers for r in recorded.requests)


def test_iterating_is_lazy():
    client, recorded = memory(paged("facts", [[fact(1)], [fact(2)]]))
    first = next(iter(client.user("dana").iter_facts()))
    assert first.ref == "mem_1" and len(recorded.requests) == 1


@pytest.mark.anyio
async def test_the_async_iterators():
    client, _ = async_memory(paged("facts", [[fact(1)], [fact(2)]]))
    assert [f.ref async for f in client.user("dana").iter_facts()] == ["mem_1", "mem_2"]
    client, _ = async_memory(paged("items", [[{"id": "a", "text": "A"}], [{"id": "b"}]]))
    assert [i.id async for i in client.user("dana").iter_items()] == ["a", "b"]
    client, _ = async_memory(paged("records", [[{"type": "item"}]]))
    assert [r["type"] async for r in client.user("dana").iter_export()] == ["item"]
    client, _ = async_memory(paged("users", [[{"user": "ann"}], [{"user": "ben"}]]))
    assert [u.user async for u in client.iter_users()] == ["ann", "ben"]


# ------------------------------------------------------------------------------ batches --


def took(request: httpx.Request) -> httpx.Response:
    items = json.loads(request.content)["items"]
    return ok(
        {"items": [{"id": i["text"], "status": "queued"} for i in items], "waiting": len(items)},
        status=202,
    )


def test_more_than_500_items_go_in_batches_of_500_and_merge():
    client, recorded = memory(took)
    added = client.user("dana").add([f"note {n}" for n in range(1201)], session="s")
    sizes = [len(b["items"]) for b in recorded.bodies("add")]
    assert sizes == [500, 500, 201]
    assert added.waiting == 1201 and len(added.items) == 1201
    assert added.ids[0] == "note 0" and added.ids[-1] == "note 1200"
    assert all(i["session"] == "s" for b in recorded.bodies("add") for i in b["items"])
    assert len(added.raw["batches"]) == 3


def test_each_batch_has_one_calls_uuid_and_its_index():
    client, recorded = memory(took)
    client.user("dana").add(["x"] * 1001)
    keys = [r.headers["idempotency-key"] for r in recorded.requests]
    uuid4 = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
    assert all(re.fullmatch(f"{uuid4}-[0-2]", k) for k in keys), keys
    assert len({k.rsplit("-", 1)[0] for k in keys}) == 1
    assert [k.rsplit("-", 1)[1] for k in keys] == ["0", "1", "2"]
    client.user("dana").add("again")
    assert recorded.last.headers["idempotency-key"].rsplit("-", 1)[0] != keys[0].rsplit("-", 1)[0]


def test_a_retried_batch_sends_the_same_key():
    answers = iter([ok({"detail": "busy"}, 503), ok({"items": [], "waiting": 0}, 202)])
    client, recorded = memory(lambda r: next(answers))
    client.user("dana").add("x")
    first, second = recorded.requests
    assert first.headers["idempotency-key"] == second.headers["idempotency-key"]
    assert first.content == second.content


def test_an_empty_list_sends_nothing():
    client, recorded = memory(took)
    added = client.user("dana").add([])
    assert added.items == [] and added.waiting == 0 and not added.failed
    assert recorded.requests == []


@pytest.mark.anyio
async def test_the_async_client_batches_too():
    client, recorded = async_memory(took)
    added = await client.user("dana").add([f"n{n}" for n in range(501)])
    assert [len(b["items"]) for b in recorded.bodies("add")] == [500, 1]
    assert len(added.items) == 501
