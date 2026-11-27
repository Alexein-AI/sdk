"""`alexein-cli connect`: Alexein AI's memory server added to the AI tools on this computer -
Claude Code, Cursor, VS Code, GitHub Copilot CLI, Codex, Gemini CLI, Antigravity and Devin
Desktop - so each searches the person's memory and saves what it learns. The same as
`@alexein/cli connect`, tool for tool, so a Python developer needs no Node for it.

Each tool is told through its own command where it has one (`claude mcp add`, `code --add-mcp`),
so it writes its own settings; only Cursor and Devin Desktop without its CLI have their file
edited, the `alexein` entry alone, after a copy of the file is kept. Where a tool has an Alexein
AI plugin, the plugin goes in instead: the same server, and the guidance on when to search and
save. Nothing is replaced that is already there, short of `--force`.

`--remove` takes out what this adds - the plugin, the `alexein` server, or its entry in a file -
through the tool's own command where it has one, and leaves anything else named for Alexein.

The tools sign in to Alexein themselves, so no key is written anywhere. `--key` is for where
nobody is there to sign in: then each gets the key in a header, and no plugin.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from alexein_cli._version import __version__
from alexein_cli.ui import Console

URL = "https://api.alexein.ai/v1/mcp"
# The server's name in every tool. A plugin's server is named by the plugin.
NAME = "alexein"
# What Claude Code calls the plugin's server: `plugin:<plugin>:<server>`.
CLAUDE_PLUGIN_SERVER = f"plugin:alexein:{NAME}"
DOCS = "https://docs.alexein.ai/mcp"

Step = tuple[str, list[str]]


@dataclass(frozen=True)
class Ran:
    """A command run quietly: its exit code and what it printed."""

    code: int
    out: str


class Host(Protocol):
    """What `connect` needs of the computer: a test hands in one over a scratch home."""

    @property
    def home(self) -> Path: ...

    @property
    def platform(self) -> str: ...

    @property
    def env(self) -> Mapping[str, str]: ...

    def has(self, command: str) -> bool:
        """Whether a command is on PATH."""
        ...

    def run(self, command: str, args: Sequence[str]) -> Ran:
        """A command run quietly."""
        ...

    def attach(self, command: str, args: Sequence[str]) -> int:
        """A command run in the terminal, for a sign-in that opens the browser."""
        ...


class LocalHost:
    """This computer."""

    def __init__(self) -> None:
        self.home = Path.home()
        self.platform = sys.platform
        self.env: Mapping[str, str] = os.environ

    def has(self, command: str) -> bool:
        return shutil.which(command) is not None

    def run(self, command: str, args: Sequence[str]) -> Ran:
        try:
            done = subprocess.run(
                [shutil.which(command) or command, *args],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return Ran(1, str(error))
        return Ran(done.returncode, f"{done.stdout or ''}{done.stderr or ''}")

    def attach(self, command: str, args: Sequence[str]) -> int:
        try:
            return subprocess.run([shutil.which(command) or command, *args], check=False).returncode
        except OSError:
            return 1


@dataclass(frozen=True)
class ConnectOptions:
    only: list[str] = field(default_factory=list[str])
    key: str | None = None
    plugins: bool = True
    force: bool = False
    listing: bool = False
    dry_run: bool = False
    # Take out what `connect` added, instead of adding it.
    remove: bool = False
    # With `listing`: the same, as JSON.
    as_json: bool = False


@dataclass(frozen=True)
class Plan:
    """What a tool is told, in one of the ways a `Client` knows."""

    how: str
    steps: list[Step]


@dataclass(frozen=True)
class Client:
    id: str
    name: str
    # Whether it is on this computer.
    found: Callable[[Host], bool]
    # Whether Alexein is in it already, under any name.
    present: Callable[[Host], bool]
    # The commands that add it: with the plugin when there is one and plugins are on.
    plan: Callable[[Host, ConnectOptions], Plan | None]
    # Where the person signs in, when not from the terminal.
    sign_in: str
    # Edits a settings file instead of running a command.
    write: Callable[[Host, ConnectOptions], Path] | None = None
    # The commands that take out what `plan` added, of what is here; None when none is.
    removal: Callable[[Host], Plan | None] | None = None
    # Takes the `alexein` entry out of a settings file; None when it has none by that name.
    unwrite: Callable[[Host], Path | None] | None = None
    # A sign-in run from the terminal, when the tool has one.
    login: Callable[[ConnectOptions], Step] | None = None


def headers(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "X-Alexein-User": "me"}


def header_flags(flag: str, key: str | None) -> list[str]:
    return [part for k, v in headers(key).items() for part in (flag, f"{k}: {v}")] if key else []


def mentions(out: str) -> bool:
    return re.search(r"\balexein(-ai)?\b", out, re.IGNORECASE) is not None


def commands(steps: list[Step]) -> str:
    """What steps run, by each command's first words: `claude plugin uninstall`."""
    return ", ".join(" ".join([command, *args[:2]]) for command, args in steps)


def read_settings(path: Path) -> dict[str, Any] | None:
    """A JSON settings file, or `{}` when it is not there; None when it is not a JSON object."""
    if not path.exists():
        return {}
    try:
        parsed: object = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None  # pyright: ignore[reportUnknownVariableType]


def servers(path: Path, field: str) -> dict[str, Any]:
    """The servers under `field` in a settings file."""
    value = (read_settings(path) or {}).get(field)
    return dict(value) if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownArgumentType]


def has_server(path: Path, field: str) -> bool:
    return any(mentions(name) for name in servers(path, field))


def _save(path: Path, settings: dict[str, Any]) -> None:
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n")


def merge_server(path: Path, field: str, entry: dict[str, Any]) -> Path:
    """`entry` set as `NAME` under `field`, the rest of the file as it was, and a copy kept."""
    settings = read_settings(path)
    if settings is None:
        raise ValueError(f"{path} is not valid JSON; fix it, or add Alexein by hand")
    if path.exists():
        shutil.copyfile(path, f"{path}.bak")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    settings[field] = {**servers(path, field), NAME: entry}
    _save(path, settings)
    return path


def drop_server(path: Path, field: str) -> Path | None:
    """`NAME` taken out from under `field`, the rest of the file as it was, and a copy kept;
    None when there is no server by that name - one under another name was not added here."""
    settings = read_settings(path)
    if settings is None:
        raise ValueError(f"{path} is not valid JSON; take alexein out by hand")
    kept = servers(path, field)
    if NAME not in kept:
        return None
    shutil.copyfile(path, f"{path}.bak")
    settings[field] = {name: entry for name, entry in kept.items() if name != NAME}
    _save(path, settings)
    return path


def _roaming(host: Host) -> Path:
    return Path(host.env.get("APPDATA") or host.home / "AppData" / "Roaming")


def vscode_settings(host: Host) -> Path:
    if host.platform == "darwin":
        return host.home / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    if host.platform == "win32":
        return _roaming(host) / "Code" / "User" / "mcp.json"
    return host.home / ".config" / "Code" / "User" / "mcp.json"


def devin_settings(host: Host) -> Path:
    if host.platform == "win32":
        return _roaming(host) / "devin" / "mcp_config.json"
    return host.home / ".config" / "devin" / "mcp_config.json"


def cursor_settings(host: Host) -> Path:
    return host.home / ".cursor" / "mcp.json"


def _with_plugin(o: ConnectOptions) -> bool:
    return o.plugins and not o.key


def _claude_present(host: Host) -> bool:
    return (
        host.run("claude", ["mcp", "get", NAME]).code == 0
        or re.search(r"alexein@alexein", host.run("claude", ["plugin", "list"]).out) is not None
    )


def _claude_plan(_host: Host, o: ConnectOptions) -> Plan:
    if _with_plugin(o):
        return Plan(
            "the Alexein AI plugin",
            [
                ("claude", ["plugin", "marketplace", "add", "Alexein-AI/claude-plugins"]),
                ("claude", ["plugin", "install", "alexein@alexein"]),
            ],
        )
    add = ["mcp", "add", "--transport", "http", "--scope", "user"]
    return Plan("claude mcp add", [("claude", [*add, *header_flags("--header", o.key), NAME, URL])])


def _claude_removal(host: Host) -> Plan | None:
    """The plugin, and the server at the user scope `plan` adds it at: never a project's own."""
    steps: list[Step] = []
    if re.search(r"alexein@alexein", host.run("claude", ["plugin", "list"]).out):
        steps.append(("claude", ["plugin", "uninstall", "alexein@alexein"]))
    if host.run("claude", ["mcp", "get", NAME]).code == 0:
        steps.append(("claude", ["mcp", "remove", "--scope", "user", NAME]))
    return Plan(commands(steps), steps) if steps else None


def _vscode_plan(_host: Host, o: ConnectOptions) -> Plan:
    server: dict[str, Any] = {"name": NAME, "type": "http", "url": URL}
    if o.key:
        server["headers"] = headers(o.key)
    # Compact, as JSON.stringify writes it: the argument `code` reads.
    entry = json.dumps(server, separators=(",", ":"), ensure_ascii=False)
    return Plan("code --add-mcp", [("code", ["--add-mcp", entry])])


def _copilot_plan(_host: Host, o: ConnectOptions) -> Plan:
    if _with_plugin(o):
        return Plan(
            "the Alexein AI plugin",
            [
                ("copilot", ["plugin", "marketplace", "add", "Alexein-AI/copilot-plugin"]),
                ("copilot", ["plugin", "install", "alexein-ai@alexein-ai"]),
            ],
        )
    add = ["mcp", "add", "--transport", "http", *header_flags("--header", o.key), NAME, URL]
    return Plan("copilot mcp add", [("copilot", add)])


def _copilot_removal(host: Host) -> Plan:
    """The plugin's server goes with the plugin: `mcp remove` refuses it."""
    if mentions(host.run("copilot", ["plugin", "list"]).out):
        uninstall = ["plugin", "uninstall", "alexein-ai@alexein-ai"]
        return Plan("copilot plugin uninstall", [("copilot", uninstall)])
    return Plan("copilot mcp remove", [("copilot", ["mcp", "remove", NAME])])


def _codex_plan(_host: Host, o: ConnectOptions) -> Plan | None:
    if o.key:
        return None
    return Plan("codex mcp add", [("codex", ["mcp", "add", NAME, "--url", URL])])


def _gemini_plan(_host: Host, o: ConnectOptions) -> Plan:
    add = ["mcp", "add", "--transport", "http", "--scope", "user"]
    return Plan("gemini mcp add", [("gemini", [*add, *header_flags("--header", o.key), NAME, URL])])


def _gemini_removal(_host: Host) -> Plan:
    """The user scope `plan` adds it at: without one, `gemini mcp remove` looks in the project's."""
    return Plan("gemini mcp remove", [("gemini", ["mcp", "remove", "--scope", "user", NAME])])


def _antigravity_plan(_host: Host, o: ConnectOptions) -> Plan:
    if _with_plugin(o):
        repository = "https://github.com/Alexein-AI/antigravity-plugin"
        return Plan("the Alexein AI plugin", [("agy", ["plugin", "install", repository])])
    return Plan(
        "agy mcp add", [("agy", ["mcp", "add", *header_flags("--header", o.key), NAME, URL])]
    )


def _antigravity_removal(host: Host) -> Plan | None:
    """The plugin, by its name. A server alone is taken out in Antigravity's settings: its CLI
    documents no command for that."""
    if mentions(host.run("agy", ["plugin", "list"]).out):
        return Plan("agy plugin uninstall", [("agy", ["plugin", "uninstall", "alexein-ai"])])
    return None


def _devin_removal(host: Host) -> Plan | None:
    """Its CLI where it has it, at the user scope `plan` adds it at: that writes the file
    `present` reads, which is edited instead without the CLI."""
    if host.has("devin") and NAME in servers(devin_settings(host), "mcpServers"):
        return Plan("devin mcp remove", [("devin", ["mcp", "remove", "-s", "user", NAME])])
    return None


def _devin_plan(host: Host, o: ConnectOptions) -> Plan | None:
    if host.has("devin") and not o.key:
        return Plan("devin mcp add", [("devin", ["mcp", "add", NAME, URL, "-s", "user"])])
    return None


def _entry(o: ConnectOptions, **fields: str) -> dict[str, Any]:
    return {"url": URL, **fields, **({"headers": headers(o.key)} if o.key else {})}


CLIENTS: list[Client] = [
    Client(
        id="claude-code",
        name="Claude Code",
        found=lambda host: host.has("claude"),
        present=_claude_present,
        plan=_claude_plan,
        login=lambda o: (
            "claude",
            ["mcp", "login", CLAUDE_PLUGIN_SERVER if _with_plugin(o) else NAME],
        ),
        sign_in="run /mcp in Claude Code and sign in",
        removal=_claude_removal,
    ),
    Client(
        id="cursor",
        name="Cursor",
        found=lambda host: host.has("cursor") or (host.home / ".cursor").exists(),
        present=lambda host: has_server(cursor_settings(host), "mcpServers"),
        plan=lambda _host, _o: None,
        write=lambda host, o: merge_server(cursor_settings(host), "mcpServers", _entry(o)),
        sign_in="open Cursor Settings › MCP and select Connect on alexein",  # noqa: RUF001
        unwrite=lambda host: drop_server(cursor_settings(host), "mcpServers"),
    ),
    Client(
        id="vscode",
        name="VS Code",
        found=lambda host: host.has("code"),
        present=lambda host: has_server(vscode_settings(host), "servers"),
        plan=_vscode_plan,
        sign_in="run MCP: List Servers, start alexein and allow the sign-in",
        # `code` adds a server but has no command that takes one out: its file is edited instead.
        unwrite=lambda host: drop_server(vscode_settings(host), "servers"),
    ),
    Client(
        id="copilot",
        name="GitHub Copilot CLI",
        found=lambda host: host.has("copilot"),
        present=lambda host: mentions(host.run("copilot", ["mcp", "list"]).out),
        plan=_copilot_plan,
        sign_in="run /mcp in copilot and authenticate",
        removal=_copilot_removal,
    ),
    Client(
        id="codex",
        name="Codex",
        found=lambda host: host.has("codex"),
        present=lambda host: mentions(host.run("codex", ["mcp", "list"]).out),
        plan=_codex_plan,
        login=lambda _o: ("codex", ["mcp", "login", NAME]),
        sign_in="run codex mcp login alexein",
        removal=lambda _host: Plan("codex mcp remove", [("codex", ["mcp", "remove", NAME])]),
    ),
    Client(
        id="gemini",
        name="Gemini CLI",
        found=lambda host: host.has("gemini"),
        present=lambda host: mentions(host.run("gemini", ["mcp", "list"]).out),
        plan=_gemini_plan,
        sign_in="start Gemini CLI; it opens the sign-in (or run /mcp auth alexein)",
        removal=_gemini_removal,
    ),
    Client(
        id="antigravity",
        name="Antigravity",
        found=lambda host: host.has("agy"),
        present=lambda host: (
            mentions(host.run("agy", ["plugin", "list"]).out)
            or mentions(host.run("agy", ["mcp", "list"]).out)
        ),
        plan=_antigravity_plan,
        sign_in="open /plugin in Antigravity, expand alexein-ai and choose Sign in",
        removal=_antigravity_removal,
    ),
    Client(
        id="devin",
        name="Devin Desktop",
        found=lambda host: host.has("devin") or devin_settings(host).parent.exists(),
        present=lambda host: has_server(devin_settings(host), "mcpServers"),
        plan=_devin_plan,
        write=lambda host, o: merge_server(
            devin_settings(host), "mcpServers", _entry(o, transport="http")
        ),
        sign_in="open Customize › MCPs and select Authenticate on alexein",  # noqa: RUF001
        removal=_devin_removal,
        unwrite=lambda host: drop_server(devin_settings(host), "mcpServers"),
    ),
]

# The tool names' column, for the sign-in lines.
WIDTH = max(len(c.name) for c in CLIENTS) + 2

# The chat apps, which are added from the app itself.
ELSEWHERE = "claude.ai, Claude Desktop and ChatGPT: add Alexein from the app"


def connect(o: ConnectOptions, console: Console, host: Host | None = None) -> int:
    """0 when every tool asked for was set up or already had Alexein; 1 when any failed."""
    host = host or LocalHost()
    known = [c.id for c in CLIENTS]
    unknown = [name for name in o.only if name not in known]
    if unknown:
        console.fail(f"no tool called {', '.join(unknown)}; there is: {', '.join(known)}")
        return 2
    asked = [c for c in CLIENTS if not o.only or c.id in o.only]
    found = [c for c in asked if c.found(host)]
    if o.as_json:
        present = {c.id for c in found if c.present(host)}
        tools = [
            {
                "id": c.id,
                "name": c.name,
                "found": c in found,
                "added": (c.id in present) if c in found else None,
            }
            for c in asked
        ]
        console.line(json.dumps({"tools": tools}, indent=2, ensure_ascii=False))
        return 0
    console.line(f"alexein-cli {__version__} - Alexein AI for the AI tools on this computer")
    console.line()
    if not found:
        console.line("  No AI tools found that connect from here.")
        console.line(f"  {ELSEWHERE}: {DOCS}")
        return 1 if o.only else 0
    present = {c.id for c in found if c.present(host)}
    for c in found:
        console.step("has" if c.id in present else "found", c.name)
    for c in asked:
        if c not in found:
            console.step("missing", c.name)
    console.line()
    if o.listing:
        return 0
    if o.remove:
        return _remove([c for c in found if c.id in present], o, console, host)

    todo = [c for c in found if o.force or c.id not in present]
    if not todo:
        console.line("  Every tool found has Alexein already. --force adds it again.")
        return 0
    names = ", ".join(c.name for c in todo)
    if not o.dry_run and not console.confirm(f"Add Alexein AI to {names}?"):
        console.line(_unchanged(console))
        return 1

    failed = 0
    sign_ins: list[Client] = []
    for c in todo:
        plan = c.plan(host, o)
        if plan is None and c.write is None:
            console.step("skipped", f"{c.name}: a key goes in its settings by hand - see {DOCS}")
            continue
        if o.dry_run:
            how = (
                " && ".join(shown(cmd, args, o.key) for cmd, args in plan.steps)
                if plan
                else "an entry in its settings"
            )
            console.step("would", f"add {c.name}, with {how}")
            continue
        try:
            if plan:
                for command, args in plan.steps:
                    done = host.run(command, args)
                    # A marketplace already added is fine: the install after it is what matters.
                    already = "marketplace" in args and re.search("already", done.out, re.I)
                    if done.code != 0 and not already:
                        raise RuntimeError(_last_line(done.out) or f"{command} {args[0]} failed")
                how = plan.how
            else:
                assert c.write is not None
                how = str(c.write(host, o)).replace(str(host.home), "~")
        except (OSError, ValueError, RuntimeError) as error:
            failed += 1
            console.step("failed", f"{c.name}: {error}")
            continue
        console.step("added", f"{c.name} ({how})")
        if not o.key:
            sign_ins.append(c)
    if o.dry_run:
        return 0

    if sign_ins:
        console.line()
        console.line("  Sign in to Alexein from each, and keep Read and save so it can save:")
        for c in sign_ins:
            if (
                c.login
                and console.interactive
                and console.confirm(f"Sign in to {c.name} now?")
                and host.attach(*c.login(o)) == 0
            ):
                console.step("signed in", c.name)
                continue
            console.line(f"  {c.name:<{WIDTH}}{c.sign_in}")
    console.line()
    console.line(f"  {ELSEWHERE}: {DOCS}")
    return 1 if failed else 0


def _remove(todo: list[Client], o: ConnectOptions, console: Console, host: Host) -> int:
    """`--remove`: what `connect` added taken out of each tool in `todo`, the ones that have
    Alexein - the plugin, the `alexein` server, or its settings entry. A server under another
    name was not added here and is left, with a line saying so. Memory and the tool's sign-in
    are untouched."""
    if not todo:
        console.line("  No tool found has Alexein: nothing to take out.")
        return 0
    names = ", ".join(c.name for c in todo)
    if not o.dry_run and not console.confirm(f"Take Alexein AI out of {names}?"):
        console.line(_unchanged(console))
        return 1

    def by_hand(c: Client) -> None:
        console.step("skipped", f"{c.name}: take Alexein out in its own settings")

    failed = 0
    for c in todo:
        try:
            plan = c.removal(host) if c.removal else None
            if plan is None and c.unwrite is None:
                by_hand(c)
                continue
            if o.dry_run:
                how = (
                    " && ".join(shown(cmd, args) for cmd, args in plan.steps)
                    if plan
                    else "its alexein entry taken out of its settings"
                )
                console.step("would", f"remove {c.name}, with {how}")
                continue
            if plan:
                for command, args in plan.steps:
                    done = host.run(command, args)
                    if done.code != 0:
                        raise RuntimeError(_last_line(done.out) or f"{command} {args[0]} failed")
                how: str | None = plan.how
            else:
                assert c.unwrite is not None
                path = c.unwrite(host)
                how = str(path).replace(str(host.home), "~") if path else None
        except (OSError, ValueError, RuntimeError) as error:
            failed += 1
            console.step("failed", f"{c.name}: {error}")
            continue
        if how is None:
            by_hand(c)
        else:
            console.step("removed", f"{c.name} ({how})")
    if o.dry_run:
        return 0
    console.line()
    console.line(
        "  Your memory is as it was. To end a tool's sign-in too, disconnect it in My memory."
    )
    return 1 if failed else 0


def _unchanged(console: Console) -> str:
    if console.interactive:
        return "  Nothing changed."
    return "  Nothing changed: run it at a terminal, or pass --yes."


def _last_line(out: str) -> str:
    lines = [line.strip() for line in out.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def shown(command: str, args: Sequence[str], key: str | None = None) -> str:
    """A command as it would be typed, with the key masked."""
    masked = [a.replace(key, "tm_***") if key else a for a in args]
    return " ".join([command, *(f"'{a}'" if re.search(r'[\s"{}]', a) else a for a in masked)])
