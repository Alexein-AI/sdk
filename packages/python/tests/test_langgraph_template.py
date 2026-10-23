"""The `memory.py` that `twinmemory-cli init langgraph` writes, run inside a real LangGraph graph
against a recorded memory API."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from conftest import Answer, answer, load_memory_file, memory, ok

pytest.importorskip("langgraph")
pytest.importorskip("langchain")

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from twinmemory import AuthenticationError, ServiceUnavailableError


def load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: Answer,
    *,
    asynchronous: bool = False,
    parts: tuple[str, ...] = ("nodes", "tools"),
) -> tuple[ModuleType, Any]:
    template = "memory_async.py.tmpl" if asynchronous else "memory.py.tmpl"
    return load_memory_file(
        tmp_path,
        monkeypatch,
        f"langgraph/{template}",
        answer,
        parts=parts,
        integration="langgraph",
        asynchronous=asynchronous,
    )


@pytest.fixture
def generated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Any]:
    return load(tmp_path, monkeypatch, answer)


def graph(module: ModuleType, agent: Any) -> Any:
    builder = StateGraph(module.MemoryState, context_schema=module.MemoryContext)
    builder.add_node("recall", module.recall)
    builder.add_node("agent", agent)
    builder.add_node("remember", module.remember)
    builder.add_edge(START, "recall")
    builder.add_edge("recall", "agent")
    builder.add_edge("agent", "remember")
    builder.add_edge("remember", END)
    return builder.compile(checkpointer=InMemorySaver())


CALLS = [
    {"name": "memory_search", "args": {"query": "home"}, "id": "c1"},
    {"name": "memory_read", "args": {"path": "passages/p1.md"}, "id": "c2"},
    {"name": "memory_add", "args": {"text": "Prefers trains."}, "id": "c3"},
]


def tools_graph(module: ModuleType, state: Any = None) -> Any:
    """A model that calls every tool once, then the tools."""
    builder = StateGraph(state or module.MemoryState, context_schema=module.MemoryContext)

    def agent(state: Any) -> dict[str, Any]:
        return {"messages": [AIMessage("", tool_calls=CALLS)]}

    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(module.MEMORY_WRITE_TOOLS))
    builder.add_edge(START, "agent")
    builder.add_edge("agent", "tools")
    builder.add_edge("tools", END)
    return builder.compile()


def test_a_turn_is_recalled_before_the_model_and_saved_after(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    prompts: list[str] = []

    def agent(state: Any) -> dict[str, Any]:
        prompts.append(module.memory_prompt(state))
        return {"messages": [AIMessage("You live in Lisbon.", id="ai-1")]}

    out = graph(module, agent).invoke(
        {"messages": [HumanMessage("Where do I live?", id="h-1")]},
        config={"configurable": {"thread_id": "t-1"}},
        context={"user_id": "dana"},
    )

    search, add = recorded.requests
    assert search.url.path == "/v1/memory/search"
    assert search.headers["X-Twin-Account"] == "dana"
    assert json.loads(search.content)["query"] == "Where do I live?"
    assert "Dana lives in Lisbon." in out["memory"]
    assert "Dana lives in Lisbon." in prompts[0]

    assert add.headers["X-Twin-Account"] == "dana"
    assert json.loads(add.content)["items"] == [
        {"session": "t-1", "id": "h-1", "role": "user", "text": "Where do I live?"},
        {"session": "t-1", "id": "ai-1", "role": "assistant", "text": "You live in Lisbon."},
    ]


def test_a_user_with_no_memory_yet_recalls_nothing(generated: tuple[ModuleType, Any]) -> None:
    module, _ = generated
    client, _ = memory(lambda r: ok({"detail": "no memory"}, status=404))
    module._memory = lambda: client  # type: ignore[attr-defined]
    state = {"messages": [HumanMessage("hi")]}
    runtime = type("R", (), {"context": {"user_id": "new"}})()

    assert module.recall(state, runtime, {"configurable": {}}) == {"memory": ""}
    assert module.memory_prompt({"messages": [], "memory": ""}) == ""


def test_the_user_id_can_come_from_config_and_must_come_from_somewhere(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    state = {"messages": [HumanMessage("hi")]}
    no_context = type("R", (), {"context": None})()

    module.recall(state, no_context, {"configurable": {"user_id": "sam"}})
    assert recorded.last.headers["X-Twin-Account"] == "sam"

    with pytest.raises(ValueError, match="whose memory"):
        module.recall(state, no_context, {"configurable": {}})


def test_tool_calls_and_tool_results_are_not_saved(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    state = {
        "messages": [
            HumanMessage("Book it", id="h-1"),
            AIMessage("", id="ai-1", tool_calls=[{"name": "book", "args": {}, "id": "c1"}]),
            AIMessage("Booked.", id="ai-2"),
        ]
    }
    runtime = type("R", (), {"context": {"user_id": "dana"}})()

    module.remember(state, runtime, {"configurable": {"thread_id": "t-1"}})

    items = json.loads(recorded.last.content)["items"]
    assert [i["id"] for i in items] == ["h-1", "ai-2"]


def test_tools_read_the_user_from_the_run_never_from_the_model(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    for each in module.MEMORY_WRITE_TOOLS:
        assert "runtime" not in each.tool_call_schema.model_json_schema()["properties"]

    out = tools_graph(module).invoke(
        {"messages": [HumanMessage("x")]},
        config={"configurable": {"thread_id": "t-9"}},
        context={"user_id": "dana"},
    )

    assert {r.headers["X-Twin-Account"] for r in recorded.requests} == {"dana"}
    results = {m.tool_call_id: m.content for m in out["messages"][-3:]}
    assert "Dana lives in Lisbon." in results["c1"]
    assert results["c1"].endswith("To read one whole, memory_read:\n- passages/p1.md")
    assert results["c2"] == "Dana: I moved to Lisbon."
    assert results["c3"] == "Saved."
    added = next(r for r in recorded.requests if r.url.path.endswith("/add"))
    assert json.loads(added.content)["items"] == [
        {"kind": "note", "session": "t-9", "text": "Prefers trains."}
    ]


# ----------------------------------------------------------------------- memory being down --


def down(request: httpx.Request) -> httpx.Response:
    return ok({"detail": "rebuilding"}, status=503)


def test_a_turn_goes_ahead_when_memory_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    module, _ = load(tmp_path, monkeypatch, down)

    def agent(state: Any) -> dict[str, Any]:
        return {"messages": [AIMessage("Still here.", id="ai-1")]}

    out = graph(module, agent).invoke(
        {"messages": [HumanMessage("hi", id="h-1")]},
        config={"configurable": {"thread_id": "t-1"}},
        context={"user_id": "dana"},
    )

    assert out["memory"] == "" and out["messages"][-1].text == "Still here."
    assert any("unavailable" in r.message for r in caplog.records)


def test_tools_tell_the_model_memory_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _ = load(tmp_path, monkeypatch, down)
    out = tools_graph(module).invoke(
        {"messages": [HumanMessage("x")]},
        config={"configurable": {"thread_id": "t-9"}},
        context={"user_id": "dana"},
    )
    results = [m.content for m in out["messages"][-3:]]
    assert results == [module.UNAVAILABLE] * 3


def test_strict_raises_instead(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _ = load(tmp_path, monkeypatch, down)
    client, _ = memory(down, fail_open=False)
    monkeypatch.setattr(module, "_memory", lambda: client)
    monkeypatch.setattr(module, "STRICT", True)
    runtime = type("R", (), {"context": {"user_id": "dana"}})()
    with pytest.raises(ServiceUnavailableError):
        module.recall({"messages": [HumanMessage("hi")]}, runtime, {"configurable": {}})


def test_a_wrong_key_raises_even_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _ = load(tmp_path, monkeypatch, lambda r: ok({"detail": "bad key"}, status=401))
    runtime = type("R", (), {"context": {"user_id": "dana"}})()
    with pytest.raises(AuthenticationError):
        module.recall({"messages": [HumanMessage("hi")]}, runtime, {"configurable": {}})
    with pytest.raises(AuthenticationError):
        tools_graph(module).invoke({"messages": [HumanMessage("x")]}, context={"user_id": "dana"})


def test_a_long_message_is_searched_by_its_end(generated: tuple[ModuleType, Any]) -> None:
    """The service takes a question of at most 2,000 characters; a pasted email is longer."""
    module, recorded = generated
    runtime = type("R", (), {"context": {"user_id": "dana"}})()
    asked = "x" * 2500 + " Where do I live?"
    module.recall({"messages": [HumanMessage(asked)]}, runtime, {"configurable": {}})
    query = recorded.body(0)["query"]
    assert len(query) == 2000 and query.endswith("Where do I live?")


def test_requests_say_they_came_from_langgraph(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    runtime = type("R", (), {"context": {"user_id": "dana"}})()
    module.recall({"messages": [HumanMessage("hi")]}, runtime, {"configurable": {}})
    assert recorded.last.headers["User-Agent"].endswith(" langgraph")


# ------------------------------------------------------------------------- presets, async --


@pytest.mark.anyio
async def test_the_async_file_runs_under_ainvoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, recorded = load(tmp_path, monkeypatch, answer, asynchronous=True)

    async def agent(state: Any) -> dict[str, Any]:
        assert "Dana lives in Lisbon." in module.memory_prompt(state)
        return {"messages": [AIMessage("You live in Lisbon.", id="ai-1")]}

    out = await graph(module, agent).ainvoke(
        {"messages": [HumanMessage("Where do I live?", id="h-1")]},
        config={"configurable": {"thread_id": "t-1"}},
        context={"user_id": "dana"},
    )
    assert "Dana lives in Lisbon." in out["memory"]
    assert [r.url.path.rsplit("/", 1)[-1] for r in recorded.requests] == ["search", "add"]

    tools = await tools_graph(module).ainvoke(
        {"messages": [HumanMessage("x")]},
        config={"configurable": {"thread_id": "t-9"}},
        context={"user_id": "dana"},
    )
    results = {m.tool_call_id: m.content for m in tools["messages"][-3:]}
    assert results["c3"] == "Saved." and results["c2"] == "Dana: I moved to Lisbon."


@pytest.mark.anyio
async def test_the_async_file_fails_open_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _ = load(tmp_path, monkeypatch, down, asynchronous=True)
    runtime = type("R", (), {"context": {"user_id": "dana"}})()
    state = {"messages": [HumanMessage("hi"), AIMessage("hello")]}
    assert await module.recall(state, runtime, {"configurable": {}}) == {"memory": ""}
    assert await module.remember(state, runtime, {"configurable": {}}) == {}


def test_tools_only_needs_no_memory_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, recorded = load(tmp_path, monkeypatch, answer, parts=("tools",))
    assert not hasattr(module, "recall") and not hasattr(module, "MemoryState")
    out = tools_graph(module, MessagesState).invoke(
        {"messages": [HumanMessage("x")]}, context={"user_id": "dana"}
    )
    assert {r.headers["X-Twin-Account"] for r in recorded.requests} == {"dana"}
    assert out["messages"][-1].content == "Saved."


def test_nodes_only_has_no_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _ = load(tmp_path, monkeypatch, answer, parts=("nodes",))
    assert hasattr(module, "recall") and not hasattr(module, "MEMORY_TOOLS")
