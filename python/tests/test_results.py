"""What each answer becomes: typed results from the JSON the v2 API sends, each keeping it in
`raw`."""

from __future__ import annotations

import conftest as api
import pytest
from conftest import answer, memory, ok

from alexein import (
    AddedItem,
    AppUser,
    Erased,
    Excerpt,
    Fact,
    FollowUp,
    ItemStatus,
    Known,
    Memories,
    OpenItem,
    SearchResult,
    Source,
    StoredItem,
    Value,
)


@pytest.fixture
def dana():
    client, _ = memory(answer)
    return client.user("dana")


def test_search(dana):
    found = dana.search("Where does Dana live?")
    assert found.query == "Where does Dana live?"
    assert found.answerable is True and found.failed is False
    assert found.notes == ["Prefer the newest of two values."]
    assert found.memories == [
        Known("Dana lives in Lisbon."),
        Fact("mem_f1", "Dana moved to Lisbon for a job at Acme.", source="mem_e1"),
        Excerpt(
            "mem_e1",
            "Dana: I moved to Lisbon for the job at Acme.",
            date="2026-10-01T09:30:00Z",
            added_at="2026-10-01T09:30:02Z",
            session="onboarding",
            roles=["user"],
        ),
    ]
    assert [m.type for m in found.memories] == ["known", "fact", "excerpt"]
    assert found.known == [found.memories[0]]
    assert found.facts == [found.memories[1]]
    assert found.excerpts == [found.memories[2]]
    assert found.refs == ["mem_f1", "mem_e1"]
    assert found.sources is None
    assert found.raw == api.SEARCHED


def test_context_is_the_same_text_every_client_writes():
    """Notes, one blank line, then `- <text>`, excerpts after their date's first 10 characters:
    pinned, because the TypeScript client and the n8n node write exactly this."""
    found = SearchResult.parse(api.SEARCHED)
    assert found.context() == (
        "Prefer the newest of two values.\n"
        "\n"
        "- Dana lives in Lisbon.\n"
        "- Dana moved to Lisbon for a job at Acme.\n"
        "- 2026-10-01: Dana: I moved to Lisbon for the job at Acme."
    )
    without_notes = SearchResult.parse({**api.SEARCHED, "notes": []})
    assert without_notes.context().startswith("- Dana lives in Lisbon.\n- Dana moved")
    undated = SearchResult.parse({"memories": [{**api.EXCERPT, "date": None}]})
    assert undated.context() == "- Dana: I moved to Lisbon for the job at Acme."


def test_context_is_cut_at_a_whole_memory():
    found = SearchResult.parse(api.SEARCHED)
    whole = found.context()
    two = (
        "Prefer the newest of two values.\n\n"
        "- Dana lives in Lisbon.\n- Dana moved to Lisbon for a job at Acme."
    )
    assert found.context(len(whole)) == whole
    assert found.context(len(whole) - 1) == two
    assert found.context(len(two)) == two
    assert found.fitting(len(two)) == found.memories[:2]
    for size in range(len(whole) + 1):
        assert len(found.context(size)) <= size


def test_context_is_empty_when_nothing_was_found_or_nothing_fits():
    assert SearchResult.parse(api.EMPTY_SEARCH).context() == ""
    assert SearchResult.parse({"notes": ["A note."], "memories": []}).context() == ""
    assert SearchResult.parse(api.SEARCHED).context(10) == ""
    assert SearchResult.unavailable("q").context() == ""


def test_an_empty_memory_searches_to_an_empty_result(dana):
    client, _ = memory(lambda r: ok(api.EMPTY_SEARCH))
    found = client.user("new").search("q")
    assert found.memories == [] and found.answerable is None and not found.failed


def test_grep_latest_around_are_iterable_memories(dana):
    grepped = dana.grep("Lisbon")
    assert isinstance(grepped, Memories)
    assert (grepped.pattern, grepped.total, len(grepped)) == ("Lisbon", 3, 1)
    assert [m.ref for m in grepped] == ["mem_e1"]
    latest = dana.latest()
    assert latest.places == ["slack", "items"] and latest.pattern is None
    assert next(iter(dana.around("mem_e1"))).session == "onboarding"


def test_open_a_fact_and_an_excerpt():
    client, _ = memory(answer)
    opened = client.user("dana").open("mem_f1")
    assert isinstance(opened.memory, Fact) and opened.memory.source == "mem_e1"
    assert [s.ref for s in opened.sources] == ["mem_e1"]
    client, _ = memory(lambda r: ok(api.OPENED_EXCERPT))
    opened = client.user("dana").open("mem_e1")
    assert isinstance(opened.memory, Excerpt) and opened.sources == []


def test_history(dana):
    history = dana.history("Dana")
    assert history.subject == "Dana" and history.suggestions is None
    assert history.values[1] == Value("city", "Lisbon", "2026-10-01", False)
    client, _ = memory(lambda r: ok(api.HISTORY_UNKNOWN))
    assert client.user("dana").history("Dna").suggestions == ["Dana"]


def test_summary_and_sources(dana):
    summary = dana.summary()
    source = Source("github", "items", "conn_1", 12, 2, "2026-10-30T08:00:00Z")
    assert (summary.items, summary.first, summary.last) == (
        14,
        "2025-01-01T00:00:00Z",
        "2026-10-30T08:00:00Z",
    )
    assert summary.sources == [source] and summary.known == ["Dana lives in Lisbon."]
    assert list(dana.sources()) == [source]


def test_an_empty_summary():
    client, _ = memory(
        lambda r: ok({"items": 0, "first": None, "last": None, "sources": [], "known": []})
    )
    summary = client.user("new").summary()
    assert (summary.items, summary.first, summary.sources, summary.known) == (0, None, [], [])


def test_pages(dana):
    facts = dana.facts()
    assert facts.next == "cur_2" and facts.facts[0].date == "2026-10-01T09:30:00Z"
    items = dana.items()
    assert items.next is None
    assert items.items[0] == StoredItem(
        id="diet",
        text="Vegetarian, allergic to peanuts.",
        status="stored",
        kind="note",
        author={"name": "Dana", "self": True},
        about=["topic:food"],
        metadata={"source": "crm"},
    )
    assert items.items[1].truncated and items.items[1].status == "queued"
    exported = dana.export()
    assert (exported.user, exported.next, exported.withheld) == ("dana", None, ["version"])
    assert [r["type"] for r in exported.records] == ["item", "fact"]


def test_item_and_an_item_memory_does_not_hold(dana):
    assert dana.item("diet").kind == "note"
    client, _ = memory(lambda r: ok(api.NO_ITEM))
    assert client.user("dana").item("nope") is None


def test_users():
    client, _ = memory(answer)
    page = client.users()
    assert page.users == [AppUser("dana", 14, 6, "2026-10-30T08:00:00Z")]
    assert page.next == "dana"


def test_open_items(dana):
    found = dana.open_items()
    assert found.items == [
        OpenItem("mem_e2", "PR #12: Fix the login page", "2026-10-28", "2026-10-28T10:00:00Z", 7)
    ]
    assert found.follow_ups == [FollowUp("Send the deck", "sam", "2026-10-20", 15)]


def test_writes(dana):
    added = dana.add("I moved to Lisbon.")
    assert added.items == [AddedItem("diet", "stored", {"PHONE": 1}), AddedItem("k:1", "queued")]
    assert added.waiting == 1 and added.ids == ["diet", "k:1"] and not added.failed
    statuses = dana.status(["diet", "nope"])
    assert statuses.items[1] == ItemStatus("nope", "unknown", "Memory holds nothing by this id.")
    assert statuses.by_id == {"diet": "processed", "nope": "unknown"}
    forgotten = dana.forget(items=["diet"])
    assert forgotten.erased == Erased(2, 3, 1, 0, 1) and forgotten.complete
    corrected = dana.correct("mem_f1", "Porto")
    assert (corrected.retracted, corrected.replacement) == ("mem_f1", "corr_1")
    versions = dana.versions("diet")
    assert versions.state == "live" and versions.history[0]["event"] == "version"
    deleted = dana.delete()
    assert deleted.user == "dana" and deleted.deleted


def test_me():
    client, _ = memory(answer)
    me = client.me()
    assert (me.kind, me.org, me.project, me.key_id, me.writes) == (
        "key",
        "o7k2m9qx4ab",
        "production",
        "key_3f9a1c2b7d4e",
        True,
    )
    assert (me.label, me.created_by, me.org_name, me.project_name, me.space) == (
        "backend",
        "dana@example.com",
        "Acme",
        "Production",
        "project",
    )
    assert me.raw == api.ME


def test_a_field_the_api_adds_later_is_in_raw():
    client, _ = memory(lambda r: ok({**api.SUMMARY, "new_field": 1}))
    assert client.user("dana").summary().raw["new_field"] == 1


def test_results_are_frozen(dana):
    found = dana.search("q")
    with pytest.raises(AttributeError):
        found.query = "other"  # type: ignore[misc]
