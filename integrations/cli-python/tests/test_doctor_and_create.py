"""`alexein-cli doctor` and `alexein-cli create langgraph`: the check of a project's
setup, and a new project with memory wired in - run here with a stand-in model and a recorded
memory API."""

from __future__ import annotations

import importlib
import json
import os
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from alexein import Memory
from conftest import answer, wire
from test_cli import lint_clean

from alexein_cli import create as creating
from alexein_cli import doctor as checking
from alexein_cli import env
from alexein_cli.create import create
from alexein_cli.doctor import doctor
from alexein_cli.render import render
from alexein_cli.scaffold import Options
from alexein_cli.ui import Console

# The key's real check, kept before the fixture below answers it here.
real_check = env.check


@pytest.fixture(autouse=True)
def checked(monkeypatch: pytest.MonkeyPatch) -> list[env.Check]:
    """The key's check, answered here; set `checked[0]` to change the answer."""
    answers = [env.Check(True, True, "scratch/demo, reads and writes")]
    monkeypatch.setattr(env, "check", lambda key, base_url, timeout=10.0: answers[0])
    monkeypatch.delenv(env.KEY, raising=False)
    monkeypatch.delenv(env.BASE_URL, raising=False)
    return answers


@pytest.fixture(autouse=True)
def imports(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """The import check, run in the project's own Python: recorded and answered here (set
    `imports[0]` to a module's name to make it fail). The real one is tested below."""
    failing: list[list[str]] = [[]]

    def ran(command: list[str], **_: Any) -> Any:
        module = command[-1].removeprefix("import ")
        failed = module in failing[0]
        error = f"ModuleNotFoundError: No module named '{module.split('.')[-1]}'"
        return type("Done", (), {"returncode": int(failed), "stderr": error if failed else ""})

    monkeypatch.setattr(checking.subprocess, "run", ran)
    return failing


def quiet(**fields: Any) -> Console:
    return Console(out=lambda _: None, **fields)


def said(console: Console) -> str:
    return "\n".join(console.said)


def default_address() -> str:
    """Where the client sends requests when nothing names an address: its own default."""
    with Memory("tm_x") as client:
        return client.base_url


# --------------------------------------------------------------------------------- doctor --


def healthy(root: Path) -> Path:
    deps = '"langgraph>=1", "alexein[langgraph]>=0.3"'
    (root / "pyproject.toml").write_text(f'[project]\nname = "a"\ndependencies = [{deps}]\n')
    site = root / ".venv" / "lib" / "python3.12" / "site-packages"
    for dist in ("langgraph-1.2.16", "langchain-1.4.7", "alexein-0.3.0"):
        (site / f"{dist}.dist-info").mkdir(parents=True)
    (root / ".venv" / "bin").mkdir()
    (root / ".venv" / "bin" / "python").write_text("")
    (root / "app").mkdir()
    values = {"version": "0.3.0", "fast": "False"}
    (root / "app" / "memory.py").write_text(render("langgraph/memory.py.tmpl", (), values))
    (root / ".env").write_text(f"{env.KEY}=tm_x\n")
    (root / ".gitignore").write_text(".env\n")
    return root


def test_doctor_passes_a_project_that_is_set_up(tmp_path: Path) -> None:
    console = quiet()
    assert doctor(healthy(tmp_path), console) == 0
    text = said(console)
    assert "✓ memory file app/memory.py (written by 0.3.0, for LangGraph)" in text
    assert "✓ dependencies: alexein[langgraph]>=0.3" in text
    assert "✓ alexein 0.3.0" in text and "✓ langgraph 1.2.16" in text
    assert "✓ alexein.langgraph imports" in text
    assert f"✓ {env.KEY} from .env" in text
    assert f"✓ key at {default_address()}: scratch/demo, reads and writes" in text
    assert "All good." in text


def test_doctor_names_the_address_the_client_calls(tmp_path: Path) -> None:
    """The client's own address, not one written here: its default when nothing names one,
    else the project's, as the client reads it."""
    root = healthy(tmp_path)
    console = quiet()
    assert doctor(root, console) == 0
    assert f"✓ key at {default_address()}: scratch/demo" in said(console)

    (root / ".env").write_text(f"{env.KEY}=tm_x\n{env.BASE_URL}=https://memory.example.com/\n")
    console = quiet()
    assert doctor(root, console) == 0
    assert f"✓ {env.BASE_URL} from .env: https://memory.example.com/" in said(console)
    assert "✓ key at https://memory.example.com: scratch/demo" in said(console)


def test_doctor_reads_the_key_and_address_from_the_environment_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = healthy(tmp_path)
    (root / ".env").write_text("")
    monkeypatch.setenv(env.KEY, "tm_env")
    monkeypatch.setenv(env.BASE_URL, "http://localhost:8210")
    console = quiet()
    assert doctor(root, console) == 0
    text = said(console)
    assert f"✓ {env.KEY} from the environment" in text
    assert f"✓ {env.BASE_URL} from the environment: http://localhost:8210" in text
    assert "✓ key at http://localhost:8210: scratch/demo" in text


def test_doctor_notes_a_key_set_differently_in_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = healthy(tmp_path)
    monkeypatch.setenv(env.KEY, "tm_other")
    console = quiet()
    assert doctor(root, console) == 0
    assert f"- {env.KEY} is set in .env and in the environment, differently" in said(console)


@pytest.mark.parametrize("base_url", [None, "https://memory.example.com/"])
def test_the_key_is_checked_where_doctor_says(
    base_url: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real check, with its request answered here: it goes to `env.address`, the address
    doctor names."""
    named = env.address(base_url)
    sent: list[str] = []

    def answered(request: httpx.Request) -> httpx.Response:
        sent.append(str(request.url))
        return httpx.Response(200, json={"kind": "key", "org": "o", "project": "p", "writes": True})

    def client(key: str, **options: Any) -> Memory:
        http = httpx.Client(transport=httpx.MockTransport(answered))
        return Memory(key, http_client=http, **options)

    monkeypatch.setattr(env, "Memory", client)
    assert real_check("tm_x", base_url) == env.Check(True, True, "o/p, reads and writes")
    assert sent == [f"{named}/v2/me"]


def test_the_key_check_uses_the_consoles_names(monkeypatch: pytest.MonkeyPatch) -> None:
    def answered(request: httpx.Request) -> httpx.Response:
        me = {"kind": "key", "org": "o7k2", "org_name": "Acme", "project": "production"}
        return httpx.Response(200, json={**me, "project_name": "Production", "writes": False})

    def client(key: str, **options: Any) -> Memory:
        http = httpx.Client(transport=httpx.MockTransport(answered))
        return Memory(key, http_client=http, **options)

    monkeypatch.setattr(env, "Memory", client)
    assert real_check("tm_x", None) == env.Check(True, False, "Acme/Production, reads only")


def test_a_key_the_service_does_not_know(monkeypatch: pytest.MonkeyPatch) -> None:
    def client(key: str, **options: Any) -> Memory:
        refused = httpx.MockTransport(lambda r: httpx.Response(401, json={"detail": "no"}))
        return Memory(key, http_client=httpx.Client(transport=refused), **options)

    monkeypatch.setattr(env, "Memory", client)
    assert real_check("tm_x", None) == env.Check(False, None, "the service does not know this key")


def test_doctor_says_what_is_missing_and_how_to_fix_it(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "a"\ndependencies = []\n')
    console = quiet()

    assert doctor(tmp_path, console) == 1

    text = said(console)
    assert "✗ no memory file" in text and "alexein-cli init langgraph" in text
    assert "✗ not dependencies: alexein[langgraph]>=0.3" in text
    assert "- installed versions not checked" in text
    assert "- imports not checked" in text
    assert f"✗ no {env.KEY}" in text


def test_doctor_finds_the_extra_missing(tmp_path: Path, imports: list[list[str]]) -> None:
    root = healthy(tmp_path)
    (root / "pyproject.toml").write_text('[project]\nname = "a"\ndependencies = ["alexein"]\n')
    imports[0] = ["alexein.langgraph"]
    console = quiet()
    assert doctor(root, console) == 1
    text = said(console)
    assert "✗ not dependencies: alexein[langgraph]>=0.3" in text
    assert "✗ alexein.langgraph does not import: ModuleNotFoundError" in text
    fix = text.split("does not import")[1].splitlines()[1].strip()
    assert fix in ("uv add 'alexein[langgraph]>=0.3'", "pip install 'alexein[langgraph]>=0.3'")


def test_the_import_check_runs_in_the_projects_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real check: the project's interpreter imports the integration module, or says why."""
    monkeypatch.undo()
    root = tmp_path
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    os.chmod(python, 0o755)
    console = quiet()
    assert checking._importable(root, ["langgraph"], console)  # pyright: ignore[reportPrivateUsage]
    assert "✓ alexein.langgraph imports" in said(console)
    python.write_text("#!/bin/sh\necho 'ImportError: nope' >&2\nexit 1\n")
    os.chmod(python, 0o755)
    console = quiet()
    assert not checking._importable(root, ["crewai"], console)  # pyright: ignore[reportPrivateUsage]
    assert "✗ alexein.crewai does not import: ImportError: nope" in said(console)


def test_doctor_catches_an_old_version_and_a_bad_key(
    tmp_path: Path, checked: list[env.Check]
) -> None:
    root = healthy(tmp_path)
    site = root / ".venv" / "lib" / "python3.12" / "site-packages"
    (site / "langgraph-1.2.16.dist-info").rename(site / "langgraph-0.6.0.dist-info")
    checked[0] = env.Check(False, None, "the service does not know this key")
    console = quiet()

    assert doctor(root, console) == 1

    assert "✗ langgraph 0.6.0 is older than 1.2" in said(console)
    assert f"✗ key at {default_address()}: the service does not know this key" in said(console)


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
        ["uv", "add", "alexein[langgraph]>=0.3", "python-dotenv", "langchain-anthropic"],
        ["uv", "add", "--dev", "langgraph-cli[inmem]"],
    ]
    assert "uv run -m my_agent.chat --user dana" in said(console)
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


@pytest.mark.parametrize("fast", [False, True])
def test_every_created_file_is_clean(tmp_path: Path, fast: bool) -> None:
    made(tmp_path, fast=fast)
    for path in (tmp_path / "my-agent" / "src" / "my_agent").glob("*.py"):
        if path.stat().st_size:
            lint_clean(path)


# ----------------------------------------- the created graph, run with a stand-in model --

pytest.importorskip("langgraph")

from langchain_core.language_models.fake_chat_models import (  # noqa: E402
    GenericFakeChatModel,
)
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402


@pytest.fixture
def created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Make a project, import its graph with no key set, stand in for its model and memory."""

    def make(replies: list[AIMessage]) -> tuple[Any, Any]:
        made(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path / "my-agent" / "src"))
        for name in [m for m in sys.modules if m.startswith("my_agent")]:
            monkeypatch.delitem(sys.modules, name)
        graph_module = importlib.import_module("my_agent.graph")  # needs no key
        monkeypatch.setenv(env.KEY, "tm_test")
        recorded = wire(monkeypatch, answer)
        model = GenericFakeChatModel(messages=iter(replies))
        monkeypatch.setattr(graph_module, "_model", lambda: model)
        return graph_module.graph, recorded

    yield make


SEARCH_CALL = AIMessage(
    "", tool_calls=[{"name": "memory_search", "args": {"query": "home"}, "id": "c1"}]
)


def run(graph: Any, asynchronous: bool) -> Any:
    inputs = {"messages": [HumanMessage("Where do I live?", id="h-1")]}
    config = {"configurable": {"thread_id": "t-1"}}
    if asynchronous:
        import asyncio

        return asyncio.run(graph.ainvoke(inputs, config=config, context={"user_id": "dana"}))
    return graph.invoke(inputs, config=config, context={"user_id": "dana"})


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_the_created_graph_recalls_searches_and_remembers(created: Any, asynchronous: bool) -> None:
    graph, recorded = created([SEARCH_CALL, AIMessage("Lisbon.", id="ai-1")])
    out = run(graph, asynchronous)
    assert out["messages"][-1].text == "Lisbon."
    assert recorded.routes() == ["search", "search", "add"]  # recall, the tool, remember
    assert recorded.users() == {"dana"}
    assert json.loads(recorded.last.content)["items"][0]["session"] == "t-1"


def test_the_chat_ends_quietly_when_its_input_does(
    created: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ctrl-D, or piped input with no empty line at the end, ends the conversation."""
    import io

    created([AIMessage("Lisbon.", id="ai-1"), AIMessage("Dana.", id="ai-2")])
    chat = importlib.import_module("my_agent.chat")
    monkeypatch.setattr(sys, "argv", ["chat", "--user", "dana"])
    monkeypatch.setattr(sys, "stdin", io.StringIO("Where do I live?\nWho am I?\n"))
    chat.main()
    out = capsys.readouterr().out
    assert "agent> Lisbon." in out and "agent> Dana." in out


def test_doctor_notes_a_read_only_key(tmp_path: Path, checked: list[env.Check]) -> None:
    """Whether the developer wires `remember` in is theirs to say: a key that only reads is
    noted, not failed."""
    root = healthy(tmp_path)
    checked[0] = env.Check(True, False, "scratch/demo, reads only")
    console = quiet()
    assert doctor(root, console) == 0
    assert "- the key only reads: remember, memory_add" in said(console)


def test_create_asks_only_for_the_keys_still_unset(tmp_path: Path) -> None:
    _, console, _ = made(tmp_path, key="tm_k")
    assert "fill in ANTHROPIC_API_KEY in .env" in said(console)
    assert f"{env.KEY} in .env" not in said(console).split("Next:")[1]


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
