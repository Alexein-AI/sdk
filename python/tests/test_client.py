"""What each method sends, and what it makes of the answer."""

from __future__ import annotations

import httpx
import pytest
from conftest import async_memory, memory, ok

from twinmemory import Memory, SearchResult, TwinMemoryError, __version__

SEARCHED = {
    "query": "Where does Dana live?",
    "found": 1,
    "known": ["Dana lives in Lisbon (since 2026-10-01)."],
    "facts": [
        {
            "path": "records/x.md",
            "id": "th_1#r1",
            "thread": "th_1",
            "source": "passages/memory/messages/th_1/p_0001.md",
            "text": "2026-10-01: Dana moved to Lisbon for a job at Acme.",
        }
    ],
    "hits": [
        {
            "path": "passages/memory/messages/th_1/p_0001.md",
            "id": "th_1/p_0001",
            "thread": "th_1",
            "text": "**Dana** 00:00 · I moved to Lisbon\nfor the job at Acme.",
        }
    ],
    "held": True,
    "filtered": True,
}


def test_a_user_call_sends_the_key_the_end_user_and_who_is_calling():
    client, sent = memory(lambda _: ok(SEARCHED))
    client.user("dana").search("Where does Dana live?")
    request = sent.last
    assert request.method == "POST"
    assert str(request.url) == "https://api.alexein.ai/v1/memory/search"
    assert request.headers["Authorization"] == "Bearer tm_test"
    assert request.headers["X-Twin-Account"] == "dana"
    assert request.headers["User-Agent"] == f"twinmemory-python/{__version__}"
    assert sent.body() == {"query": "Where does Dana live?", "fast": False}


def test_me_names_no_end_user():
    answer = {"kind": "key", "org": "o1", "project": "prod", "key_id": "key_1", "writes": True}
    client, sent = memory(lambda _: ok(answer))
    me = client.me()
    assert (me.kind, me.org, me.project, me.key_id, me.writes) == (
        "key",
        "o1",
        "prod",
        "key_1",
        True,
    )
    assert sent.last.method == "GET" and sent.last.url.path == "/v1/me"
    assert "X-Twin-Account" not in sent.last.headers


def test_the_key_and_base_url_come_from_the_environment(monkeypatch, clean_env):
    with pytest.raises(TwinMemoryError, match="TWIN_MEMORY_API_KEY"):
        Memory()
    monkeypatch.setenv("TWIN_MEMORY_API_KEY", "tm_env")
    monkeypatch.setenv("TWIN_MEMORY_BASE_URL", "https://memory.example.com/")
    client = Memory()
    assert client.base_url == "https://memory.example.com"
    assert client._http.headers["Authorization"] == "Bearer tm_env"


@pytest.mark.parametrize("bad", ["", "-dana", "dana smith", "dana/1", "x" * 65])
def test_an_unusable_end_user_id_fails_before_a_round_trip(bad):
    client, sent = memory(lambda _: ok())
    with pytest.raises(ValueError, match="end user id"):
        client.user(bad)
    assert not sent.requests


def test_a_string_is_an_item_and_keyword_fields_fill_what_an_item_leaves_out():
    client, sent = memory(lambda _: ok({"items": [], "queued": 0, "pending": 0}))
    client.user("dana").add(
        ["I moved to Lisbon.", {"text": "Booked the hotel.", "role": "assistant"}],
        role="user",
        session="trip",
        wait=True,
    )
    assert sent.body() == {
        "items": [
            {"role": "user", "session": "trip", "text": "I moved to Lisbon."},
            {"role": "assistant", "session": "trip", "text": "Booked the hotel."},
        ],
        "wait": True,
    }
    assert len(sent.last.headers["Idempotency-Key"]) > 16


def test_an_item_without_text_is_refused_before_sending():
    client, sent = memory(lambda _: ok())
    with pytest.raises(ValueError, match="text"):
        client.user("dana").add([{"id": "x"}])  # type: ignore[typeddict-item]
    with pytest.raises(ValueError, match="at least one"):
        client.user("dana").add([])
    assert not sent.requests


def test_a_long_add_goes_in_batches_of_500_and_comes_back_as_one():
    def answer(request: httpx.Request) -> httpx.Response:
        n = len(httpx.Response(200, content=request.content).json()["items"])
        items = [{"id": f"i{k}", "event_id": f"ev_{k}", "landed": False} for k in range(n)]
        return ok({"items": items, "queued": n, "pending": n}, status=202)

    client, sent = memory(answer)
    result = client.user("dana").add([f"fact {k}" for k in range(1201)])
    assert [len(sent.body(at)["items"]) for at in range(3)] == [500, 500, 201]
    keys = [r.headers["Idempotency-Key"] for r in sent.requests]
    assert len(set(keys)) == 3 and len({k.rsplit("-", 1)[0] for k in keys}) == 1
    assert (len(result.items), result.queued, result.pending) == (1201, 1201, 1201)


def test_a_search_is_read_into_typed_parts():
    client, _ = memory(lambda _: ok(SEARCHED))
    result = client.user("dana").search("Where does Dana live?", fast=True, after="2026-01-01")
    assert result.known == ["Dana lives in Lisbon (since 2026-10-01)."]
    assert result.facts[0].source == "passages/memory/messages/th_1/p_0001.md"
    assert result.hits[0].thread == "th_1"
    assert result.held is True and result.filtered is True
    assert result.raw == SEARCHED


def test_context_is_known_then_facts_then_passages_and_whole_entries_only():
    result = SearchResult.parse(SEARCHED)
    assert result.context() == (
        "What is known:\n- Dana lives in Lisbon (since 2026-10-01).\n\n"
        "Facts:\n- 2026-10-01: Dana moved to Lisbon for a job at Acme.\n\n"
        "Passages:\n- **Dana** 00:00 · I moved to Lisbon for the job at Acme."
    )
    short = result.context(max_chars=60)
    assert short == "What is known:\n- Dana lives in Lisbon (since 2026-10-01)."
    assert SearchResult.parse({"hits": []}).context() == ""


def test_every_other_method_reaches_its_route_with_its_fields():
    client, sent = memory(lambda _: ok())
    dana = client.user("dana")
    calls = [
        (lambda: dana.grep("Lisbon", limit=5), "grep", {"pattern": "Lisbon", "limit": 5}),
        (lambda: dana.read("a/b.md"), "read", {"path": "a/b.md"}),
        (lambda: dana.ls(), "ls", {"path": ""}),
        (lambda: dana.around("th_1/p_0001"), "around", {"passage_id": "th_1/p_0001", "width": 2}),
        (
            lambda: dana.history("Dana", attribute="city"),
            "history",
            {"subject": "Dana", "attribute": "city"},
        ),
        (lambda: dana.latest(k=3), "latest", {"k": 3, "place": ""}),
        (lambda: dana.overview(), "overview", {}),
        (lambda: dana.forget(items=["diet"]), "forget", {"items": ["diet"]}),
        (
            lambda: dana.correct("th_1#r1", "Porto"),
            "correct",
            {"record_id": "th_1#r1", "replacement": "Porto"},
        ),
        (lambda: dana.versions("diet"), "versions", {"id": "diet"}),
        (lambda: dana.status(["diet"]), "status", {"ids": ["diet"]}),
        (lambda: dana.lineage("diet"), "lineage", {"id": "diet"}),
    ]
    for call, route, body in calls:
        call()
        assert sent.last.url.path == f"/v1/memory/{route}", route
        assert sent.body() == body, route


def test_a_forget_naming_nothing_is_refused():
    client, _ = memory(lambda _: ok())
    with pytest.raises(ValueError, match="at least one"):
        client.user("dana").forget()


def test_a_receipt_reads_each_tables_before_and_after():
    receipt = {"events": 1, "tables": {"events": {"before": 3, "after": 2}}}
    client, _ = memory(lambda _: ok(receipt))
    got = client.user("dana").forget(items=["diet"])
    assert got.events == 1 and got.tables["events"].after == 2


@pytest.mark.anyio
async def test_the_async_client_sends_the_same_requests():
    client, sent = async_memory(lambda _: ok(SEARCHED))
    async with client:
        dana = client.user("dana")
        result = await dana.search("Where does Dana live?", fast=True)
        await dana.add("Prefers green tea.", kind="note")
    assert result.known and sent.body(0) == {"query": "Where does Dana live?", "fast": True}
    assert sent.body(1) == {
        "items": [{"kind": "note", "text": "Prefers green tea."}],
        "wait": False,
    }
    assert sent.requests[1].headers["X-Twin-Account"] == "dana"
