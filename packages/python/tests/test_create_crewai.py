# pyright: reportMissingImports=false
# CrewAI and the OpenAI Agents SDK are never installed together (see pyproject.toml).
"""`twinmemory-cli create crewai <name>`: a classic crew with memory wired in - its files, what it
installs, and the crew itself, run with a stand-in model against a recorded memory API."""

from __future__ import annotations

import importlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import memory
from test_cli import lint_clean

from twinmemory_cli import env, main
from twinmemory_cli.create_crewai import DEFAULT_MODEL, create
from twinmemory_cli.scaffold import Options
from twinmemory_cli.ui import Console

os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")


class Recorder:
    def __init__(self) -> None:
        self.ran: list[list[str]] = []

    def __call__(self, command: Sequence[str], cwd: Path) -> int:
        self.ran.append(list(command))
        return 0


@pytest.fixture(autouse=True)
def no_key_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        env,
        "check",
        lambda key, base_url, timeout=10.0: env.Check(True, True, "o/p, reads and writes"),
    )
    monkeypatch.delenv(env.KEY, raising=False)
    monkeypatch.delenv(env.BASE_URL, raising=False)


def made(
    tmp_path: Path, name: str = "trip-crew", model: str = DEFAULT_MODEL, **given: Any
) -> tuple[int, Console, Recorder]:
    recorder = Recorder()
    given.setdefault("skip_key", True)
    console = Console(out=lambda _: None)
    code = create(
        name, tmp_path, model, Options(run=recorder, framework="crewai", **given), console
    )
    return code, console, recorder


def said(console: Console) -> str:
    return "\n".join(console.said)


def test_create_makes_a_classic_crew_with_memory_wired_in(tmp_path: Path) -> None:
    code, console, recorder = made(tmp_path)
    assert code == 0
    root = tmp_path / "trip-crew"
    for path in ("pyproject.toml", "README.md", ".gitignore", ".env", ".env.example"):
        assert (root / path).exists(), path
    home = root / "src" / "trip_crew"
    for path in (
        "__init__.py",
        "crew.py",
        "main.py",
        "memory.py",
        "config/agents.yaml",
        "config/tasks.yaml",
    ):
        assert (home / path).exists(), path
    assert '[tool.crewai]\ntype = "crew"' in (root / "pyproject.toml").read_text()
    assert "memory = TwinMemory()" in (home / "crew.py").read_text()
    assert env.read(root / ".env") == {"MODEL": DEFAULT_MODEL, "ANTHROPIC_API_KEY": "", env.KEY: ""}
    assert recorder.ran == [
        ["uv", "add", "twinmemory>=0.2", "crewai[anthropic]>=1.15", "python-dotenv"]
    ]
    assert "uv run run_crew --user dana" in said(console)


@pytest.mark.parametrize(
    ("model", "package", "key"),
    [
        ("openai/gpt-5-mini", "crewai>=1.15", "OPENAI_API_KEY"),
        ("openrouter/deepseek/deepseek-v4.1-flash", "crewai>=1.15", "OPENROUTER_API_KEY"),
        ("gemini/gemini-3-flash", "crewai[google-genai]>=1.15", "GEMINI_API_KEY"),
    ],
)
def test_the_model_decides_crewais_extra_and_the_key(
    tmp_path: Path, model: str, package: str, key: str
) -> None:
    _, _, recorder = made(tmp_path, model=model)
    assert recorder.ran[0][3] == package
    assert key in env.read(tmp_path / "trip-crew" / ".env")


def test_a_full_directory_and_a_bad_name_are_refused(tmp_path: Path) -> None:
    (tmp_path / "trip-crew").mkdir()
    (tmp_path / "trip-crew" / "notes.txt").write_text("mine")
    assert made(tmp_path)[0] == 1
    assert made(tmp_path, name="9lives")[0] == 2


def test_dry_run_makes_nothing(tmp_path: Path) -> None:
    code, console, recorder = made(tmp_path, dry_run=True)
    assert code == 0 and recorder.ran == [] and list(tmp_path.iterdir()) == []
    assert "would    write src/trip_crew/crew.py" in said(console)


@pytest.mark.parametrize("parts", [("nodes", "tools"), ("tools",)])
def test_every_created_file_is_clean(tmp_path: Path, parts: tuple[str, ...]) -> None:
    made(tmp_path, parts=parts)
    for path in (tmp_path / "trip-crew" / "src" / "trip_crew").glob("*.py"):
        if path.stat().st_size:
            lint_clean(path)


def test_the_command_line_makes_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert (
        main(["create", "crewai", "my-crew", "--no-install", "--yes"], Console(out=lambda _: None))
        == 0
    )
    assert (tmp_path / "my-crew" / "src" / "my_crew" / "crew.py").exists()


# ---------------------------------------------- the created crew, run with a stand-in model --

pytest.importorskip("crewai")

from test_crewai_template import answering, stand  # noqa: E402


def run_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parts: tuple[str, ...], *answers: Any
) -> tuple[Any, list[tuple[str, str, Any]]]:
    made(tmp_path, parts=parts)
    monkeypatch.syspath_prepend(str(tmp_path / "trip-crew" / "src"))
    for name in [m for m in sys.modules if m.startswith("trip_crew")]:
        monkeypatch.delitem(sys.modules, name)
    memory_module = importlib.import_module("trip_crew.memory")
    crew_module = importlib.import_module("trip_crew.crew")
    sent: list[tuple[str, str, Any]] = []

    def recorded(request: httpx.Request) -> httpx.Response:
        sent.append(
            (
                request.url.path.rsplit("/", 1)[-1],
                request.headers.get("X-Twin-Account", ""),
                json.loads(request.content) if request.content else None,
            )
        )
        return answering(request)

    client, _ = memory(recorded, fail_open=True, max_retries=0)
    monkeypatch.setattr(memory_module, "_memory", lambda: client)
    monkeypatch.setattr(crew_module, "MODEL", stand(*answers))
    return crew_module, sent


def test_the_created_crew_recalls_and_saves_for_its_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    crew_module, sent = run_created(tmp_path, monkeypatch, ("nodes", "tools"))
    out = (
        crew_module.TripCrew()
        .crew()
        .kickoff(inputs={"user_id": "dana", "question": "Where do I live?"})
    )
    assert getattr(out, "raw", None) == "Lisbon it is."
    assert [r for r, a, _ in sent if a == "dana" and r != "me"] == ["search", "add"]


def test_the_tools_only_crew_saves_its_result_after_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, sent = run_created(tmp_path, monkeypatch, ("tools",))
    main_module = importlib.import_module("trip_crew.main")
    main_module.ask("dana", "Where do I live?")
    assert [r for r, a, _ in sent if a == "dana"] == ["add"]


def test_the_tools_only_crews_tools_are_for_the_runs_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CrewBase makes the agents when the crew class is made, so the user is given then."""
    crew_module, _ = run_created(tmp_path, monkeypatch, ("tools",))
    (agent,) = crew_module.TripCrew("dana").crew().agents
    assert {getattr(t, "user_id", None) for t in agent.tools} == {"dana"}


def test_create_checks_the_crewai_it_installed(tmp_path: Path) -> None:
    """`uv add crewai>=1.15` takes the newest CrewAI, which may be newer than was tested."""

    class Installs(Recorder):
        def __call__(self, command: Sequence[str], cwd: Path) -> int:
            site = cwd / ".venv" / "lib" / "python3.12" / "site-packages"
            (site / "crewai-1.17.0.dist-info").mkdir(parents=True)
            return super().__call__(command, cwd)

    console = Console(out=lambda _: None)
    options = Options(run=Installs(), framework="crewai", skip_key=True)
    assert create("trip-crew", tmp_path, DEFAULT_MODEL, options, console) == 0
    assert "crewai 1.17.0 is newer than this release was tested with" in said(console)
