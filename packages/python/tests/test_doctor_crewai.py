"""`twinmemory-cli doctor` in a CrewAI project: the file `init crewai` wrote, CrewAI's version,
and a key that only reads when the file saves."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_crewai_project import classic

from twinmemory_cli import env
from twinmemory_cli.doctor import doctor
from twinmemory_cli.render import render
from twinmemory_cli.ui import Console


@pytest.fixture(autouse=True)
def checked(monkeypatch: pytest.MonkeyPatch) -> list[env.Check]:
    answers = [env.Check(True, True, "o/p, reads and writes")]
    monkeypatch.setattr(env, "check", lambda key, base_url, timeout=10.0: answers[0])
    monkeypatch.delenv(env.KEY, raising=False)
    monkeypatch.delenv(env.BASE_URL, raising=False)
    return answers


def said(console: Console) -> str:
    return "\n".join(console.said)


def quiet() -> Console:
    return Console(out=lambda _: None)


def healthy(
    root: Path, crewai: str = "1.15.28", parts: tuple[str, ...] = ("auto", "tools")
) -> Path:
    home = classic(root, "my_crew")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "my-crew"\ndependencies = ["crewai>=1.15", "twinmemory>=0.2"]\n'
        '\n[tool.crewai]\ntype = "crew"\n'
    )
    site = root / ".venv" / "lib" / "python3.12" / "site-packages"
    for dist in (f"crewai-{crewai}", "twinmemory-0.2.0"):
        (site / f"{dist}.dist-info").mkdir(parents=True)
    values = {"version": "0.2.0", "fast": "False"}
    (home / "memory.py").write_text(render("crewai/memory.py.tmpl", parts, values))
    (root / ".env").write_text(f"{env.KEY}=tm_x\n")
    (root / ".gitignore").write_text(".env\n")
    return home


def test_doctor_passes_a_crew_that_is_set_up(tmp_path: Path) -> None:
    healthy(tmp_path)
    console = quiet()
    assert doctor(tmp_path, console) == 0
    text = said(console)
    assert "✓ memory file src/my_crew/memory.py (written by 0.2.0, for CrewAI)" in text
    assert "✓ dependencies: twinmemory, crewai" in text
    assert "✓ crewai 1.15.28" in text and "langgraph" not in text
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


def test_doctor_fails_a_read_only_key_when_the_file_saves(
    tmp_path: Path, checked: list[env.Check]
) -> None:
    healthy(tmp_path)
    checked[0] = env.Check(True, False, "o/p, reads only")
    console = quiet()
    assert doctor(tmp_path, console) == 1
    assert "only reads, and the memory file saves" in said(console)


def test_doctor_passes_a_read_only_key_for_a_tools_file_that_only_reads(
    tmp_path: Path, checked: list[env.Check]
) -> None:
    home = healthy(tmp_path, parts=("tools", "tools_only"))
    text = (home / "memory.py").read_text()
    reads_only = text.split("class _Save(")[0] + text[text.index("def memory_tools(") :].replace(
        "return [*tools, _Save(user_id=user_id)] if writes else tools", "return tools"
    )
    (home / "memory.py").write_text(reads_only.split("def save_result(")[0])
    checked[0] = env.Check(True, False, "o/p, reads only")
    assert doctor(tmp_path, quiet()) == 0


def test_doctor_in_a_crew_without_the_file_names_init_crewai(tmp_path: Path) -> None:
    classic(tmp_path, "my_crew")
    console = quiet()
    assert doctor(tmp_path, console) == 1
    assert "twinmemory-cli init crewai" in said(console)


def test_doctor_says_what_to_watch_for_on_a_newer_crewai(tmp_path: Path) -> None:
    healthy(tmp_path, crewai="1.17.0")
    console = quiet()
    doctor(tmp_path, console)
    assert "warnings on the `twinmemory` logger" in said(console)


def test_doctor_in_a_flow_says_flows_are_not_supported(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "f"\ndependencies = ["crewai>=1.15"]\n\n[tool.crewai]\ntype = "flow"\n'
    )
    console = quiet()
    assert doctor(tmp_path, console) == 1
    text = said(console)
    assert "Flows are not supported yet" in text and "init crewai" not in text
