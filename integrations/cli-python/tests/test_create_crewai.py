# pyright: reportMissingImports=false
# CrewAI and the OpenAI Agents SDK are never installed together (see pyproject.toml).
"""`alexein-cli create crewai <name>`: a classic crew with memory wired in - its files, what it
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
from conftest import route, wire
from test_cli import lint_clean

from alexein_cli import env, main
from alexein_cli.create_crewai import DEFAULT_MODEL, create
from alexein_cli.scaffold import Options
from alexein_cli.ui import Console

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
    assert "memory = alexein_memory" in (home / "crew.py").read_text()
    assert env.read(root / ".env") == {"MODEL": DEFAULT_MODEL, "ANTHROPIC_API_KEY": "", env.KEY: ""}
    assert recorder.ran == [
        ["uv", "add", "alexein[crewai]>=0.3", "crewai[anthropic]>=1.15", "python-dotenv"]
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


@pytest.mark.parametrize("fast", [False, True])
def test_every_created_file_is_clean(tmp_path: Path, fast: bool) -> None:
    made(tmp_path, fast=fast)
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *answers: Any
) -> tuple[Any, list[tuple[str, str, Any]]]:
    """Make the crew, import it with no key set, stand in for its model and memory."""
    made(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path / "trip-crew" / "src"))
    for name in [m for m in sys.modules if m.startswith("trip_crew")]:
        monkeypatch.delitem(sys.modules, name)
    crew_module = importlib.import_module("trip_crew.crew")  # needs no key
    sent: list[tuple[str, str, Any]] = []

    def recorded(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        sent.append((route(request), request.headers.get("x-alexein-user", ""), body))
        return answering(request)

    monkeypatch.setenv(env.KEY, "tm_test")
    wire(monkeypatch, recorded)
    monkeypatch.setattr(crew_module, "MODEL", stand(*answers))
    return crew_module, sent


def test_the_created_crew_recalls_and_saves_for_its_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    crew_module, sent = run_created(tmp_path, monkeypatch)
    out = (
        crew_module.TripCrew()
        .crew()
        .kickoff(inputs={"user_id": "dana", "question": "Where do I live?"})
    )
    assert getattr(out, "raw", None) == "Lisbon it is."
    assert [r for r, a, _ in sent if a == "dana" and r != "me"] == ["search", "add"]


def test_the_created_crew_runs_from_its_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, sent = run_created(tmp_path, monkeypatch)
    main_module = importlib.import_module("trip_crew.main")
    assert main_module.ask("dana", "Where do I live?") == "Lisbon it is."
    assert [r for r, a, _ in sent if a == "dana"] == ["search", "add"]


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
