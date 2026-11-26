"""The memory commands, `login`, `logout` and `whoami`: what each sends through the real `alexein`
client to a recorded API, what it prints, and where a login keeps its key - with the keychain a
stand-in over a scratch directory. The same as `@alexein/cli`'s."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import SEARCHED, Recorded, answer, ok, route, wire

from alexein_cli import SKILL, _parser, credentials, main, memory  # pyright: ignore[reportPrivateUsage]
from alexein_cli.connect import Ran
from alexein_cli.outline import outline
from alexein_cli.ui import Console

KEY = "tm_test"
PROJECT = {
    "kind": "key",
    "writes": True,
    "org": "org_1",
    "org_name": "Acme",
    "project": "production",
    "project_name": "Production",
    "space": "project",
}
PERSONAL = {"kind": "key", "writes": True, "org": "org_1", "org_name": "Dana", "space": "personal"}


def as_key(who: dict[str, Any], more: Any = answer) -> Any:
    """The API as `conftest` answers it, with `me` the key `who` describes."""

    def answering(request: httpx.Request) -> httpx.Response:
        return ok(who) if route(request) == "me" else more(request)

    return answering


class Computer:
    """A computer whose keychain is one value: `secret-tool` on Linux, `security` on macOS, or
    none."""

    def __init__(
        self,
        tmp: Path,
        platform: str = "linux",
        commands: Sequence[str] = ("secret-tool",),
        env: dict[str, str] | None = None,
    ) -> None:
        self.home = tmp / "home"
        self.home.mkdir(exist_ok=True)
        self.platform = platform
        self.commands = list(commands)
        self.env = {"ALEXEIN_CONFIG_DIR": str(self.home / "config"), **(env or {})}
        self.ran: list[str] = []
        self.inputs: list[str] = []
        self.kept: str | None = None

    def has(self, command: str) -> bool:
        return command in self.commands

    def run(self, command: str, args: Sequence[str], stdin: str | None = None) -> Ran:
        self.ran.append(" ".join([command, *args]))
        if stdin is not None:
            self.inputs.append(stdin)
        verb = (stdin or "").split(" ")[0] if list(args[:1]) == ["-i"] else args[0]
        if verb == "store":
            self.kept = stdin
        if verb == "add-generic-password":
            self.kept = (stdin or "").split(" -w ")[1].strip()
        if verb in ("lookup", "find-generic-password"):
            return Ran(0, f"{self.kept}\n") if self.kept else Ran(44, "")
        if verb in ("clear", "delete-generic-password"):
            had = self.kept is not None
            self.kept = None
            return Ran(0 if had else 1, "")
        return Ran(0, "")

    @property
    def file(self) -> Path:
        return Path(self.env["ALEXEIN_CONFIG_DIR"]) / "credentials.json"


def run(
    argv: Sequence[str],
    shell: Computer,
    stdin: str | None = None,
    answers: Sequence[str] | None = None,
) -> tuple[int, str]:
    args = _parser().parse_args(list(argv))
    console = Console(
        interactive=answers is not None, answers=list(answers or []), out=lambda _: None
    )
    code = memory.run(args, console, lambda: stdin, shell)
    return code, "\n".join(console.said)


def keyed(tmp_path: Path, **env: str) -> Computer:
    return Computer(tmp_path, commands=(), env={"ALEXEIN_API_KEY": KEY, **env})


def sent_user(request: httpx.Request) -> str:
    return request.headers.get("x-alexein-user", "")


def body(request: httpx.Request) -> Any:
    return json.loads(request.content or b"{}")


# ------------------------------------------------------------------------ the memory commands --


def test_search_prints_what_the_users_memory_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = wire(monkeypatch, answer)
    argv = ["search", "where", "does", "dana", "live", "--user", "dana", "--fast"]
    code, said = run(argv, keyed(tmp_path))
    assert code == 0
    assert recorded.routes() == ["search"]
    assert body(recorded.last)["query"] == "where does dana live"
    assert body(recorded.last)["fast"] is True
    assert sent_user(recorded.last) == "dana"
    assert "known\n  Dana lives in Lisbon." in said
    assert "excerpt   2026-10-01  mem_e1  (session onboarding)\n  Dana: I moved to Lisbon." in said


def test_json_prints_the_apis_json_as_it_came(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(monkeypatch, answer)
    _, said = run(["search", "q", "--user", "dana", "--json"], keyed(tmp_path))
    assert json.loads(said) == SEARCHED


def test_a_personal_key_reads_me_and_a_projects_key_names_its_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    personal = wire(monkeypatch, as_key(PERSONAL))
    assert run(["latest"], keyed(tmp_path))[0] == 0
    assert personal.routes() == ["me", "latest"]
    assert sent_user(personal.requests[1]) == "me"

    project = wire(monkeypatch, as_key(PROJECT))
    code, said = run(["latest"], keyed(tmp_path))
    assert code == 2
    assert "this key is a project's: name the app user with --user or ALEXEIN_USER" in said
    assert project.routes() == ["me"]

    named = wire(monkeypatch, as_key(PROJECT))
    assert run(["latest", "--limit", "3"], keyed(tmp_path, ALEXEIN_USER="dana"))[0] == 0
    assert named.routes() == ["latest"]
    assert body(named.last)["k"] == 3


def test_add_reads_stdin_with_dash_as_the_persons_own_words(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = wire(monkeypatch, answer)
    argv = ["add", "-", "--user", "dana", "--id", "note-1", "--session", "s-1", "--self", "--wait"]
    code, _ = run(argv, keyed(tmp_path), stdin="I moved to Lisbon.\n\n")
    assert code == 0
    assert recorded.routes() == ["add"]
    item = body(recorded.last)["items"][0]
    assert item["id"] == "note-1" and item["text"] == "I moved to Lisbon."
    assert item["session"] == "s-1" and item["author"] == {"self": True}
    assert body(recorded.last)["wait"] is True
    assert run(["add", "-", "--user", "dana"], keyed(tmp_path), stdin="  \n")[0] == 2


def test_forget_asks_first_and_forgets_nothing_unasked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = wire(monkeypatch, answer)
    shell = keyed(tmp_path)
    argv = ["forget", "--user", "dana", "--item", "note-1", "--item", "note-2", "--session", "s-1"]
    code, said = run(argv, shell)
    assert code == 1 and "Nothing forgotten: pass --yes to forget." in said
    assert recorded.requests == []

    _, said = run(argv, shell, answers=["n"])
    assert "Forget 2 items, 1 session of dana, for good? It cannot be undone." in said
    assert recorded.requests == []

    assert run([*argv, "--yes"], shell)[0] == 0
    assert recorded.routes() == ["forget"]
    assert body(recorded.last) == {"items": ["note-1", "note-2"], "sessions": ["s-1"]}
    assert run(["forget", "--user", "dana", "--yes"], shell)[0] == 2


def test_export_writes_every_page_as_json_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pages = {
        "": {"records": [{"type": "item", "id": "a"}], "next": "p2"},
        "p2": {"records": [{"type": "fact", "ref": "mem_f1"}], "next": None},
    }

    def exporting(request: httpx.Request) -> httpx.Response:
        if route(request) == "export":
            return ok(pages[body(request).get("cursor") or ""])
        return answer(request)

    recorded: Recorded = wire(monkeypatch, exporting)
    shell = keyed(tmp_path)
    _, said = run(["export", "--user", "dana"], shell)
    assert [json.loads(line) for line in said.splitlines()] == [
        {"type": "item", "id": "a"},
        {"type": "fact", "ref": "mem_f1"},
    ]
    out = tmp_path / "dana.jsonl"
    _, said = run(["export", "--user", "dana", "--out", str(out)], shell)
    assert said == f"2 records in {out}"
    assert len(out.read_text().splitlines()) == 2
    assert out.stat().st_mode & 0o777 == 0o600
    assert recorded.routes().count("export") == 4


def test_open_subject_summary_history_and_status_show_an_outline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = wire(monkeypatch, answer)
    shell = keyed(tmp_path, ALEXEIN_USER="dana")
    _, said = run(["open", "mem_e1"], shell)
    assert "memory:\n  type: excerpt\n  ref: mem_e1" in said
    for argv in (
        ["subject", "Dana", "Chen"],
        ["summary"],
        ["history", "Dana"],
        ["status", "a", "b"],
    ):
        assert run(argv, shell)[0] == 0, argv
    assert recorded.routes() == ["open", "subject", "summary", "history", "status"]
    assert body(recorded.requests[1])["name"] == "Dana Chen"
    assert body(recorded.requests[4])["items"] == ["a", "b"]


@pytest.mark.parametrize(
    "argv",
    [["open", "a", "b"], ["latest", "now"], ["search"], ["search", "q", "--session", "s"]],
)
def test_refuses_words_and_flags_a_command_does_not_take(argv: list[str], tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        run(argv, keyed(tmp_path))


def test_says_when_there_is_no_key_and_when_the_service_does_not_know_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, said = run(["latest", "--user", "dana"], Computer(tmp_path, commands=()))
    assert code == 1 and "no key: run alexein login, or set ALEXEIN_API_KEY" in said

    wire(monkeypatch, lambda _: ok({"detail": "bad key"}, status=401))
    code, said = run(["latest", "--user", "dana"], keyed(tmp_path))
    assert code == 1 and "the service does not know this key" in said


# ------------------------------------------------------------------ login, whoami, logout --


def test_login_keeps_the_key_in_the_keychain_and_the_rest_in_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded = wire(monkeypatch, as_key(PERSONAL))
    shell = Computer(tmp_path)
    code, said = run(["login", "--key", "-"], shell, stdin="tm_kept\n")
    assert code == 0
    assert "Logged in: Dana, a personal key" in said
    assert "The key is in the system keyring." in said and "your own memory (me)" in said
    assert shell.kept == "tm_kept"
    saved = json.loads(shell.file.read_text())
    assert saved["store"] == "keychain" and saved["space"] == "personal"
    assert "tm_kept" not in shell.file.read_text()
    assert shell.file.stat().st_mode & 0o777 == 0o600

    assert run(["latest"], shell)[0] == 0
    assert recorded.last.headers["authorization"] == "Bearer tm_kept"
    assert sent_user(recorded.last) == "me"

    _, said = run(["whoami", "--json"], shell)
    who = json.loads(said)
    assert who["space"] == "personal" and who["user"] == "me"
    assert who["key_from"] == "the system keyring, from alexein login"

    _, said = run(["logout"], shell)
    assert "Logged out: took out the key, from the system keyring and" in said
    assert shell.kept is None and not shell.file.exists()
    assert "Not logged in." in run(["logout"], shell)[1]


def test_login_writes_to_macos_keychain_on_stdin_never_a_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(monkeypatch, as_key(PROJECT))
    shell = Computer(tmp_path, platform="darwin", commands=("security",))
    run(["login", "--key", "tm_mac", "--user", "dana"], shell)
    assert shell.kept == "tm_mac"
    assert shell.inputs[0] == "add-generic-password -U -s alexein -a api-key -w tm_mac\n"
    assert "tm_mac" not in "\n".join(shell.ran)
    saved = json.loads(shell.file.read_text())
    assert saved["store"] == "keychain" and saved["user"] == "dana"


@pytest.mark.parametrize(
    ("commands", "flags", "fell_back"),
    [((), [], True), (("secret-tool",), ["--insecure-storage"], False)],
)
def test_login_keeps_the_key_in_a_file_only_its_owner_reads_without_a_keychain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    commands: Sequence[str],
    flags: list[str],
    fell_back: bool,
) -> None:
    wire(monkeypatch, as_key(PROJECT))
    shell = Computer(tmp_path, commands=commands)
    _, said = run(["login", "--key", "tm_file", *flags], shell)
    saved = json.loads(shell.file.read_text())
    assert saved["store"] == "file" and saved["key"] == "tm_file"
    assert shell.file.stat().st_mode & 0o777 == 0o600
    assert ("There is no keychain here" in said) is fell_back
    assert "This is a project's key: name an app user" in said


def test_login_keeps_nothing_for_a_key_the_service_does_not_know(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(monkeypatch, lambda _: ok({"detail": "bad key"}, status=401))
    shell = Computer(tmp_path)
    code, said = run(["login", "--key", "tm_wrong"], shell)
    assert code == 1 and "the service does not know this key; nothing was kept" in said
    assert shell.kept is None and not shell.file.exists()


def test_key_and_the_environment_come_before_the_login(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wire(monkeypatch, as_key(PROJECT))
    shell = Computer(tmp_path, env={"ALEXEIN_API_KEY": "tm_env"})
    run(["login", "--key", "tm_kept", "--user", "dana"], shell)
    _, said = run(["whoami"], shell)
    assert "from     ALEXEIN_API_KEY" in said
    # The login's user goes with the login's key, not with another.
    assert "user     none: name one with --user or ALEXEIN_USER" in said


def test_a_login_from_either_cli_is_read_by_the_other(tmp_path: Path) -> None:
    """The file and keychain entry are the TypeScript CLI's too: what it writes, this reads."""
    shell = Computer(tmp_path)
    shell.file.parent.mkdir(parents=True)
    shell.file.write_text(json.dumps({"store": "keychain", "user": "dana", "space": "project"}))
    shell.kept = "tm_from_node"
    loaded = credentials.load(shell)
    assert loaded is not None and loaded.key == "tm_from_node" and loaded.saved["user"] == "dana"


def test_skill_prints_the_guide_the_typescript_cli_prints() -> None:
    console = Console(out=lambda _: None)
    assert main(["skill"], console) == 0
    skill = "\n".join(console.said)
    assert skill.startswith("---\nname: alexein-memory\n")
    assert 'alexein search "<a plain question>" --json' in skill
    node = Path(__file__).parents[2] / "cli-js" / "templates" / "skill" / "SKILL.md"
    assert SKILL.read_text() == node.read_text()


def test_outline_shows_json_as_a_person_reads_it() -> None:
    value = {
        "name": "Dana",
        "values": [{"city": "Lisbon", "since": None}],
        "tags": [],
        "note": "a\nb",
    }
    assert outline(value) == [
        "name: Dana",
        "values:",
        "  - city: Lisbon",
        "    since: -",
        "tags: (none)",
        "note: a\n  b",
    ]
