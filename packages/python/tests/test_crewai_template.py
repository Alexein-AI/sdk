"""The `memory.py` that `twinmemory-cli init crewai` writes, run inside real CrewAI crews - CrewAI's
own classes, with a stand-in model - against a recorded memory API."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from conftest import Answer, memory, ok
from test_cli import lint_clean

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
pytest.importorskip("crewai")

from crewai import Agent, Crew, Task
from crewai.llms.base_llm import BaseLLM
from pydantic import Field
from twinmemory import AuthenticationError

from twinmemory_cli.render import render

SEARCHED = {
    "query": "q",
    "found": 1,
    "known": ["Dana lives in Lisbon."],
    "facts": [
        {"text": "2026-10-01: Dana moved to Lisbon.", "id": "f1", "path": "r/1", "source": "p/1"}
    ],
    "hits": [{"path": "passages/p1.md", "id": "p1", "text": "Dana: I moved to Lisbon."}],
}


class Stand(BaseLLM):
    """A model that answers from a list (or the same line), and keeps every prompt it was shown.
    An answer that is an exception is raised instead."""

    answers: list[Any] = Field(default_factory=list)
    prompts: list[str] = Field(default_factory=list)

    def call(self, messages: Any, *args: Any, **kwargs: Any) -> str:
        shown = (
            messages
            if isinstance(messages, str)
            else "\n".join(str(m.get("content")) for m in messages)
        )
        self.prompts.append(shown)
        answer = self.answers.pop(0) if self.answers else "Final Answer: Lisbon it is."
        if isinstance(answer, Exception):
            raise answer
        return answer

    def supports_function_calling(self) -> bool:
        return False


def stand(*answers: Any) -> Stand:
    return Stand(model="stand-in", answers=list(answers), prompts=[])


class Recorder:
    """What the memory API was sent, by route and account; and a request's text, for matching."""

    def __init__(self, answer: Answer) -> None:
        self.sent: list[tuple[str, str, Any]] = []
        self.answer = answer

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.sent.append(
            (request.url.path.rsplit("/", 1)[-1], request.headers.get("X-Twin-Account", ""), body)
        )
        return self.answer(request)

    def routes(self, account: str | None = None) -> list[str]:
        return [r for r, a, _ in self.sent if account is None or a == account]


def answering(request: httpx.Request) -> httpx.Response:
    route = request.url.path.rsplit("/", 1)[-1]
    if route == "me":
        return ok({"kind": "key", "org": "o", "project": "p", "writes": True})
    if route == "search":
        return ok(SEARCHED)
    if route == "add":
        items = json.loads(request.content)["items"]
        return ok(
            {
                "items": [{"id": i.get("id", ""), "event_id": "e"} for i in items],
                "queued": 1,
                "pending": 1,
            },
            status=202,
        )
    return ok()


def load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    answer: Answer = answering,
    *,
    parts: tuple[str, ...] = ("auto", "tools"),
) -> tuple[ModuleType, Recorder]:
    """The file as `init crewai` writes it, imported fresh, its client answered by `answer`."""
    path = tmp_path / "memory.py"
    path.write_text(render("crewai/memory.py.tmpl", parts, {"version": "test", "fast": "False"}))
    name = f"generated_crewai_memory_{abs(hash(tmp_path))}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    recorder = Recorder(answer)
    client, _ = memory(recorder, fail_open=not module.STRICT, integration="crewai", max_retries=0)
    monkeypatch.setattr(module, "_memory", lambda: client)
    return module, recorder


def crew_of(module: ModuleType, llm: Stand, *, memory: Any = None) -> Crew:
    planner = Agent(role="Travel planner", goal="Plan trips", backstory="Plans trips.", llm=llm)
    task = Task(description="Plan a weekend in {city}.", expected_output="A plan.", agent=planner)
    return Crew(
        agents=[planner],
        tasks=[task],
        memory=module.TwinMemory() if memory is None else memory,
        before_kickoff_callbacks=[module.whose],
    )


# ---------------------------------------------------------------------------------- recall --


def test_a_task_recalls_the_users_memory_into_its_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, recorder = load(tmp_path, monkeypatch)
    llm = stand()
    crew_of(module, llm).kickoff(inputs={"user_id": "dana", "city": "Porto"})
    searches = [(a, b) for r, a, b in recorder.sent if r == "search"]
    assert searches and searches[0][0] == "dana"
    assert searches[0][1]["query"] == "Plan a weekend in Porto."
    assert "Dana lives in Lisbon." in llm.prompts[0]


def test_recall_returns_at_most_the_limit_best_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _ = load(tmp_path, monkeypatch)
    module.whose({"user_id": "dana"})
    matches = module.TwinMemory().recall("where", limit=2)
    assert [m.record.content for m in matches] == [
        "Dana lives in Lisbon.",
        "2026-10-01: Dana moved to Lisbon.",
    ]
    assert matches[0].score >= matches[1].score


def test_a_user_with_no_memory_yet_recalls_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def none_yet(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/me"):
            return answering(request)
        return ok({"detail": "no memory"}, status=404)

    module, _ = load(tmp_path, monkeypatch, none_yet)
    module.whose({"user_id": "new"})
    assert module.TwinMemory().recall("anything") == []


# ------------------------------------------------------------------------------------ save --


def test_a_tasks_result_is_saved_under_the_user_with_the_agents_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, recorder = load(tmp_path, monkeypatch)
    crew_of(module, stand()).kickoff(inputs={"user_id": "dana", "city": "Porto"})
    adds = [(a, b) for r, a, b in recorder.sent if r == "add"]
    assert len(adds) == 1 and adds[0][0] == "dana"
    (item,) = adds[0][1]["items"]
    assert item["kind"] == "note" and item["author"] == "Travel planner"
    assert "Lisbon it is." in item["text"] and item["session"] and item["id"]


def test_one_kickoff_is_one_session_and_the_next_is_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, recorder = load(tmp_path, monkeypatch)
    crew = crew_of(module, stand())
    crew.kickoff(inputs={"user_id": "dana", "city": "Porto"})
    crew.kickoff(inputs={"user_id": "dana", "city": "Porto"})
    sessions = [b["items"][0]["session"] for r, _, b in recorder.sent if r == "add"]
    assert len(sessions) == 2 and sessions[0] != sessions[1]


def test_an_empty_result_saves_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CrewAI itself refuses a task whose answer is empty, so this is the file's own rule: a
    task that found nothing is not sent to memory."""
    module, recorder = load(tmp_path, monkeypatch)
    memory_ = module.TwinMemory()
    blank = "Task: Plan a weekend.\nAgent: Travel planner\nExpected result: A plan.\nResult:   "
    assert memory_.extract_memories(blank) == []
    assert memory_.extract_memories(blank.rstrip() + " Porto.") != []
    module.whose({"user_id": "dana"})
    memory_.remember_many(["", "  "], agent_role="Travel planner")
    assert "add" not in recorder.routes()


def test_remember_returns_a_record_the_save_tool_can_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, recorder = load(tmp_path, monkeypatch)
    module.whose({"user_id": "dana"})
    record = module.TwinMemory().remember("Prefers trains.")
    assert record is not None and record.content == "Prefers trains."
    assert hasattr(record, "scope") and hasattr(record, "importance")
    assert recorder.routes("dana")[-1] == "add"


# ------------------------------------------------------------------------- whose memory --


@pytest.mark.parametrize("inputs", [{}, {"user_id": ""}, {"user_id": None}])
def test_a_run_without_a_user_stops_before_any_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inputs: dict[str, Any]
) -> None:
    module, recorder = load(tmp_path, monkeypatch)
    llm = stand()
    with pytest.raises(ValueError, match='inputs=\\{"user_id"'):
        crew_of(module, llm).kickoff(inputs={"city": "Porto", **inputs})
    assert llm.prompts == [] and recorder.sent == []


def test_a_wrong_key_stops_the_run_at_kickoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _ = load(tmp_path, monkeypatch, lambda r: ok({"detail": "bad key"}, status=401))
    llm = stand()
    with pytest.raises(AuthenticationError):
        crew_of(module, llm).kickoff(inputs={"user_id": "dana", "city": "Porto"})
    assert llm.prompts == []


def test_the_key_is_checked_once_per_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, recorder = load(tmp_path, monkeypatch)
    crew = crew_of(module, stand())
    crew.kickoff(inputs={"user_id": "dana", "city": "Porto"})
    crew.kickoff(inputs={"user_id": "sam", "city": "Faro"})
    assert recorder.routes().count("me") == 1


def test_a_failed_run_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, recorder = load(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError):
        crew_of(module, stand(*[RuntimeError("model down")] * 20)).kickoff(
            inputs={"user_id": "dana", "city": "Porto"}
        )
    recorder.sent.clear()
    crew_of(module, stand()).kickoff(inputs={"user_id": "sam", "city": "Faro"})
    assert {a for r, a, _ in recorder.sent if r != "me"} == {"sam"}


def test_one_memory_shared_by_runs_for_different_users_keeps_them_apart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A JSON crew's memory is one module-level object for every run; it holds no user."""
    module, recorder = load(tmp_path, monkeypatch)
    for user, city in (("dana", "Porto"), ("sam", "Faro")):
        crew_of(module, stand(), memory=module.twin_memory).kickoff(
            inputs={"user_id": user, "city": city}
        )
    for route, account, body in recorder.sent:
        if route in ("search", "add"):
            text = json.dumps(body)
            assert ("Porto" in text) == (account == "dana") and ("Faro" in text) == (
                account == "sam"
            )


def test_concurrent_runs_never_mix_users(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, recorder = load(tmp_path, monkeypatch)
    pairs = {"ann": "Porto", "ben": "Faro", "cy": "Braga", "di": "Evora"}
    shared = module.TwinMemory()
    crew = crew_of(module, stand(), memory=shared)

    async def all_at_once() -> None:
        await crew.kickoff_for_each_async(
            inputs=[{"user_id": u, "city": c} for u, c in pairs.items()]
        )

    asyncio.run(all_at_once())
    seen = [(a, json.dumps(b)) for r, a, b in recorder.sent if r in ("search", "add")]
    assert {a for a, _ in seen} == set(pairs)
    for account, text in seen:
        assert pairs[account] in text, (account, text)
        assert all(city not in text for user, city in pairs.items() if user != account)


# ------------------------------------------------------------------------- memory down --


def test_memory_down_lets_the_crew_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    module, _ = load(tmp_path, monkeypatch, lambda r: ok({"detail": "rebuilding"}, status=503))
    out = crew_of(module, stand()).kickoff(inputs={"user_id": "dana", "city": "Porto"})
    assert getattr(out, "raw", None) == "Lisbon it is."
    assert any("unavailable" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------- tools part --


def test_the_tools_only_part_binds_the_user_in_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, recorder = load(tmp_path, monkeypatch, parts=("tools", "tools_only"))
    assert not hasattr(module, "TwinMemory")
    tools = {t.name: t for t in module.memory_tools("dana")}
    assert set(tools) == {"Search memory", "Read memory", "Save to memory"}
    for each in tools.values():
        assert "user" not in json.dumps(each.args_schema.model_json_schema()).lower()
    assert "Dana lives in Lisbon." in tools["Search memory"].run(query="home")
    assert tools["Save to memory"].run(text="Prefers trains.") == "Saved."
    assert {a for _, a, _ in recorder.sent} == {"dana"}
    assert set(t.name for t in module.memory_tools("dana", writes=False)) == {
        "Search memory",
        "Read memory",
    }


def test_save_result_saves_a_finished_crews_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module, recorder = load(tmp_path, monkeypatch, parts=("tools", "tools_only"))
    out = crew_of_tools(module).kickoff(inputs={"city": "Porto"})
    module.save_result("dana", out)
    (add,) = [(a, b) for r, a, b in recorder.sent if r == "add"]
    assert add[0] == "dana" and add[1]["items"][0]["text"] == "Lisbon it is."


def crew_of_tools(module: ModuleType) -> Crew:
    planner = Agent(
        role="Travel planner",
        goal="Plan trips",
        backstory="Plans trips.",
        llm=stand(),
        tools=module.memory_tools("dana"),
    )
    task = Task(description="Plan a weekend in {city}.", expected_output="A plan.", agent=planner)
    return Crew(agents=[planner], tasks=[task])


# --------------------------------------------------------------------------- written clean --


@pytest.mark.parametrize("parts", [("auto", "tools"), ("tools", "tools_only")])
@pytest.mark.parametrize("fast", ["False", "True"])
def test_every_part_writes_clean_code(tmp_path: Path, parts: tuple[str, ...], fast: str) -> None:
    path = tmp_path / "memory.py"
    path.write_text(render("crewai/memory.py.tmpl", parts, {"version": "0.2.0", "fast": fast}))
    lint_clean(path)


def test_native_async_runs_never_mix_users(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`akickoff` runs on the event loop rather than a thread; each run still keeps its user."""
    module, recorder = load(tmp_path, monkeypatch)
    pairs = {"ann": "Porto", "ben": "Faro"}

    async def both() -> None:
        crews = [crew_of(module, stand(), memory=module.twin_memory) for _ in pairs]
        await asyncio.gather(
            *(
                c.akickoff(inputs={"user_id": u, "city": city})
                for c, (u, city) in zip(crews, pairs.items(), strict=True)
            )
        )

    asyncio.run(both())
    seen = [(a, json.dumps(b)) for r, a, b in recorder.sent if r in ("search", "add")]
    assert {a for a, _ in seen} == set(pairs)
    for account, text in seen:
        assert pairs[account] in text and all(
            c not in text for u, c in pairs.items() if u != account
        )
