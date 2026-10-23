"""`twinmemory-cli init`: what it checks before writing, where it writes, what it installs, and the
key - which can be skipped."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from twinmemory_cli import env, main
from twinmemory_cli.scaffold import PARTS, Options, init
from twinmemory_cli.ui import Console


class Project:
    """A project in `tmp_path`, and `init` run over it with commands recorded, not run, and
    the key's check answered, not sent."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.ran: list[list[str]] = []
        self.code = 0
        self.checked: list[tuple[str, str | None]] = []
        self.check = env.Check(True, True, "scratch/demo, reads and writes")
        monkeypatch.setattr(env, "check", self._check)

    def _check(self, key: str, base_url: str | None, timeout: float = 10.0) -> env.Check:
        self.checked.append((key, base_url))
        return self.check

    def _run(self, command: Sequence[str], cwd: Path) -> int:
        self.ran.append(list(command))
        return self.code

    def uv(self, deps: str = '"langgraph>=1"') -> Project:
        (self.root / "pyproject.toml").write_text(
            f'[project]\nname = "my-agent"\nversion = "0.1.0"\ndependencies = [{deps}]\n'
        )
        (self.root / "uv.lock").write_text("")
        return self

    def graphs(self, **specs: Any) -> Project:
        for spec in specs.values():
            where = spec["path"] if isinstance(spec, dict) else spec
            (self.root / where.split(":")[0]).parent.mkdir(parents=True, exist_ok=True)
        (self.root / "langgraph.json").write_text(json.dumps({"graphs": specs}))
        return self

    def installed(self, **versions: str) -> Project:
        site = self.root / ".venv" / "lib" / "python3.12" / "site-packages"
        for package, version in versions.items():
            (site / f"{package}-{version}.dist-info").mkdir(parents=True)
        return self

    def init(
        self,
        *,
        cwd: Path | None = None,
        console: Console | None = None,
        framework: str = "langgraph",
        **options: Any,
    ) -> tuple[int, Console]:
        console = console or Console(out=lambda _: None)
        options.setdefault("skip_key", True)
        code = init(framework, cwd or self.root, Options(run=self._run, **options), console)
        return code, console

    def text(self, path: str) -> str:
        return (self.root / path).read_text()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    monkeypatch.delenv(env.KEY, raising=False)
    monkeypatch.delenv(env.BASE_URL, raising=False)
    return Project(tmp_path, monkeypatch)


def said(console: Console) -> str:
    return "\n".join(console.said)


def quiet(**fields: Any) -> Console:
    return Console(out=lambda _: None, **fields)


# ------------------------------------------------------------------------- where it writes --


def test_writes_beside_the_graph_langgraph_json_names(project: Project) -> None:
    project.uv().graphs(agent="./app/graph.py:graph")

    code, _ = project.init()

    assert code == 0
    written = project.text("app/memory.py")
    assert "def recall(" in written and "{version}" not in written and "# >>>" not in written
    assert project.ran == [["uv", "add", "twinmemory>=0.2", "langchain>=1.0"]]


def test_a_graph_given_as_an_object_is_understood(project: Project) -> None:
    project.uv().graphs(agent={"path": "./agents/main.py:graph", "description": "x"})
    project.init()
    assert (project.root / "agents" / "memory.py").exists()


def test_a_src_package_is_found_by_the_project_name(project: Project) -> None:
    project.uv('"langgraph>=1", "langchain>=1"')
    (project.root / "src" / "my_agent").mkdir(parents=True)

    _, console = project.init()

    assert (project.root / "src" / "my_agent" / "memory.py").exists()
    assert project.ran == [["uv", "add", "twinmemory>=0.2"]]
    assert "from my_agent.memory import" in said(console)


def test_run_from_a_subdirectory_finds_the_root(project: Project) -> None:
    project.uv()
    deep = project.root / "notebooks" / "scratch"
    deep.mkdir(parents=True)
    project.init(cwd=deep)
    assert (project.root / "memory.py").exists()
    assert (project.root / ".env").exists()


def test_dir_and_file_put_it_where_asked(project: Project) -> None:
    project.uv()
    project.init(directory=Path("agents/shared"), filename="twin.py")
    assert (project.root / "agents" / "shared" / "twin.py").exists()


# ------------------------------------------------------------------------ several graphs --


def test_several_graphs_and_nobody_to_ask_stops_naming_them(project: Project) -> None:
    project.uv().graphs(a="./a/g.py:graph", b="./b/g.py:graph")

    code, console = project.init()

    assert code == 1
    assert "2 graphs (a, b); name one with --graph" in said(console)
    assert not list(project.root.rglob("memory.py"))


def test_graph_picks_one(project: Project) -> None:
    project.uv().graphs(a="./a/g.py:graph", b="./b/g.py:graph")
    project.init(graph="b")
    assert (project.root / "b" / "memory.py").exists()


def test_a_graph_that_is_not_there_stops(project: Project) -> None:
    project.uv().graphs(a="./a/g.py:graph")
    code, console = project.init(graph="z")
    assert code == 1 and "no graph 'z'" in said(console)


def test_at_a_terminal_the_graph_is_asked_for(project: Project) -> None:
    project.uv().graphs(a="./a/g.py:graph", b="./b/g.py:graph")
    project.init(console=quiet(interactive=True, answers=["2"]))
    assert (project.root / "b" / "memory.py").exists()


# ---------------------------------------------------------- a LangGraph project, new enough --


def bare(project: Project) -> None:
    (project.root / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = []\n')
    (project.root / "uv.lock").write_text("")


def test_a_project_without_langgraph_stops_unless_told(project: Project) -> None:
    bare(project)

    code, console = project.init()

    assert code == 1 and "not a LangGraph project" in said(console)
    assert not (project.root / "memory.py").exists() and project.ran == []


def test_yes_adds_langgraph_to_it(project: Project) -> None:
    bare(project)
    code, _ = project.init(console=quiet(yes=True))
    assert code == 0
    assert project.ran == [["uv", "add", "twinmemory>=0.2", "langgraph>=1.0", "langchain>=1.0"]]


def test_at_a_terminal_it_asks_first(project: Project) -> None:
    bare(project)
    project.init(console=quiet(interactive=True, answers=["y"]))
    assert (project.root / "memory.py").exists()


def test_an_import_of_langgraph_is_enough(project: Project) -> None:
    bare(project)
    (project.root / "agent.py").write_text("from langgraph.graph import StateGraph\n")
    assert project.init()[0] == 0


def test_an_import_inside_the_environment_does_not_count(project: Project) -> None:
    bare(project)
    site = project.root / ".venv" / "lib" / "python3.12" / "site-packages" / "x"
    site.mkdir(parents=True)
    (site / "a.py").write_text("import langgraph\n")
    assert project.init()[0] == 1


def test_an_old_langgraph_installed_stops_with_the_upgrade(project: Project) -> None:
    project.uv().installed(langgraph="0.6.2", langchain="1.4.7")

    code, console = project.init()

    assert code == 1
    assert "langgraph 0.6.2 (needs >=1.0)" in said(console)
    assert "uv add 'langgraph>=1.0'" in said(console)
    assert not (project.root / "memory.py").exists()


def test_new_enough_versions_go_ahead(project: Project) -> None:
    project.uv().installed(langgraph="1.2.16", langchain="1.4.7")
    assert project.init()[0] == 0


# ----------------------------------------------------------------------------- installing --


def test_poetry_is_asked_to_add(project: Project) -> None:
    (project.root / "pyproject.toml").write_text('[tool.poetry]\nname = "x"\nlanggraph = "1"\n')
    project.init()
    assert project.ran[0][:2] == ["poetry", "add"]


def test_requirements_only_is_appended_to_and_nothing_is_run(project: Project) -> None:
    (project.root / "requirements.txt").write_text("langgraph>=1\nlangchain-core")

    _, console = project.init()

    assert project.ran == []
    assert project.text("requirements.txt").splitlines() == [
        "langgraph>=1",
        "langchain-core",
        "twinmemory>=0.2",
        "langchain>=1.0",
    ]
    assert "pip install 'twinmemory>=0.2' 'langchain>=1.0'" in said(console)


def test_no_install_prints_the_command(project: Project) -> None:
    project.uv()
    _, console = project.init(install=False)
    assert project.ran == []
    assert "uv add 'twinmemory>=0.2' 'langchain>=1.0'" in said(console)


def test_nothing_is_installed_when_everything_is_declared(project: Project) -> None:
    project.uv('"langgraph>=1", "langchain>=1", "twinmemory>=0.2"')
    project.init()
    assert project.ran == []


def test_sdk_installs_from_where_it_is_told(project: Project) -> None:
    project.uv('"langgraph>=1", "langchain>=1"')
    project.init(sdk="/src/twin-memory-python")
    assert project.ran == [["uv", "add", "/src/twin-memory-python"]]


def test_a_failed_install_still_writes_and_says_so(project: Project) -> None:
    project.uv()
    project.code = 1
    code, console = project.init()
    assert code == 1
    assert (project.root / "memory.py").exists()
    assert "failed; run it yourself" in said(console)


# ------------------------------------------------------------------------------------ key --


def test_skipped_the_key_is_an_empty_line_once(project: Project) -> None:
    project.uv()
    (project.root / ".env").write_text("OPENAI_API_KEY=sk-1")

    project.init()
    project.init(force=True)

    assert project.text(".env") == f"OPENAI_API_KEY=sk-1\n{env.KEY}=\n"
    assert project.checked == []


def test_a_key_given_is_written_and_checked(project: Project) -> None:
    project.uv()
    (project.root / ".env").write_text(f"{env.KEY}=\nOTHER=1\n")

    _, console = project.init(key="tm_new", base_url="http://localhost:8210")

    assert env.read(project.root / ".env") == {
        env.KEY: "tm_new",
        "OTHER": "1",
        env.BASE_URL: "http://localhost:8210",
    }
    assert project.checked == [("tm_new", "http://localhost:8210")]
    assert "key: scratch/demo, reads and writes" in said(console)


def test_a_key_already_there_is_kept_and_checked(project: Project) -> None:
    project.uv()
    (project.root / ".env").write_text(f"{env.KEY}=tm_real\n")
    project.init()
    assert project.text(".env") == f"{env.KEY}=tm_real\n"
    assert project.checked == [("tm_real", None)]


def test_at_a_terminal_the_key_is_asked_for_and_not_shown(project: Project) -> None:
    project.uv()
    console = quiet(interactive=True, answers=["tm_typed"])
    project.init(console=console, skip_key=False)
    assert env.read(project.root / ".env")[env.KEY] == "tm_typed"
    assert "tm_typed" not in said(console)


def test_enter_skips_the_key(project: Project) -> None:
    project.uv()
    console = quiet(interactive=True, answers=[""])
    project.init(console=console, skip_key=False)
    assert env.read(project.root / ".env")[env.KEY] == ""
    assert "fill it in later" in said(console)


def test_a_key_that_does_not_work_warns_and_goes_on(project: Project) -> None:
    project.uv()
    project.check = env.Check(False, None, "the service does not know this key")
    code, console = project.init(key="tm_bad")
    assert code == 0
    assert "the key did not check out: the service does not know this key" in said(console)


def test_a_key_that_only_reads_is_warned_about_for_nodes(project: Project) -> None:
    project.uv()
    project.check = env.Check(True, False, "scratch/demo, reads only")
    _, console = project.init(key="tm_read")
    assert "this key only reads" in said(console)
    _, console = project.init(key="tm_read", force=True, parts=("tools",))
    assert "this key only reads" not in said(console)


def test_an_unignored_env_is_warned_about(project: Project) -> None:
    project.uv()
    _, console = project.init()
    assert ".env is not in .gitignore" in said(console)
    (project.root / ".gitignore").write_text(".venv\n.env\n")
    _, console = project.init(force=True)
    assert ".env is not in .gitignore" not in said(console)


# ------------------------------------------------------------------------------- refusals --


def test_an_existing_file_is_not_replaced_without_force(project: Project) -> None:
    project.uv()
    (project.root / "memory.py").write_text("# mine")

    code, _ = project.init()

    assert code == 1
    assert project.text("memory.py") == "# mine"
    assert project.ran == [] and not (project.root / ".env").exists()


def test_outside_a_project_nothing_is_written(project: Project) -> None:
    code, console = project.init()
    assert code == 1 and "twinmemory-cli create langgraph" in said(console)
    assert list(project.root.iterdir()) == []


def test_an_unknown_framework_names_the_known_one(project: Project) -> None:
    code, console = project.init(framework="autogen")
    assert code == 2 and "langgraph" in said(console)


def test_file_must_be_python(project: Project) -> None:
    project.uv()
    assert project.init(filename="memory.txt")[0] == 2


# -------------------------------------------------------------------------------- presets --

VARIANTS = [
    pytest.param({}, id="sync"),
    pytest.param({"asynchronous": True}, id="async"),
    pytest.param({"parts": ("nodes",)}, id="nodes-only"),
    pytest.param({"parts": ("tools",)}, id="tools-only"),
    pytest.param({"parts": ("nodes",), "asynchronous": True}, id="async-nodes-only"),
    pytest.param({"parts": ("tools",), "asynchronous": True}, id="async-tools-only"),
    pytest.param({"fast": True}, id="fast"),
]


def lint_clean(path: Path) -> None:
    """Code that lands in projects with linters of their own must pass them as written, at
    black's and ruff's default line length of 88, with nothing unused."""
    rules = "E,F,I,B,UP,SIM,RUF,W"
    lint = [sys.executable, "-m", "ruff", "check", "--isolated", "--select", rules, str(path)]
    fmt = [sys.executable, "-m", "ruff", "format", "--isolated", "--check", str(path)]
    for command in (lint, fmt):
        done = subprocess.run(command, cwd=path.parent, capture_output=True, text=True, check=False)
        assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.parametrize("preset", VARIANTS)
def test_every_preset_writes_clean_code(project: Project, preset: dict[str, Any]) -> None:
    project.uv()
    project.init(**preset)
    lint_clean(project.root / "memory.py")


def test_presets_shape_the_file(project: Project) -> None:
    project.uv()
    project.init(parts=("tools",))
    tools_only = project.text("memory.py")
    assert "def memory_search" in tools_only and "def recall" not in tools_only
    assert "MemoryState" not in tools_only

    project.init(parts=("nodes",), force=True)
    nodes_only = project.text("memory.py")
    assert "def recall" in nodes_only and "memory_search" not in nodes_only

    project.init(asynchronous=True, fast=True, force=True)
    both = project.text("memory.py")
    assert "async def recall" in both and "async def memory_search" in both
    assert "AsyncMemory(" in both and "FAST = True" in both
    assert PARTS == ("nodes", "tools")


def test_main_parses_the_command(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    project.uv()
    monkeypatch.chdir(project.root)
    argv = ["init", "langgraph", "--no-install", "--tools-only", "--async", "--yes"]
    assert main(argv, quiet()) == 0
    assert "async def memory_search" in project.text("memory.py")


# -------------------------------------------------------------------------------- dry run --


def test_a_dry_run_checks_everything_and_changes_nothing(project: Project) -> None:
    project.uv().graphs(agent="./app/graph.py:graph")
    before = sorted(p.name for p in project.root.rglob("*"))

    code, console = project.init(dry_run=True, key="tm_k")

    assert code == 0
    assert sorted(p.name for p in project.root.rglob("*")) == before
    assert project.ran == [] and project.checked == []
    text = said(console)
    assert "would    write ./app/memory.py" in text
    assert "would    run uv add 'twinmemory>=0.2' 'langchain>=1.0'" in text
    assert f"would    set {env.KEY} in .env, and check it" in text


def test_a_dry_run_still_stops_where_init_would(project: Project) -> None:
    project.uv().graphs(a="./a/g.py:graph", b="./b/g.py:graph")
    code, console = project.init(dry_run=True)
    assert code == 1 and "name one with --graph" in said(console)
