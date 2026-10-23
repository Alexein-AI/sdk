"""The `memory.py` that `twinmemory-cli init openai-agents` writes, run inside the OpenAI Agents
SDK's own `Runner` - with its scripted model standing in for OpenAI - against a recorded memory
API."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest
from conftest import Answer, async_memory, ok

pytest.importorskip("agents")

from agents import Agent, RunConfig, Runner, SQLiteSession, UserError, handoff
from agents.run import CallModelData, ModelInputData
from agents.testing.model import ModelStep, ScriptedModel, assistant_message, function_call
from pydantic import BaseModel
from twinmemory import AuthenticationError, ServiceUnavailableError

from twinmemory_cli.render import render

pytestmark = pytest.mark.anyio

SEARCHED = {
    "query": "q",
    "found": 1,
    "known": ["Dana lives in Lisbon."],
    "facts": [],
    "hits": [{"path": "passages/p1.md", "id": "p1", "text": "Dana: I moved to Lisbon."}],
}


def answer(request: httpx.Request) -> httpx.Response:
    route = request.url.path.rsplit("/", 1)[-1]
    if route == "search":
        return ok(SEARCHED)
    if route == "read":
        return ok({"path": "passages/p1.md", "text": "Dana: I moved to Lisbon."})
    if route == "add":
        items = json.loads(request.content)["items"]
        return ok({"accepted": len(items), "items": []}, status=202)
    return ok()


def down(request: httpx.Request) -> httpx.Response:
    return ok({"detail": "rebuilding"}, status=503)


def wrong_key(request: httpx.Request) -> httpx.Response:
    return ok({"detail": "bad key"}, status=401)


def load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: Answer,
    *,
    parts: tuple[str, ...] = ("nodes", "tools"),
) -> tuple[ModuleType, Any]:
    """The file as `init` writes it, imported, its client answered by `answer` - made as the
    file makes its own, failing open unless STRICT."""
    path = tmp_path / "memory.py"
    values = {"version": "test", "fast": "False"}
    path.write_text(render("openai_agents/memory.py.tmpl", parts, values))
    spec = importlib.util.spec_from_file_location("generated_agents_memory", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "generated_agents_memory", module)
    spec.loader.exec_module(module)
    client, recorded = async_memory(
        answer, fail_open=not module.STRICT, integration="openai-agents"
    )
    monkeypatch.setattr(module, "_memory", lambda: client)
    return module, recorded


@pytest.fixture
def generated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Any]:
    return load(tmp_path, monkeypatch, answer)


def routes(recorded: Any) -> list[str]:
    return [r.url.path.rsplit("/", 1)[-1] for r in recorded.requests]


def told(call: Any) -> str:
    """The instructions a model call was given."""
    return call.system_instructions or ""


def bodies(recorded: Any, route: str) -> list[Any]:
    return [json.loads(r.content) for r in recorded.requests if r.url.path.endswith(route)]


async def turn(
    module: ModuleType, model: ScriptedModel, said: Any = "Where do I live?", **run: Any
):
    agent = Agent(
        name="Assistant", instructions="Be brief.", model=model, tools=run.pop("tools", [])
    )
    run.setdefault("context", module.MemoryContext(user_id="dana", session_id="conv-7"))
    config = RunConfig(call_model_input_filter=module.recall, tracing_disabled=True)
    result = await Runner.run(agent, said, run_config=config, **run)
    await module.remember(result)
    return result


# ------------------------------------------------------------------- recall and remember --


async def test_a_turn_is_recalled_before_the_model_and_saved_after(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    model = ScriptedModel([[assistant_message("You live in Lisbon.")]])

    result = await turn(module, model)

    assert result.final_output == "You live in Lisbon."
    assert routes(recorded) == ["search", "add"]
    assert {r.headers["X-Twin-Account"] for r in recorded.requests} == {"dana"}
    assert bodies(recorded, "search")[0]["query"] == "Where do I live?"
    (call,) = model.calls
    assert told(call).startswith("Be brief.\n\nWhat you remember")
    assert "Dana lives in Lisbon." in told(call)
    items = bodies(recorded, "add")[0]["items"]
    assert [(i["role"], i["text"], i.get("author")) for i in items] == [
        ("user", "Where do I live?", None),
        ("assistant", "You live in Lisbon.", "Assistant"),
    ]
    assert {i["session"] for i in items} == {"conv-7"}


async def test_a_tool_loop_searches_once_and_every_call_has_the_memory(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    model = ScriptedModel(
        [
            [function_call("memory_read", {"path": "passages/p1.md"}, call_id="c1")],
            [assistant_message("Lisbon.")],
        ]
    )

    await turn(module, model, tools=module.MEMORY_TOOLS)

    assert routes(recorded) == ["search", "read", "add"]  # recall, the tool, remember
    assert all("Dana lives in Lisbon." in told(c) for c in model.calls)
    items = bodies(recorded, "add")[0]["items"]
    assert [i["role"] for i in items] == ["user", "assistant"]  # no tool call, no tool output


async def test_after_a_handoff_the_next_agent_has_the_memory_too(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    expert_model = ScriptedModel([[assistant_message("Lisbon, as you said.")]])
    expert = Agent(name="Expert", instructions="Know things.", model=expert_model)
    triage_model = ScriptedModel([[function_call("transfer_to_expert", {}, call_id="h1")]])
    triage = Agent(name="Triage", model=triage_model, handoffs=[handoff(expert)])
    config = RunConfig(call_model_input_filter=module.recall, tracing_disabled=True)

    result = await Runner.run(
        triage, "Where do I live?", context=module.MemoryContext("dana"), run_config=config
    )
    await module.remember(result)

    assert routes(recorded) == ["search", "add"]
    assert "Dana lives in Lisbon." in told(expert_model.calls[0])
    assert bodies(recorded, "add")[0]["items"][1]["author"] == "Expert"


async def test_a_streamed_run_is_remembered_once_consumed(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    model = ScriptedModel([[assistant_message("Lisbon.")]])
    agent = Agent(name="Assistant", model=model)
    config = RunConfig(call_model_input_filter=module.recall, tracing_disabled=True)

    streamed = Runner.run_streamed(
        agent, "Where do I live?", context=module.MemoryContext("dana"), run_config=config
    )
    async for _ in streamed.stream_events():
        pass
    await module.remember(streamed)

    assert routes(recorded) == ["search", "add"]
    assert bodies(recorded, "add")[0]["items"][1]["text"] == "Lisbon."


async def test_memory_never_lands_in_the_session(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    session = SQLiteSession("conv-7")
    model = ScriptedModel([[assistant_message("Hello.")], [assistant_message("Lisbon.")]])

    await turn(module, model, "Hi", session=session)
    await turn(module, model, "Where do I live?", session=session)

    stored = json.dumps(await session.get_items())
    assert "Dana lives in Lisbon." not in stored
    assert [b["query"] for b in bodies(recorded, "search")] == ["Hi", "Where do I live?"]
    # The second turn's input is the history and then the new message: that is what is saved.
    assert bodies(recorded, "add")[1]["items"][0]["text"] == "Where do I live?"


async def test_saving_the_same_result_twice_saves_the_same_ids(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    result = await turn(module, ScriptedModel([[assistant_message("Lisbon.")]]))
    await module.remember(result)
    first, second = bodies(recorded, "add")
    assert [i["id"] for i in first["items"]] == [i["id"] for i in second["items"]]


class Place(BaseModel):
    city: str


async def test_structured_output_is_saved_as_json(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    model = ScriptedModel([[assistant_message('{"city": "Lisbon"}')]])
    agent = Agent(name="Assistant", model=model, output_type=Place)
    config = RunConfig(call_model_input_filter=module.recall, tracing_disabled=True)

    result = await Runner.run(
        agent, "Where do I live?", context=module.MemoryContext("dana"), run_config=config
    )
    await module.remember(result)

    assert json.loads(bodies(recorded, "add")[0]["items"][1]["text"]) == {"city": "Lisbon"}


async def test_a_user_with_no_memory_yet_recalls_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def empty(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("search"):
            return ok({"detail": "no such account"}, status=404)
        return answer(request)

    module, _ = load(tmp_path, monkeypatch, empty)
    model = ScriptedModel([[assistant_message("Hello.")]])
    await turn(module, model)
    assert told(model.calls[0]) == "Be brief."


@dataclass
class Yours:
    """A context the developer already had, given a `user_id`."""

    user_id: str
    plan: str = "pro"


@pytest.mark.parametrize("context", [Yours("dana"), {"user_id": "dana"}], ids=["object", "dict"])
async def test_any_context_with_a_user_id_will_do(
    generated: tuple[ModuleType, Any], context: Any
) -> None:
    module, recorded = generated
    await turn(module, ScriptedModel([[assistant_message("Hi.")]]), context=context)
    assert {r.headers["X-Twin-Account"] for r in recorded.requests} == {"dana"}
    assert "session" not in bodies(recorded, "add")[0]["items"][0]


async def test_without_a_user_id_the_run_stops(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    with pytest.raises(ValueError, match="whose memory"):
        await turn(module, ScriptedModel([[assistant_message("Hi.")]]), context=None)
    assert recorded.requests == []


async def test_requests_say_they_came_from_openai_agents(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    await turn(module, ScriptedModel([[assistant_message("Hi.")]]))
    assert recorded.last.headers["User-Agent"].endswith(" openai-agents")


# ------------------------------------------------- what a real model and server send --


async def test_a_long_message_is_searched_by_its_end(generated: tuple[ModuleType, Any]) -> None:
    """The service takes a question of at most 2,000 characters; a pasted email is longer."""
    module, recorded = generated
    asked = "x" * 2500 + " Where do I live?"
    await turn(module, ScriptedModel([[assistant_message("Lisbon.")]]), asked)
    query = bodies(recorded, "search")[0]["query"]
    assert len(query) == 2000 and query.endswith("Where do I live?")


async def test_a_model_without_response_ids_still_saves_each_turn_apart(
    generated: tuple[ModuleType, Any],
) -> None:
    """Chat Completions and LiteLLM models give no response id."""
    module, recorded = generated
    steps = [ModelStep(output=[assistant_message("You're welcome.")], response_id=None)] * 2
    model = ScriptedModel(steps)
    context = module.MemoryContext("dana")
    first = await turn(module, model, "Thanks", context=context)
    await turn(module, model, "Thanks", context=context)
    await module.remember(first)
    ids = [[i["id"] for i in body["items"]] for body in bodies(recorded, "add")]
    assert ids[0] != ids[1]  # two turns, said the same way
    assert ids[0] == ids[2]  # one turn, saved twice


def call(context: Any, *items: Any) -> CallModelData[Any]:
    """What the runner hands the filter before a model call."""
    data = ModelInputData(input=list(items), instructions="Be brief.")
    return CallModelData(model_data=data, agent=Agent(name="A"), context=context)


ASKED = {"role": "user", "content": "Where do I live?"}
TOOL_OUTPUT = {"type": "function_call_output", "call_id": "c1", "output": "..."}


def echo(request: httpx.Request) -> httpx.Response:
    """A search that says which question it answered."""
    if request.url.path.endswith("search"):
        return ok({"query": "q", "known": [f"ANSWER FOR: {json.loads(request.content)['query']}"]})
    return answer(request)


async def test_two_turns_in_flight_for_one_user_keep_their_own_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _ = load(tmp_path, monkeypatch, echo)
    first, second = module.MemoryContext("dana"), module.MemoryContext("dana")
    await module.recall(call(first, ASKED))
    await module.recall(call(second, {"role": "user", "content": "My dog's name?"}))

    after_a_tool = await module.recall(call(first, ASKED, TOOL_OUTPUT))

    assert "ANSWER FOR: Where do I live?" in (after_a_tool.instructions or "")
    assert "dog" not in (after_a_tool.instructions or "")


async def test_a_resumed_run_with_nothing_kept_searches_its_users_message(
    generated: tuple[ModuleType, Any],
) -> None:
    """A run resumed after an approval, or in another process, starts on a tool output."""
    module, recorded = generated
    resumed = await module.recall(call(module.MemoryContext("dana"), ASKED, TOOL_OUTPUT))
    assert [b["query"] for b in bodies(recorded, "search")] == ["Where do I live?"]
    assert "Dana lives in Lisbon." in (resumed.instructions or "")


async def test_a_developer_message_after_the_users_still_recalls(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    note = {"role": "developer", "content": "Today is Friday."}
    await module.recall(call(module.MemoryContext("dana"), ASKED, note))
    assert [b["query"] for b in bodies(recorded, "search")] == ["Where do I live?"]


async def test_a_run_paused_for_an_approval_saves_nothing(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    await module.remember(SimpleNamespace(interruptions=["approve memory_add?"]))
    assert recorded.requests == []


# ------------------------------------------------------------------------------- tools --

CALLS = [
    function_call("memory_search", {"query": "home"}, call_id="c1"),
    function_call("memory_read", {"path": "passages/p1.md"}, call_id="c2"),
    function_call("memory_add", {"text": "Prefers trains."}, call_id="c3"),
]


async def tool_outputs(module: ModuleType, context: Any = None) -> dict[str, str]:
    """A model that calls every tool once, then stops: what each call returned."""
    model = ScriptedModel([CALLS, [assistant_message("Done.")]])
    agent = Agent(name="Assistant", model=model, tools=module.MEMORY_WRITE_TOOLS)
    context = context or module.MemoryContext("dana", session_id="conv-7")
    config = RunConfig(tracing_disabled=True)
    await Runner.run(agent, "x", context=context, run_config=config)
    outputs = [i for i in model.calls[1].input if i.get("type") == "function_call_output"]
    return {i["call_id"]: i["output"] for i in outputs}


async def test_tools_read_the_user_from_the_run_never_from_the_model(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    outputs = await tool_outputs(module)

    assert "Dana lives in Lisbon." in outputs["c1"]
    assert "memory_read:\n- passages/p1.md" in outputs["c1"]
    assert outputs["c2"] == "Dana: I moved to Lisbon."
    assert outputs["c3"] == "Saved."
    assert {r.headers["X-Twin-Account"] for r in recorded.requests} == {"dana"}
    assert bodies(recorded, "add")[0]["items"] == [
        {"text": "Prefers trains.", "kind": "note", "session": "conv-7"}
    ]
    schemas = {t.name: t.params_json_schema for t in module.MEMORY_WRITE_TOOLS}
    assert all("user" not in json.dumps(s) for s in schemas.values())


async def test_the_models_own_mistakes_go_back_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad request from the model is the model's to fix: it is told, and the run goes on."""

    def strict(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("read"):
            return ok({"detail": "read needs a path"}, status=422)
        return answer(request)

    module, _ = load(tmp_path, monkeypatch, strict)
    model = ScriptedModel(
        [
            [
                function_call("memory_read", {"path": ""}, call_id="c1"),
                function_call("memory_search", "not json", call_id="c2"),
            ],
            [assistant_message("Sorry.")],
        ]
    )
    agent = Agent(name="A", model=model, tools=module.MEMORY_TOOLS)
    context = module.MemoryContext("dana")
    result = await Runner.run(
        agent, "x", context=context, run_config=RunConfig(tracing_disabled=True)
    )

    outputs = [i["output"] for i in model.calls[1].input if i.get("type") == "function_call_output"]
    assert result.final_output == "Sorry."
    assert all(o.startswith("That did not work:") for o in outputs), outputs
    assert "read needs a path" in outputs[0]


async def test_a_tool_run_with_no_user_raises(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    with pytest.raises(Exception, match="whose memory"):
        await tool_outputs(module, context=SimpleNamespace(plan="pro"))
    assert recorded.requests == []


# ---------------------------------------------------------------------- when memory fails --


async def test_a_turn_goes_ahead_when_memory_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    module, recorded = load(tmp_path, monkeypatch, down)
    model = ScriptedModel([[assistant_message("Still here.")]])

    result = await turn(module, model)

    assert result.final_output == "Still here."
    assert told(model.calls[0]) == "Be brief."
    assert routes(recorded)[-1] == "add"  # tried, failed open
    assert any("unavailable" in r.message for r in caplog.records)


async def test_tools_tell_the_model_memory_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _ = load(tmp_path, monkeypatch, down)
    assert set((await tool_outputs(module)).values()) == {module.UNAVAILABLE}


async def test_strict_raises_instead(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _ = load(tmp_path, monkeypatch, down)
    client, _ = async_memory(down, fail_open=False)
    monkeypatch.setattr(module, "_memory", lambda: client)
    monkeypatch.setattr(module, "STRICT", True)
    with pytest.raises(ServiceUnavailableError):
        await turn(module, ScriptedModel([[assistant_message("Hi.")]]))


async def test_a_wrong_key_raises_even_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _ = load(tmp_path, monkeypatch, wrong_key)
    with pytest.raises(AuthenticationError):
        await turn(module, ScriptedModel([[assistant_message("Hi.")]]))
    # From a tool, the SDK raises its own error, with memory's as the cause.
    with pytest.raises(UserError) as raised:
        await tool_outputs(module)
    assert isinstance(raised.value.__cause__, AuthenticationError)


# ----------------------------------------------------------------------------- presets --


async def test_tools_only_has_no_recall(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, recorded = load(tmp_path, monkeypatch, answer, parts=("tools",))
    assert not hasattr(module, "recall") and not hasattr(module, "remember")
    assert (await tool_outputs(module))["c3"] == "Saved."
    assert routes(recorded) == ["search", "read", "add"]


async def test_nodes_only_has_no_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, recorded = load(tmp_path, monkeypatch, answer, parts=("nodes",))
    assert not hasattr(module, "MEMORY_TOOLS")
    await turn(module, ScriptedModel([[assistant_message("Hi.")]]))
    assert routes(recorded) == ["search", "add"]
