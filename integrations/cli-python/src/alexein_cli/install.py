"""The `alexein` command on PATH for good, so that after one `uvx alexein-cli ...` it is typed
directly. uvx runs the CLI in an environment of its cache and never keeps it on PATH: `install`
installs it with `uv tool install`, and puts uv's folder for such commands on PATH with
`uv tool update-shell` where it is not - and the setup commands offer to, once, when they run at a
terminal. `@alexein/cli install` (TypeScript) does the same through `npm install -g`.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from alexein_cli.connect import Host, LocalHost
from alexein_cli.credentials import directory
from alexein_cli.ui import Console

PACKAGE = "alexein-cli"


def _uv_caches(host: Host) -> list[str]:
    """Where uv keeps its cache, which is where uvx makes the environments it runs a tool in:
    `UV_CACHE_DIR`, else the platform's place for caches."""
    env = host.env
    places = [
        env.get("UV_CACHE_DIR"),
        os.path.join(env["XDG_CACHE_HOME"], "uv") if env.get("XDG_CACHE_HOME") else None,
        str(host.home / ".cache" / "uv"),
        os.path.join(env["LOCALAPPDATA"], "uv", "cache") if env.get("LOCALAPPDATA") else None,
    ]
    return [os.path.realpath(place) for place in places if place]


def installed(host: Host) -> bool:
    """Whether `alexein` is on PATH for good. uvx puts the bin folder of the environment it runs
    the CLI in - a folder in uv's cache - on the PATH of the command, so folders in uv's cache are
    not counted: they are this run's copy, not a command a new terminal has. Any other folder is:
    pip's, pipx's, uv tool's, or an activated environment's."""
    caches = _uv_caches(host)

    def cached(folder: str) -> bool:
        real = os.path.realpath(folder)
        return any(real == cache or real.startswith(cache + os.sep) for cache in caches)

    lasting = [f for f in host.env.get("PATH", "").split(os.pathsep) if f and not cached(f)]
    return shutil.which("alexein", path=os.pathsep.join(lasting)) is not None


def _uv(host: Host) -> str | None:
    """uv: the one that runs this, as it says in `UV`, else the one on PATH."""
    return host.env.get("UV") or ("uv" if host.has("uv") else None)


def install(console: Console, host: Host | None = None) -> int:
    """`install`: 0 when `alexein` is on PATH, or installed with its folder put on PATH."""
    host = host or LocalHost()
    if installed(host):
        console.line("alexein is on your PATH already: type alexein in any terminal.")
        console.line(f"  To upgrade it: uv tool upgrade {PACKAGE}")
        return 0
    uv = _uv(host)
    if uv is None:
        console.fail(
            "uv is not on PATH: install it (https://docs.astral.sh/uv/), then run this again"
        )
        return 1
    console.step("running", f"uv tool install {PACKAGE}")
    if host.attach(uv, ["tool", "install", PACKAGE]) != 0:
        console.fail(f"uv tool install {PACKAGE} failed; what uv said is above")
        return 1
    if installed(host):
        console.step("installed", "alexein: type alexein in any terminal")
        return 0
    folder = host.run(uv, ["tool", "dir", "--bin"]).out.strip() or "uv's folder for commands"
    console.step("running", "uv tool update-shell")
    if host.attach(uv, ["tool", "update-shell"]) == 0:
        console.step("installed", f"alexein, in {folder}: open a new terminal, then type alexein")
        return 0
    console.step("installed", f"alexein, in {folder}")
    console.line(
        "  That folder is not on your PATH. Add it in your shell's profile, "
        "then open a new terminal:"
    )
    console.line(f'    export PATH="{folder}:$PATH"')
    return 0


def _state_file(host: Host) -> Path:
    """`state.json` beside the login: what the CLI remembers that is not a login."""
    return directory(host) / "state.json"


def _state(host: Host) -> dict[str, Any]:
    try:
        state: object = json.loads(_state_file(host).read_text())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}  # pyright: ignore[reportUnknownVariableType]


def offer_install(
    console: Console,
    host: Host | None = None,
    *,
    terminal: bool | None = None,
) -> None:
    """After a setup command that did what it was asked, at a terminal: when `alexein` is not on
    PATH, ask once - Enter is yes - to install it. A no is kept, and it is not asked again. Never
    asked where nobody can answer, or where what is printed goes somewhere other than a
    terminal."""
    if not console.interactive or not (sys.stdout.isatty() if terminal is None else terminal):
        return
    host = host or LocalHost()
    if installed(host) or _state(host).get("install") == "declined":
        return
    console.line()
    question = "Install the alexein command, so you can type alexein in any terminal?"
    if console.confirm(question, by_default=True):
        install(console, host)
        return
    folder = directory(host)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = {**_state(host), "install": "declined"}
    _state_file(host).write_text(json.dumps(state, indent=2) + "\n")
    console.line(f"  Not installed, and not asked again. Any time: uvx {PACKAGE} install")
