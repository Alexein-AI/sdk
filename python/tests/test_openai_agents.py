# pyright: reportMissingImports=false
# CrewAI and the OpenAI Agents SDK are never installed together (see pyproject.toml): these run
# with `uv run --no-group crewai --group openai-agents pytest`.
"""`alexein.openai_agents`, run inside the OpenAI Agents SDK's own `Runner` - with its scripted
model standing in for OpenAI - against a recorded memory API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from conftest import EMPTY_SEARCH, answer, async_memory, ok

pytest.importorskip("agents")

from agents import Agent, FunctionTool, RunConfig, Runner, SQLiteSession, UserError, handoff
from agents.run import CallModelData, ModelInputData
from agents.testing.model import (
    ModelStep,
    ScriptedModel,
    assistant_message,
    function_call,
)
from pydantic import BaseModel

import alexein.openai_agents as oa
from alexein import AuthenticationError, ServiceUnavailableError
from alexein._integration import UNAVAILABLE

pytestmark = pytest.mark.anyio


def down(request: httpx.Request) -> httpx.Response:
    return ok({"detail": "rebuilding"}, status=503)


def wired(answer_with: Any = answer, *, strict: bool = False) -> tuple[oa.AlexeinMemory, Any]:
    client, recorded = async_memory(answer_with, fail_open=not strict, integration="openai-agents")
    return oa.AlexeinMemory(client, strict=strict), recorded


def told(call: Any) -> str:
    """The instructions a model call was given."""
    return call.system_instructions or ""


async def turn(
    mem: oa.AlexeinMemory, model: ScriptedModel, said: Any = "Where do I live?", **run: Any
):
    agent = Agent(
        name="Assistant", instructions="Be brief.", model=model, tools=run.pop("tools", [])
    )
    run.setdefault("context", oa.MemoryContext(user_id="dana", session_id="conv-7"))
    config = RunConfig(call_model_input_filter=mem.recall, tracing_disabled=True)
    result = await Runner.run(agent, said, run_config=config, **run)
    await mem.remember(result)
    return result


# ------------------------------------------------------------------- recall and remember --


async def test_a_turn_is_recalled_before_the_model_and_saved_after():
    mem, recorded = wired()
    model = ScriptedModel([[assistant_message("You live in Lisbon.")]])

    result = await turn(mem, model)

    assert result.final_output == "You live in Lisbon."
    assert recorded.routes() == ["search", "add"]
    assert {r.headers["x-alexein-user"] for r in recorded.requests} == {"dana"}
    assert recorded.bodies("search")[0] == {"query": "Where do I live?"}
    (call,) = model.calls
    assert told(call).startswith("Be brief.\n\nWhat you remember")
    assert "- Dana lives in Lisbon." in told(call)
    items = recorded.bodies("add")[0]["items"]
    assert [(i["role"], i["text"], i.get("author")) for i in items] == [
        ("user", "Where do I live?", None),
        ("assistant", "You live in Lisbon.", "Assistant"),
    ]
    assert {i["session"] for i in items} == {"conv-7"}


async def test_a_tool_loop_searches_once_and_every_call_has_the_memory():
    mem, recorded = wired()
    model = ScriptedModel(
        [
            [function_call("memory_open", {"ref": "mem_f1"}, call_id="c1")],
            [assistant_message("Lisbon.")],
        ]
    )
    await turn(mem, model, tools=mem.tools())
    assert recorded.routes() == ["search", "open", "add"]  # recall, the tool, remember
    assert all("Dana lives in Lisbon." in told(c) for c in model.calls)
    assert [i["role"] for i in recorded.bodies("add")[0]["items"]] == ["user", "assistant"]


async def test_after_a_handoff_the_next_agent_has_the_memory_too():
    mem, recorded = wired()
    expert_model = ScriptedModel([[assistant_message("Lisbon, as you said.")]])
    expert = Agent(name="Expert", instructions="Know things.", model=expert_model)
    triage_model = ScriptedModel([[function_call("transfer_to_expert", {}, call_id="h1")]])
    triage = Agent(name="Triage", model=triage_model, handoffs=[handoff(expert)])
    config = RunConfig(call_model_input_filter=mem.recall, tracing_disabled=True)

    result = await Runner.run(
        triage, "Where do I live?", context=oa.MemoryContext("dana"), run_config=config
    )
    await mem.remember(result)

    assert recorded.routes() == ["search", "add"]
    assert "Dana lives in Lisbon." in told(expert_model.calls[0])
    assert recorded.bodies("add")[0]["items"][1]["author"] == "Expert"


async def test_a_streamed_run_is_remembered_once_consumed():
    mem, recorded = wired()
    agent = Agent(name="Assistant", model=ScriptedModel([[assistant_message("Lisbon.")]]))
    config = RunConfig(call_model_input_filter=mem.recall, tracing_disabled=True)
    streamed = Runner.run_streamed(
        agent, "Where do I live?", context=oa.MemoryContext("dana"), run_config=config
    )
    async for _ in streamed.stream_events():
        pass
    await mem.remember(streamed)
    assert recorded.routes() == ["search", "add"]
    assert recorded.bodies("add")[0]["items"][1]["text"] == "Lisbon."


async def test_memory_never_lands_in_the_session():
    mem, recorded = wired()
    session = SQLiteSession("conv-7")
    model = ScriptedModel([[assistant_message("Hello.")], [assistant_message("Lisbon.")]])
    await turn(mem, model, "Hi", session=session)
    await turn(mem, model, "Where do I live?", session=session)
    assert "Dana lives in Lisbon." not in json.dumps(await session.get_items())
    assert [b["query"] for b in recorded.bodies("search")] == ["Hi", "Where do I live?"]
    assert recorded.bodies("add")[1]["items"][0]["text"] == "Where do I live?"


async def test_saving_the_same_result_twice_saves_the_same_ids():
    mem, recorded = wired()
    result = await turn(mem, ScriptedModel([[assistant_message("Lisbon.")]]))
    await mem.remember(result)
    first, second = recorded.bodies("add")
    assert [i["id"] for i in first["items"]] == [i["id"] for i in second["items"]]


class Place(BaseModel):
    city: str


async def test_structured_output_is_saved_as_json():
    mem, recorded = wired()
    agent = Agent(
        name="A",
        model=ScriptedModel([[assistant_message('{"city": "Lisbon"}')]]),
        output_type=Place,
    )
    config = RunConfig(call_model_input_filter=mem.recall, tracing_disabled=True)
    result = await Runner.run(agent, "Where?", context=oa.MemoryContext("dana"), run_config=config)
    await mem.remember(result)
    assert json.loads(recorded.bodies("add")[0]["items"][1]["text"]) == {"city": "Lisbon"}


async def test_a_user_with_no_memory_yet_recalls_nothing():
    mem, _ = wired(lambda r: ok(EMPTY_SEARCH) if r.url.path.endswith("search") else answer(r))
    model = ScriptedModel([[assistant_message("Hello.")]])
    await turn(mem, model)
    assert told(model.calls[0]) == "Be brief."


@dataclass
class Yours:
    """A context the developer already had, given a `user_id`."""

    user_id: str
    plan: str = "pro"


@pytest.mark.parametrize("context", [Yours("dana"), {"user_id": "dana"}], ids=["object", "dict"])
async def test_any_context_with_a_user_id_will_do(context: Any):
    mem, recorded = wired()
    await turn(mem, ScriptedModel([[assistant_message("Hi.")]]), context=context)
    assert {r.headers["x-alexein-user"] for r in recorded.requests} == {"dana"}
    assert "session" not in recorded.bodies("add")[0]["items"][0]


async def test_without_a_user_id_the_run_stops():
    mem, recorded = wired()
    with pytest.raises(ValueError, match="whose memory"):
        await turn(mem, ScriptedModel([[assistant_message("Hi.")]]), context=None)
    assert recorded.requests == []


async def test_requests_say_they_came_from_openai_agents():
    mem, recorded = wired()
    await turn(mem, ScriptedModel([[assistant_message("Hi.")]]))
    assert recorded.last.headers["user-agent"].endswith(" openai-agents")


async def test_a_long_message_is_searched_by_its_end():
    mem, recorded = wired()
    await turn(
        mem, ScriptedModel([[assistant_message("Lisbon.")]]), "x" * 2500 + " Where do I live?"
    )
    query = recorded.bodies("search")[0]["query"]
    assert len(query) == 2000 and query.endswith("Where do I live?")


async def test_a_model_without_response_ids_still_saves_each_turn_apart():
    """Chat Completions and LiteLLM models give no response id."""
    mem, recorded = wired()
    model = ScriptedModel(
        [ModelStep(output=[assistant_message("You're welcome.")], response_id=None)] * 2
    )
    context = oa.MemoryContext("dana")
    first = await turn(mem, model, "Thanks", context=context)
    await turn(mem, model, "Thanks", context=context)
    await mem.remember(first)
    ids = [[i["id"] for i in body["items"]] for body in recorded.bodies("add")]
    assert ids[0] != ids[1] and ids[0] == ids[2]


def call(context: Any, *items: Any) -> CallModelData[Any]:
    """What the runner hands the filter before a model call."""
    data = ModelInputData(input=list(items), instructions="Be brief.")
    return CallModelData(model_data=data, agent=Agent(name="A"), context=context)


ASKED = {"role": "user", "content": "Where do I live?"}
TOOL_OUTPUT = {"type": "function_call_output", "call_id": "c1", "output": "..."}


def echo(request: httpx.Request) -> httpx.Response:
    """A search that says which question it answered."""
    if request.url.path.endswith("search"):
        asked = json.loads(request.content)["query"]
        return ok({"query": asked, "memories": [{"type": "known", "text": f"FOR: {asked}"}]})
    return answer(request)


async def test_two_turns_in_flight_for_one_user_keep_their_own_memory():
    mem, _ = wired(echo)
    first, second = oa.MemoryContext("dana"), oa.MemoryContext("dana")
    await mem.recall(call(first, ASKED))
    await mem.recall(call(second, {"role": "user", "content": "My dog's name?"}))
    after_a_tool = await mem.recall(call(first, ASKED, TOOL_OUTPUT))
    assert "FOR: Where do I live?" in (after_a_tool.instructions or "")
    assert "dog" not in (after_a_tool.instructions or "")


async def test_a_resumed_run_with_nothing_kept_searches_its_users_message():
    mem, recorded = wired()
    resumed = await mem.recall(call(oa.MemoryContext("dana"), ASKED, TOOL_OUTPUT))
    assert [b["query"] for b in recorded.bodies("search")] == ["Where do I live?"]
    assert "Dana lives in Lisbon." in (resumed.instructions or "")


async def test_a_developer_message_after_the_users_still_recalls():
    mem, recorded = wired()
    note = {"role": "developer", "content": "Today is Friday."}
    await mem.recall(call(oa.MemoryContext("dana"), ASKED, note))
    assert [b["query"] for b in recorded.bodies("search")] == ["Where do I live?"]


async def test_a_run_paused_for_an_approval_saves_nothing():
    mem, recorded = wired()
    await mem.remember(SimpleNamespace(interruptions=["approve memory_add?"]))  # type: ignore[arg-type]
    assert recorded.requests == []


# ------------------------------------------------------------------------------- tools --

CALLS = [
    function_call("memory_search", {"query": "home"}, call_id="c1"),
    function_call("memory_open", {"ref": "mem_f1"}, call_id="c2"),
    function_call("memory_add", {"text": "Prefers trains."}, call_id="c3"),
]


async def tool_outputs(mem: oa.AlexeinMemory, context: Any = None) -> dict[str, str]:
    """A model that calls every tool once, then stops: what each call returned."""
    model = ScriptedModel([CALLS, [assistant_message("Done.")]])
    agent = Agent(name="Assistant", model=model, tools=mem.tools(write=True))
    context = context or oa.MemoryContext("dana", session_id="conv-7")
    await Runner.run(agent, "x", context=context, run_config=RunConfig(tracing_disabled=True))
    outputs = [i for i in model.calls[1].input if i.get("type") == "function_call_output"]
    return {i["call_id"]: i["output"] for i in outputs}


async def test_tools_read_the_user_from_the_run_never_from_the_model():
    mem, recorded = wired()
    outputs = await tool_outputs(mem)
    assert "- Dana lives in Lisbon." in outputs["c1"]
    assert outputs["c1"].endswith("memory_open:\n- mem_f1\n- mem_e1")
    assert outputs["c2"].startswith("Dana moved to Lisbon for a job at Acme.\n\nLearned from:")
    assert outputs["c3"] == "Saved."
    assert {r.headers["x-alexein-user"] for r in recorded.requests} == {"dana"}
    assert recorded.bodies("add")[0]["items"] == [
        {"text": "Prefers trains.", "kind": "note", "session": "conv-7"}
    ]
    tools = mem.tools(write=True)
    assert [t.name for t in tools] == ["memory_search", "memory_open", "memory_add"]
    assert [t.name for t in mem.tools()] == ["memory_search", "memory_open"]
    schemas = [t.params_json_schema for t in tools if isinstance(t, FunctionTool)]
    assert len(schemas) == 3 and all("user" not in json.dumps(s) for s in schemas)


async def test_the_models_own_mistakes_go_back_to_it():
    """A bad request from the model is the model's to fix: it is told, and the run goes on."""

    def strict(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("open"):
            return ok({"detail": "`ref` must not be empty"}, status=422)
        return answer(request)

    mem, _ = wired(strict)
    model = ScriptedModel(
        [
            [
                function_call("memory_open", {"ref": ""}, call_id="c1"),
                function_call("memory_search", "not json", call_id="c2"),
            ],
            [assistant_message("Sorry.")],
        ]
    )
    agent = Agent(name="A", model=model, tools=mem.tools())
    result = await Runner.run(
        agent, "x", context=oa.MemoryContext("dana"), run_config=RunConfig(tracing_disabled=True)
    )
    outputs = [i["output"] for i in model.calls[1].input if i.get("type") == "function_call_output"]
    assert result.final_output == "Sorry."
    assert all(o.startswith("That did not work:") for o in outputs), outputs
    assert "`ref` must not be empty" in outputs[0]


async def test_a_tool_run_with_no_user_raises():
    mem, recorded = wired()
    with pytest.raises(Exception, match="whose memory"):
        await tool_outputs(mem, context=SimpleNamespace(plan="pro"))
    assert recorded.requests == []


# ---------------------------------------------------------------------- when memory fails --


async def test_a_turn_goes_ahead_when_memory_is_down(caplog: pytest.LogCaptureFixture):
    mem, recorded = wired(down)
    model = ScriptedModel([[assistant_message("Still here.")]])
    result = await turn(mem, model)
    assert result.final_output == "Still here." and told(model.calls[0]) == "Be brief."
    assert recorded.routes()[-1] == "add"  # tried, failed open
    assert any("unavailable" in r.message for r in caplog.records)


async def test_tools_tell_the_model_memory_is_down():
    mem, _ = wired(down)
    assert set((await tool_outputs(mem)).values()) == {UNAVAILABLE}


async def test_strict_raises_instead():
    mem, _ = wired(down, strict=True)
    with pytest.raises(ServiceUnavailableError):
        await turn(mem, ScriptedModel([[assistant_message("Hi.")]]))


async def test_a_wrong_key_raises_even_so():
    mem, _ = wired(lambda r: ok({"detail": "bad key"}, status=401))
    with pytest.raises(AuthenticationError):
        await turn(mem, ScriptedModel([[assistant_message("Hi.")]]))
    # From a tool, the SDK raises its own error, with memory's as the cause.
    with pytest.raises(UserError) as raised:
        await tool_outputs(mem)
    assert isinstance(raised.value.__cause__, AuthenticationError)


async def test_the_module_level_defaults():
    assert oa.recall.__self__ is oa.remember.__self__  # type: ignore[attr-defined]
    assert [t.name for t in oa.memory_tools(write=True)] == [
        "memory_search",
        "memory_open",
        "memory_add",
    ]
    with pytest.raises(ValueError, match="whose memory"):
        await oa.recall(call(None, ASKED))
