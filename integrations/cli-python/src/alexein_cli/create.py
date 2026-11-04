"""`alexein-cli create <framework> <name>`: a new project with memory already wired in - for
LangGraph a graph, a terminal chat, `langgraph.json` for `langgraph dev`; for the OpenAI Agents
SDK an agent and a terminal chat; and `memory.py` as `init` writes it - so there is something to
run before there is anything to wire.

The project is a uv one: `uvx` is how this command is run, so uv is there to run it with.
"""

from __future__ import annotations

import re
import shlex
import shutil
from pathlib import Path

from alexein_cli import env, scaffold
from alexein_cli.render import render
from alexein_cli.ui import Console

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
    packages = [*scaffold.requirements(root, options), "python-dotenv"]
    packages += [library] if library else []
    commands = [["uv", "add", *packages]]
    commands += [["uv", "add", "--dev", "langgraph-cli[inmem]"]] if langgraph else []
    if options.dry_run:
        _plan(root, package, commands, options, console)
        return 0
    _skeleton(root, name, package, model, provider_key, options.framework)
    console.step("made", f"{root}")
    scaffold.write(root / "src" / package, options)
    console.step("wrote", f"src/{package}/memory.py, {_MAIN[options.framework]}, chat.py")
    installed = _install(root, commands, options, console)
    if langgraph and not library:
        console.step("note", f"add the LangChain package for {model!r} yourself")
    scaffold.setup_key(root, options, console)
    console.line()
    key, _ = env.resolve(root)
    unset = [k for k in (provider_key,) if k] + ([] if key else [env.KEY])
    console.line(_next(name, package, unset, langgraph=langgraph))
    return 0 if installed else 1


# The file each framework's project is built around, beside `memory.py` and `chat.py`, and
# what the project is, for its pyproject.toml.
_MAIN = {"langgraph": "graph.py", "openai-agents": "agent.py"}
_DESCRIBED = {"langgraph": "A LangGraph agent", "openai-agents": "An OpenAI Agents SDK agent"}


def _plan(
    root: Path, package: str, commands: list[list[str]], options: scaffold.Options, console: Console
) -> None:
    """What `create` would do, nothing made and nothing run."""
    console.step("would", f"make {root}")
    langgraph = ("langgraph.json",) if options.framework == "langgraph" else ()
    for path in ("pyproject.toml", *langgraph, "README.md", ".gitignore", ".env"):
        console.step("would", f"write {path}")
    for path in (_MAIN[options.framework], "chat.py", "memory.py"):
        console.step("would", f"write src/{package}/{path}")
    verb = "run" if options.install else "print"
    for command in commands:
        console.step("would", f"{verb} {_shown(command)}")
    console.line()
    console.line("Dry run: nothing was made.")


def _skeleton(
    root: Path, name: str, package: str, model: str, provider_key: str, framework: str
) -> None:
    langgraph = framework == "langgraph"
    values = {
        "name": name,
        "package": package,
        "model": model,
        "provider_key": provider_key,
        "description": f"{_DESCRIBED[framework]} that remembers the people it talks to, "
        "with Alexein.",
    }
    own = f"{framework.replace('-', '_')}/project"
    main = _MAIN[framework]
    files: dict[str, tuple[str, tuple[str, ...]] | None] = {
        "pyproject.toml": ("project/pyproject.toml.tmpl", ()),
        ".gitignore": ("project/gitignore.tmpl", ("langgraph",) if langgraph else ()),
        "README.md": (f"{own}/README.md.tmpl", ()),
        ".env.example": (f"{own}/env.example.tmpl", ("provider_key",) if provider_key else ()),
        f"src/{package}/{main}": (f"{own}/{main}.tmpl", ()),
        f"src/{package}/chat.py": (f"{own}/chat.py.tmpl", ()),
        f"src/{package}/__init__.py": None,
    }
    if langgraph:
        files["langgraph.json"] = (f"{own}/langgraph.json.tmpl", ())
    for path, source in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if source is None:
            target.write_text("")
            continue
        template, parts = source
        target.write_text(render(template, parts, values))
    example = (root / ".env.example").read_text()
    (root / ".env").write_text(
        "\n".join(line for line in example.splitlines() if not line.startswith("#")) + "\n"
    )


def _shown(command: list[str]) -> str:
    """A command as it would be typed, quoted for the shell."""
    return shlex.join(command)


def _install(
    root: Path, commands: list[list[str]], options: scaffold.Options, console: Console
) -> bool:
    for command in commands:
        shown = _shown(command)
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
    steps = [(f"uv run -m {package}.chat --user dana", "talk to it")]
    steps += [("uv run langgraph dev", "or open it in LangGraph Studio")] if langgraph else []
    steps += [("uvx alexein-cli doctor", "check the setup")]
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
