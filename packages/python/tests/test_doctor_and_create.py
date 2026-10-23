"""`twinmemory-cli doctor` and `twinmemory-cli create langgraph`: the check of a project's
setup, and a new project with memory wired in - run here with a stand-in model and a recorded
memory API."""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import async_memory, memory, ok
from test_cli import lint_clean

from twinmemory_cli import create as creating
from twinmemory_cli import env
from twinmemory_cli.create import create
from twinmemory_cli.doctor import doctor
from twinmemory_cli.render import render
from twinmemory_cli.scaffold import Options
from twinmemory_cli.ui import Console


@pytest.fixture(autouse=True)
def checked(monkeypatch: pytest.MonkeyPatch) -> list[env.Check]:
    """The key's check, answered here; set `checked[0]` to change the answer."""
    answers = [env.Check(True, True, "scratch/demo, reads and writes")]
    monkeypatch.setattr(env, "check", lambda key, base_url, timeout=10.0: answers[0])
    monkeypatch.delenv(env.KEY, raising=False)
    monkeypatch.delenv(env.BASE_URL, raising=False)
    return answers


def quiet(**fields: Any) -> Console:
    return Console(out=lambda _: None, **fields)


def said(console: Console) -> str:
    return "\n".join(console.said)


# --------------------------------------------------------------------------------- doctor --


def healthy(root: Path) -> Path:
    deps = '"langgraph>=1", "langchain>=1", "twinmemory>=0.2"'
    (root / "pyproject.toml").write_text(f'[project]\nname = "a"\ndependencies = [{deps}]\n')
    site = root / ".venv" / "lib" / "python3.12" / "site-packages"
    for dist in ("langgraph-1.2.16", "langchain-1.4.7", "twinmemory-0.2.0"):
        (site / f"{dist}.dist-info").mkdir(parents=True)
    (root / "app").mkdir()
    values = {"version": "0.2.0", "fast": "False"}
    (root / "app" / "memory.py").write_text(render("langgraph/memory.py.tmpl", ["nodes"], values))
    (root / ".env").write_text(f"{env.KEY}=tm_x\n")
    (root / ".gitignore").write_text(".env\n")
    return root


def test_doctor_passes_a_project_that_is_set_up(tmp_path: Path) -> None:
    console = quiet()
    assert doctor(healthy(tmp_path), console) == 0
    text = said(console)
    assert "✓ memory file app/memory.py (written by 0.2.0)" in text
    assert "✓ langgraph 1.2.16" in text
    assert "✓ key at the hosted service: scratch/demo, reads and writes" in text
    assert "All good." in text


def test_doctor_says_what_is_missing_and_how_to_fix_it(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "a"\ndependencies = []\n')
    console = quiet()

    assert doctor(tmp_path, console) == 1

    text = said(console)
    assert "✗ no memory file" in text and "twinmemory-cli init langgraph" in text
    assert "✗ not dependencies: twinmemory, langgraph, langchain" in text
    assert "- installed versions not checked" in text
    assert f"✗ no {env.KEY}" in text


def test_doctor_catches_an_old_version_and_a_bad_key(
    tmp_path: Path, checked: list[env.Check]
) -> None:
    root = healthy(tmp_path)
    site = root / ".venv" / "lib" / "python3.12" / "site-packages"
    (site / "langgraph-1.2.16.dist-info").rename(site / "langgraph-0.6.0.dist-info")
    checked[0] = env.Check(False, None, "the service does not know this key")
    console = quiet()

    assert doctor(root, console) == 1

    assert "✗ langgraph 0.6.0 is older than 1.0" in said(console)
    assert "✗ key at the hosted service: the service does not know this key" in said(console)


def test_doctor_outside_a_project(tmp_path: Path) -> None:
    assert doctor(tmp_path, quiet()) == 1


# --------------------------------------------------------------------------------- create --


class Recorder:
    def __init__(self, code: int = 0) -> None:
        self.ran: list[list[str]] = []
        self.code = code

    def __call__(self, command: Sequence[str], cwd: Path) -> int:
        self.ran.append(list(command))
        return self.code


def made(
    tmp_path: Path, name: str = "my-agent", model: str = creating.DEFAULT_MODEL, **options: Any
) -> tuple[int, Console, Recorder]:
    recorder = Recorder()
    options.setdefault("skip_key", True)
    console = quiet()
    code = create(name, tmp_path, model, Options(run=recorder, **options), console)
    return code, console, recorder


def test_create_makes_a_runnable_project(tmp_path: Path) -> None:
    code, console, recorder = made(tmp_path)

    assert code == 0
    root = tmp_path / "my-agent"
    for path in (
        "pyproject.toml",
        "langgraph.json",
        "README.md",
        ".gitignore",
        ".env",
        ".env.example",
    ):
        assert (root / path).exists(), path
    for path in ("__init__.py", "graph.py", "chat.py", "memory.py"):
        assert (root / "src" / "my_agent" / path).exists(), path
    graphs = json.loads((root / "langgraph.json").read_text())["graphs"]
    assert graphs == {"agent": "./src/my_agent/graph.py:graph"}
    assert env.read(root / ".env") == {
        "MODEL": "anthropic:claude-sonnet-5-5",
        "ANTHROPIC_API_KEY": "",
        env.KEY: "",
    }
    assert recorder.ran == [
        [
            "uv",
            "add",
            "twinmemory>=0.2",
            "langgraph>=1.0",
            "langchain>=1.0",
            "python-dotenv",
            "langchain-anthropic",
        ],
        ["uv", "add", "--dev", "langgraph-cli[inmem]"],
    ]
    assert "uv run python -m my_agent.chat --user dana" in said(console)
    assert ".env is not in .gitignore" not in said(console)


def test_create_with_another_provider_and_a_key(tmp_path: Path) -> None:
    code, _, recorder = made(tmp_path, model="openai:gpt-5", key="tm_k", base_url="http://x")
    root = tmp_path / "my-agent"
    assert code == 0
    values = env.read(root / ".env")
    assert values["MODEL"] == "openai:gpt-5" and values["OPENAI_API_KEY"] == ""
    assert values[env.KEY] == "tm_k" and values[env.BASE_URL] == "http://x"
    assert recorder.ran[0][-1] == "langchain-openai"


def test_create_with_a_provider_it_does_not_know_says_so(tmp_path: Path) -> None:
    _, console, recorder = made(tmp_path, model="somecloud:model-1")
    assert "add the LangChain package for 'somecloud:model-1' yourself" in said(console)
    assert recorder.ran[0][-1] == "python-dotenv"


def test_create_will_not_write_into_a_full_directory(tmp_path: Path) -> None:
    (tmp_path / "my-agent").mkdir()
    (tmp_path / "my-agent" / "notes.txt").write_text("mine")
    code, _, recorder = made(tmp_path)
    assert code == 1 and recorder.ran == []
    assert list((tmp_path / "my-agent").iterdir()) == [tmp_path / "my-agent" / "notes.txt"]


def test_create_needs_a_name_that_is_a_name(tmp_path: Path) -> None:
    assert made(tmp_path, name="../evil")[0] == 2
    assert made(tmp_path, name="9lives")[0] == 2


def test_create_needs_uv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(creating.shutil, "which", lambda name: None)
    code, console, _ = made(tmp_path)
    assert code == 1 and "needs uv" in said(console)


PRESETS = [
    pytest.param({}, id="both"),
    pytest.param({"asynchronous": True}, id="async"),
    pytest.param({"parts": ("nodes",)}, id="nodes-only"),
    pytest.param({"parts": ("tools",)}, id="tools-only"),
    pytest.param({"parts": ("nodes",), "asynchronous": True}, id="async-nodes-only"),
    pytest.param({"parts": ("tools",), "asynchronous": True}, id="async-tools-only"),
]


@pytest.mark.parametrize("preset", PRESETS)
def test_every_created_file_is_clean(tmp_path: Path, preset: dict[str, Any]) -> None:
    made(tmp_path, **preset)
    for path in (tmp_path / "my-agent" / "src" / "my_agent").glob("*.py"):
        if path.stat().st_size:
            lint_clean(path)


# ----------------------------------------- the created graph, run with a stand-in model --

pytest.importorskip("langgraph")

from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

SEARCHED = {"query": "q", "found": 1, "known": ["Dana lives in Lisbon."]}


def answer(request: httpx.Request) -> httpx.Response:
    route = request.url.path.rsplit("/", 1)[-1]
    if route == "search":
        return ok(SEARCHED)
    if route == "add":
        return ok({"items": [], "queued": 1, "pending": 1}, status=202)
    return ok()


@pytest.fixture
def created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Make a project with a preset, import its graph, stand in for its model and memory."""

    def make(preset: dict[str, Any], replies: list[AIMessage]) -> tuple[Any, Any]:
        made(tmp_path, **preset)
        monkeypatch.syspath_prepend(str(tmp_path / "my-agent" / "src"))
        for name in [m for m in sys.modules if m.startswith("my_agent")]:
            monkeypatch.delitem(sys.modules, name)
        memory_module = importlib.import_module("my_agent.memory")
        graph_module = importlib.import_module("my_agent.graph")
        make_client = async_memory if preset.get("asynchronous") else memory
        client, recorded = make_client(answer, fail_open=True)
        monkeypatch.setattr(memory_module, "_memory", lambda: client)
        model = GenericFakeChatModel(messages=iter(replies))
        monkeypatch.setattr(graph_module, "_model", lambda: model)
        return graph_module.graph, recorded

    yield make


SEARCH_CALL = AIMessage(
    "", tool_calls=[{"name": "memory_search", "args": {"query": "home"}, "id": "c1"}]
)


def routes(recorded: Any) -> list[str]:
    return [r.url.path.rsplit("/", 1)[-1] for r in recorded.requests]


def run(graph: Any, asynchronous: bool) -> Any:
    inputs = {"messages": [HumanMessage("Where do I live?", id="h-1")]}
    config = {"configurable": {"thread_id": "t-1"}}
    if asynchronous:
        import asyncio

        return asyncio.run(graph.ainvoke(inputs, config=config, context={"user_id": "dana"}))
    return graph.invoke(inputs, config=config, context={"user_id": "dana"})


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_the_created_graph_recalls_searches_and_remembers(created: Any, asynchronous: bool) -> None:
    graph, recorded = created(
        {"asynchronous": asynchronous}, [SEARCH_CALL, AIMessage("Lisbon.", id="ai-1")]
    )
    out = run(graph, asynchronous)
    assert out["messages"][-1].text == "Lisbon."
    assert routes(recorded) == ["search", "search", "add"]  # recall, the tool, remember


def test_the_nodes_only_graph(created: Any) -> None:
    graph, recorded = created({"parts": ("nodes",)}, [AIMessage("Lisbon.", id="ai-1")])
    run(graph, False)
    assert routes(recorded) == ["search", "add"]


def test_the_tools_only_graph_lets_the_model_save(created: Any) -> None:
    save = AIMessage(
        "", tool_calls=[{"name": "memory_add", "args": {"text": "Lives in Lisbon."}, "id": "c1"}]
    )
    graph, recorded = created({"parts": ("tools",)}, [save, AIMessage("Noted.", id="ai-1")])
    run(graph, False)
    assert routes(recorded) == ["add"]


def test_doctor_fails_a_read_only_key_when_the_file_saves(
    tmp_path: Path, checked: list[env.Check]
) -> None:
    root = healthy(tmp_path)  # its memory file has `remember`
    checked[0] = env.Check(True, False, "scratch/demo, reads only")
    console = quiet()
    assert doctor(root, console) == 1
    assert "only reads, and the memory file saves" in said(console)


def test_doctor_passes_a_read_only_key_for_a_file_that_only_reads(
    tmp_path: Path, checked: list[env.Check]
) -> None:
    root = healthy(tmp_path)
    values = {"version": "0.2.0", "fast": "False"}
    reads = render("langgraph/memory.py.tmpl", ["tools"], values)
    (root / "app" / "memory.py").write_text(reads.split("@tool\ndef memory_add")[0])  # reads only
    checked[0] = env.Check(True, False, "scratch/demo, reads only")
    assert doctor(root, quiet()) == 0


def test_create_asks_only_for_the_keys_still_unset(tmp_path: Path) -> None:
    _, console, _ = made(tmp_path, key="tm_k")
    assert "fill in ANTHROPIC_API_KEY in .env" in said(console)
    assert "TWIN_MEMORY_API_KEY in .env" not in said(console).split("Next:")[1]


def test_create_dry_run_makes_nothing(tmp_path: Path) -> None:
    code, console, recorder = made(tmp_path, dry_run=True)
    assert code == 0 and recorder.ran == [] and list(tmp_path.iterdir()) == []
    assert "would    write src/my_agent/graph.py" in said(console)


def test_create_lines_up_its_next_steps(tmp_path: Path) -> None:
    for name in ("a", "a-much-longer-agent-name"):
        _, console, _ = made(tmp_path / name, name=name, key="tm_k")
        lines = said(console).splitlines()
        steps = [line for line in lines if "  # " in line and "fill in" not in line]
        assert len(steps) == 3 and len({line.index("# ") for line in steps}) == 1, steps
