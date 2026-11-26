"""The memory commands - `alexein search`, `add`, `latest`, `open`, `subject`, `summary`,
`history`, `status`, `forget` and `export` - each one route of the memory API through the
`alexein` client, and `login`, `logout` and `whoami` for the key they use. Each prints what came
back for a person to read, or with `--json` the API's JSON as it came, for a script or an agent.
The TypeScript CLI's are the same, command for command.

The key is `--key`, else `ALEXEIN_API_KEY`, else the one `alexein login` kept. Whose memory is
`--user`, else `ALEXEIN_USER`, else the one `login --user` kept, else `me` for a personal key - the
person's own memory, as the console and every connected app name it. A project's key has no such
default: its app users are its project's, and a command names one.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from alexein import AlexeinError, AuthenticationError, Me, Memory, User

from alexein_cli import credentials
from alexein_cli.env import described
from alexein_cli.outline import memories, outline
from alexein_cli.ui import Console

# `add_parser` of the CLI's subcommands.
AddParser = Callable[..., argparse.ArgumentParser]
Stdin = Callable[[], str | None]


class Usage(Exception):
    """A command given wrongly: exit 2, as a usage error is everywhere in this CLI."""


def _print(console: Console, raw: Any) -> int:
    console.line(json.dumps(raw, indent=2, ensure_ascii=False))
    return 0


def _show(console: Console, lines: list[str]) -> int:
    for line in lines:
        console.line(line)
    return 0


def _answer(console: Console, args: argparse.Namespace, raw: Any) -> int:
    return _print(console, raw) if args.json else _show(console, outline(raw))


def _count(given: str) -> int:
    try:
        n = int(given)
    except ValueError:
        n = 0
    if n < 1:
        raise argparse.ArgumentTypeError(f"takes a whole number: {given}")
    return n


# ------------------------------------------------------------------------------ the commands --


def _search(user: User, args: argparse.Namespace, console: Console, _stdin: Stdin) -> int:
    found = user.search(
        " ".join(args.question),
        after=args.after,
        before=args.before,
        provider=args.provider,
        source=args.source,
        fast=args.fast,
    )
    if args.json:
        return _print(console, found.raw)
    if found.answerable is False:
        console.line("Memory does not seem to hold the answer. The closest it has:\n")
    _show(console, memories(found.raw.get("memories"), "Nothing found."))
    for note in found.notes:
        console.line(f"\nnote: {note}")
    return 0


def _latest(user: User, args: argparse.Namespace, console: Console, _stdin: Stdin) -> int:
    found = user.latest(
        k=args.limit,
        after=args.after,
        before=args.before,
        provider=args.provider,
        source=args.source,
    )
    if args.json:
        return _print(console, found.raw)
    return _show(console, memories(found.raw.get("memories"), "Nothing yet."))


def _open(user: User, args: argparse.Namespace, console: Console, _stdin: Stdin) -> int:
    return _answer(console, args, user.open(args.ref).raw)


def _subject(user: User, args: argparse.Namespace, console: Console, _stdin: Stdin) -> int:
    return _answer(console, args, user.subject(" ".join(args.name), limit=args.limit).raw)


def _summary(user: User, args: argparse.Namespace, console: Console, _stdin: Stdin) -> int:
    return _answer(console, args, user.summary().raw)


def _history(user: User, args: argparse.Namespace, console: Console, _stdin: Stdin) -> int:
    found = user.history(" ".join(args.subject), attribute=args.attribute)
    return _answer(console, args, found.raw)


def _add(user: User, args: argparse.Namespace, console: Console, stdin: Stdin) -> int:
    said = (stdin() or "") if args.text == ["-"] else " ".join(args.text)
    if not said.strip():
        raise Usage("nothing to add: give the text, or - and pipe it in")
    name: str | None = args.author
    author: Any = {"self": True, **({"name": name} if name else {})} if args.self else name
    added = user.add(
        said.rstrip(),
        id=args.id,
        session=args.session,
        role=args.role,
        author=author,
        kind=args.kind,
        title=args.title,
        wait=args.wait,
    )
    return _answer(console, args, added.raw)


def _status(user: User, args: argparse.Namespace, console: Console, _stdin: Stdin) -> int:
    return _answer(console, args, user.status(args.ids).raw)


def _forget(user: User, args: argparse.Namespace, console: Console, _stdin: Stdin) -> int:
    items: list[str] = args.item or []
    sessions: list[str] = args.session or []
    refs: list[str] = args.ref or []

    def counted(n: int, one: str, many: str) -> list[str]:
        return [f"{n} {one if n == 1 else many}"] if n else []

    what = [
        *counted(len(items), "item", "items"),
        *counted(len(sessions), "session", "sessions"),
        *counted(len(refs), "memory", "memories"),
    ]
    if not what:
        raise Usage("name what to forget: --item, --session or --ref")
    question = f"Forget {', '.join(what)} of {user.id}, for good? It cannot be undone."
    if not (args.yes or console.confirm(question)):
        console.line(
            "Nothing forgotten."
            if console.interactive
            else "Nothing forgotten: pass --yes to forget."
        )
        return 1
    done = user.forget(items=items or None, sessions=sessions or None, refs=refs or None)
    return _answer(console, args, done.raw)


def _export(user: User, args: argparse.Namespace, console: Console, _stdin: Stdin) -> int:
    out: str | None = args.out
    records = 0
    if out is None:
        for record in user.iter_export():
            console.line(json.dumps(record, ensure_ascii=False))
            records += 1
        return 0
    opened = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(out, 0o600)
    with os.fdopen(opened, "w") as file:
        for record in user.iter_export():
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            records += 1
    console.line(f"{records} record{'' if records == 1 else 's'} in {out}")
    return 0


Run = Callable[[User, argparse.Namespace, Console, Stdin], int]

RUNS: dict[str, Run] = {
    "search": _search,
    "latest": _latest,
    "open": _open,
    "subject": _subject,
    "summary": _summary,
    "history": _history,
    "add": _add,
    "status": _status,
    "forget": _forget,
    "export": _export,
}
NAMES = {*RUNS, "login", "logout", "whoami"}


# ---------------------------------------------------------------------------- their parsers --


def _common(parser: argparse.ArgumentParser) -> None:
    """What every memory command takes besides its own flags."""
    parser.add_argument(
        "--user",
        metavar="ID",
        help="whose memory: an app user of the key's project; me, your own, for a personal key",
    )
    parser.add_argument(
        "--key", help="the key, instead of ALEXEIN_API_KEY or your login; - reads it from stdin"
    )
    parser.add_argument(
        "--base-url", metavar="URL", help="memory's address, instead of ALEXEIN_API_URL or yours"
    )
    parser.add_argument("--json", action="store_true", help="the API's JSON, as it came")


def _dates(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--after", metavar="DATE", help="only memory from this day on (YYYY-MM-DD)")
    parser.add_argument("--before", metavar="DATE", help="as of this day (YYYY-MM-DD)")


def _origin(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", metavar="APP", help="only what this connected app delivered")
    parser.add_argument("--source", help="only this one of the app's sources")


def register(add: AddParser) -> None:
    """The memory commands' parsers, beside the setup commands'."""

    def command(name: str, about: str) -> argparse.ArgumentParser:
        parser = add(name, help=about, description=about)
        _common(parser)
        return parser

    search = command("search", "What memory holds for a question.")
    search.add_argument("question", nargs="+")
    _dates(search)
    _origin(search)
    search.add_argument("--fast", action="store_true", help="sooner, a little less precisely, free")

    latest = command("latest", "The most recent memories, newest first.")
    latest.add_argument("--limit", type=_count, metavar="N", help="how many (10 unless set)")
    _dates(latest)
    _origin(latest)

    command(
        "open", "One memory by its ref, whole: an excerpt in full, or a fact and its sources."
    ).add_argument("ref")

    subject = command("subject", "One person or thing by name: its values, facts and relations.")
    subject.add_argument("name", nargs="+")
    subject.add_argument("--limit", type=_count, metavar="N", help="how many facts at most")

    command("summary", "What this memory holds, in brief.")

    history = command("history", "Every value a subject was stated to have, and since when.")
    history.add_argument("subject", nargs="+")
    history.add_argument("--attribute", metavar="NAME", help="only this attribute's values")

    adding = command("add", "Save something to memory. - reads the text from stdin.")
    adding.add_argument("text", nargs="+")
    adding.add_argument("--id", help="its id: the same id again edits it")
    adding.add_argument("--session", metavar="ID", help="the conversation it belongs to")
    adding.add_argument("--role", help="user or assistant, for a message")
    adding.add_argument("--author", metavar="NAME", help="who said or wrote it")
    adding.add_argument(
        "--self", action="store_true", help="said by the person whose memory this is"
    )
    adding.add_argument("--kind", choices=["message", "document", "note"], help="what it is")
    adding.add_argument("--title", help="a document's title")
    adding.add_argument("--wait", action="store_true", help="answer once it can be searched")

    command(
        "status", "How far each added item has got: queued, stored, processed or unknown."
    ).add_argument("ids", nargs="+", metavar="ITEM_ID")

    forget = command("forget", "Erase items, sessions or memories for good, and what they taught.")
    forget.add_argument("--item", action="append", metavar="ID", help="an item, by its id")
    forget.add_argument("--session", action="append", metavar="ID", help="a whole session")
    forget.add_argument("--ref", action="append", help="a fact or excerpt, by its ref")
    forget.add_argument("--yes", "-y", action="store_true", help="do not ask first")

    export = command("export", "Everything memory holds for this user, as JSON lines.")
    export.add_argument("--out", metavar="FILE", help="write it to this file, readable only by you")

    login = add(
        "login", help="Keep a key for the memory commands, in the keychain where there is one."
    )
    login.add_argument("--key", help="the key; - reads it from stdin (else asked)")
    login.add_argument("--base-url", metavar="URL", help="memory's address, kept with it")
    login.add_argument("--user", metavar="ID", help="the app user the commands use, kept with it")
    login.add_argument(
        "--insecure-storage",
        action="store_true",
        help="keep the key in a file only you can read, even where there is a keychain",
    )
    add("logout", help="Take the kept key out of the keychain, and the login with it.")
    whoami = add("whoami", help="Which key the memory commands use, where from, and whose memory.")
    _common(whoami)


# ------------------------------------------------------------------------ the key, the user --


@dataclass(frozen=True)
class _Found:
    """The key the commands use, and where it came from: `--key`, the environment, the login."""

    key: str
    where: str
    saved: dict[str, Any] | None = None


def _find_key(args: argparse.Namespace, shell: credentials.Shell, stdin: Stdin) -> _Found:
    given = credentials.key_from(args.key, stdin)
    if given:
        return _Found(given, "--key")
    set_key = (shell.env.get("ALEXEIN_API_KEY") or "").strip()
    if set_key:
        return _Found(set_key, "ALEXEIN_API_KEY")
    kept = credentials.load(shell)
    if kept:
        return _Found(kept.key, f"{kept.where}, from alexein login", kept.saved)
    raise ValueError("no key: run alexein login, or set ALEXEIN_API_KEY")


def _base_url(args: argparse.Namespace, shell: credentials.Shell, found: _Found) -> str | None:
    """`--base-url`, else `ALEXEIN_API_URL`, else the login's with its key."""
    saved = (found.saved or {}).get("base_url")
    return (
        args.base_url
        or (shell.env.get("ALEXEIN_API_URL") or "").strip()
        or (saved if isinstance(saved, str) else None)
        or None
    )


def _user(
    args: argparse.Namespace, shell: credentials.Shell, found: _Found, space: str | None
) -> str | None:
    """Whose memory, by the order the module's note gives; None for a project's key unnamed."""
    saved = (found.saved or {}).get("user")
    return (
        args.user
        or (shell.env.get("ALEXEIN_USER") or "").strip()
        or (saved if isinstance(saved, str) else None)
        or ("me" if space == "personal" else None)
    )


# -------------------------------------------------------------------------------- running --


def run(
    args: argparse.Namespace,
    console: Console,
    stdin: Stdin,
    shell: credentials.Shell | None = None,
) -> int:
    """`alexein <command> ...` for a command in `NAMES`. 0 when it did what it was asked."""
    shell = shell or credentials.LocalShell()
    try:
        if args.command == "login":
            return _login(args, console, shell, stdin)
        if args.command == "logout":
            return _logout(console, shell)
        if args.command == "whoami":
            return _whoami(args, console, shell, stdin)
        found = _find_key(args, shell, stdin)
        with Memory(found.key, base_url=_base_url(args, shell, found), integration="cli") as memory:
            saved_space = (found.saved or {}).get("space")
            space = saved_space if isinstance(saved_space, str) else None
            user = _user(args, shell, found, space)
            if user is None and space is None:
                space = memory.me().space
                user = _user(args, shell, found, space)
            if user is None:
                raise Usage(
                    "this key is a project's: name the app user with --user or ALEXEIN_USER, "
                    "or keep one with alexein login --user"
                )
            return RUNS[args.command](memory.user(user), args, console, stdin)
    except Usage as error:
        console.fail(str(error))
        return 2
    except AuthenticationError:
        console.fail(
            "the service does not know this key: run alexein login, or check ALEXEIN_API_KEY"
        )
        return 1
    except (AlexeinError, ValueError, OSError) as error:
        console.fail(str(error))
        return 1


def _login(
    args: argparse.Namespace, console: Console, shell: credentials.Shell, stdin: Stdin
) -> int:
    key = credentials.key_from(args.key, stdin) or console.secret(
        "Your Alexein API key (the console's API keys, or My memory › Personal keys):"  # noqa: RUF001
    )
    if not key:
        raise Usage("no key given: pass --key (or --key - and pipe it in), or run it at a terminal")
    try:
        with Memory(
            key, base_url=args.base_url, timeout=10.0, max_retries=0, integration="cli"
        ) as client:
            me: Me = client.me()
    except AuthenticationError:
        console.fail("the service does not know this key; nothing was kept")
        return 1
    label = described(me)
    where, fell_back = credentials.save(
        shell,
        credentials.Login(
            key=key,
            base_url=args.base_url,
            user=args.user,
            space=me.space,
            label=label,
            insecure=args.insecure_storage,
        ),
    )
    console.line(f"Logged in: {label}.")
    console.line(
        f"There is no keychain here: the key is in {where}, a file only you can read."
        if fell_back
        else f"The key is in {where}."
    )
    if args.user:
        console.line(f"The memory commands use the app user {args.user}.")
    elif me.space == "personal":
        console.line("The memory commands use your own memory (me).")
    else:
        console.line(
            "This is a project's key: name an app user with --user or ALEXEIN_USER, "
            "or log in with --user."
        )
    return 0


def _logout(console: Console, shell: credentials.Shell) -> int:
    gone = credentials.forget_login(shell)
    console.line(f"Logged out: took out {' and '.join(gone)}." if gone else "Not logged in.")
    if (shell.env.get("ALEXEIN_API_KEY") or "").strip():
        console.line("ALEXEIN_API_KEY is still set, and the memory commands use it.")
    return 0


def _whoami(
    args: argparse.Namespace, console: Console, shell: credentials.Shell, stdin: Stdin
) -> int:
    found = _find_key(args, shell, stdin)
    with Memory(found.key, base_url=_base_url(args, shell, found), integration="cli") as client:
        me = client.me()
        address = client.base_url
    user = _user(args, shell, found, me.space)
    if args.json:
        return _print(
            console, {**me.raw, "key_from": found.where, "base_url": address, "user": user}
        )
    own = " (your own memory)" if user == "me" and me.space == "personal" else ""
    return _show(
        console,
        [
            f"key      {described(me)}",
            f"from     {found.where}",
            f"address  {address}",
            f"user     {f'{user}{own}' if user else 'none: name one with --user or ALEXEIN_USER'}",
        ],
    )
