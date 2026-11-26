"""`install` and its offer: `alexein` put on PATH with `uv tool install`, and uvx's own copy not
taken for it - the same as `@alexein/cli install` with npm."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from alexein_cli.connect import Ran
from alexein_cli.install import install, installed, offer_install
from alexein_cli.ui import Console


def executable(path: Path) -> None:
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)


class Computer:
    """A computer running the CLI through uvx: the environment uvx made, with its own `alexein`,
    first on PATH, and uv's folder for commands after it when `on_path`. `uv tool install` writes
    `alexein` there."""

    def __init__(
        self,
        tmp: Path,
        *,
        uv: bool = True,
        on_path: bool = True,
        fails: bool = False,
        shell_updated: bool = True,
    ) -> None:
        self.home = tmp / "home"
        self.home.mkdir()
        self.platform = "linux"
        self.running = tmp / "cache" / "archive-v0" / "IprIy8" / "bin"
        self.bin = tmp / "local" / "bin"
        for folder in (self.running, self.bin):
            folder.mkdir(parents=True)
        executable(self.running / "alexein")
        path = [self.running, *([self.bin] if on_path else [])]
        self.env = {
            "PATH": os.pathsep.join(str(p) for p in path),
            "ALEXEIN_CONFIG_DIR": str(self.home / "config"),
            **({"UV": "/opt/uv/bin/uv"} if uv else {}),
        }
        self.fails = fails
        self.shell_updated = shell_updated
        self.attached: list[str] = []

    def has(self, command: str) -> bool:
        return False

    def run(self, command: str, args: Sequence[str]) -> Ran:
        if list(args) == ["tool", "dir", "--bin"]:
            return Ran(0, f"{self.bin}\n")
        return Ran(1, "")

    def attach(self, command: str, args: Sequence[str]) -> int:
        self.attached.append(" ".join([command, *args]))
        if self.fails:
            return 1
        if list(args[:2]) == ["tool", "install"]:
            executable(self.bin / "alexein")
        if list(args[:2]) == ["tool", "update-shell"]:
            return 0 if self.shell_updated else 1
        return 0


def quiet(answers: Sequence[str] | None = None) -> Console:
    return Console(interactive=answers is not None, answers=list(answers or []), out=lambda _: None)


def said(console: Console) -> str:
    return "\n".join(console.said)


def test_uvx_own_copy_is_not_taken_for_alexein_on_path(tmp_path: Path) -> None:
    computer = Computer(tmp_path)
    assert not installed(computer, computer.running)
    executable(computer.bin / "alexein")
    assert installed(computer, computer.running)


def test_install_runs_uv_tool_install_with_the_uv_that_runs_it(tmp_path: Path) -> None:
    computer = Computer(tmp_path)
    console = quiet()
    assert install(console, computer, computer.running) == 0
    assert computer.attached == ["/opt/uv/bin/uv tool install alexein-cli"]
    assert "installed alexein: type alexein in any terminal" in said(console)


def test_install_puts_uvs_folder_on_path_where_it_is_not(tmp_path: Path) -> None:
    computer = Computer(tmp_path, on_path=False)
    console = quiet()
    assert install(console, computer, computer.running) == 0
    assert computer.attached == [
        "/opt/uv/bin/uv tool install alexein-cli",
        "/opt/uv/bin/uv tool update-shell",
    ]
    assert f"alexein, in {computer.bin}: open a new terminal, then type alexein" in said(console)

    (tmp_path / "again").mkdir()
    stuck = Computer(tmp_path / "again", on_path=False, shell_updated=False)
    console = quiet()
    assert install(console, stuck, stuck.running) == 0
    assert f'export PATH="{stuck.bin}:$PATH"' in said(console)


def test_install_leaves_an_alexein_there_and_says_when_uv_is_missing_or_fails(
    tmp_path: Path,
) -> None:
    (tmp_path / "a").mkdir()
    there = Computer(tmp_path / "a")
    executable(there.bin / "alexein")
    console = quiet()
    assert install(console, there, there.running) == 0
    assert there.attached == [] and "on your PATH already" in said(console)

    (tmp_path / "b").mkdir()
    no_uv = Computer(tmp_path / "b", uv=False)
    console = quiet()
    assert install(console, no_uv, no_uv.running) == 1
    assert "uv is not on PATH" in said(console)

    (tmp_path / "c").mkdir()
    failing = Computer(tmp_path / "c", fails=True)
    assert install(quiet(), failing, failing.running) == 1


def test_the_offer_asks_once_at_a_terminal_and_enter_installs(tmp_path: Path) -> None:
    computer = Computer(tmp_path)
    console = quiet([""])
    offer_install(console, computer, terminal=True, running=computer.running)
    question = "Install the alexein command, so you can type alexein in any terminal? [Y/n]"
    assert question in said(console)
    assert computer.attached == ["/opt/uv/bin/uv tool install alexein-cli"]


def test_the_offer_keeps_a_no_and_does_not_ask_again(tmp_path: Path) -> None:
    computer = Computer(tmp_path)
    first = quiet(["n"])
    offer_install(first, computer, terminal=True, running=computer.running)
    assert computer.attached == []
    assert "not asked again. Any time: uvx alexein-cli install" in said(first)
    state = json.loads((Path(computer.env["ALEXEIN_CONFIG_DIR"]) / "state.json").read_text())
    assert state == {"install": "declined"}

    second = quiet(["y"])
    offer_install(second, computer, terminal=True, running=computer.running)
    assert second.said == [] and computer.attached == []


def test_the_offer_is_never_made_where_nobody_can_answer(tmp_path: Path) -> None:
    computer = Computer(tmp_path)
    offer_install(quiet(), computer, terminal=True, running=computer.running)
    offer_install(quiet(["y"]), computer, terminal=False, running=computer.running)
    assert computer.attached == []
