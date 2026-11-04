"""Finding a CrewAI crew: classic (`@CrewBase` in `src/<pkg>/crew.py`) or JSON (`crew.jsonc`,
CrewAI's default since `crewai create` changed), and a Flow, which `init crewai` refuses."""

from __future__ import annotations

from pathlib import Path

from twinmemory_cli import project

CREW_PY = "from crewai.project import CrewBase\n\n\n@CrewBase\nclass MyCrew:\n    pass\n"


def classic(root: Path, package: str, *, table: bool = True) -> Path:
    tool = '\n[tool.crewai]\ntype = "crew"\n' if table else ""
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{package.replace("_", "-")}"\ndependencies = ["crewai>=1.15"]\n' + tool
    )
    home = root / "src" / package
    home.mkdir(parents=True)
    (home / "crew.py").write_text(CREW_PY)
    return home


def json_crew(root: Path, definition: str = "crew.jsonc") -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nname = "j"\ndependencies = ["crewai>=1.15"]\n\n'
        f'[tool.crewai]\ntype = "crew"\ndefinition = "{definition}"\n'
    )
    (root / definition).parent.mkdir(parents=True, exist_ok=True)
    (root / definition).write_text('{"name": "j", "agents": [], "tasks": []}\n')


def test_a_classic_crew_is_found_by_its_crew_py(tmp_path: Path) -> None:
    home = classic(tmp_path, "my_crew")
    assert project.crew(tmp_path) == project.Crew("classic", home)


def test_a_json_crew_is_found_by_its_definition(tmp_path: Path) -> None:
    json_crew(tmp_path, definition="crews/main.jsonc")
    assert project.crew(tmp_path) == project.Crew("json", tmp_path / "crews")


def test_a_json_crew_at_the_root(tmp_path: Path) -> None:
    json_crew(tmp_path)
    assert project.crew(tmp_path) == project.Crew("json", tmp_path)


def test_a_flow_is_named_as_one(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "f"\n\n[tool.crewai]\ntype = "flow"\n'
    )
    found = project.crew(tmp_path)
    assert found is not None and found.kind == "flow"


def test_a_crewai_dependency_without_the_table_is_classic_when_crew_py_is_there(
    tmp_path: Path,
) -> None:
    home = classic(tmp_path, "my_crew", table=False)
    assert project.crew(tmp_path) == project.Crew("classic", home)


def test_a_crew_py_without_crewbase_is_not_a_crew(tmp_path: Path) -> None:
    home = classic(tmp_path, "my_crew")
    (home / "crew.py").write_text("print('hello')\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "my-crew"\n')
    assert project.crew(tmp_path) is None


def test_no_crewai_is_none(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["langgraph"]\n'
    )
    assert project.crew(tmp_path) is None


def test_the_crewai_table_is_read(tmp_path: Path) -> None:
    json_crew(tmp_path)
    assert project.pyproject(tmp_path).crewai == {"type": "crew", "definition": "crew.jsonc"}
