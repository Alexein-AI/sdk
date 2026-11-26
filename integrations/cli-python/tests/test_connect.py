"""`alexein-cli connect`: which tools it finds, what it runs or writes for each, what it takes
out again with `--remove`, and what it leaves alone - the same as `@alexein/cli connect`."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from alexein_cli import connect as connecting
from alexein_cli import key_from, main
from alexein_cli.connect import NAME, URL, ConnectOptions, Ran, connect
from alexein_cli.ui import Console


class Computer:
    """A computer with `commands` on PATH, each answering `list` or `get` with `listed`, over a
    scratch home."""

    def __init__(
        self, tmp: Path, commands: Sequence[str], listed: dict[str, str] | None = None
    ) -> None:
        self.home = tmp / "home"
        self.home.mkdir()
        self.platform = "linux"
        self.env: dict[str, str] = {}
        self.commands = list(commands)
        self.listed = listed or {}
        self.ran: list[str] = []
        self.attached: list[str] = []
        self.failing: set[str] = set()

    def has(self, command: str) -> bool:
        return command in self.commands

    def run(self, command: str, args: Sequence[str]) -> Ran:
        reading = len(args) > 1 and args[1] in ("list", "get")
        if reading:
            out = self.listed.get(f"{command} {args[0]}", "")
            return Ran(1 if args[1] == "get" and not out else 0, out)
        self.ran.append(" ".join([command, *args]))
        if command in self.failing:
            return Ran(1, "something went wrong\nError: not signed in")
        return Ran(0, "")

    def attach(self, command: str, args: Sequence[str]) -> int:
        self.attached.append(" ".join([command, *args]))
        return 0

    def file(self, path: str, text: str) -> Computer:
        (self.home / path).parent.mkdir(parents=True, exist_ok=True)
        (self.home / path).write_text(text)
        return self

    def text(self, path: str) -> str:
        return (self.home / path).read_text()

    def json(self, path: str) -> Any:
        return json.loads(self.text(path))


def run(computer: Computer, answers: Sequence[str] = (), **options: Any) -> tuple[int, str]:
    console = Console(
        interactive=bool(answers), yes=not answers, answers=list(answers), out=lambda _: None
    )
    code = connect(ConnectOptions(**options), console, computer)
    return code, "\n".join(console.said)


def test_installs_the_plugin_where_a_tool_has_one_and_the_server_where_not(tmp_path: Path) -> None:
    computer = Computer(tmp_path, ["claude", "copilot", "codex", "gemini", "code"])
    code, said = run(computer)
    assert code == 0
    assert computer.ran == [
        "claude plugin marketplace add Alexein-AI/claude-plugins",
        "claude plugin install alexein@alexein",
        f'code --add-mcp {{"name":"{NAME}","type":"http","url":"{URL}"}}',
        "copilot plugin marketplace add Alexein-AI/copilot-plugin",
        "copilot plugin install alexein-ai@alexein-ai",
        f"codex mcp add {NAME} --url {URL}",
        f"gemini mcp add --transport http --scope user {NAME} {URL}",
    ]
    assert "added    Claude Code (the Alexein AI plugin)" in said
    assert "Codex" in said and "run codex mcp login alexein" in said
    assert "claude.ai, Claude Desktop and ChatGPT" in said


def test_adds_the_server_alone_with_no_plugin(tmp_path: Path) -> None:
    computer = Computer(tmp_path, ["claude", "copilot", "agy"])
    run(computer, plugins=False)
    assert computer.ran == [
        f"claude mcp add --transport http --scope user {NAME} {URL}",
        f"copilot mcp add --transport http {NAME} {URL}",
        f"agy mcp add {NAME} {URL}",
    ]


def test_leaves_a_tool_that_has_alexein_already_unless_force(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    listed = {"copilot mcp": "User servers:\n  alexein (http)"}
    computer = Computer(tmp_path / "a", ["copilot", "gemini"], listed)
    _, said = run(computer)
    assert "has      GitHub Copilot CLI" in said
    assert computer.ran == [f"gemini mcp add --transport http --scope user {NAME} {URL}"]

    (tmp_path / "b").mkdir()
    again = Computer(tmp_path / "b", ["copilot"], {"copilot mcp": "alexein-ai (http)"})
    run(again, force=True, plugins=False)
    assert again.ran == [f"copilot mcp add --transport http {NAME} {URL}"]


def test_merges_into_cursors_mcp_json_keeping_its_other_servers_and_a_copy(
    tmp_path: Path,
) -> None:
    other = {"url": "https://x.test/mcp"}
    computer = Computer(tmp_path, []).file(
        ".cursor/mcp.json", json.dumps({"mcpServers": {"other": other}, "theme": "dark"})
    )
    code, said = run(computer)
    assert code == 0
    assert computer.json(".cursor/mcp.json") == {
        "mcpServers": {"other": other, NAME: {"url": URL}},
        "theme": "dark",
    }
    assert (computer.home / ".cursor/mcp.json.bak").exists()
    assert "added    Cursor (~/.cursor/mcp.json)" in said


def test_does_not_touch_a_settings_file_that_is_not_json(tmp_path: Path) -> None:
    computer = Computer(tmp_path, []).file(".cursor/mcp.json", "{ not json")
    code, said = run(computer)
    assert code == 1
    assert computer.text(".cursor/mcp.json") == "{ not json"
    assert "is not valid JSON" in said


def test_writes_devin_desktops_file_when_its_cli_is_not_installed(tmp_path: Path) -> None:
    computer = Computer(tmp_path, []).file(".config/devin/mcp_config.json", "{}")
    run(computer)
    assert computer.json(".config/devin/mcp_config.json")["mcpServers"][NAME] == {
        "url": URL,
        "transport": "http",
    }


def test_sends_a_key_in_headers_installs_no_plugin_and_skips_codex(tmp_path: Path) -> None:
    computer = Computer(tmp_path, ["claude", "codex"]).file(".cursor/mcp.json", "{}")
    _, said = run(computer, key="tm_secret")
    assert computer.ran == [
        "claude mcp add --transport http --scope user --header Authorization: Bearer tm_secret "
        f"--header X-Alexein-User: me {NAME} {URL}"
    ]
    assert computer.json(".cursor/mcp.json")["mcpServers"][NAME]["headers"] == {
        "Authorization": "Bearer tm_secret",
        "X-Alexein-User": "me",
    }
    assert "skipped  Codex" in said
    assert "tm_secret" not in said


def test_changes_nothing_with_dry_run_or_list_and_masks_the_key(tmp_path: Path) -> None:
    computer = Computer(tmp_path, ["gemini"]).file(".cursor/mcp.json", "{}")
    _, said = run(computer, dry_run=True, key="tm_secret")
    assert computer.ran == []
    assert computer.json(".cursor/mcp.json") == {}
    assert "would    add" in said
    assert "tm_***" in said and "tm_secret" not in said

    _, listing = run(computer, listing=True)
    assert computer.ran == []
    assert "found    Gemini CLI" in listing


def test_runs_only_the_tools_named_and_refuses_a_name_it_does_not_know(tmp_path: Path) -> None:
    computer = Computer(tmp_path, ["claude", "gemini"])
    run(computer, only=["gemini"])
    assert computer.ran == [f"gemini mcp add --transport http --scope user {NAME} {URL}"]
    assert run(computer, only=["emacs"])[0] == 2


def test_says_what_failed_and_goes_on_to_the_next_tool(tmp_path: Path) -> None:
    computer = Computer(tmp_path, ["claude", "gemini"])
    computer.failing.add("claude")
    code, said = run(computer)
    assert code == 1
    assert "failed   Claude Code: Error: not signed in" in said
    assert "added    Gemini CLI" in said


def test_asks_before_adding_and_offers_a_sign_in_where_the_tool_has_one(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    computer = Computer(tmp_path / "a", ["codex"])
    code, _ = run(computer, ["y", "y"])
    assert code == 0
    assert computer.attached == [f"codex mcp login {NAME}"]

    (tmp_path / "b").mkdir()
    declined = Computer(tmp_path / "b", ["codex"])
    _, said = run(declined, ["n"])
    assert declined.ran == []
    assert "Nothing changed." in said


def test_signs_claude_code_in_to_the_plugins_server(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    computer = Computer(tmp_path / "a", ["claude"])
    run(computer, ["y", "y"])
    assert computer.attached == ["claude mcp login plugin:alexein:alexein"]

    (tmp_path / "b").mkdir()
    bare = Computer(tmp_path / "b", ["claude"])
    run(bare, ["y", "y"], plugins=False)
    assert bare.attached == [f"claude mcp login {NAME}"]


def test_takes_out_what_it_added_with_remove(tmp_path: Path) -> None:
    other = {"url": "https://x.test/mcp"}
    computer = (
        Computer(
            tmp_path,
            ["claude", "code"],
            {"claude plugin": "alexein@alexein  enabled", "claude mcp": "alexein:\n  Scope: User"},
        )
        .file(".cursor/mcp.json", json.dumps({"mcpServers": {NAME: {"url": URL}, "other": other}}))
        .file(".config/Code/User/mcp.json", json.dumps({"servers": {NAME: {"url": URL}}}))
    )
    code, said = run(computer, remove=True)
    assert code == 0
    assert computer.ran == [
        "claude plugin uninstall alexein@alexein",
        f"claude mcp remove --scope user {NAME}",
    ]
    assert computer.json(".cursor/mcp.json") == {"mcpServers": {"other": other}}
    assert (computer.home / ".cursor/mcp.json.bak").exists()
    assert computer.json(".config/Code/User/mcp.json") == {"servers": {}}
    assert "removed  Claude Code (claude plugin uninstall, claude mcp remove)" in said
    assert "removed  Cursor (~/.cursor/mcp.json)" in said
    assert "disconnect it in My memory" in said


def test_takes_alexein_out_of_the_other_tools_with_their_own_commands(tmp_path: Path) -> None:
    devin = json.dumps({"mcpServers": {NAME: {"url": URL}}})
    (tmp_path / "a").mkdir()
    computer = Computer(
        tmp_path / "a",
        ["copilot", "codex", "gemini", "agy", "devin"],
        {
            "copilot plugin": "alexein-ai@alexein-ai",
            "copilot mcp": "alexein-ai (plugin)",
            "codex mcp": "alexein  https://api.alexein.ai/v1/mcp",
            "gemini mcp": "alexein (http)",
            "agy plugin": "alexein-ai",
        },
    ).file(".config/devin/mcp_config.json", devin)
    code, _ = run(computer, remove=True)
    assert code == 0
    assert computer.ran == [
        "copilot plugin uninstall alexein-ai@alexein-ai",
        f"codex mcp remove {NAME}",
        f"gemini mcp remove --scope user {NAME}",
        "agy plugin uninstall alexein-ai",
        f"devin mcp remove -s user {NAME}",
    ]

    (tmp_path / "b").mkdir()
    servers = Computer(
        tmp_path / "b", ["copilot", "agy"], {"copilot mcp": "alexein (http)", "agy mcp": "alexein"}
    ).file(".config/devin/mcp_config.json", devin)
    _, said = run(servers, remove=True)
    assert servers.ran == [f"copilot mcp remove {NAME}"]
    assert "skipped  Antigravity: take Alexein out in its own settings" in said
    assert servers.json(".config/devin/mcp_config.json") == {"mcpServers": {}}


def test_leaves_a_server_it_did_not_add_under_another_name(tmp_path: Path) -> None:
    theirs = json.dumps({"mcpServers": {"alexein-ai": {"url": URL}}})
    computer = Computer(tmp_path, []).file(".cursor/mcp.json", theirs)
    code, said = run(computer, remove=True)
    assert code == 0
    assert computer.text(".cursor/mcp.json") == theirs
    assert "skipped  Cursor: take Alexein out in its own settings" in said


def test_remove_dry_run_changes_nothing_and_a_tool_without_alexein_has_nothing_to_take(
    tmp_path: Path,
) -> None:
    (tmp_path / "a").mkdir()
    computer = Computer(tmp_path / "a", ["claude"], {"claude mcp": "alexein:"}).file(
        ".cursor/mcp.json", json.dumps({"mcpServers": {NAME: {"url": URL}}})
    )
    _, said = run(computer, remove=True, dry_run=True)
    assert computer.ran == []
    assert computer.json(".cursor/mcp.json")["mcpServers"][NAME] == {"url": URL}
    assert "would    remove Claude Code, with claude mcp remove --scope user alexein" in said
    assert "would    remove Cursor" in said

    (tmp_path / "b").mkdir()
    bare = Computer(tmp_path / "b", ["gemini"])
    code, nothing = run(bare, remove=True)
    assert code == 0 and bare.ran == []
    assert "nothing to take out" in nothing


def test_asks_before_taking_anything_out(tmp_path: Path) -> None:
    computer = Computer(tmp_path, ["claude"], {"claude mcp": "alexein:"})
    code, said = run(computer, ["n"], remove=True)
    assert code == 1
    assert computer.ran == []
    assert "Take Alexein AI out of Claude Code?" in said


def test_lists_the_tools_as_json_and_runs_nothing(tmp_path: Path) -> None:
    computer = Computer(tmp_path, ["claude"], {"claude mcp": "alexein:"})
    code, said = run(computer, listing=True, as_json=True, only=["claude-code", "gemini"])
    assert code == 0
    assert computer.ran == []
    assert json.loads(said) == {
        "tools": [
            {"id": "claude-code", "name": "Claude Code", "found": True, "added": True},
            {"id": "gemini", "name": "Gemini CLI", "found": False, "added": None},
        ]
    }


def test_finds_nothing_on_a_bare_computer_and_points_at_the_chat_apps(tmp_path: Path) -> None:
    code, said = run(Computer(tmp_path, []))
    assert code == 0
    assert "No AI tools found" in said


# --------------------------------------------------------------------------- the command line --


def quiet() -> Console:
    return Console(out=lambda _: None)


def test_main_parses_connect_and_its_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    computer = Computer(tmp_path, ["gemini"])
    monkeypatch.setattr(connecting, "LocalHost", lambda: computer)
    console = quiet()
    argv = ["connect", "--only", "gemini, claude-code", "--key", "-", "--dry-run"]
    assert main(argv, console, stdin=lambda: "tm_piped\n") == 0
    said = "\n".join(console.said)
    assert "would    add Gemini CLI, with gemini mcp add" in said
    assert "Authorization: Bearer tm_***" in said and "tm_piped" not in said
    assert computer.ran == []


def test_reads_key_dash_from_stdin_and_refuses_it_when_nothing_comes() -> None:
    assert key_from("-", lambda: "tm_piped\nignored\n") == "tm_piped"
    assert key_from("tm_given", lambda: "tm_piped") == "tm_given"
    assert key_from(None, lambda: "tm_piped") is None
    for read in (lambda: None, lambda: "\n"):
        with pytest.raises(ValueError, match="none came"):
            key_from("-", read)
    console = quiet()
    assert main(["init", "langgraph", "--key", "-"], console, stdin=lambda: None) == 2
    assert "--key - reads the key from stdin" in "\n".join(console.said)


@pytest.mark.parametrize("flag", ["--key=tm_x", "--no-plugin", "--force", "--list"])
def test_remove_goes_only_with_what_fits_it(flag: str) -> None:
    console = quiet()
    assert main(["connect", "--remove", flag], console) == 2
    assert "--remove goes with --only, --dry-run and --yes" in "\n".join(console.said)


def test_json_is_for_doctor_and_connect_list() -> None:
    assert main(["connect", "--json"], quiet()) == 2
    with pytest.raises(SystemExit):
        main(["init", "langgraph", "--json"], quiet())
