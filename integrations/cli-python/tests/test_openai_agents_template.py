# pyright: reportMissingImports=false
# CrewAI and the OpenAI Agents SDK are never installed together (see pyproject.toml).
"""The `memory.py` that `alexein-cli init openai-agents` writes, run inside the OpenAI Agents
SDK's own `Runner` - with its scripted model standing in for OpenAI - against a recorded memory
API: its settings reach the client and `alexein.openai_agents`, and what it wires recalls,
remembers and offers tools as the docs say."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest
from conftest import STRICT, Answer, answer, down, load_memory_file, ok, route, wrong_key

pytest.importorskip("agents")

from agents import Agent, RunConfig, Runner, SQLiteSession, UserError, handoff
from agents.run import CallModelData, ModelInputData
from agents.testing.model import ModelStep, ScriptedModel, assistant_message, function_call
from alexein import AlexeinError, AuthenticationError, ServiceUnavailableError
from pydantic import BaseModel

pytestmark = pytest.mark.anyio

UNAVAILABLE = "Memory is unavailable right now; carry on without it."


def load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: Answer = answer, **given: Any
) -> tuple[ModuleType, Any]:
    return load_memory_file(tmp_path, monkeypatch, "openai-agents", answer, **given)


@pytest.fixture
def generated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Any]:
    return load(tmp_path, monkeypatch, answer)


def told(call: Any) -> str:
    """The instructions a model call was given."""
    return call.system_instructions or ""


def bodies(recorded: Any, name: str) -> list[Any]:
    return recorded.bodies(name)


def routes(recorded: Any) -> list[str]:
    return [route(r) for r in recorded.requests]


async def turn(
    module: ModuleType, model: ScriptedModel, said: Any = "Where do I live?", **run: Any
):
    agent = Agent(
        name="Assistant", instructions="Be brief.", model=model, tools=run.pop("tools", [])
    )
    run.setdefault("context", module.MemoryContext(user_id="dana", session_id="conv-7"))
    config = RunConfig(call_model_input_filter=module.memory.recall, tracing_disabled=True)
    result = await Runner.run(agent, said, run_config=config, **run)
    await module.memory.remember(result)
    return result


# ------------------------------------------------------------------------------ the file --


async def test_the_settings_reach_the_client_and_the_memory(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    memory = module.memory
    assert (memory.fast, memory.max_chars, memory.strict) == (False, 4000, False)
    assert memory.timeout == module.TIMEOUT
    await turn(module, ScriptedModel([[assistant_message("Hi.")]]))
    assert recorded.timeouts == [module.TIMEOUT]  # the client, made on first use
    assert recorded.last.headers["user-agent"].endswith(" openai-agents")
    assert recorded.last.headers["authorization"] == "Bearer tm_test"


async def test_importing_needs_no_key_and_the_first_run_says_how_to_set_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, recorded = load(tmp_path, monkeypatch, key=None)
    with pytest.raises(AlexeinError, match="ALEXEIN_API_KEY"):
        await turn(module, ScriptedModel([[assistant_message("Hi.")]]))
    assert recorded.requests == []


async def test_fast_as_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, recorded = load(tmp_path, monkeypatch, fast=True)
    await turn(module, ScriptedModel([[assistant_message("Hi.")]]))
    assert bodies(recorded, "search") == [{"query": "Where do I live?", "fast": True}]


# ------------------------------------------------------------------- recall and remember --


async def test_a_turn_is_recalled_before_the_model_and_saved_after(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    model = ScriptedModel([[assistant_message("You live in Lisbon.")]])

    result = await turn(module, model)

    assert result.final_output == "You live in Lisbon."
    assert routes(recorded) == ["search", "add"]
    assert recorded.users() == {"dana"}
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
            [function_call("memory_open", {"ref": "mem_e1"}, call_id="c1")],
            [assistant_message("Lisbon.")],
        ]
    )

    await turn(module, model, tools=module.memory.tools())

    assert routes(recorded) == ["search", "open", "add"]  # recall, the tool, remember
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
    config = RunConfig(call_model_input_filter=module.memory.recall, tracing_disabled=True)

    result = await Runner.run(
        triage, "Where do I live?", context=module.MemoryContext("dana"), run_config=config
    )
    await module.memory.remember(result)

    assert routes(recorded) == ["search", "add"]
    assert "Dana lives in Lisbon." in told(expert_model.calls[0])
    assert bodies(recorded, "add")[0]["items"][1]["author"] == "Expert"


async def test_a_streamed_run_is_remembered_once_consumed(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    model = ScriptedModel([[assistant_message("Lisbon.")]])
    agent = Agent(name="Assistant", model=model)
    config = RunConfig(call_model_input_filter=module.memory.recall, tracing_disabled=True)

    streamed = Runner.run_streamed(
        agent, "Where do I live?", context=module.MemoryContext("dana"), run_config=config
    )
    async for _ in streamed.stream_events():
        pass
    await module.memory.remember(streamed)

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
    await module.memory.remember(result)
    first, second = bodies(recorded, "add")
    assert [i["id"] for i in first["items"]] == [i["id"] for i in second["items"]]


class Place(BaseModel):
    city: str


async def test_structured_output_is_saved_as_json(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    model = ScriptedModel([[assistant_message('{"city": "Lisbon"}')]])
    agent = Agent(name="Assistant", model=model, output_type=Place)
    config = RunConfig(call_model_input_filter=module.memory.recall, tracing_disabled=True)

    result = await Runner.run(
        agent, "Where do I live?", context=module.MemoryContext("dana"), run_config=config
    )
    await module.memory.remember(result)

    assert json.loads(bodies(recorded, "add")[0]["items"][1]["text"]) == {"city": "Lisbon"}


async def test_a_user_with_no_memory_yet_recalls_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def empty(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("search"):
            return ok({"detail": "nothing added for this app user yet"}, status=404)
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
    assert recorded.users() == {"dana"}
    assert "session" not in bodies(recorded, "add")[0]["items"][0]


async def test_without_a_user_id_the_run_stops(generated: tuple[ModuleType, Any]) -> None:
    module, recorded = generated
    with pytest.raises(ValueError, match="whose memory"):
        await turn(module, ScriptedModel([[assistant_message("Hi.")]]), context=None)
    assert recorded.requests == []


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
    await module.memory.remember(first)
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
    if route(request) == "search":
        asked = json.loads(request.content)["query"]
        return ok({"query": asked, "memories": [{"type": "known", "text": f"ANSWER FOR: {asked}"}]})
    return answer(request)


async def test_two_turns_in_flight_for_one_user_keep_their_own_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _ = load(tmp_path, monkeypatch, echo)
    first, second = module.MemoryContext("dana"), module.MemoryContext("dana")
    await module.memory.recall(call(first, ASKED))
    await module.memory.recall(call(second, {"role": "user", "content": "My dog's name?"}))

    after_a_tool = await module.memory.recall(call(first, ASKED, TOOL_OUTPUT))

    assert "ANSWER FOR: Where do I live?" in (after_a_tool.instructions or "")
    assert "dog" not in (after_a_tool.instructions or "")


async def test_a_resumed_run_with_nothing_kept_searches_its_users_message(
    generated: tuple[ModuleType, Any],
) -> None:
    """A run resumed after an approval, or in another process, starts on a tool output."""
    module, recorded = generated
    resumed = await module.memory.recall(call(module.MemoryContext("dana"), ASKED, TOOL_OUTPUT))
    assert [b["query"] for b in bodies(recorded, "search")] == ["Where do I live?"]
    assert "Dana lives in Lisbon." in (resumed.instructions or "")


async def test_a_developer_message_after_the_users_still_recalls(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    note = {"role": "developer", "content": "Today is Friday."}
    await module.memory.recall(call(module.MemoryContext("dana"), ASKED, note))
    assert [b["query"] for b in bodies(recorded, "search")] == ["Where do I live?"]


async def test_a_run_paused_for_an_approval_saves_nothing(
    generated: tuple[ModuleType, Any],
) -> None:
    module, recorded = generated
    await module.memory.remember(SimpleNamespace(interruptions=["approve memory_add?"]))
    assert recorded.requests == []


# ------------------------------------------------------------------------------- tools --

CALLS = [
    function_call("memory_search", {"query": "home"}, call_id="c1"),
    function_call("memory_open", {"ref": "mem_e1"}, call_id="c2"),
    function_call("memory_add", {"text": "Prefers trains."}, call_id="c3"),
]


async def tool_outputs(module: ModuleType, context: Any = None) -> dict[str, str]:
    """A model that calls every tool once, then stops: what each call returned."""
    model = ScriptedModel([CALLS, [assistant_message("Done.")]])
    agent = Agent(name="Assistant", model=model, tools=module.memory.tools(write=True))
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
    assert "memory_open:\n- mem_f1\n- mem_e1" in outputs["c1"]
    assert outputs["c2"] == "2026-10-01: Dana: I moved to Lisbon."
    assert outputs["c3"] == "Saved."
    assert recorded.users() == {"dana"}
    assert bodies(recorded, "add")[0]["items"] == [
        {"text": "Prefers trains.", "kind": "note", "session": "conv-7"}
    ]
    schemas = {t.name: t.params_json_schema for t in module.memory.tools(write=True)}
    assert all("user" not in json.dumps(s) for s in schemas.values())


async def test_the_models_own_mistakes_go_back_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bad request from the model is the model's to fix: it is told, and the run goes on."""

    def strict(request: httpx.Request) -> httpx.Response:
        if route(request) == "open":
            return ok({"detail": "open needs a ref"}, status=422)
        return answer(request)

    module, _ = load(tmp_path, monkeypatch, strict)
    model = ScriptedModel(
        [
            [
                function_call("memory_open", {"ref": ""}, call_id="c1"),
                function_call("memory_search", "not json", call_id="c2"),
            ],
            [assistant_message("Sorry.")],
        ]
    )
    agent = Agent(name="A", model=model, tools=module.memory.tools())
    context = module.MemoryContext("dana")
    result = await Runner.run(
        agent, "x", context=context, run_config=RunConfig(tracing_disabled=True)
    )

    outputs = [i["output"] for i in model.calls[1].input if i.get("type") == "function_call_output"]
    assert result.final_output == "Sorry."
    assert all(o.startswith("That did not work:") for o in outputs), outputs
    assert "open needs a ref" in outputs[0]


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
    assert set((await tool_outputs(module)).values()) == {UNAVAILABLE}


async def test_strict_as_written_raises_instead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _ = load(tmp_path, monkeypatch, down, edits=STRICT)
    assert module.memory.strict is True
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
