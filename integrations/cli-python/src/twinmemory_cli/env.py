"""The project's `.env`: the key and the address memory is reached at, read and set one line at
a time so every other line in the file stays exactly as it was. And the check that a key works.

Not a dotenv parser: `KEY=value` lines, optionally quoted, are all it reads, which is all it
ever writes.
"""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from pathlib import Path

from twinmemory import AuthenticationError, Memory, NotFoundError, TwinMemoryError

KEY = "TWIN_MEMORY_API_KEY"
BASE_URL = "TWIN_MEMORY_BASE_URL"


def read(env: Path) -> dict[str, str]:
    """The `KEY=value` lines of a `.env`, unquoted; empty when there is none."""
    values: dict[str, str] = {}
    try:
        lines = env.read_text().splitlines()
    except OSError:
        return values
    for line in lines:
        name, sep, value = line.partition("=")
        name = name.strip().removeprefix("export ").strip()
        if sep and name and not name.startswith("#"):
            values[name] = value.strip().strip("'\"")
    return values


def put(env: Path, name: str, value: str, *, replace: bool) -> str:
    """Set `name` in `.env`: added when absent, replaced when `replace` or empty, else kept.
    Returns what happened: "added", "replaced" or "kept"."""
    text = env.read_text() if env.exists() else ""
    lines = text.splitlines()
    for n, line in enumerate(lines):
        if line.partition("=")[0].strip().removeprefix("export ").strip() != name:
            continue
        if not replace and read(env).get(name):
            return "kept"
        lines[n] = f"{name}={value}"
        env.write_text("\n".join(lines) + "\n")
        return "replaced"
    separator = "" if not text or text.endswith("\n") else "\n"
    env.write_text(f"{text}{separator}{name}={value}\n")
    return "added"


def ignored(root: Path) -> bool:
    """Whether `.gitignore` keeps `.env` out of the repository."""
    try:
        lines = (root / ".gitignore").read_text().splitlines()
    except OSError:
        return False
    return any(line.strip() in (".env", "/.env", ".env*", "*.env", ".env.*") for line in lines)


@dataclass(frozen=True)
class Check:
    """What trying a key found. `ok` is whether it works; `writes` is None when it was not
    checked; `detail` is the line to print."""

    ok: bool
    writes: bool | None
    detail: str


def address(base_url: str | None) -> str:
    """Where the client sends requests: `base_url`, else its own default. Nothing is sent."""
    with Memory("tm_unsent", base_url=base_url) as memory:  # the client is made with a key
        return memory.base_url


def check(key: str, base_url: str | None, timeout: float = 10.0) -> Check:
    """Try a key with `GET /v1/me`: its organisation and project, and whether it writes. Should
    that answer 404, a free fast search for an end user nobody has written for stands in: a 404
    there means the key works, and `writes` is then None."""
    try:
        with Memory(key, base_url=base_url, timeout=timeout, max_retries=0) as memory:
            try:
                me = memory.me()
            except NotFoundError:
                return _probe(memory)
    except AuthenticationError:
        return Check(False, None, "the service does not know this key")
    except TwinMemoryError as error:
        return Check(False, None, f"could not check it: {error}")
    where = f"{me.org}/{me.project}" if me.org and me.project else (me.org or "this key")
    access = "reads and writes" if me.writes else "reads only"
    return Check(True, me.writes, f"{where}, {access}")


def _probe(memory: Memory) -> Check:
    with contextlib.suppress(NotFoundError):  # a working key, and nobody written for
        memory.user("twinmemory-key-check").search("key check", fast=True)
    return Check(True, None, "works; whether it writes was not checked")


def resolve(root: Path) -> tuple[str, str | None]:
    """The key and address the project will run with: its `.env`, else the environment."""
    values = read(root / ".env")
    key = values.get(KEY) or os.environ.get(KEY, "")
    base_url = values.get(BASE_URL) or os.environ.get(BASE_URL) or None
    return key, base_url
