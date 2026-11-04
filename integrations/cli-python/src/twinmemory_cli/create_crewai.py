"""`twinmemory-cli create crewai <name>`: a new classic CrewAI crew with memory already wired in -
an assistant agent, its task, `run_crew`, and `memory.py` as `init crewai` writes it - so there is
something to run before there is anything to wire.

The project is a uv one, laid out as `crewai create crew --classic` lays one out, made here so the
`crewai` command need not be installed first.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from twinmemory_cli import crews, env, scaffold
from twinmemory_cli.render import render
from twinmemory_cli.ui import Console

DEFAULT_MODEL = "anthropic/claude-sonnet-5-5"

# What each CrewAI provider needs: the `crewai` extra that brings its SDK, and the key it reads.
# A provider not named here still works; its key is the developer's to add.
PROVIDERS = {
    "anthropic": ("anthropic", "ANTHROPIC_API_KEY"),
    "claude": ("anthropic", "ANTHROPIC_API_KEY"),
    "openai": ("", "OPENAI_API_KEY"),
    "openrouter": ("", "OPENROUTER_API_KEY"),
    "deepseek": ("", "DEEPSEEK_API_KEY"),
    "gemini": ("google-genai", "GEMINI_API_KEY"),
    "google": ("google-genai", "GEMINI_API_KEY"),
    "bedrock": ("bedrock", ""),
    "ollama": ("", ""),
}
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
_PROJECT = "crewai/project/"


def create(name: str, cwd: Path, model: str, options: scaffold.Options, console: Console) -> int:
    """Make the crew; 0 when it is ready, 1 when something stopped it, 2 a bad command."""
    if not _NAME.fullmatch(name):
        console.fail(f"{name!r} is not a project name: lowercase letters, digits and '-'")
        return 2
    root = (cwd / name).resolve()
    if root.exists() and any(root.iterdir()):
        console.fail(f"{root} exists and is not empty. Nothing changed.")
        return 1
    if options.install and not options.dry_run and not shutil.which("uv"):
        console.fail("this needs uv to set the project up: https://docs.astral.sh/uv/")
        return 1
    options.framework = "crewai"
    options.parts = ("tools", "tools_only") if options.parts == ("tools",) else ("auto", "tools")
    package = name.replace("-", "_")
    extra, provider_key = PROVIDERS.get(model.split("/", 1)[0], ("", ""))
    floor = crews.CREWAI_MINIMUM
    crewai = f"crewai[{extra}]>={floor}" if extra else f"crewai>={floor}"
    packages = [*scaffold.requirements(root, options), crewai, "python-dotenv"]
    files = _files(package, provider_key, options.parts)
    if options.dry_run:
        console.step("would", f"make {root}")
        for path in [*files, f"src/{package}/memory.py"]:
            console.step("would", f"write {path}")
        console.step(
            "would", f"{'run' if options.install else 'print'} uv add {' '.join(packages)}"
        )
        console.line()
        console.line("Dry run: nothing was made.")
        return 0
    values = {
        "name": name,
        "package": package,
        "model": model,
        "provider_key": provider_key,
        "crew_class": "".join(part.capitalize() for part in name.split("-")),
    }
    for path, (template, parts) in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(_PROJECT + template, parts, values) if template else "")
    example = (root / ".env.example").read_text().splitlines()
    (root / ".env").write_text("\n".join(x for x in example if not x.startswith("#")) + "\n")
    scaffold.write(root / "src" / package, options)
    console.step("made", str(root))
    installed = _install(root, packages, options, console)
    if installed and options.install:
        crews.require_version(root, console)  # the newest CrewAI, maybe newer than tested
    scaffold.setup_key(root, options, console)
    key, _ = env.resolve(root)
    unset = [k for k in (provider_key,) if k] + ([] if key else [env.KEY])
    console.line()
    console.line(_next(name, unset))
    return 0 if installed else 1


def _files(
    package: str, provider_key: str, parts: tuple[str, ...]
) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Each file the project gets, from which template, with which of its parts: the crew and
    `main.py` follow the preset, as `memory.py` does."""
    return {
        f"src/{package}/crew.py": ("crew.py.tmpl", parts),
        f"src/{package}/main.py": ("main.py.tmpl", parts),
        "pyproject.toml": ("pyproject.toml.tmpl", ()),
        "README.md": ("README.md.tmpl", ()),
        ".gitignore": ("gitignore.tmpl", ()),
        ".env.example": ("env.example.tmpl", ("provider_key",) if provider_key else ()),
        f"src/{package}/__init__.py": ("", ()),
        f"src/{package}/config/agents.yaml": ("agents.yaml.tmpl", ()),
        f"src/{package}/config/tasks.yaml": ("tasks.yaml.tmpl", ()),
    }


def _install(root: Path, packages: list[str], options: scaffold.Options, console: Console) -> bool:
    command = ["uv", "add", *packages]
    shown = " ".join(f"'{w}'" if ">" in w or "[" in w else w for w in command)
    if not options.install:
        console.step("run", shown)
        return True
    console.step("running", shown)
    if options.run(command, root) != 0:
        console.fail(f"`{shown}` failed; run it in {root} yourself, then go on.")
        return False
    console.step("ran", shown)
    return True


def _next(name: str, unset: list[str]) -> str:
    fill = [f"    # fill in {' and '.join(unset)} in .env"] if unset else []
    steps = [
        ('uv run run_crew --user dana "I just moved to Lisbon."', "tell it something"),
        ('uv run run_crew --user dana "Where do I live?"', "it remembers"),
        ("uvx twinmemory-cli doctor", "check the setup"),
    ]
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
