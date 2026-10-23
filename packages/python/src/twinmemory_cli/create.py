"""`twinmemory-cli create <framework> <name>`: a new project with memory already wired in - for
LangGraph a graph, a terminal chat, `langgraph.json` for `langgraph dev`; for the OpenAI Agents
SDK an agent and a terminal chat; and `memory.py` as `init` writes it - so there is something to
run before there is anything to wire.

The project is a uv one: `uvx` is how this command is run, so uv is there to run it with.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from twinmemory_cli import env, scaffold
from twinmemory_cli.render import render
from twinmemory_cli.ui import Console

# LangGraph's, as `init_chat_model` names it. The OpenAI Agents SDK has a default of its own,
# which an agent gets when it names none.
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
    langgraph = options.framework == "langgraph"
    if langgraph:
        provider = model.split(":", 1)[0] if ":" in model else ""
        library, provider_key = PROVIDERS.get(provider, ("", ""))
    else:
        library, provider_key = "", "OPENAI_API_KEY"
    if options.dry_run:
        _plan(root, package, library, options, console)
        return 0
    _skeleton(root, name, package, model, provider_key, options)
    console.step("made", f"{root}")
    scaffold.write(root / "src" / package, options)
    console.step("wrote", f"src/{package}/memory.py, {_MAIN[options.framework]}, chat.py")

    packages = [*scaffold.requirements(root, options), "python-dotenv"]
    packages += [library] if library else []
    installed = _install(root, packages, options, console)
    if langgraph and not library:
        console.step("note", f"add the LangChain package for {model!r} yourself")
    scaffold.setup_key(root, options, console)
    console.line()
    key, _ = env.resolve(root)
    unset = [k for k in (provider_key,) if k] + ([] if key else [env.KEY])
    console.line(_next(name, package, unset, langgraph=langgraph))
    return 0 if installed else 1


# The file each framework's project is built around, beside `memory.py` and `chat.py`.
_MAIN = {"langgraph": "graph.py", "openai-agents": "agent.py"}


def _plan(
    root: Path, package: str, library: str, options: scaffold.Options, console: Console
) -> None:
    """What `create` would do, nothing made and nothing run."""
    console.step("would", f"make {root}")
    langgraph = ("langgraph.json",) if options.framework == "langgraph" else ()
    for path in ("pyproject.toml", *langgraph, "README.md", ".gitignore", ".env"):
        console.step("would", f"write {path}")
    for path in (_MAIN[options.framework], "chat.py", "memory.py"):
        console.step("would", f"write src/{package}/{path}")
    packages = [*scaffold.requirements(root, options), "python-dotenv"]
    packages += [library] if library else []
    verb = "run" if options.install else "print"
    shown = " ".join(f"'{p}'" if ">" in p else p for p in packages)
    console.step("would", f"{verb} uv add {shown}")
    if langgraph:
        console.step("would", f"{verb} uv add --dev 'langgraph-cli[inmem]'")
    console.line()
    console.line("Dry run: nothing was made.")


def _skeleton(
    root: Path, name: str, package: str, model: str, provider_key: str, options: scaffold.Options
) -> None:
    values = {"name": name, "package": package, "model": model, "provider_key": provider_key}
    preset = _preset(options)
    files: dict[str, tuple[str, tuple[str, ...]] | None] = {
        "pyproject.toml": ("pyproject.toml.tmpl", ()),
        ".gitignore": ("gitignore.tmpl", ()),
        "README.md": ("README.md.tmpl", ()),
        f"src/{package}/chat.py": ("chat.py.tmpl", preset),
        f"src/{package}/__init__.py": None,
    }
    if options.framework == "langgraph":
        files["langgraph.json"] = ("langgraph.json.tmpl", ())
        files[".env.example"] = ("env.example.tmpl", ("provider_key",) if provider_key else ())
        files[f"src/{package}/graph.py"] = ("graph.py.tmpl", preset)
    else:
        files[".env.example"] = ("env.example.tmpl", ("model",) if model else ("no_model",))
        files[f"src/{package}/agent.py"] = ("agent.py.tmpl", preset)
    directory = options.framework.replace("-", "_")
    for path, source in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source is None:
            target.write_text("")
            continue
        template, parts = source
        target.write_text(render(f"{directory}/project/{template}", parts, values))
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
    commands = [["uv", "add", *packages]]
    if options.framework == "langgraph":
        commands += [["uv", "add", "--dev", "langgraph-cli[inmem]"]]
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


def _next(name: str, package: str, unset: list[str], *, langgraph: bool) -> str:
    fill = [f"    # fill in {' and '.join(unset)} in .env"] if unset else []
    steps = [(f"uv run python -m {package}.chat --user dana", "talk to it")]
    steps += [("uv run langgraph dev", "or open it in LangGraph Studio")] if langgraph else []
    steps += [("uvx twinmemory-cli doctor", "check the setup")]
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
