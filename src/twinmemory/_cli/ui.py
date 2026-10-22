"""How the CLI talks to the person running it: lines of output, and questions when there is
someone at a terminal to answer them. A test hands in a `Console` with answers ready; a script
or CI gets one that asks nothing and takes every default.
"""

from __future__ import annotations

import getpass
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field


@dataclass
class Console:
    """`interactive` is whether questions can be asked. `answers` stand in for typed replies
    in tests, in order; `said` keeps every line printed, for the same."""

    interactive: bool = False
    yes: bool = False
    answers: list[str] = field(default_factory=list[str])
    said: list[str] = field(default_factory=list[str])
    out: Callable[[str], None] | None = None

    @classmethod
    def for_terminal(cls, *, yes: bool) -> Console:
        return cls(interactive=sys.stdin.isatty() and not yes, yes=yes)

    def line(self, text: str = "") -> None:
        self.said.append(text)
        (self.out or _print)(text)

    def step(self, verb: str, what: str) -> None:
        self.line(f"  {verb:<9}{what}")

    def fail(self, why: str) -> None:
        self.line(f"twinmemory: {why}")

    def _reply(self, prompt: str, *, secret: bool) -> str:
        if self.answers:
            reply = self.answers.pop(0)
            self.said.append(f"{prompt}{'***' if secret and reply else reply}")
            return reply
        if secret:
            return getpass.getpass(prompt)
        return input(prompt)

    def confirm(self, question: str) -> bool:
        """Yes with `--yes`; asked at a terminal; no otherwise."""
        if self.yes:
            return True
        if not self.interactive:
            return False
        return self._reply(f"  {question} [y/N] ", secret=False).strip().lower() in ("y", "yes")

    def secret(self, question: str) -> str:
        """A key, typed without echo; empty when skipped or when nobody can answer."""
        if not self.interactive:
            return ""
        return self._reply(f"  {question} ", secret=True).strip()

    def choose(self, question: str, options: Sequence[str]) -> str | None:
        """One of `options` by number or name; None when nobody can answer."""
        if not self.interactive:
            return None
        for n, option in enumerate(options, 1):
            self.line(f"    {n}. {option}")
        reply = self._reply(f"  {question} ", secret=False).strip()
        if reply.isdigit() and 1 <= int(reply) <= len(options):
            return options[int(reply) - 1]
        return reply if reply in options else None


def _print(text: str) -> None:
    print(text, flush=True)
