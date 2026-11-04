"""`alexein-cli`, in the manner of shadcn: what it writes is the developer's own code from
then on - a short `memory.py` with their settings and one configured `AlexeinMemory`, wired
from the `alexein` client's integration modules - and nothing in this package reaches back
into it.

    alexein-cli init langgraph            memory for a LangGraph project you have
    alexein-cli init openai-agents        ... or an OpenAI Agents SDK one
    alexein-cli init crewai               ... or a CrewAI crew
    alexein-cli create <framework> X      a new project with memory wired in
    alexein-cli doctor                    whether a project is set up for memory

The standard library and the `alexein` client only; it never imports a framework. Never an
installer of anything but the package the written files import, and never a writer of a key it
was not given.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

# The modules, not their functions: `create` and `doctor` are names of both, and binding the
# function here would hide the module of the same name from `alexein_cli.create`.
from alexein_cli import create as creating
from alexein_cli import create_crewai
from alexein_cli import doctor as checking
from alexein_cli._version import __version__
from alexein_cli.scaffold import MINIMUMS, Options, init
from alexein_cli.ui import Console


def _setup_flags(parser: argparse.ArgumentParser) -> None:
    """What `init` and `create` share: the one preset, the key, and how far to go unasked."""
    parser.add_argument(
        "--fast",
        action="store_true",
        help="FAST = True: searches skip the relevance check, free and quicker",
    )
    key = parser.add_argument_group("the key (all of it can be skipped, and done later)")
    key.add_argument("--key", help="your API key, written into .env and checked")
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
        "as code you own.",
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

    commands.add_parser("doctor", help="check that this project is set up for memory")
    return parser


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


def main(argv: Sequence[str] | None = None, console: Console | None = None) -> int:
    args = _parser().parse_args(argv)
    cwd = Path.cwd()
    if args.command == "doctor":
        return checking.doctor(cwd, console or Console.for_terminal(yes=True))
    console = console or Console.for_terminal(yes=args.yes)
    if args.command == "create":
        if args.framework not in MINIMUMS:
            console.fail(f"no template for {args.framework!r}; there is: {', '.join(MINIMUMS)}")
            return 2
        if args.framework == "crewai":
            model = args.model or create_crewai.DEFAULT_MODEL
            return create_crewai.create(args.name, cwd, model, _options(args), console)
        model = args.model or (creating.DEFAULT_MODEL if args.framework == "langgraph" else "")
        return creating.create(args.name, cwd, model, _options(args), console)
    return init(cwd, _options(args), console)


if __name__ == "__main__":
    sys.exit(main())
