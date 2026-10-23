"""`twinmemory-cli init langgraph`: write memory into a LangGraph project as code its developer
owns.

The steps, in order, each of which can stop the command before anything is written: find the
project, make sure it is a LangGraph one (or that adding LangGraph is wanted), make sure what is
installed is new enough, and pick the graph the file goes beside. Then: write the file, add the
packages it imports, and set up the key - which can be skipped, and added later.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from twinmemory_cli import env, project
from twinmemory_cli._version import __version__
from twinmemory_cli.render import render
from twinmemory_cli.ui import Console

# What the written file needs, at least: `Runtime`, `context_schema` and `ToolRuntime` are
# LangGraph 1 and LangChain 1, and `fail_open` and `integration` are this package's 0.2.
MINIMUMS = {"twinmemory": "0.2", "langgraph": "1.0", "langchain": "1.0"}
PARTS = ("nodes", "tools")

Runner = Callable[[Sequence[str], Path], int]


def run_command(command: Sequence[str], cwd: Path) -> int:
    return subprocess.run(list(command), cwd=cwd, check=False).returncode


@dataclass
class Options:
    """Everything `init` can be told. `parts` are what the file holds; `sdk` installs this
    package from somewhere other than PyPI (a path, while it is not published)."""

    directory: Path | None = None
    filename: str = "memory.py"
    graph: str | None = None
    force: bool = False
    install: bool = True
    asynchronous: bool = False
    parts: tuple[str, ...] = PARTS
    fast: bool = False
    key: str | None = None
    base_url: str | None = None
    skip_key: bool = False
    sdk: str | None = None
    dry_run: bool = False
    run: Runner = field(default=run_command)


class Stop(Exception):
    """Why `init` stopped before writing anything, with the exit code to stop with."""

    def __init__(self, why: str, code: int = 1) -> None:
        super().__init__(why)
        self.code = code


def init(framework: str, cwd: Path, options: Options, console: Console) -> int:
    """Run `init`; the exit code: 0 done, 1 stopped or the install failed, 2 a bad command."""
    try:
        root, target = _prepare(framework, cwd, options, console)
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
    console.line(next_steps(_module(written, root), options))
    return 0 if installed else 1


def _prepare(framework: str, cwd: Path, options: Options, console: Console) -> tuple[Path, Path]:
    """The project's root and where the file goes, or `Stop` with why not."""
    if framework != "langgraph":
        raise Stop(f"no template for {framework!r}; there is: langgraph", code=2)
    if options.filename and not options.filename.endswith(".py"):
        raise Stop(f"--file must name a Python file: {options.filename!r}", code=2)
    root = project.find_root(cwd)
    if root is None:
        raise Stop(
            "no Python project here (no pyproject.toml, requirements.txt or langgraph.json at "
            "or above this directory). Run it from your project, or start one with "
            "`twinmemory-cli create langgraph <name>`."
        )
    console.step("found", f"{project.installer(root, ['twinmemory']).name} project at {root}")
    _require_langgraph(root, console)
    _require_versions(root)
    target = (
        (cwd / options.directory).resolve()
        if options.directory
        else _graph_dir(root, options, console)
    )
    written = target / options.filename
    if written.exists() and not options.force:
        raise Stop(f"{_relative(written, root)} exists; --force replaces it. Nothing changed.")
    return root, target


def _require_langgraph(root: Path, console: Console) -> None:
    if project.uses_langgraph(root):
        return
    console.step("note", "this project does not use LangGraph yet")
    if not console.confirm("Add LangGraph to it and go on?"):
        raise Stop(
            "not a LangGraph project; run again with --yes to add LangGraph to it, or start a "
            "new one with `twinmemory-cli create langgraph <name>`. Nothing changed."
        )


def _require_versions(root: Path) -> None:
    site = project.environment(root)
    if site is None:
        return
    stale = [
        (package, version, minimum)
        for package, minimum in MINIMUMS.items()
        if package != "twinmemory"
        and (version := project.installed(site, package))
        and project.older(version, minimum)
    ]
    if stale:
        found = ", ".join(f"{p} {v} (needs >={m})" for p, v, m in stale)
        upgrade = " ".join(f"'{p}>={m}'" for p, _, m in stale)
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
    console.step("would", f"{verb} {_quoted(found.hint)}")


def write(target: Path, options: Options) -> Path:
    template = (
        "langgraph/memory_async.py.tmpl" if options.asynchronous else "langgraph/memory.py.tmpl"
    )
    values = {"version": __version__, "fast": str(options.fast)}
    target.mkdir(parents=True, exist_ok=True)
    written = target / options.filename
    written.write_text(render(template, options.parts, values))
    return written


def requirements(root: Path, options: Options) -> list[str]:
    """What still has to be added for the file to import, each with its minimum."""
    missing = [p for p in MINIMUMS if not project.declares(root, p)]
    return [
        options.sdk if p == "twinmemory" and options.sdk else f"{p}>={MINIMUMS[p]}" for p in missing
    ]


def install(root: Path, options: Options, console: Console) -> bool:
    """Add what the project does not depend on yet, with its own tool; True unless that failed."""
    packages = requirements(root, options)
    if not packages:
        console.step("kept", f"{', '.join(MINIMUMS)}: already dependencies")
        return True
    found = project.installer(root, packages)
    if found.requirements is not None:
        present = found.requirements.read_text()
        separator = "" if not present or present.endswith("\n") else "\n"
        found.requirements.write_text(present + separator + "\n".join(packages) + "\n")
        console.step("added", f"{', '.join(packages)} to {found.requirements.name}")
    if found.command is None or not options.install:
        console.step("run", _quoted(found.hint))
        return True
    shown = _quoted(" ".join(found.command))
    console.step("running", shown)
    if options.run(found.command, root) != 0:
        console.fail(f"`{shown}` failed; run it yourself, then go on.")
        return False
    console.step("ran", shown)
    return True


def setup_key(root: Path, options: Options, console: Console) -> None:
    """Put the key (and address) in `.env` and check it. Skippable: without one, an empty
    `TWIN_MEMORY_API_KEY=` is left to fill in, and `twinmemory-cli doctor` checks it later."""
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
                "Your twin memory API key (from the console, under API keys; Enter to skip):"
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
    if checked.writes is False and "nodes" in options.parts:
        console.step("warning", "this key only reads: remember and memory_add need one that writes")


def next_steps(module: str, options: Options) -> str:
    nodes, tools = "nodes" in options.parts, "tools" in options.parts
    run = "await graph.ainvoke" if options.asynchronous else "graph.invoke"
    names = ["MemoryContext"]
    names += ["MemoryState", "memory_prompt", "recall", "remember"] if nodes else []
    names += ["MEMORY_TOOLS"] if tools else []
    lines = [
        "  Wire it in, where you build your graph:",
        "",
        f"    from {module} import {', '.join(sorted(names))}",
        "",
    ]
    if nodes:
        lines += [
            "    builder = StateGraph(MemoryState, context_schema=MemoryContext)",
            '    builder.add_node("recall", recall)',
            '    builder.add_node("remember", remember)',
            '    builder.add_edge(START, "recall")',
            '    builder.add_edge("recall", "agent")    # your model node: memory_prompt(state)',
            '    builder.add_edge("agent", "remember")  # goes in its system prompt',
            "",
        ]
    if tools:
        lines += [
            "    # the model looks things up itself: give it the tools",
            "    create_agent(model, tools=[*MEMORY_TOOLS, ...], context_schema=MemoryContext)",
            "",
        ]
    lines += [
        "  Run with the end user's id; the model never chooses it:",
        "",
        f'    {run}(inputs, config={{"configurable": {{"thread_id": "t-1"}}}},',
        '                 context={"user_id": "dana"})',
        "",
        f"  The key is {env.KEY} in .env. `langgraph dev` reads .env when langgraph.json",
        '  has "env": ".env"; a plain script loads it itself.',
        "  `twinmemory-cli doctor` checks it all.",
    ]
    return "\n".join(lines)


def _quoted(command: str) -> str:
    """A command as it would be typed: specifiers with `>` quoted for the shell."""
    return " ".join(f"'{word}'" if ">" in word else word for word in command.split(" "))


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
