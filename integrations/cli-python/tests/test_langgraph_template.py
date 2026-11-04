"""The `memory.py` that `alexein-cli init langgraph` writes, run inside real LangGraph graphs
against a recorded memory API: its settings reach the client and `alexein.langgraph`, and what
it wires recalls, remembers and offers tools as the docs say."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from conftest import STRICT, Answer, answer, down, load_memory_file, ok, wrong_key

pytest.importorskip("langgraph")
pytest.importorskip("langchain")

from alexein import AlexeinError, AuthenticationError, ServiceUnavailableError
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

UNAVAILABLE = "Memory is unavailable right now; carry on without it."


def load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: Answer = answer, **given: Any
) -> tuple[ModuleType, Any]:
    return load_memory_file(tmp_path, monkeypatch, "langgraph", answer, **given)


@pytest.fixture
def generated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Any]:
    return load(tmp_path, monkeypatch)


def run(context: Any, thread_id: str | None = None) -> Any:
    """The runtime LangGraph hands a node: the run's context, and the thread it runs in."""
    return SimpleNamespace(context=context, execution_info=SimpleNamespace(thread_id=thread_id))


def graph(module: ModuleType, agent: Any, *, asynchronous: bool = False) -> Any:
    memory = module.memory
    builder = StateGraph(module.MemoryState, context_schema=module.MemoryContext)
    builder.add_node("recall", memory.arecall if asynchronous else memory.recall)
    builder.add_node("agent", agent)
    builder.add_node("remember", memory.aremember if asynchronous else memory.remember)
    builder.add_edge(START, "recall")
    builder.add_edge("recall", "agent")
    builder.add_edge("agent", "remember")
    builder.add_edge("remember", END)
    return builder.compile(checkpointer=InMemorySaver())


CALLS = [
    {"name": "memory_search", "args": {"query": "home"}, "id": "c1"},
    {"name": "memory_open", "args": {"ref": "mem_e1"}, "id": "c2"},
    {"name": "memory_add", "args": {"text": "Prefers trains."}, "id": "c3"},
]


def tools_graph(module: ModuleType, state: Any = None) -> Any:
    """A model that calls every tool once, then the tools."""
    builder = StateGraph(state or module.MemoryState, context_schema=module.MemoryContext)

    def agent(state: Any) -> dict[str, Any]:
        return {"messages": [AIMessage("", tool_calls=CALLS)]}

    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(module.memory.tools(write=True)))
    builder.add_edge(START, "agent")
    builder.add_edge("agent", "tools")
    builder.add_edge("tools", END)
    return builder.compile()


def results(out: dict[str, Any]) -> dict[str, str]:
    return {m.tool_call_id: m.content for m in out["messages"][-3:]}


# --------------------------------------------------------------------------- the file --


def test_the_settings_reach_the_client_and_the_memory(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    memory = module.memory
    assert (memory.fast, memory.max_chars, memory.strict) == (False, 4000, False)
    assert memory.timeout == module.TIMEOUT
    state = {"messages": [HumanMessage("hi")]}
    memory.recall(state, runtime=run({"user_id": "dana"}))
    assert recorded.timeouts == [module.TIMEOUT]  # the client, made on first use
    assert recorded.last.headers["user-agent"].endswith(" langgraph")
    assert recorded.last.headers["authorization"] == "Bearer tm_test"


def test_fast_and_max_chars_as_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, recorded = load(
        tmp_path, monkeypatch, fast=True, edits={"MAX_CHARS = 4000": "MAX_CHARS = 30"}
    )
    state = {"messages": [HumanMessage("hi")]}
    found = module.memory.recall(state, runtime=run({"user_id": "dana"}))
    assert found == {"memory": "- Dana lives in Lisbon."}  # the first memory alone fits in 30
    assert recorded.body() == {"query": "hi", "fast": True}


def test_importing_needs_no_key_and_the_first_call_says_how_to_set_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing the file - building the graph - needs no key: the client is made on the
    first call, which names the variable when there is none."""
    module, recorded = load(tmp_path, monkeypatch, key=None)
    state = {"messages": [HumanMessage("hi")]}
    with pytest.raises(ValueError, match="whose memory"):  # first, before the key
        module.memory.recall(state, runtime=run(None))
    with pytest.raises(AlexeinError, match="ALEXEIN_API_KEY"):
        module.memory.recall(state, runtime=run({"user_id": "dana"}))
    assert recorded.requests == []


# ----------------------------------------------------------------------- the nodes --


def test_a_turn_is_recalled_before_the_model_and_saved_after(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    prompts: list[str] = []

    def agent(state: Any) -> dict[str, Any]:
        prompts.append(module.memory.prompt(state))
        return {"messages": [AIMessage("You live in Lisbon.", id="ai-1")]}

    out = graph(module, agent).invoke(
        {"messages": [HumanMessage("Where do I live?", id="h-1")]},
        config={"configurable": {"thread_id": "t-1"}},
        context={"user_id": "dana"},
    )

    assert recorded.routes() == ["search", "add"]
    assert recorded.users() == {"dana"}
    assert recorded.bodies("search") == [{"query": "Where do I live?"}]
    assert "Dana lives in Lisbon." in out["memory"]
    assert prompts[0].startswith("What you remember about this user")
    assert recorded.bodies("add")[0]["items"] == [
        {"session": "t-1", "id": "h-1", "role": "user", "text": "Where do I live?"},
        {"session": "t-1", "id": "ai-1", "role": "assistant", "text": "You live in Lisbon."},
    ]


def test_a_user_with_no_memory_yet_recalls_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _ = load(tmp_path, monkeypatch, lambda r: ok({"detail": "no memory"}, status=404))
    state = {"messages": [HumanMessage("hi")]}
    assert module.memory.recall(state, runtime=run({"user_id": "new"})) == {"memory": ""}
    assert module.memory.prompt({"messages": [], "memory": ""}) == ""


def test_a_run_with_no_user_says_so(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    with pytest.raises(ValueError, match="whose memory"):
        module.memory.recall({"messages": [HumanMessage("hi")]}, runtime=run(None))
    assert recorded.requests == []


def test_tool_calls_and_tool_results_are_not_saved(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    state = {
        "messages": [
            HumanMessage("Book it", id="h-1"),
            AIMessage("", id="ai-1", tool_calls=[{"name": "book", "args": {}, "id": "c1"}]),
            AIMessage("Booked.", id="ai-2"),
        ]
    }
    module.memory.remember(state, runtime=run({"user_id": "dana"}, thread_id="t-1"))
    assert [i["id"] for i in recorded.body()["items"]] == ["h-1", "ai-2"]


def test_a_long_message_is_searched_by_its_end(generated: tuple[ModuleType, Any]) -> None:
    """The service takes a question of at most 2,000 characters; a pasted email is longer."""
    module, recorded = generated
    asked = "x" * 2500 + " Where do I live?"
    module.memory.recall({"messages": [HumanMessage(asked)]}, runtime=run({"user_id": "dana"}))
    query = recorded.body(0)["query"]
    assert len(query) == 2000 and query.endswith("Where do I live?")


# ----------------------------------------------------------------------- the tools --


def test_tools_read_the_user_from_the_run_never_from_the_model(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    for each in module.memory.tools(write=True):
        assert "runtime" not in each.tool_call_schema.model_json_schema()["properties"]

    out = tools_graph(module).invoke(
        {"messages": [HumanMessage("x")]},
        config={"configurable": {"thread_id": "t-9"}},
        context={"user_id": "dana"},
    )

    assert recorded.users() == {"dana"}
    told = results(out)
    assert "Dana lives in Lisbon." in told["c1"] and "memory_open" in told["c1"]
    assert told["c2"] == "2026-10-01: Dana: I moved to Lisbon."
    assert told["c3"] == "Saved."
    assert recorded.bodies("add")[0]["items"] == [
        {"kind": "note", "session": "t-9", "text": "Prefers trains."}
    ]


def test_tools_need_no_memory_state(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    out = tools_graph(module, MessagesState).invoke(
        {"messages": [HumanMessage("x")]}, context={"user_id": "dana"}
    )
    assert recorded.users() == {"dana"}
    assert out["messages"][-1].content == "Saved."


def test_the_model_is_offered_only_the_reading_tools_by_default(
    generated: tuple[ModuleType, Any],
) -> None:
    module, _ = generated
    assert [t.name for t in module.memory.tools()] == ["memory_search", "memory_open"]


# ----------------------------------------------------------------- memory being down --


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
    assert list(results(out).values()) == [UNAVAILABLE] * 3


def test_strict_as_written_raises_instead(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _ = load(tmp_path, monkeypatch, down, edits=STRICT)
    assert module.memory.strict is True
    with pytest.raises(ServiceUnavailableError):
        module.memory.recall({"messages": [HumanMessage("hi")]}, runtime=run({"user_id": "d"}))


def test_a_wrong_key_raises_even_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _ = load(tmp_path, monkeypatch, wrong_key)
    with pytest.raises(AuthenticationError):
        module.memory.recall({"messages": [HumanMessage("hi")]}, runtime=run({"user_id": "d"}))
    with pytest.raises(AuthenticationError):
        tools_graph(module).invoke({"messages": [HumanMessage("x")]}, context={"user_id": "d"})


# -------------------------------------------------------------------------- async --


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True], ids=["nodes", "anodes"])
async def test_the_file_runs_under_ainvoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asynchronous: bool
) -> None:
    """With the `Memory` the file makes, `recall` and `remember` - and their async
    counterparts - run under ainvoke, and so do the tools."""
    module, recorded = load(tmp_path, monkeypatch)

    async def agent(state: Any) -> dict[str, Any]:
        assert "Dana lives in Lisbon." in module.memory.prompt(state)
        return {"messages": [AIMessage("You live in Lisbon.", id="ai-1")]}

    out = await graph(module, agent, asynchronous=asynchronous).ainvoke(
        {"messages": [HumanMessage("Where do I live?", id="h-1")]},
        config={"configurable": {"thread_id": "t-1"}},
        context={"user_id": "dana"},
    )
    assert "Dana lives in Lisbon." in out["memory"]
    assert recorded.routes() == ["search", "add"]

    tools = await tools_graph(module).ainvoke(
        {"messages": [HumanMessage("x")]},
        config={"configurable": {"thread_id": "t-9"}},
        context={"user_id": "dana"},
    )
    assert results(tools)["c3"] == "Saved."
