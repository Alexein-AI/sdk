"""`alexein-cli doctor` in a CrewAI project: the file `init crewai` wrote, the client with its
CrewAI extra, and CrewAI's version."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_crewai_project import classic

from alexein_cli import doctor as checking
from alexein_cli import env
from alexein_cli.doctor import doctor
from alexein_cli.render import render
from alexein_cli.ui import Console


@pytest.fixture(autouse=True)
def checked(monkeypatch: pytest.MonkeyPatch) -> list[env.Check]:
    answers = [env.Check(True, True, "o/p, reads and writes")]
    monkeypatch.setattr(env, "check", lambda key, base_url, timeout=10.0: answers[0])
    monkeypatch.delenv(env.KEY, raising=False)
    monkeypatch.delenv(env.BASE_URL, raising=False)
    return answers


@pytest.fixture(autouse=True)
def imports(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The import check in the project's own Python, recorded and passed here."""
    ran: list[str] = []

    def run(command: list[str], **_: Any) -> Any:
        ran.append(command[-1])
        return type("Done", (), {"returncode": 0, "stderr": ""})

    monkeypatch.setattr(checking.subprocess, "run", run)
    return ran


def said(console: Console) -> str:
    return "\n".join(console.said)


def quiet() -> Console:
    return Console(out=lambda _: None)


def healthy(root: Path, crewai: str = "1.15.28") -> Path:
    home = classic(root, "my_crew")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "my-crew"\n'
        'dependencies = ["crewai>=1.15", "alexein[crewai]>=0.3"]\n'
        '\n[tool.crewai]\ntype = "crew"\n'
    )
    site = root / ".venv" / "lib" / "python3.12" / "site-packages"
    for dist in (f"crewai-{crewai}", "alexein-0.3.0"):
        (site / f"{dist}.dist-info").mkdir(parents=True)
    (root / ".venv" / "bin").mkdir()
    (root / ".venv" / "bin" / "python").write_text("")
    values = {"version": "0.3.0", "fast": "False"}
    (home / "memory.py").write_text(render("crewai/memory.py.tmpl", (), values))
    (root / ".env").write_text(f"{env.KEY}=tm_x\n")
    (root / ".gitignore").write_text(".env\n")
    return home


def test_doctor_passes_a_crew_that_is_set_up(tmp_path: Path, imports: list[str]) -> None:
    healthy(tmp_path)
    console = quiet()
    assert doctor(tmp_path, console) == 0
    text = said(console)
    assert "✓ memory file src/my_crew/memory.py (written by 0.3.0, for CrewAI)" in text
    assert "✓ dependencies: alexein[crewai]>=0.3" in text
    assert "✓ alexein 0.3.0" in text and "✓ crewai 1.15.28" in text and "langgraph" not in text
    assert "✓ alexein.crewai imports" in text and imports == ["import alexein.crewai"]
    assert "All good." in text


def test_doctor_stops_on_an_old_crewai(tmp_path: Path) -> None:
    healthy(tmp_path, crewai="1.14.6")
    console = quiet()
    assert doctor(tmp_path, console) == 1
    assert "✗ crewai 1.14.6 is older than 1.15" in said(console)


def test_doctor_notes_a_newer_crewai_and_passes(tmp_path: Path) -> None:
    healthy(tmp_path, crewai="1.17.0")
    console = quiet()
    assert doctor(tmp_path, console) == 0
    assert "- crewai 1.17.0 is newer than this release was tested with (1.15)" in said(console)


def test_doctor_in_a_crew_without_the_file_names_init_crewai(tmp_path: Path) -> None:
    classic(tmp_path, "my_crew")
    console = quiet()
    assert doctor(tmp_path, console) == 1
    assert "alexein-cli init crewai" in said(console)


def test_doctor_says_what_to_watch_for_on_a_newer_crewai(tmp_path: Path) -> None:
    healthy(tmp_path, crewai="1.17.0")
    console = quiet()
    doctor(tmp_path, console)
    assert "warnings on the `alexein` logger" in said(console)


def test_doctor_in_a_flow_says_flows_are_not_supported(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "f"\ndependencies = ["crewai>=1.15"]\n\n[tool.crewai]\ntype = "flow"\n'
    )
    console = quiet()
    assert doctor(tmp_path, console) == 1
    text = said(console)
    assert "Flows are not supported yet" in text and "init crewai" not in text
