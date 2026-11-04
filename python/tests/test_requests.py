"""What each method sends: the route, the headers, and a body with only what was set."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import answer, memory

from alexein import AlexeinError, Memory, __version__


def sent(call: Any, **kwargs: Any) -> tuple[str, dict[str, str], Any]:
    """The route, headers and body of the one request `call(user)` makes."""
    client, recorded = memory(answer, **kwargs)
    call(client.user("dana"))
    (request,) = recorded.requests
    return request.url.path, dict(request.headers), recorded.body()


CASES: list[tuple[Any, str, Any]] = [
    (lambda u: u.search("Where?"), "search", {"query": "Where?"}),
    (
        lambda u: u.search(
            "Where?",
            before="2026-12-01",
            after="2026-01-01",
            filters={"author": "dana"},
            provider="github",
            source="items",
            kind=["issue", "pull_request"],
            fast=True,
        ),
        "search",
        {
            "query": "Where?",
            "before": "2026-12-01",
            "after": "2026-01-01",
            "filters": {"author": "dana"},
            "provider": "github",
            "source": "items",
            "kind": ["issue", "pull_request"],
            "fast": True,
        },
    ),
    (lambda u: u.search("q", kind=("issue",)), "search", {"query": "q", "kind": ["issue"]}),
    (lambda u: u.grep("Acme"), "grep", {"pattern": "Acme"}),
    (
        lambda u: u.grep("Acme", limit=5, provider="slack", source="eng", kind="message"),
        "grep",
        {"pattern": "Acme", "limit": 5, "provider": "slack", "source": "eng", "kind": "message"},
    ),
    (lambda u: u.latest(), "latest", {}),
    (
        lambda u: u.latest(
            k=3,
            place="eng",
            after="2026-01-01",
            before="2026-02-01",
            filters={"metadata": {"p": 1}},
            provider="slack",
            source="s",
            kind=["message"],
        ),
        "latest",
        {
            "k": 3,
            "place": "eng",
            "after": "2026-01-01",
            "before": "2026-02-01",
            "filters": {"metadata": {"p": 1}},
            "provider": "slack",
            "source": "s",
            "kind": ["message"],
        },
    ),
    (lambda u: u.around("mem_e1"), "around", {"ref": "mem_e1"}),
    (lambda u: u.around("mem_e1", width=4), "around", {"ref": "mem_e1", "width": 4}),
    (lambda u: u.open("mem_f1"), "open", {"ref": "mem_f1"}),
    (lambda u: u.history("Dana"), "history", {"subject": "Dana"}),
    (
        lambda u: u.history("Dana", attribute="city"),
        "history",
        {"subject": "Dana", "attribute": "city"},
    ),
    (lambda u: u.summary(), "summary", {}),
    (lambda u: u.facts(), "facts", {}),
    (lambda u: u.facts(limit=5, cursor="cur_1"), "facts", {"limit": 5, "cursor": "cur_1"}),
    (lambda u: u.open_items(), "open_items", {}),
    (
        lambda u: u.open_items(
            kind="issue", provider="github", place="repo", mine=False, within_days=30, limit=10
        ),
        "open_items",
        {
            "kind": "issue",
            "provider": "github",
            "place": "repo",
            "mine": False,
            "within_days": 30,
            "limit": 10,
        },
    ),
    (lambda u: u.sources(), "sources", {}),
    (lambda u: u.items(), "items", {}),
    (
        lambda u: u.items(limit=2, cursor="cur_1", filters={"metadata": {"source": "crm"}}),
        "items",
        {"limit": 2, "cursor": "cur_1", "filters": {"metadata": {"source": "crm"}}},
    ),
    (lambda u: u.item("diet"), "item", {"id": "diet"}),
    (lambda u: u.status(["diet", "k:1"]), "status", {"items": ["diet", "k:1"]}),
    (lambda u: u.forget(items=["diet"]), "forget", {"items": ["diet"]}),
    (
        lambda u: u.forget(items=["a"], sessions=("s",), refs=["mem_f1"]),
        "forget",
        {"items": ["a"], "sessions": ["s"], "refs": ["mem_f1"]},
    ),
    (lambda u: u.correct("mem_f1"), "correct", {"ref": "mem_f1"}),
    (lambda u: u.correct("mem_f1", "Porto"), "correct", {"ref": "mem_f1", "replacement": "Porto"}),
    (lambda u: u.versions("diet"), "versions", {"id": "diet"}),
    (lambda u: u.export(), "export", {}),
    (lambda u: u.export(limit=100, cursor="cur_9"), "export", {"limit": 100, "cursor": "cur_9"}),
    (lambda u: u.delete(), "users/delete", {}),
]


@pytest.mark.parametrize(("call", "name", "body"), CASES)
def test_each_method_posts_its_route_with_only_what_was_set(call: Any, name: str, body: Any):
    path, headers, sent_body = sent(call)
    assert path == f"/v2/memory/{name}"
    assert sent_body == body
    assert headers["x-alexein-user"] == "dana"
    assert headers["authorization"] == "Bearer tm_test"
    assert headers["content-type"] == "application/json"
    assert headers["user-agent"] == f"alexein-python/{__version__}"
    assert "idempotency-key" not in headers


def test_add_sends_items_with_the_keyword_fields_filled_in():
    path, headers, body = sent(
        lambda u: u.add(
            [
                "I moved to Lisbon.",
                {
                    "text": "Vegetarian.",
                    "kind": "note",
                    "id": "diet",
                    "session": "own",
                    "expires": None,
                },
            ],
            wait=True,
            redact=True,
            kind="message",
            session="onboarding",
            role="user",
            author={"name": "Dana", "self": True},
            title="Chat",
            about=("project:move",),
            expires="2027-01-01",
            at="2026-10-01",
            metadata={"k": 1},
        )
    )
    assert path == "/v2/memory/add"
    assert headers["x-alexein-user"] == "dana"
    assert headers["idempotency-key"].endswith("-0")
    shared = {
        "kind": "message",
        "session": "onboarding",
        "role": "user",
        "author": {"name": "Dana", "self": True},
        "title": "Chat",
        "about": ["project:move"],
        "expires": "2027-01-01",
        "at": "2026-10-01",
        "metadata": {"k": 1},
    }
    assert body == {
        "items": [
            {**shared, "text": "I moved to Lisbon."},
            # An item's own fields win, and a null it sets is sent: it clears that field.
            {
                **shared,
                "text": "Vegetarian.",
                "kind": "note",
                "id": "diet",
                "session": "own",
                "expires": None,
            },
        ],
        "wait": True,
        "redact": True,
    }


def test_a_bare_add_sends_text_alone():
    _, _, body = sent(lambda u: u.add("Prefers green tea."))
    assert body == {"items": [{"text": "Prefers green tea."}]}


def test_an_item_without_text_fails_before_sending():
    client, recorded = memory(answer)
    with pytest.raises(ValueError, match="needs text"):
        client.user("dana").add([{"kind": "note"}])  # type: ignore[list-item]
    assert recorded.requests == []


def test_forget_naming_nothing_fails_before_sending():
    client, recorded = memory(answer)
    with pytest.raises(ValueError, match="at least one"):
        client.user("dana").forget(items=[], sessions=())
    assert recorded.requests == []


def test_me_and_users_name_no_app_user():
    client, recorded = memory(answer)
    client.me()
    client.users()
    client.users(limit=10, cursor="dana")
    me, first, _second = recorded.requests
    assert (me.method, me.url.path, me.content) == ("GET", "/v2/me", b"")
    assert (first.method, first.url.path) == ("POST", "/v2/memory/users")
    assert recorded.body(1) == {} and recorded.body(2) == {"limit": 10, "cursor": "dana"}
    assert all("x-alexein-user" not in r.headers for r in recorded.requests)


# --------------------------------------------------------------------------- settings --


@pytest.mark.parametrize(
    "given",
    [
        "http://localhost:8210",
        "http://localhost:8210/",
        "http://localhost:8210/v2",
        "http://localhost:8210/v2/",
        " http://localhost:8210// ",
    ],
)
def test_a_base_url_with_a_trailing_slash_or_v2_is_the_same_host(given: str):
    client, recorded = memory(answer, base_url=given)
    assert client.base_url == "http://localhost:8210"
    client.user("dana").summary()
    assert str(recorded.last.url) == "http://localhost:8210/v2/memory/summary"


def test_the_default_host_is_alexeins():
    client, recorded = memory(answer)
    client.me()
    assert str(recorded.last.url) == "https://api.alexein.ai/v2/me"


def test_key_and_host_come_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALEXEIN_API_KEY", "tm_env")
    monkeypatch.setenv("ALEXEIN_API_URL", "http://localhost:8210/v2")
    client = Memory()
    assert client.base_url == "http://localhost:8210"
    assert client._transport.http.headers["authorization"] == "Bearer tm_env"  # pyright: ignore[reportPrivateUsage]


def test_a_missing_key_says_where_to_get_one():
    with pytest.raises(AlexeinError, match="ALEXEIN_API_KEY") as raised:
        Memory()
    assert "console" in str(raised.value) and "API keys" in str(raised.value)


def test_an_integration_is_one_word_on_the_user_agent():
    client, recorded = memory(answer, integration="langgraph")
    client.me()
    assert recorded.last.headers["user-agent"] == f"alexein-python/{__version__} langgraph"
    for wrong in ("Lang Graph", "", "-x", "x" * 33):
        with pytest.raises(ValueError, match="integration"):
            Memory("tm_test", integration=wrong)


@pytest.mark.parametrize("user_id", ["dana", "d", "user_42", "a.b-c_d", "9" * 35])
def test_a_usable_user_id_is_taken(user_id: str):
    client, _ = memory(answer)
    assert client.user(user_id).id == user_id


@pytest.mark.parametrize(
    "user_id", ["", "-dana", ".dana", "_dana", "dana smith", "dana@example.com", "x" * 36]
)
def test_a_wrong_user_id_fails_where_it_was_named(user_id: str):
    client, recorded = memory(answer)
    with pytest.raises(ValueError, match="app user id"):
        client.user(user_id)
    assert recorded.requests == []
