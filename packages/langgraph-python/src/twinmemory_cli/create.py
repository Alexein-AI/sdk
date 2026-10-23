"""`twinmemory-cli create langgraph <name>`: a new LangGraph project with memory already wired in -
a graph, a terminal chat, `langgraph.json` for `langgraph dev`, and `memory.py` as `init` writes
it - so there is something to run before there is anything to wire.

The project is a uv one: `uvx` is how this command is run, so uv is there to run it with.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from twinmemory_cli import env, scaffold
from twinmemory_cli.render import render
from twinmemory_cli.ui import Console

DEFAULT_MODEL = "anthropic:claude-sonnet-5-5"

# The LangChain package each `init_chat_model` provider needs, and the key it reads. A provider
# not named here still works; its package and key are the developer's to add.
PROVIDERS = {
    "anthropic": ("langchain-anthropic", "ANTHROPIC_API_KEY"),
    "openai": ("langchain-openai", "OPENAI_API_KEY"),
    "azure_openai": ("langchain-openai", "AZURE_OPENAI_API_KEY"),
    "google_genai": ("langchain-google-genai", "GOOGLE_API_KEY"),
    "mistralai": ("langchain-mistralai", "MISTRAL_API_KEY"),
    "groq": ("langchain-groq", "GROQ_API_KEY"),
    "ollama": ("langchain-ollama", ""),
    "bedrock_converse": ("langchain-aws", ""),
}
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")


def create(name: str, cwd: Path, model: str, options: scaffold.Options, console: Console) -> int:
    """Make the project; 0 when it is ready, 1 when something stopped it, 2 a bad command."""
    if not _NAME.fullmatch(name):
        console.fail(f"{name!r} is not a project name: letters, digits, '-' and '_'")
        return 2
    root = (cwd / name).resolve()
    if root.exists() and any(root.iterdir()):
        console.fail(f"{root} exists and is not empty. Nothing changed.")
        return 1
    if options.install and not shutil.which("uv"):
        console.fail("this needs uv to set the project up: https://docs.astral.sh/uv/")
        return 1
    package = name.replace("-", "_").lower()
    provider = model.split(":", 1)[0] if ":" in model else ""
    library, provider_key = PROVIDERS.get(provider, ("", ""))
    if options.dry_run:
        _plan(root, package, library, options, console)
        return 0
    _skeleton(root, name, package, model, provider_key, options)
    console.step("made", f"{root}")
    scaffold.write(root / "src" / package, options)
    console.step("wrote", f"src/{package}/memory.py, graph.py, chat.py")

    packages = [*scaffold.requirements(root, options), "python-dotenv"]
    packages += [library] if library else []
    installed = _install(root, packages, options, console)
    if not library:
        console.step("note", f"add the LangChain package for {model!r} yourself")
    scaffold.setup_key(root, options, console)
    console.line()
    key, _ = env.resolve(root)
    console.line(
        _next(name, package, [k for k in (provider_key,) if k] + ([] if key else [env.KEY]))
    )
    return 0 if installed else 1


def _plan(
    root: Path, package: str, library: str, options: scaffold.Options, console: Console
) -> None:
    """What `create` would do, nothing made and nothing run."""
    console.step("would", f"make {root}")
    for path in ("pyproject.toml", "langgraph.json", "README.md", ".gitignore", ".env"):
        console.step("would", f"write {path}")
    for path in ("graph.py", "chat.py", "memory.py"):
        console.step("would", f"write src/{package}/{path}")
    packages = [*scaffold.requirements(root, options), "python-dotenv"]
    packages += [library] if library else []
    verb = "run" if options.install else "print"
    shown = " ".join(f"'{p}'" if ">" in p else p for p in packages)
    console.step("would", f"{verb} uv add {shown}")
    console.step("would", f"{verb} uv add --dev 'langgraph-cli[inmem]'")
    console.line()
    console.line("Dry run: nothing was made.")


def _skeleton(
    root: Path, name: str, package: str, model: str, provider_key: str, options: scaffold.Options
) -> None:
    values = {"name": name, "package": package, "model": model, "provider_key": provider_key}
    preset = _preset(options)
    files = {
        "pyproject.toml": ("pyproject.toml.tmpl", ()),
        "langgraph.json": ("langgraph.json.tmpl", ()),
        ".gitignore": ("gitignore.tmpl", ()),
        "README.md": ("README.md.tmpl", ()),
        ".env.example": ("env.example.tmpl", ("provider_key",) if provider_key else ()),
        f"src/{package}/graph.py": ("graph.py.tmpl", preset),
        f"src/{package}/chat.py": ("chat.py.tmpl", preset),
        f"src/{package}/__init__.py": None,
    }
    for path, source in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source is None:
            target.write_text("")
            continue
        template, parts = source
        target.write_text(render(f"langgraph/project/{template}", parts, values))
    example = (root / ".env.example").read_text()
    (root / ".env").write_text(
        "\n".join(line for line in example.splitlines() if not line.startswith("#")) + "\n"
    )


def _preset(options: scaffold.Options) -> tuple[str, ...]:
    """The graph's parts, from the file's: which of nodes and tools, both, and sync or async."""
    nodes, tools = "nodes" in options.parts, "tools" in options.parts
    parts = ["async" if options.asynchronous else "sync"]
    parts += ["nodes"] if nodes else []
    parts += ["tools"] if tools else []
    parts += ["both"] if nodes and tools else ["nodes_only"] if nodes else ["tools_only"]
    return tuple(parts)


def _install(root: Path, packages: list[str], options: scaffold.Options, console: Console) -> bool:
    commands = [["uv", "add", *packages], ["uv", "add", "--dev", "langgraph-cli[inmem]"]]
    for command in commands:
        shown = " ".join(f"'{w}'" if ">" in w or "[" in w else w for w in command)
        if not options.install:
            console.step("run", shown)
            continue
        console.step("running", shown)
        if options.run(command, root) != 0:
            console.fail(f"`{shown}` failed; run it in {root} yourself, then go on.")
            return False
        console.step("ran", shown)
    return True


def _next(name: str, package: str, unset: list[str]) -> str:
    fill = [f"    # fill in {' and '.join(unset)} in .env"] if unset else []
    steps = [
        (f"uv run python -m {package}.chat --user dana", "talk to it"),
        ("uv run langgraph dev", "or open it in LangGraph Studio"),
        ("uvx twinmemory-cli doctor", "check the setup"),
    ]
    # The comments line up however long the package's name makes the first command.
    width = max(len(command) for command, _ in steps) + 3
    return "\n".join(
        [
            "  Next:",
            "",
            f"    cd {name}",
            *fill,
            *(f"    {command.ljust(width)}# {why}" for command, why in steps),
        ]
    )
