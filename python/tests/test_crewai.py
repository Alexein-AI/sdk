# pyright: reportMissingImports=false
# CrewAI and the OpenAI Agents SDK are never installed together (see pyproject.toml).
"""`alexein.crewai`, run inside real CrewAI crews - CrewAI's own classes, with a stand-in model -
against a recorded memory API."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx
import pytest
from conftest import EMPTY_SEARCH, SEARCHED, memory, ok, route

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
pytest.importorskip("crewai")

from crewai import Agent, Crew, Task
from crewai.llms.base_llm import BaseLLM
from pydantic import Field

import alexein.crewai as cw
from alexein import AlexeinError, AuthenticationError


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
    """What the memory API was sent: route, app user, body."""

    def __init__(self, answer: Any) -> None:
        self.sent: list[tuple[str, str, Any]] = []
        self.answer = answer

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.sent.append((route(request), request.headers.get("x-alexein-user", ""), body))
        return self.answer(request)

    def routes(self, user: str | None = None) -> list[str]:
        return [r for r, u, _ in self.sent if user is None or u == user]


def answering(request: httpx.Request) -> httpx.Response:
    name = route(request)
    if name == "me":
        return ok({"kind": "key", "org": "o", "project": "p", "writes": True})
    if name == "search":
        return ok(SEARCHED)
    if name == "add":
        items = json.loads(request.content)["items"]
        return ok(
            {"items": [{"id": i.get("id", ""), "status": "queued"} for i in items], "waiting": 1},
            status=202,
        )
    return ok()


def wired(answer: Any = answering, *, strict: bool = False) -> tuple[cw.AlexeinMemory, Recorder]:
    recorder = Recorder(answer)
    client, _ = memory(recorder, fail_open=not strict, integration="crewai", max_retries=0)
    return cw.AlexeinMemory(client, strict=strict), recorder


def crew_of(mem: cw.AlexeinMemory, llm: Stand, *, hook: bool = True) -> Crew:
    planner = Agent(role="Travel planner", goal="Plan trips", backstory="Plans trips.", llm=llm)
    task = Task(description="Plan a weekend in {city}.", expected_output="A plan.", agent=planner)
    return Crew(
        agents=[planner],
        tasks=[task],
        memory=mem,
        before_kickoff_callbacks=[mem.whose] if hook else [],
    )


# ---------------------------------------------------------------------------------- recall --


def test_a_task_recalls_the_users_memory_into_its_prompt():
    mem, recorder = wired()
    llm = stand()
    crew_of(mem, llm).kickoff(inputs={"user_id": "dana", "city": "Porto"})
    searches = [(u, b) for r, u, b in recorder.sent if r == "search"]
    assert searches and searches[0] == ("dana", {"query": "Plan a weekend in Porto."})
    assert "Dana lives in Lisbon." in llm.prompts[0]


def test_recall_returns_at_most_the_limit_best_first_with_refs():
    mem, _ = wired()
    mem.whose({"user_id": "dana"})
    matches = mem.recall("where", limit=3)
    assert [m.record.content for m in matches] == [
        "Dana lives in Lisbon.",
        "Dana moved to Lisbon for a job at Acme.",
        "2026-10-01: Dana: I moved to Lisbon for the job at Acme.",
    ]
    assert [m.record.metadata for m in matches] == [{}, {"ref": "mem_f1"}, {"ref": "mem_e1"}]
    assert matches[0].score >= matches[1].score >= matches[2].score
    assert len(mem.recall("where", limit=1)) == 1


def test_a_user_with_no_memory_yet_recalls_nothing():
    mem, _ = wired(lambda r: ok(EMPTY_SEARCH) if route(r) == "search" else answering(r))
    mem.whose({"user_id": "new"})
    assert mem.recall("anything") == []


def test_one_huge_line_is_cut_to_max_chars():
    huge = {"query": "q", "memories": [{"type": "known", "text": "x" * 10_000}]}
    mem, _ = wired(lambda r: ok(huge) if route(r) == "search" else answering(r))
    mem.whose({"user_id": "dana"})
    (match,) = mem.recall("anything")
    assert len(match.record.content) == mem.max_chars


def test_recall_takes_arguments_a_newer_crewai_may_pass():
    mem, _ = wired()
    mem.whose({"user_id": "dana"})
    assert mem.recall("where", None, None, limit=1, some_new_option=True) != []


# ------------------------------------------------------------------------------------ save --


def test_a_tasks_result_is_saved_under_the_user_with_the_agents_role():
    mem, recorder = wired()
    crew_of(mem, stand()).kickoff(inputs={"user_id": "dana", "city": "Porto"})
    adds = [(u, b) for r, u, b in recorder.sent if r == "add"]
    assert len(adds) == 1 and adds[0][0] == "dana"
    (item,) = adds[0][1]["items"]
    assert item["kind"] == "note" and item["author"] == "Travel planner"
    assert "Lisbon it is." in item["text"] and item["session"] and item["id"]


def test_one_kickoff_is_one_session_and_the_next_is_another():
    mem, recorder = wired()
    crew = crew_of(mem, stand())
    crew.kickoff(inputs={"user_id": "dana", "city": "Porto"})
    crew.kickoff(inputs={"user_id": "dana", "city": "Porto"})
    sessions = [b["items"][0]["session"] for r, _, b in recorder.sent if r == "add"]
    assert len(sessions) == 2 and sessions[0] != sessions[1]


def test_an_empty_result_saves_nothing():
    mem, recorder = wired()
    blank = "Task: Plan a weekend.\nAgent: Travel planner\nExpected result: A plan.\nResult:   "
    assert mem.extract_memories(blank) == []
    assert mem.extract_memories(blank.rstrip() + " Porto.") != []
    assert mem.extract_memories(blank.rstrip() + " The report.\nResult:") != []
    mem.whose({"user_id": "dana"})
    mem.remember_many(["", "  "], agent_role="Travel planner")
    assert "add" not in recorder.routes()


def test_remember_returns_a_record():
    mem, recorder = wired()
    mem.whose({"user_id": "dana"})
    record = mem.remember("Prefers trains.")
    assert record is not None and record.content == "Prefers trains."
    assert recorder.routes("dana")[-1] == "add"


def test_forget_and_reset_point_to_the_client():
    mem, _ = wired()
    with pytest.raises(NotImplementedError, match="forget"):
        mem.forget()
    with pytest.raises(NotImplementedError):
        mem.reset()


# ------------------------------------------------------------------------- whose memory --


@pytest.mark.parametrize("inputs", [{}, {"user_id": ""}, {"user_id": None}])
def test_a_run_without_a_user_stops_before_any_task(inputs: dict[str, Any]):
    mem, recorder = wired()
    llm = stand()
    with pytest.raises(ValueError, match='inputs=\\{"user_id"'):
        crew_of(mem, llm).kickoff(inputs={"city": "Porto", **inputs})
    assert llm.prompts == [] and recorder.sent == []


def test_a_wrong_key_stops_the_run_at_kickoff():
    mem, _ = wired(lambda r: ok({"detail": "bad key"}, status=401))
    llm = stand()
    with pytest.raises(AuthenticationError):
        crew_of(mem, llm).kickoff(inputs={"user_id": "dana", "city": "Porto"})
    assert llm.prompts == []


def test_the_key_is_checked_once():
    mem, recorder = wired()
    crew = crew_of(mem, stand())
    crew.kickoff(inputs={"user_id": "dana", "city": "Porto"})
    crew.kickoff(inputs={"user_id": "sam", "city": "Faro"})
    assert recorder.routes().count("me") == 1


def test_a_failed_run_leaves_nothing_behind():
    mem, recorder = wired()
    with pytest.raises(RuntimeError):
        crew_of(mem, stand(*[RuntimeError("model down")] * 20)).kickoff(
            inputs={"user_id": "dana", "city": "Porto"}
        )
    recorder.sent.clear()
    crew_of(mem, stand()).kickoff(inputs={"user_id": "sam", "city": "Faro"})
    assert {u for r, u, _ in recorder.sent if r != "me"} == {"sam"}


def test_a_crew_without_whose_never_uses_the_last_runs_user(caplog: pytest.LogCaptureFixture):
    """A second crew on the same memory that skips the hook must not read or save as the user
    the first crew's run named: a wrong user is worse than no memory."""
    mem, recorder = wired()
    crew_of(mem, stand()).kickoff(inputs={"user_id": "dana", "city": "Porto"})
    recorder.sent.clear()
    out = crew_of(mem, stand(), hook=False).kickoff(inputs={"user_id": "sam", "city": "Faro"})
    assert getattr(out, "raw", None) == "Lisbon it is."
    assert recorder.sent == []
    assert any("whose" in r.message for r in caplog.records)


@pytest.mark.parametrize("user_id", ["dana@example.com", "dana smith", "-dana"])
def test_a_user_id_memory_cannot_hold_stops_at_kickoff(user_id: str):
    mem, recorder = wired()
    llm = stand()
    with pytest.raises(ValueError, match="not a usable app user id"):
        crew_of(mem, llm).kickoff(inputs={"user_id": user_id, "city": "Porto"})
    assert llm.prompts == [] and recorder.sent == []
    with pytest.raises(ValueError, match="not a usable app user id"):
        mem.tools(user_id)


def test_strict_stops_the_run_when_memory_is_down_at_kickoff():
    mem, _ = wired(lambda r: ok({"detail": "rebuilding"}, status=503), strict=True)
    llm = stand()
    with pytest.raises(AlexeinError):
        crew_of(mem, llm).kickoff(inputs={"user_id": "dana", "city": "Porto"})
    assert llm.prompts == []


def test_one_memory_shared_by_runs_for_different_users_keeps_them_apart():
    mem, recorder = wired()
    for user, city in (("dana", "Porto"), ("sam", "Faro")):
        crew_of(mem, stand()).kickoff(inputs={"user_id": user, "city": city})
    for name, user, body in recorder.sent:
        if name in ("search", "add"):
            text = json.dumps(body)
            assert ("Porto" in text) == (user == "dana") and ("Faro" in text) == (user == "sam")


def test_concurrent_runs_never_mix_users():
    mem, recorder = wired()
    pairs = {"ann": "Porto", "ben": "Faro", "cy": "Braga", "di": "Evora"}
    crew = crew_of(mem, stand())

    async def all_at_once() -> None:
        await crew.kickoff_for_each_async(
            inputs=[{"user_id": u, "city": c} for u, c in pairs.items()]
        )

    asyncio.run(all_at_once())
    seen = [(u, json.dumps(b)) for r, u, b in recorder.sent if r in ("search", "add")]
    assert {u for u, _ in seen} == set(pairs)
    for user, text in seen:
        assert pairs[user] in text and all(c not in text for u, c in pairs.items() if u != user)


def test_native_async_runs_never_mix_users():
    mem, recorder = wired()
    pairs = {"ann": "Porto", "ben": "Faro"}

    async def both() -> None:
        crews = [crew_of(mem, stand()) for _ in pairs]
        await asyncio.gather(
            *(
                c.akickoff(inputs={"user_id": u, "city": city})
                for c, (u, city) in zip(crews, pairs.items(), strict=True)
            )
        )

    asyncio.run(both())
    seen = [(u, json.dumps(b)) for r, u, b in recorder.sent if r in ("search", "add")]
    assert {u for u, _ in seen} == set(pairs)
    for user, text in seen:
        assert pairs[user] in text and all(c not in text for u, c in pairs.items() if u != user)


# ------------------------------------------------------------------------- memory down --


def test_memory_down_lets_the_crew_finish(caplog: pytest.LogCaptureFixture):
    mem, _ = wired(lambda r: ok({"detail": "rebuilding"}, status=503))
    out = crew_of(mem, stand()).kickoff(inputs={"user_id": "dana", "city": "Porto"})
    assert getattr(out, "raw", None) == "Lisbon it is."
    assert any("unavailable" in r.message for r in caplog.records)


# ------------------------------------------------------------------------------- tools --


def test_tools_bind_the_user_in_code():
    mem, recorder = wired()
    tools = {t.name: t for t in mem.tools("dana", write=True)}
    assert list(tools) == ["memory_search", "memory_open", "memory_add"]
    for each in tools.values():
        assert "user" not in json.dumps(each.args_schema.model_json_schema()).lower()
    found = tools["memory_search"].run(query="home")
    assert "- Dana lives in Lisbon." in found and found.endswith("- mem_f1\n- mem_e1")
    assert tools["memory_add"].run(text="Prefers trains.") == "Saved."
    assert {u for _, u, _ in recorder.sent} == {"dana"}
    assert [t.name for t in mem.tools("dana")] == ["memory_search", "memory_open"]


def test_tools_tell_the_agent_memory_is_down():
    mem, _ = wired(lambda r: ok({"detail": "rebuilding"}, status=503))
    tools = {t.name: t for t in mem.tools("dana", write=True)}
    assert tools["memory_search"].run(query="x").startswith("Memory is unavailable")
    assert tools["memory_open"].run(ref="mem_f1").startswith("Memory is unavailable")
    assert tools["memory_add"].run(text="x").startswith("Memory is unavailable")


def test_save_result_saves_a_finished_crews_result():
    mem, recorder = wired()
    planner = Agent(
        role="Travel planner",
        goal="Plan trips",
        backstory="Plans trips.",
        llm=stand(),
        tools=mem.tools("dana"),
    )
    task = Task(description="Plan a weekend in {city}.", expected_output="A plan.", agent=planner)
    out = Crew(agents=[planner], tasks=[task]).kickoff(inputs={"city": "Porto"})
    mem.save_result("dana", out)
    (add,) = [(u, b) for r, u, b in recorder.sent if r == "add"]
    assert add[0] == "dana" and add[1]["items"][0]["text"] == "Lisbon it is."


def test_the_module_level_defaults():
    assert [t.name for t in cw.memory_tools("dana")] == ["memory_search", "memory_open"]
    with pytest.raises(ValueError, match="whose memory"):
        cw.whose({})
