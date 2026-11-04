"""Why a command stopped before changing anything, with the exit code to stop with."""

from __future__ import annotations


class Stop(Exception):
    """Raised by a check that fails; the command prints it and exits with `code`, having
    changed nothing: 1 when the project is not ready, 2 when the command itself is wrong."""

    def __init__(self, why: str, code: int = 1) -> None:
        super().__init__(why)
        self.code = code
