"""What the CLI finds out about the project it is run in: where its root is, which graphs it
has, where generated code should go, whether it uses LangGraph, which versions are installed,
and how it adds a dependency. It only reads; the commands do the writing.

Not a general project detector: the checks are the few files that decide those answers, in the
order the tools themselves give them precedence.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

# A directory holding any of these is a Python project's root.
_MARKERS = ("pyproject.toml", "langgraph.json", "requirements.txt", "setup.py", "setup.cfg")


@dataclass(frozen=True)
class Installer:
    """How this project adds dependencies. `command` is run; with none, `hint` is printed for the
    developer to run, and `requirements` (if set) is the file the packages are appended to."""

    name: str
    command: list[str] | None
    hint: str
    requirements: Path | None = None


def find_root(start: Path) -> Path | None:
    """The nearest directory at or above `start` that is a Python project."""
    for directory in (start, *start.parents):
        if any((directory / marker).exists() for marker in _MARKERS):
            return directory
        if list(directory.glob("requirements*.txt")):
            return directory
    return None


@dataclass(frozen=True)
class Pyproject:
    """What is read from `pyproject.toml`: the project's name, which tools configure themselves in
    it (`[tool.uv]`, `[tool.poetry]`, ...), and CrewAI's own table, `[tool.crewai]`."""

    name: str
    tools: frozenset[str]
    crewai: dict[str, str] = field(default_factory=dict[str, str])


# Line by line rather than tomllib, which Python 3.10 does not have; these two shapes are all
# that is read, and both are one line in any pyproject a tool writes.
_TABLE = re.compile(r"^\[([A-Za-z0-9_.-]+)\]\s*$")
_NAME = re.compile(r"""^name\s*=\s*["']([^"']+)["']""")
_SETTING = re.compile(r"""^([A-Za-z_][\w-]*)\s*=\s*["']([^"']*)["']""")


def pyproject(root: Path) -> Pyproject:
    try:
        lines = (root / "pyproject.toml").read_text().splitlines()
    except OSError:
        return Pyproject("", frozenset())
    name, tools, table, crewai = "", set[str](), "", dict[str, str]()
    for line in lines:
        header = _TABLE.match(line.strip())
        if header:
            table = header.group(1)
            if table.startswith("tool."):
                tools.add(table.split(".")[1])
            continue
        named = _NAME.match(line.strip())
        if table == "project" and named and not name:
            name = named.group(1)
        setting = _SETTING.match(line.strip())
        if table == "tool.crewai" and setting:
            crewai[setting.group(1)] = setting.group(2)
    return Pyproject(name, frozenset(tools), crewai)


@dataclass(frozen=True)
class Crew:
    """A CrewAI project: `classic` (a `@CrewBase` class in `src/<pkg>/crew.py`), `json` (a crew
    defined in `crew.jsonc`), or a `flow`. `home` is where the memory file goes: beside `crew.py`,
    beside the JSON definition, or the root for a flow."""

    kind: Literal["classic", "json", "flow"]
    home: Path


_CREW_BASE = re.compile(r"^\s*@CrewBase\b", re.M)


def crew(root: Path) -> Crew | None:
    """The CrewAI crew at `root`, from `[tool.crewai]` and the files it names; None when the
    project is not a CrewAI one."""
    table = pyproject(root).crewai
    if table.get("type") == "flow":
        return Crew("flow", root)
    if table.get("definition"):
        return Crew("json", (root / table["definition"]).parent)
    if table or declares(root, "crewai"):
        home = _crew_package(root)
        if home is not None:
            return Crew("classic", home)
    return None


def _crew_package(root: Path) -> Path | None:
    """The package whose `crew.py` holds a `@CrewBase` class: the project's own first, else the
    only one under `src/`."""
    name = pyproject(root).name.replace("-", "_")
    candidates = [root / "src" / name] if name else []
    candidates += sorted(p.parent for p in root.glob("src/*/crew.py"))
    for home in dict.fromkeys(candidates):
        try:
            if _CREW_BASE.search((home / "crew.py").read_text(errors="ignore")):
                return home
        except OSError:
            continue
    return None


def graphs(root: Path) -> dict[str, Path]:
    """Each graph `langgraph.json` names, and the directory its file is in. A graph is a
    `"./app/graph.py:graph"` string, or an object with that as its `path`."""
    try:
        config: object = json.loads((root / "langgraph.json").read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(config, dict):
        return {}
    named: object = cast("dict[str, Any]", config).get("graphs")
    if not isinstance(named, dict):
        return {}
    found: dict[str, Path] = {}
    for name, spec in cast("dict[str, Any]", named).items():
        where: object = cast("dict[str, Any]", spec).get("path") if isinstance(spec, dict) else spec
        if isinstance(where, str) and ":" in where:
            found[name] = (root / where.split(":", 1)[0]).parent.resolve()
    return found


def target_dir(root: Path, graph: Path | None = None) -> Path:
    """Where generated code goes: beside the chosen graph, else in the project's own package
    (`src/<name>/`, the one package under `src/`, or `app/`), else the root."""
    if graph is not None:
        return graph
    name = pyproject(root).name.replace("-", "_")
    if name and (root / "src" / name).is_dir():
        return root / "src" / name
    packages = sorted(p.parent for p in root.glob("src/*/__init__.py"))
    if len(packages) == 1:
        return packages[0]
    if (root / "app").is_dir():
        return root / "app"
    return root


# Directories that hold other people's code, never the project's own.
_SKIPPED = {".venv", "venv", "env", ".git", "node_modules", "site-packages", "__pycache__", ".tox"}
_USES = re.compile(r"^\s*(from|import)\s+langgraph\b", re.M)


def uses_langgraph(root: Path, limit: int = 2000) -> bool:
    """Whether the project depends on LangGraph or imports it anywhere of its own."""
    if declares(root, "langgraph") or (root / "langgraph.json").exists():
        return True
    for n, path in enumerate(sources(root)):
        if n >= limit:
            break
        try:
            if _USES.search(path.read_text(errors="ignore")):
                return True
        except OSError:
            continue
    return False


def sources(root: Path) -> Iterator[Path]:
    """The project's own Python files, never walking into an environment or a dependency."""
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = [d for d in subdirectories if d not in _SKIPPED]
        yield from (Path(directory, f) for f in files if f.endswith(".py"))


def environment(root: Path) -> Path | None:
    """The project's own virtual environment's site-packages, if it has one beside it."""
    for name in (".venv", "venv"):
        found = sorted((root / name).glob("lib/python*/site-packages"))
        found += [root / name / "Lib" / "site-packages"]
        for packages in found:
            if packages.is_dir():
                return packages
    return None


def installed(site: Path, package: str) -> str | None:
    """The version of `package` installed in `site`, from its dist-info directory."""
    wanted = re.sub(r"[-_.]+", "_", package).lower()
    for info in site.glob("*.dist-info"):
        name, _, version = info.name.removesuffix(".dist-info").rpartition("-")
        if re.sub(r"[-_.]+", "_", name).lower() == wanted:
            return version
    return None


def older(version: str, minimum: str) -> bool:
    """Whether `version` is below `minimum`, by their leading numbers (`0.6.2` < `1.0`)."""

    def numbers(text: str) -> tuple[int, ...]:
        return tuple(int(n) for n in re.findall(r"\d+", text.split("+")[0])[:3])

    return numbers(version) < numbers(minimum)


def installer(root: Path, packages: list[str]) -> Installer:
    """How to add `packages` here: the project's own tool where its lock file or config says
    which, else uv where it is installed, else pip."""
    tools = pyproject(root).tools
    has_pyproject = (root / "pyproject.toml").exists()
    named = " ".join(packages)
    for tool, lock in (("uv", "uv.lock"), ("poetry", "poetry.lock"), ("pdm", "pdm.lock")):
        if (root / lock).exists() or tool in tools:
            return Installer(tool, [tool, "add", *packages], f"{tool} add {named}")
    if not has_pyproject and (root / "requirements.txt").exists():
        return Installer("pip", None, f"pip install {named}", root / "requirements.txt")
    if has_pyproject and shutil.which("uv"):
        return Installer("uv", ["uv", "add", *packages], f"uv add {named}")
    return Installer("pip", None, f"pip install {named}")


def declares(root: Path, package: str) -> bool:
    """Whether the project already depends on `package` by that exact name (`langchain`, not
    `langchain-core`): a quoted requirement in `pyproject.toml` (`"langchain>=1"`), a Poetry
    table line (`langchain = "^1"`), or a line of a `requirements*.txt`. Never prose: a
    description that says "LangGraph" is not a dependency on it."""
    name = re.escape(package)
    extras = r"(?:\[[^\]]*\])?"
    quoted = re.compile(rf"""["']\s*{name}\s*{extras}\s*[<>=!~;@"']""", re.IGNORECASE)
    table = re.compile(rf"^\s*{name}\s*=", re.IGNORECASE | re.M)
    listed = re.compile(rf"^\s*{name}\s*{extras}\s*(?:[<>=!~;@]|$)", re.IGNORECASE | re.M)
    try:
        text = (root / "pyproject.toml").read_text()
        if quoted.search(text) or table.search(text):
            return True
    except OSError:
        pass
    for path in root.glob("requirements*.txt"):
        try:
            if listed.search(path.read_text()):
                return True
        except OSError:
            continue
    return False
