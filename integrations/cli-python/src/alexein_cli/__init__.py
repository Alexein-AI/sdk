"""`alexein-cli`, in the manner of shadcn: what it writes is the developer's own code from
then on - a short `memory.py` with their settings and one configured `AlexeinMemory`, wired
from the `alexein` client's integration modules - and nothing in this package reaches back
into it.

    alexein-cli init langgraph            memory for a LangGraph project you have
    alexein-cli init openai-agents        ... or an OpenAI Agents SDK one
    alexein-cli init crewai               ... or a CrewAI crew
    alexein-cli create <framework> X      a new project with memory wired in
    alexein-cli doctor                    whether a project is set up for memory
    alexein-cli connect                   Alexein AI in the AI tools on this computer
    alexein search "where does dana live"  memory itself: search, add, forget, export ...

The standard library and the `alexein` client only; it never imports a framework. Never an
installer of anything but the package the written files import, and never a writer of a key it
was not given.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

# The modules, not their functions: `create` and `doctor` are names of both, and binding the
# function here would hide the module of the same name from `alexein_cli.create`.
from alexein_cli import connect as connecting
from alexein_cli import create as creating
from alexein_cli import create_crewai, memory
from alexein_cli import doctor as checking
from alexein_cli import install as installing
from alexein_cli._version import __version__
from alexein_cli.credentials import key_from
from alexein_cli.render import TEMPLATES
from alexein_cli.scaffold import MINIMUMS, Options, init
from alexein_cli.ui import Console

# What `alexein skill` prints: the same file as `@alexein/cli skill`'s.
SKILL = TEMPLATES / "skill" / "SKILL.md"


def _setup_flags(parser: argparse.ArgumentParser) -> None:
    """What `init` and `create` share: the one preset, the key, and how far to go unasked."""
    parser.add_argument(
        "--fast",
        action="store_true",
        help="FAST = True: searches skip the relevance check, free and quicker",
    )
    key = parser.add_argument_group("the key (all of it can be skipped, and done later)")
    key.add_argument(
        "--key",
        help="your API key, written into .env and checked; - reads it from stdin, "
        "so it stays out of your shell history",
    )
    key.add_argument("--base-url", help="memory's address, written into .env")
    key.add_argument("--skip-key", action="store_true", help="do not ask for a key")
    parser.add_argument("--yes", "-y", action="store_true", help="answer yes; ask nothing")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="check everything, say what would happen, change nothing",
    )
    parser.add_argument(
        "--no-install", action="store_true", help="print install commands instead of running them"
    )
    # Installs the client from a checkout's path or a URL instead of PyPI.
    parser.add_argument("--sdk", help=argparse.SUPPRESS)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alexein-cli",
        description="Memory from Alexein for LangGraph, CrewAI and the OpenAI Agents SDK, "
        "as code you own; in the AI tools on this computer; and from here.",
    )
    parser.add_argument("--version", action="version", version=f"alexein-cli {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("init", help="write memory into this project, as code you own")
    start.add_argument("framework", help="langgraph, openai-agents or crewai")
    start.add_argument("--dir", type=Path, help="where to write the file (default: found)")
    start.add_argument("--file", default="memory.py", help="the file's name (default: memory.py)")
    start.add_argument("--graph", help="which graph in langgraph.json it is for (langgraph)")
    start.add_argument("--force", action="store_true", help="replace a file already there")
    _setup_flags(start)

    new = commands.add_parser("create", help="a new project with memory wired in")
    new.add_argument("framework", help="langgraph, openai-agents or crewai")
    new.add_argument("name", help="the project's directory and name")
    new.add_argument(
        "--model",
        help=(
            f"the model, as the framework names it (LangGraph: {creating.DEFAULT_MODEL}; "
            f"CrewAI: {create_crewai.DEFAULT_MODEL}; the OpenAI Agents SDK: its own default)"
        ),
    )
    _setup_flags(new)

    check = commands.add_parser("doctor", help="check that this project is set up for memory")
    check.add_argument("--json", action="store_true", help="the checks as JSON")

    tools = commands.add_parser(
        "connect",
        help="add Alexein AI to Claude Code, Cursor, VS Code, Copilot CLI, Codex, Gemini CLI, "
        "Antigravity and Devin Desktop",
    )
    tools.add_argument(
        "--only",
        help="just these, comma-separated: " + ", ".join(c.id for c in connecting.CLIENTS),
    )
    tools.add_argument(
        "--no-plugin",
        action="store_true",
        help="add the server alone, not Alexein AI's plugin where a tool has one",
    )
    tools.add_argument(
        "--list",
        action="store_true",
        help="say which tools are here and which have Alexein; change nothing",
    )
    tools.add_argument("--json", action="store_true", help="with --list: the same, as JSON")
    tools.add_argument(
        "--remove",
        action="store_true",
        help="take out what connect added: the plugin, the server or its entry",
    )
    tools.add_argument(
        "--key",
        help="send this key in a header instead of signing in (for CI), no plugins; "
        "- reads it from stdin",
    )
    tools.add_argument("--force", action="store_true", help="add it again where Alexein is already")
    tools.add_argument("--yes", "-y", action="store_true", help="answer yes; ask nothing")
    tools.add_argument(
        "--dry-run", action="store_true", help="say what would happen, change nothing"
    )
    memory.register(commands.add_parser)
    commands.add_parser(
        "install",
        help="put the alexein command on your PATH, to type alexein ... from then on "
        "(login, connect, init and create offer it once)",
    )
    commands.add_parser(
        "skill",
        help="the guide for an AI agent to use these commands, to save as its skill: "
        "alexein skill > ~/.claude/skills/alexein/SKILL.md",
    )
    return parser


__all__ = ["key_from", "main"]


def _read_stdin() -> str | None:
    """What was piped in; nothing at a terminal, where reading would wait for the key, echoed."""
    return None if sys.stdin.isatty() else sys.stdin.read()


def _connect(args: argparse.Namespace, console: Console) -> int:
    if args.json and not args.list:
        console.fail("--json is for doctor and connect --list")
        return 2
    if args.remove and (args.key or args.no_plugin or args.force or args.list):
        console.fail("--remove goes with --only, --dry-run and --yes")
        return 2
    only = [name.strip() for name in (args.only or "").split(",") if name.strip()]
    options = connecting.ConnectOptions(
        only=only,
        key=args.key,
        plugins=not args.no_plugin,
        force=args.force,
        listing=args.list,
        dry_run=args.dry_run,
        remove=args.remove,
        as_json=args.json,
    )
    return connecting.connect(options, console)


def _options(args: argparse.Namespace) -> Options:
    return Options(
        framework=args.framework,
        directory=getattr(args, "dir", None),
        filename=getattr(args, "file", "memory.py"),
        graph=getattr(args, "graph", None),
        force=getattr(args, "force", False),
        install=not args.no_install,
        fast=args.fast,
        key=args.key,
        base_url=args.base_url,
        skip_key=args.skip_key or args.yes,
        sdk=args.sdk,
        dry_run=args.dry_run,
    )


def main(
    argv: Sequence[str] | None = None,
    console: Console | None = None,
    stdin: Callable[[], str | None] = _read_stdin,
) -> int:
    args = _parser().parse_args(argv)
    cwd = Path.cwd()
    if args.command == "doctor":
        return checking.doctor(cwd, console or Console.for_terminal(yes=True), as_json=args.json)
    if args.command == "skill":
        (console or Console.for_terminal(yes=True)).line(SKILL.read_text().rstrip())
        return 0
    if args.command == "install":
        return installing.install(console or Console.for_terminal(yes=True))
    if args.command in memory.NAMES:
        yes = bool(getattr(args, "yes", False))
        console = console or Console.for_terminal(yes=yes)
        return _offered(memory.run(args, console, stdin), console, args.command == "login")
    console = console or Console.for_terminal(yes=args.yes)
    try:
        args.key = key_from(args.key, stdin)
    except ValueError as error:
        console.fail(str(error))
        return 2
    if args.command == "connect":
        quiet = args.list or args.json or args.dry_run or args.remove
        return _offered(_connect(args, console), console, not quiet)
    if args.command == "create":
        if args.framework not in MINIMUMS:
            console.fail(f"no template for {args.framework!r}; there is: {', '.join(MINIMUMS)}")
            return 2
        if args.framework == "crewai":
            model = args.model or create_crewai.DEFAULT_MODEL
            made = create_crewai.create(args.name, cwd, model, _options(args), console)
        else:
            model = args.model or (creating.DEFAULT_MODEL if args.framework == "langgraph" else "")
            made = creating.create(args.name, cwd, model, _options(args), console)
        return _offered(made, console, not args.dry_run)
    return _offered(init(cwd, _options(args), console), console, not args.dry_run)


def _offered(code: int, console: Console, offer: bool) -> int:
    """A setup command's exit code, after offering once to install `alexein` where it did its
    work."""
    if code == 0 and offer:
        installing.offer_install(console)
    return code


if __name__ == "__main__":
    sys.exit(main())
