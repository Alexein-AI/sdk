"""`alexein-cli init <framework>`: write memory into a project as a short file its developer
owns - the settings and one configured `AlexeinMemory`, everything else imported from the
client's integration module.

The steps, in order, each of which can stop the command before anything is written: find the
project, make sure it uses the framework (or that adding it is wanted), make sure what is
installed is new enough, and pick where the file goes: beside the graph, or the agent. Then:
write the file, add `alexein[<framework>]`, and set up the key - which can be skipped, and
added later.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from alexein_cli import crews, env, project
from alexein_cli._version import __version__
from alexein_cli.render import render
from alexein_cli.stop import Stop
from alexein_cli.ui import Console
from alexein_cli.wiring import next_steps

# The client the written file imports: `alexein.langgraph`, `.openai_agents` and `.crewai`
# are its 0.3.
CLIENT = "alexein"
CLIENT_MINIMUM = "0.3"
# What each framework's file needs installed, at least - the client, and the framework as the
# client's extra for it requires it. LangGraph's: 1.2, whose runtime carries the thread a node
# runs in (the session what is saved belongs to). The OpenAI Agents SDK's: 0.24. CrewAI's:
# nothing beyond CrewAI, which the crew has already and `crews.py` checks.
MINIMUMS = {
    "langgraph": {CLIENT: CLIENT_MINIMUM, "langgraph": "1.2", "langchain": "1.0"},
    "openai-agents": {CLIENT: CLIENT_MINIMUM, "openai-agents": "0.24"},
    "crewai": {CLIENT: CLIENT_MINIMUM},
}
# The client's extra for each framework, and the module the written file imports from it.
EXTRAS = {"langgraph": "langgraph", "openai-agents": "openai-agents", "crewai": "crewai"}
MODULES = {
    "langgraph": "alexein.langgraph",
    "openai-agents": "alexein.openai_agents",
    "crewai": "alexein.crewai",
}
# How each is named to the developer.
NAMES = {"langgraph": "LangGraph", "openai-agents": "the OpenAI Agents SDK", "crewai": "CrewAI"}

Runner = Callable[[Sequence[str], Path], int]


def run_command(command: Sequence[str], cwd: Path) -> int:
    """Run an install in the project, never in this CLI's own environment: `uv run` and `uvx`
    set VIRTUAL_ENV to it, which poetry and pdm would install into."""
    own = os.environ.get("VIRTUAL_ENV")
    environ = dict(os.environ)
    if own and Path(own).resolve() == Path(sys.prefix).resolve():
        del environ["VIRTUAL_ENV"]
    return subprocess.run(list(command), cwd=cwd, env=environ, check=False).returncode


@dataclass
class Options:
    """Everything `init` can be told. `sdk` installs the client from somewhere other than PyPI:
    a checkout's path, or a URL."""

    framework: str = "langgraph"
    directory: Path | None = None
    filename: str = "memory.py"
    graph: str | None = None
    force: bool = False
    install: bool = True
    fast: bool = False
    key: str | None = None
    base_url: str | None = None
    skip_key: bool = False
    sdk: str | None = None
    dry_run: bool = False
    run: Runner = field(default=run_command)


def init(cwd: Path, options: Options, console: Console) -> int:
    """Run `init`; the exit code: 0 done, 1 stopped or the install failed, 2 a bad command."""
    try:
        root, target = _prepare(cwd, options, console)
    except Stop as stop:
        console.fail(str(stop))
        return stop.code
    if options.dry_run:
        _plan(root, target / options.filename, options, console)
        return 0
    written = write(target, options)
    console.step("wrote", _relative(written, root))
    installed = install(root, options, console)
    setup_key(root, options, console)
    console.line()
    module = _module(written, root)
    if options.framework == "crewai":
        console.line(crews.next_steps(crews.crew(root), module))
    else:
        console.line(next_steps(module, options.framework))
    return 0 if installed else 1


def _prepare(cwd: Path, options: Options, console: Console) -> tuple[Path, Path]:
    """The project's root and where the file goes, or `Stop` with why not."""
    framework = options.framework
    if framework not in MINIMUMS:
        raise Stop(f"no template for {framework!r}; there is: {', '.join(MINIMUMS)}", code=2)
    if framework != "langgraph" and options.graph is not None:
        raise Stop(f"--graph is for langgraph, not {framework}", code=2)
    if options.filename and not options.filename.endswith(".py"):
        raise Stop(f"--file must name a Python file: {options.filename!r}", code=2)
    root = project.find_root(cwd)
    if root is None:
        raise Stop(
            "no Python project here (no pyproject.toml, requirements.txt or langgraph.json at "
            "or above this directory). Run it from your project, or start one with "
            f"`alexein-cli create {framework} <name>`."
        )
    console.step("found", f"{project.installer(root, [CLIENT]).name} project at {root}")
    if framework == "crewai":
        return root, _crew_dir(root, cwd, options, console)
    _require_framework(root, framework, console)
    _require_versions(root, framework)
    if options.directory:
        target = (cwd / options.directory).resolve()
    elif framework == "langgraph":
        target = _graph_dir(root, options, console)
    else:
        target = _agent_dir(root, console)
    written = target / options.filename
    if written.exists() and not options.force:
        raise Stop(f"{_relative(written, root)} exists; --force replaces it. Nothing changed.")
    return root, target


def _crew_dir(root: Path, cwd: Path, options: Options, console: Console) -> Path:
    """Where a CrewAI crew's file goes - beside its crew - once `crews.py` has checked it."""
    found = crews.crew(root)
    crews.require_version(root, console)
    target = (cwd / options.directory).resolve() if options.directory else found.home
    written = target / options.filename
    if written.exists() and not options.force:
        raise Stop(f"{_relative(written, root)} exists; --force replaces it. Nothing changed.")
    return target


def _require_framework(root: Path, framework: str, console: Console) -> None:
    if framework == "openai-agents" and project.shadows_agents(root):
        console.step(
            "warning",
            "this project has an `agents` package of its own; the OpenAI Agents SDK is "
            "imported as `agents` too, and the two would clash",
        )
    if project.uses(root, framework):
        return
    name = NAMES[framework]
    console.step("note", f"this project does not use {name} yet")
    if not console.confirm(f"Add {name} to it and go on?"):
        raise Stop(
            f"this project does not use {name}; run again with --yes to add it, or start a "
            f"new one with `alexein-cli create {framework} <name>`. Nothing changed."
        )


def _require_versions(root: Path, framework: str) -> None:
    site = project.environment(root)
    if site is None:
        return
    stale = [
        (package, version, minimum)
        for package, minimum in MINIMUMS[framework].items()
        if package != CLIENT
        and (version := project.installed(site, package))
        and project.older(version, minimum)
    ]
    if stale:
        found = ", ".join(f"{p} {v} (needs >={m})" for p, v, m in stale)
        upgrade = shlex.join(f"{p}>={m}" for p, _, m in stale)
        raise Stop(
            f"this project has {found} installed. Upgrade first - "
            f"{project.installer(root, []).name} add {upgrade} - then run init again. "
            "Nothing changed."
        )


def _graph_dir(root: Path, options: Options, console: Console) -> Path:
    found = project.graphs(root)
    if options.graph is not None:
        if options.graph not in found:
            names = ", ".join(found) or "none"
            raise Stop(f"no graph {options.graph!r} in langgraph.json (there is: {names})")
        return found[options.graph]
    if len(found) <= 1:
        return project.target_dir(root, next(iter(found.values()), None))
    chosen = console.choose("Which graph is memory for?", list(found))
    if chosen is None:
        raise Stop(
            f"langgraph.json has {len(found)} graphs ({', '.join(found)}); "
            "name one with --graph. Nothing changed."
        )
    return found[chosen]


def _agent_dir(root: Path, console: Console) -> Path:
    """Beside the code that builds an `Agent`; with none found, the project's own package."""
    found = project.agent_dirs(root)
    if not found:
        console.step("note", "found no file that builds an Agent; writing to the project's package")
        return project.target_dir(root)
    if len(found) == 1:
        return found[0]
    named = [_relative(d, root) for d in found]
    chosen = console.choose("Which agent is memory for?", named)
    if chosen is None:
        raise Stop(
            f"{len(found)} directories build an Agent ({', '.join(named)}); "
            "name one with --dir. Nothing changed."
        )
    return found[named.index(chosen)]


def _plan(root: Path, written: Path, options: Options, console: Console) -> None:
    """What `init` would do, every check made, nothing changed and nothing sent."""
    console.step("would", f"write {_relative(written, root)}")
    planned(root, requirements(root, options), options, console)
    key, _ = env.resolve(root)
    if options.base_url:
        console.step("would", f"set {env.BASE_URL} in .env")
    if options.key:
        console.step("would", f"set {env.KEY} in .env, and check it")
    elif not key:
        console.step("would", f"ask for the key, or add an empty {env.KEY}= to .env")
    else:
        console.step("would", "check the key already in .env")
    console.line()
    console.line("Dry run: nothing was changed.")


def planned(root: Path, packages: list[str], options: Options, console: Console) -> None:
    if not packages:
        console.step("would", "install nothing: every package is a dependency already")
        return
    found = project.installer(root, packages)
    if found.requirements is not None:
        console.step("would", f"add {', '.join(packages)} to {found.requirements.name}")
    verb = "run" if found.command and options.install else "print"
    console.step("would", f"{verb} {found.hint}")


def write(target: Path, options: Options) -> Path:
    """The memory file: the settings, one configured `AlexeinMemory`, and the names the
    framework's code uses, everything else imported from the integration module."""
    template = f"{options.framework.replace('-', '_')}/memory.py.tmpl"
    values = {"version": __version__, "fast": str(options.fast)}
    target.mkdir(parents=True, exist_ok=True)
    written = target / options.filename
    written.write_text(render(template, (), values))
    return written


def requirement(framework: str, sdk: str | None = None) -> str:
    """The client with the framework's extra: `alexein[langgraph]>=0.3`, or from `sdk` - a
    checkout's path or a URL - while it is not on PyPI."""
    named = f"{CLIENT}[{EXTRAS[framework]}]"
    if not sdk:
        return f"{named}>={CLIENT_MINIMUM}"
    if "://" in sdk:
        return f"{named} @ {sdk}"
    return f"{named} @ {Path(sdk).expanduser().resolve().as_uri()}"


def requirements(root: Path, options: Options) -> list[str]:
    """What still has to be added for the file to import: the client with the framework's
    extra, which brings the framework, unless the project depends on it already."""
    if options.sdk is None and project.declares(root, CLIENT, EXTRAS[options.framework]):
        return []
    return [requirement(options.framework, options.sdk)]


def install(root: Path, options: Options, console: Console) -> bool:
    """Add what the project does not depend on yet, with its own tool; True unless that failed."""
    packages = requirements(root, options)
    if not packages:
        console.step("kept", f"{requirement(options.framework)}: already a dependency")
        return True
    found = project.installer(root, packages)
    if found.requirements is not None:
        present = found.requirements.read_text()
        separator = "" if not present or present.endswith("\n") else "\n"
        found.requirements.write_text(present + separator + "\n".join(packages) + "\n")
        console.step("added", f"{', '.join(packages)} to {found.requirements.name}")
    if found.command is None or not options.install:
        console.step("run", found.hint)
        return True
    shown = found.hint
    console.step("running", shown)
    if options.run(found.command, root) != 0:
        console.fail(f"`{shown}` failed; run it yourself, then go on.")
        return False
    console.step("ran", shown)
    return True


def setup_key(root: Path, options: Options, console: Console) -> None:
    """Put the key (and address) in `.env` and check it. Skippable: without one, an empty
    `ALEXEIN_API_KEY=` is left to fill in, and `alexein-cli doctor` checks it later."""
    dotenv = root / ".env"
    if options.base_url:
        console.step(
            env.put(dotenv, env.BASE_URL, options.base_url, replace=True), f"{env.BASE_URL} in .env"
        )
    key, _ = env.resolve(root)
    given = options.key
    if given is None and not key and not options.skip_key:
        given = (
            console.secret(
                "Your Alexein API key (from the console, under API keys; Enter to skip):"
            )
            or None
        )
    if given:
        console.step(env.put(dotenv, env.KEY, given, replace=True), f"{env.KEY} in .env")
    elif not key:
        env.put(dotenv, env.KEY, "", replace=False)
        console.step("added", f"{env.KEY}= to .env: fill it in later (console, under API keys)")
    if not env.ignored(root):
        console.step("warning", ".env is not in .gitignore; add it before a key goes in it")
    key, base_url = env.resolve(root)
    if key:
        _check_key(key, base_url, options, console)


def _check_key(key: str, base_url: str | None, options: Options, console: Console) -> None:
    checked = env.check(key, base_url)
    if not checked.ok:
        console.step("warning", f"the key did not check out: {checked.detail}")
        return
    console.step("checked", f"key: {checked.detail}")
    if checked.writes is False:
        console.step("warning", f"this key only reads: {SAVING[options.framework]}")


# What needs a key that writes, in each framework's words.
SAVING = {
    "langgraph": "memory.remember and the memory_add tool need one that writes",
    "openai-agents": "memory.remember and the memory_add tool need one that writes",
    "crewai": "saving what a task learned needs one that writes",
}


def _relative(path: Path, root: Path) -> str:
    try:
        return f"./{path.relative_to(root)}"
    except ValueError:
        return str(path)


def _module(written: Path, root: Path) -> str:
    """How the developer's code imports the written file: `app.memory`, `memory`, ..."""
    try:
        parts = list(written.with_suffix("").relative_to(root).parts)
    except ValueError:
        return written.stem
    return ".".join(parts[1:] if parts[:1] == ["src"] else parts)
