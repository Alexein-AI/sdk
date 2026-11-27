"""Where `alexein login` keeps a key, and where the memory commands find it again: the key in the
system's keychain where there is one - macOS's through `security`, Linux's through `secret-tool` -
else in a file only its owner can read; and beside it, in `credentials.json`, what is not secret:
where the key is kept, the address, the app user to use, and what the key is.

`@alexein/cli` (TypeScript) reads and writes the same file and keychain entry, so a login with
either CLI serves both.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from alexein_cli.connect import Ran

# The keychain entry: one key per computer user, as one login is.
SERVICE = "alexein"
ACCOUNT = "api-key"
# What a key is made of; anything else is not one, and never goes on a keychain's command line.
_KEY_SHAPE = re.compile(r"[A-Za-z0-9_-]+")


def key_from(given: str | None, read: Callable[[], str | None]) -> str | None:
    """The key `--key` gives: `-` reads it from the first line of stdin, so it is in no shell's
    history. Raises when `-` brings nothing."""
    if given != "-":
        return given
    lines = (read() or "").splitlines()
    key = lines[0].strip() if lines else ""
    if not key:
        raise ValueError("--key - reads the key from stdin, and none came: pipe it in")
    return key


class Places(Protocol):
    """Where a computer keeps a user's settings: its home, its platform and its environment."""

    @property
    def home(self) -> Path: ...

    @property
    def platform(self) -> str: ...

    @property
    def env(self) -> Mapping[str, str]: ...


class Shell(Places, Protocol):
    """What the credentials need of the computer: a test hands in one over a scratch directory."""

    def has(self, command: str) -> bool:
        """Whether a command is on PATH."""
        ...

    def run(self, command: str, args: Sequence[str], stdin: str | None = None) -> Ran:
        """A command run quietly, with `stdin` on its stdin: its exit code and its stdout."""
        ...


class LocalShell:
    """This computer."""

    def __init__(self) -> None:
        self.home = Path.home()
        self.platform = sys.platform
        self.env: Mapping[str, str] = os.environ

    def has(self, command: str) -> bool:
        return shutil.which(command) is not None

    def run(self, command: str, args: Sequence[str], stdin: str | None = None) -> Ran:
        try:
            done = subprocess.run(
                [shutil.which(command) or command, *args],
                input=stdin,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return Ran(1, str(error))
        return Ran(done.returncode, done.stdout or "")


def directory(shell: Places) -> Path:
    """`ALEXEIN_CONFIG_DIR`, else `alexein` in the platform's place for settings."""
    env = shell.env
    if env.get("ALEXEIN_CONFIG_DIR"):
        return Path(env["ALEXEIN_CONFIG_DIR"])
    if shell.platform == "win32":
        return Path(env.get("APPDATA") or shell.home / "AppData" / "Roaming") / "alexein"
    return Path(env.get("XDG_CONFIG_HOME") or shell.home / ".config") / "alexein"


def credentials_file(shell: Places) -> Path:
    return directory(shell) / "credentials.json"


def _shown(path: Path, shell: Shell) -> str:
    return str(path).replace(str(shell.home), "~", 1)


@dataclass(frozen=True)
class _Keychain:
    name: str
    command: str
    put: Callable[[Shell, str], None]
    get: Callable[[Shell], str | None]
    drop: Callable[[Shell], bool]


def _found(done: Ran) -> str | None:
    return (done.out.strip() or None) if done.code == 0 else None


_ENTRY = ["-s", SERVICE, "-a", ACCOUNT]
_ATTRIBUTES = ["service", SERVICE, "account", ACCOUNT]


def _macos_put(shell: Shell, key: str) -> None:
    """Through `security -i`, so the key is on its stdin and never in the process list."""
    shell.run("security", ["-i"], f"add-generic-password -U {' '.join(_ENTRY)} -w {key}\n")


def _secret_service_put(shell: Shell, key: str) -> None:
    shell.run("secret-tool", ["store", "--label=Alexein API key", *_ATTRIBUTES], key)


_MACOS = _Keychain(
    name="the macOS keychain",
    command="security",
    put=_macos_put,
    get=lambda shell: _found(shell.run("security", ["find-generic-password", *_ENTRY, "-w"])),
    drop=lambda shell: shell.run("security", ["delete-generic-password", *_ENTRY]).code == 0,
)

_SECRET_SERVICE = _Keychain(
    name="the system keyring",
    command="secret-tool",
    put=_secret_service_put,
    get=lambda shell: _found(shell.run("secret-tool", ["lookup", *_ATTRIBUTES])),
    drop=lambda shell: shell.run("secret-tool", ["clear", *_ATTRIBUTES]).code == 0,
)


def _keychain(shell: Shell) -> _Keychain | None:
    chosen = {"darwin": _MACOS, "linux": _SECRET_SERVICE}.get(shell.platform)
    return chosen if chosen and shell.has(chosen.command) else None


def read_saved(shell: Shell) -> dict[str, Any] | None:
    """`credentials.json`, or None when there is none. Raises when it is not one."""
    path = credentials_file(shell)
    if not path.exists():
        return None
    try:
        saved: object = json.loads(path.read_text())
    except (OSError, ValueError):
        saved = None
    if not isinstance(saved, dict) or saved.get("store") not in ("keychain", "file"):  # pyright: ignore[reportUnknownMemberType]
        raise ValueError(
            f"{path} is not a login this CLI wrote; run alexein logout, then log in again"
        )
    return saved  # pyright: ignore[reportUnknownVariableType]


def _write_saved(shell: Shell, saved: dict[str, Any]) -> Path:
    folder = directory(shell)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = credentials_file(shell)
    opened = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(opened, "w") as file:
        file.write(json.dumps(saved, indent=2, ensure_ascii=False) + "\n")
    path.chmod(0o600)  # a file that was there keeps its mode through a write
    return path


@dataclass(frozen=True)
class Login:
    key: str
    base_url: str | None = None
    user: str | None = None
    space: str | None = None
    label: str | None = None
    # The key in the file even where there is a keychain.
    insecure: bool = False


def save(shell: Shell, login: Login) -> tuple[str, bool]:
    """Keep a login: the key in the keychain, checked by reading it back, else in the file.
    Returns where the key went, as a person reads it, and whether that was the file for want of
    a keychain."""
    rest = {
        name: value
        for name, value in (
            ("base_url", login.base_url),
            ("user", login.user),
            ("space", login.space),
            ("label", login.label),
        )
        if value
    }
    chain = None if login.insecure else _keychain(shell)
    if chain and _KEY_SHAPE.fullmatch(login.key):
        chain.put(shell, login.key)
        if chain.get(shell) == login.key:
            _write_saved(shell, {"store": "keychain", **rest})
            return chain.name, False
    if chain:
        chain.drop(shell)  # a key an earlier login kept there is not left behind
    path = _write_saved(shell, {"store": "file", "key": login.key, **rest})
    return _shown(path, shell), not login.insecure


@dataclass(frozen=True)
class Loaded:
    key: str
    saved: dict[str, Any]
    where: str


def load(shell: Shell) -> Loaded | None:
    """The login kept, with its key and where that is: None when there is none. Raises when the
    key is in a keychain that does not give it back - locked, or on a computer reached without its
    desktop."""
    saved = read_saved(shell)
    if saved is None:
        return None
    if saved["store"] == "file":
        path = credentials_file(shell)
        key = saved.get("key")
        if not isinstance(key, str) or not key:
            raise ValueError(f"{path} holds no key; log in again")
        return Loaded(key, saved, _shown(path, shell))
    chain = _keychain(shell)
    key = chain.get(shell) if chain else None
    if not key or chain is None:
        name = chain.name if chain else "a keychain"
        raise ValueError(
            f"the key is in {name} and it did not give it back; "
            "unlock it, log in again, or set ALEXEIN_API_KEY"
        )
    return Loaded(key, saved, chain.name)


def forget_login(shell: Shell) -> list[str]:
    """Take the login out: the keychain entry and the file. Says what went; empty when nothing
    did."""
    gone: list[str] = []
    chain = _keychain(shell)
    if chain and chain.drop(shell):
        gone.append(f"the key, from {chain.name}")
    path = credentials_file(shell)
    if path.exists():
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        gone.append(_shown(path, shell))
    return gone
