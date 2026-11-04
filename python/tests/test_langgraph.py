"""`alexein.langgraph`, run inside real LangGraph graphs against a recorded memory API."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from conftest import EMPTY_SEARCH, answer, async_memory, memory, ok

pytest.importorskip("langgraph")
pytest.importorskip("langchain")

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel

import alexein.langgraph as lg
from alexein import AuthenticationError, ServiceUnavailableError
from alexein._integration import NOTHING_FOUND, NOTHING_YET, UNAVAILABLE


def run(context: Any, thread_id: str | None = None) -> Any:
    """The runtime LangGraph hands a node: the run's context, and its thread."""
    return SimpleNamespace(context=context, execution_info=SimpleNamespace(thread_id=thread_id))


def down(request: httpx.Request) -> httpx.Response:
    return ok({"detail": "rebuilding"}, status=503)


def wired(answer_with: Any = answer, **kwargs: Any) -> tuple[lg.AlexeinMemory, Any]:
    strict = kwargs.pop("strict", False)
    client, recorded = memory(answer_with, fail_open=not strict, integration="langgraph")
    return lg.AlexeinMemory(client, strict=strict, **kwargs), recorded


def graph(mem: lg.AlexeinMemory, agent: Any, *, asynchronous: bool = False) -> Any:
    builder = StateGraph(lg.MemoryState, context_schema=lg.MemoryContext)
    builder.add_node("recall", mem.arecall if asynchronous else mem.recall)
    builder.add_node("agent", agent)
    builder.add_node("remember", mem.aremember if asynchronous else mem.remember)
    builder.add_edge(START, "recall")
    builder.add_edge("recall", "agent")
    builder.add_edge("agent", "remember")
    builder.add_edge("remember", END)
    return builder.compile(checkpointer=InMemorySaver())


CALLS = [
    {"name": "memory_search", "args": {"query": "home"}, "id": "c1"},
    {"name": "memory_open", "args": {"ref": "mem_f1"}, "id": "c2"},
    {"name": "memory_add", "args": {"text": "Prefers trains."}, "id": "c3"},
]


def tools_graph(tools: list[Any], state: Any = None) -> Any:
    """A model that calls every tool once, then the tools."""
    builder = StateGraph(state or lg.MemoryState, context_schema=lg.MemoryContext)
    builder.add_node("agent", lambda state: {"messages": [AIMessage("", tool_calls=CALLS)]})
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_edge("agent", "tools")
    builder.add_edge("tools", END)
    return builder.compile()


def results(out: dict[str, Any]) -> dict[str, str]:
    return {m.tool_call_id: m.content for m in out["messages"][-3:]}


def test_a_turn_is_recalled_before_the_model_and_saved_after():
    mem, recorded = wired()
    prompts: list[str] = []

    def agent(state: Any) -> dict[str, Any]:
        prompts.append(mem.prompt(state))
        return {"messages": [AIMessage("You live in Lisbon.", id="ai-1")]}

    out = graph(mem, agent).invoke(
        {"messages": [HumanMessage("Where do I live?", id="h-1")]},
        config={"configurable": {"thread_id": "t-1"}},
        context={"user_id": "dana"},
    )

    search, add = recorded.requests
    assert search.url.path == "/v2/memory/search" and search.headers["x-alexein-user"] == "dana"
    assert json.loads(search.content) == {"query": "Where do I live?"}
    assert out["memory"].endswith("- 2026-10-01: Dana: I moved to Lisbon for the job at Acme.")
    assert prompts[0].startswith("What you remember about this user")
    assert "- Dana lives in Lisbon." in prompts[0]
    assert add.headers["x-alexein-user"] == "dana"
    assert json.loads(add.content)["items"] == [
        {"session": "t-1", "id": "h-1", "role": "user", "text": "Where do I live?"},
        {"session": "t-1", "id": "ai-1", "role": "assistant", "text": "You live in Lisbon."},
    ]


def test_a_turn_run_again_saves_under_the_same_ids():
    mem, recorded = wired()
    state = {"messages": [HumanMessage("Hi"), AIMessage("Hello.")]}
    mem.remember(state, runtime=run({"user_id": "dana"}, thread_id="t-1"))  # type: ignore[arg-type]
    mem.remember(state, runtime=run({"user_id": "dana"}, thread_id="t-1"))  # type: ignore[arg-type]
    first, second = recorded.bodies("add")
    assert first == second and len(first["items"][0]["id"]) == 24


def test_fast_and_max_chars():
    mem, recorded = wired(fast=True, max_chars=30)
    found = mem.recall({"messages": [HumanMessage("hi")]}, runtime=run({"user_id": "d"}))  # type: ignore[arg-type]
    assert recorded.body() == {"query": "hi", "fast": True}
    assert found == {"memory": ""}  # notes and the first memory are longer than 30


def test_a_user_with_no_memory_yet_recalls_nothing():
    mem, _ = wired(lambda r: ok(EMPTY_SEARCH))
    state = {"messages": [HumanMessage("hi")]}
    assert mem.recall(state, runtime=run({"user_id": "new"})) == {"memory": ""}  # type: ignore[arg-type]
    assert mem.prompt({"messages": [], "memory": ""}) == ""


def test_the_user_id_comes_from_the_context_and_must_come():
    mem, recorded = wired()
    state = {"messages": [HumanMessage("hi")]}
    mem.recall(state, runtime=run(SimpleNamespace(user_id="ann")))  # type: ignore[arg-type]
    assert recorded.last.headers["x-alexein-user"] == "ann"
    with pytest.raises(ValueError, match="whose memory"):
        mem.recall(state, runtime=run(None))  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_a_run_with_no_user_says_so_before_anything_else():
    """Even with no key set: whose memory is the first thing a run must say."""
    state = {"messages": [HumanMessage("hi")]}
    with pytest.raises(ValueError, match="whose memory"):
        lg.recall(state, runtime=run(None))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="whose memory"):
        await lg.arecall(state, runtime=run(None))  # type: ignore[arg-type]


def test_tool_calls_and_tool_results_are_not_saved():
    mem, recorded = wired()
    state = {
        "messages": [
            HumanMessage("Hi", id="h-0"),
            AIMessage("Hello.", id="ai-0"),
            HumanMessage("Book it", id="h-1"),
            AIMessage("", id="ai-1", tool_calls=[{"name": "book", "args": {}, "id": "c1"}]),
            AIMessage("Booked.", id="ai-2"),
        ]
    }
    mem.remember(state, runtime=run({"user_id": "dana"}, thread_id="t"))  # type: ignore[arg-type]
    assert [i["id"] for i in recorded.body()["items"]] == ["h-1", "ai-2"]


def test_a_turn_without_a_reply_yet_saves_only_the_question():
    mem, recorded = wired()
    state = {"messages": [AIMessage("Old.", id="ai-0"), HumanMessage("New?", id="h-1")]}
    mem.remember(state, runtime=run({"user_id": "dana"}))  # type: ignore[arg-type]
    assert [i["id"] for i in recorded.body()["items"]] == ["h-1"]


def test_tools_read_the_user_from_the_run_never_from_the_model():
    mem, recorded = wired()
    tools = mem.tools(write=True)
    assert [t.name for t in tools] == ["memory_search", "memory_open", "memory_add"]
    assert [t.name for t in mem.tools()] == ["memory_search", "memory_open"]
    for each in tools:
        schema = cast("type[BaseModel]", each.tool_call_schema).model_json_schema()
        assert list(schema["properties"]) in (["query"], ["ref"], ["text"])  # never the run

    out = tools_graph(tools).invoke(
        {"messages": [HumanMessage("x")]},
        config={"configurable": {"thread_id": "t-9"}},
        context={"user_id": "dana"},
    )

    assert {r.headers["x-alexein-user"] for r in recorded.requests} == {"dana"}
    told = results(out)
    assert "- Dana lives in Lisbon." in told["c1"]
    assert told["c1"].endswith("To read one whole, memory_open:\n- mem_f1\n- mem_e1")
    assert told["c2"] == (
        "Dana moved to Lisbon for a job at Acme.\n\nLearned from:\n\n"
        "2026-10-01: Dana: I moved to Lisbon for the job at Acme."
    )
    assert told["c3"] == "Saved."
    assert recorded.bodies("open") == [{"ref": "mem_f1"}]
    assert recorded.bodies("add")[0]["items"] == [
        {"kind": "note", "session": "t-9", "text": "Prefers trains."}
    ]


def test_tools_say_when_nothing_is_held():
    def none(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("search"):
            return ok(EMPTY_SEARCH)
        if request.url.path.endswith("open"):
            return ok({"detail": "no memory for app user 'dana' yet"}, status=404)
        return answer(request)

    mem, _ = wired(none)
    told = results(
        tools_graph(mem.tools(write=True)).invoke({"messages": []}, context={"user_id": "dana"})
    )
    assert (told["c1"], told["c2"]) == (NOTHING_FOUND, NOTHING_YET)


def test_a_ref_memory_did_not_give_is_said_so():
    mem, _ = wired(lambda r: ok({"detail": "memory holds nothing by this ref"}, status=404))
    out = tools_graph(mem.tools()).invoke({"messages": []}, context={"user_id": "dana"})
    assert "nothing by that ref" in results(out)["c2"]


# ----------------------------------------------------------------------- memory being down --


def test_a_turn_goes_ahead_when_memory_is_down(caplog: pytest.LogCaptureFixture):
    mem, _ = wired(down)
    out = graph(mem, lambda state: {"messages": [AIMessage("Still here.", id="ai-1")]}).invoke(
        {"messages": [HumanMessage("hi", id="h-1")]},
        config={"configurable": {"thread_id": "t-1"}},
        context={"user_id": "dana"},
    )
    assert out["memory"] == "" and out["messages"][-1].text == "Still here."
    assert any("unavailable" in r.message for r in caplog.records)


def test_a_client_that_does_not_fail_open_is_ridden_out_too():
    client, _ = memory(down)
    mem = lg.AlexeinMemory(client)
    state = {"messages": [HumanMessage("hi"), AIMessage("hello")]}
    assert mem.recall(state, runtime=run({"user_id": "d"})) == {"memory": ""}  # type: ignore[arg-type]
    assert mem.remember(state, runtime=run({"user_id": "d"})) == {}  # type: ignore[arg-type]
    out = tools_graph(mem.tools(write=True)).invoke({"messages": []}, context={"user_id": "d"})
    assert set(results(out).values()) == {UNAVAILABLE}


def test_tools_tell_the_model_memory_is_down():
    mem, _ = wired(down)
    out = tools_graph(mem.tools(write=True)).invoke(
        {"messages": [HumanMessage("x")]}, context={"user_id": "dana"}
    )
    assert set(results(out).values()) == {UNAVAILABLE}


def test_strict_raises_instead():
    mem, _ = wired(down, strict=True)
    with pytest.raises(ServiceUnavailableError):
        mem.recall({"messages": [HumanMessage("hi")]}, runtime=run({"user_id": "d"}))  # type: ignore[arg-type]
    with pytest.raises(ServiceUnavailableError):
        tools_graph(mem.tools()).invoke({"messages": []}, context={"user_id": "dana"})


def test_a_wrong_key_raises_even_so():
    mem, _ = wired(lambda r: ok({"detail": "bad key"}, status=401))
    with pytest.raises(AuthenticationError):
        mem.recall({"messages": [HumanMessage("hi")]}, runtime=run({"user_id": "d"}))  # type: ignore[arg-type]
    with pytest.raises(AuthenticationError):
        tools_graph(mem.tools()).invoke({"messages": []}, context={"user_id": "dana"})


def test_a_long_message_is_searched_by_its_end():
    """The service takes a question of at most 2,000 characters; a pasted email is longer."""
    mem, recorded = wired()
    asked = "x" * 2500 + " Where do I live?"
    mem.recall({"messages": [HumanMessage(asked)]}, runtime=run({"user_id": "d"}))  # type: ignore[arg-type]
    query = recorded.body(0)["query"]
    assert len(query) == 2000 and query.endswith("Where do I live?")


def test_requests_say_they_came_from_langgraph():
    mem, recorded = wired()
    mem.recall({"messages": [HumanMessage("hi")]}, runtime=run({"user_id": "d"}))  # type: ignore[arg-type]
    assert recorded.last.headers["user-agent"].endswith(" langgraph")


# ------------------------------------------------------------------------------- async --


@pytest.mark.anyio
async def test_the_async_nodes_and_tools_run_under_ainvoke():
    client, recorded = async_memory(answer, fail_open=True)
    mem = lg.AlexeinMemory(client)

    async def agent(state: Any) -> dict[str, Any]:
        assert "Dana lives in Lisbon." in mem.prompt(state)
        return {"messages": [AIMessage("You live in Lisbon.", id="ai-1")]}

    out = await graph(mem, agent, asynchronous=True).ainvoke(
        {"messages": [HumanMessage("Where do I live?", id="h-1")]},
        config={"configurable": {"thread_id": "t-1"}},
        context={"user_id": "dana"},
    )
    assert "Dana lives in Lisbon." in out["memory"]
    assert recorded.routes() == ["search", "add"]

    told = results(
        await tools_graph(mem.tools(write=True)).ainvoke(
            {"messages": []},
            config={"configurable": {"thread_id": "t-9"}},
            context={"user_id": "dana"},
        )
    )
    assert told["c3"] == "Saved." and told["c2"].startswith("Dana moved to Lisbon")


@pytest.mark.anyio
async def test_sync_nodes_and_tools_run_under_ainvoke_too():
    mem, recorded = wired()
    out = await graph(mem, lambda state: {"messages": [AIMessage("Hi.")]}).ainvoke(
        {"messages": [HumanMessage("hi")]},
        config={"configurable": {"thread_id": "t"}},
        context={"user_id": "dana"},
    )
    assert out["memory"] and recorded.routes() == ["search", "add"]
    told = results(
        await tools_graph(mem.tools()).ainvoke({"messages": []}, context={"user_id": "d"})
    )
    assert "Dana lives in Lisbon." in told["c1"]


@pytest.mark.anyio
async def test_the_async_nodes_fail_open_too():
    client, _ = async_memory(down, fail_open=True)
    mem = lg.AlexeinMemory(client)
    state = {"messages": [HumanMessage("hi"), AIMessage("hello")]}
    assert await mem.arecall(state, runtime=run({"user_id": "d"})) == {"memory": ""}  # type: ignore[arg-type]
    assert await mem.aremember(state, runtime=run({"user_id": "d"})) == {}  # type: ignore[arg-type]


def test_an_async_client_in_a_sync_node_says_what_to_do():
    client, _ = async_memory(answer)
    mem = lg.AlexeinMemory(client)
    with pytest.raises(TypeError, match="arecall"):
        mem.recall({"messages": [HumanMessage("hi")]}, runtime=run({"user_id": "d"}))  # type: ignore[arg-type]


def test_tools_need_no_memory_state():
    mem, recorded = wired()
    out = tools_graph(mem.tools(write=True), MessagesState).invoke(
        {"messages": [HumanMessage("x")]}, context={"user_id": "dana"}
    )
    assert out["messages"][-1].content == "Saved."
    assert {r.headers["x-alexein-user"] for r in recorded.requests} == {"dana"}


def test_the_module_level_defaults():
    assert lg.memory_prompt({"memory": "- x"}).endswith("\n\n- x")
    assert [t.name for t in lg.memory_tools()] == ["memory_search", "memory_open"]
    assert [t.name for t in lg.memory_tools(write=True)][-1] == "memory_add"
