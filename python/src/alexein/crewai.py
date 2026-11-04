# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUntypedBaseClass=false, reportIncompatibleMethodOverride=false, reportIncompatibleVariableOverride=false
# CrewAI and the OpenAI Agents SDK are never installed together (pyproject.toml): where CrewAI is
# not, its types are unknown, and these checks would fail on that alone.
"""Long-term memory for a CrewAI crew: `pip install "alexein[crewai]"`.

`AlexeinMemory` is CrewAI's own memory, kept in Alexein: give it to a crew, and CrewAI recalls
the user's memory before every task, saves what each task learned, and gives every agent its
memory tools.

```python
from alexein.crewai import AlexeinMemory

memory = AlexeinMemory()
crew = Crew(agents=..., tasks=..., memory=memory, before_kickoff_callbacks=[memory.whose])
crew.kickoff(inputs={"user_id": "dana", ...})
```

or, for a JSON crew, the defaults: `"memory": {"python": "alexein.crewai.alexein_memory"}` and
`"before_kickoff_callbacks": [{"python": "alexein.crewai.whose"}]`.

Or tools an agent calls when it decides to, with the user fixed by your code -
`Agent(..., tools=memory_tools("dana"))` - and `save_result("dana", crew.kickoff(...))` after a
run to keep what it found.

Whose memory is read is decided by your code, never by the model: every kickoff names its user
in `inputs["user_id"]`, which `whose` takes out before the tasks see the inputs. `whose`,
`alexein_memory`, `memory_tools` and `save_result` at module level use one `AlexeinMemory()`,
which reads ALEXEIN_API_KEY on first use.
"""

from __future__ import annotations

import hashlib
import uuid
from contextvars import ContextVar
from typing import Any

from crewai.memory import Memory as CrewMemory
from crewai.memory import MemoryMatch, MemoryRecord
from crewai.tools import BaseTool
from opentelemetry import baggage
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from alexein import _integration as shared
from alexein._calls import checked_user
from alexein._client import Memory
from alexein._errors import AlexeinError, AuthenticationError, NotFoundError
from alexein._memories import Excerpt, Known, SearchResult
from alexein._user import User

__all__ = ["AlexeinMemory", "alexein_memory", "memory_tools", "save_result", "whose"]

log = shared.log

# The user is held per run, not on the memory, so one memory serves every run - concurrent runs
# for different users too: each kickoff has a context of its own, and CrewAI saves in a copy of
# it. The user is tied to the kickoff that named it, so a later crew on the same memory that
# skips `whose` never inherits it.
_user: ContextVar[tuple[object, str] | None] = ContextVar("alexein_user", default=None)
_session: ContextVar[str | None] = ContextVar("alexein_session", default=None)


def _kickoff() -> object:
    """The kickoff running now: CrewAI makes a new crew context for each one."""
    return baggage.get_baggage("crew_context")


def _id(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def _lines(found: SearchResult) -> list[tuple[str, str]]:
    """What a search found, best first, as (text, its ref or "")."""
    lines: list[tuple[str, str]] = []
    for m in found.memories:
        text = f"{m.date[:10]}: {m.text}" if isinstance(m, Excerpt) and m.date else m.text
        lines.append((text, "" if isinstance(m, Known) else m.ref))
    return lines


class _Nowhere:
    """Stands in for CrewAI's own storage, so no local store is ever made."""


class AlexeinMemory(CrewMemory):
    """CrewAI's memory, kept in Alexein: what CrewAI recalls before a task and saves after it go
    to the app user `whose` named for the run.

    `client` is a `Memory`; without one, one is made on first use, failing open, with a 10 s
    timeout. `fast` answers sooner and free, a little less precisely. `max_chars` bounds what
    goes into a prompt. `strict` stops a run at kickoff when memory is down (CrewAI itself logs
    and carries on past what memory raises during a task). A wrong key stops it either way."""

    client: Memory | None = Field(default=None, exclude=True)
    fast: bool = False
    max_chars: int = 4000
    strict: bool = False
    _key_checked: bool = PrivateAttr(default=False)

    def __init__(self, client: Memory | None = None, **fields: Any) -> None:
        fields.setdefault("storage", _Nowhere())
        super().__init__(client=client, **fields)

    def _client(self) -> Memory:
        if self.client is None:
            self.client = shared.made("crewai", self.strict)
        return self.client

    def whose(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Before each kickoff (`before_kickoff_callbacks=[memory.whose]`): take the app user
        from the run's inputs, and check the key once. A run that names no user stops here,
        before any task, so it can never inherit the last run's user. Returns the inputs
        without `user_id`."""
        user_id = inputs.pop("user_id", None)
        if not user_id or not isinstance(user_id, str):
            raise shared.missing_user('kick off with inputs={"user_id": "..."}')
        checked_user(user_id)
        self._check_key()
        _user.set((_kickoff(), user_id))
        _session.set(uuid.uuid4().hex)
        return inputs

    def _check_key(self) -> None:
        """Ask memory what the key is, once: CrewAI swallows memory's errors during a task, so a
        wrong key found then would only switch memory off without a word."""
        if self._key_checked:
            return
        try:
            self._client().me()
        except AuthenticationError:
            raise
        except AlexeinError as error:
            shared.ride_out(error, self.strict)
            return  # tried again on the next run
        self._key_checked = True

    def _current(self) -> User:
        held = _user.get()
        if held is None or held[0] is not _kickoff():
            message = (
                "memory has no user for this run, so it is not used: kick off with "
                'inputs={"user_id": "..."}, with memory.whose as a before-kickoff callback'
            )
            log.warning(message)  # CrewAI swallows the error below
            raise ValueError(message)
        return self._client().user(held[1])

    def recall(self, query: str, *args: Any, limit: int = 10, **_: Any) -> list[MemoryMatch]:
        """What memory holds for a task, best first, at most `limit` lines in `max_chars`."""
        try:
            found = self._current().search(query[-shared.MAX_QUERY :], fast=self.fast)
        except NotFoundError:
            return []
        except AlexeinError as error:
            log.warning("Alexein recall failed: %s", error)
            raise
        kept = _within(_lines(found), limit, self.max_chars)
        return [
            MemoryMatch(
                record=MemoryRecord(content=text, metadata={"ref": ref} if ref else {}),
                score=round(1.0 - n / max(len(kept), 1) / 2, 3),
            )
            for n, (text, ref) in enumerate(kept)
        ]

    def extract_memories(self, content: str) -> list[str]:
        """Skips the model call CrewAI makes to pick facts out of a result: Alexein learns the
        facts itself. A task that found nothing is not saved."""
        # CrewAI writes "...\nExpected result: ...\nResult: <the answer>"; the answer is what
        # follows the first "Result:" after that line, whatever the answer says.
        expected = content.find("\nExpected result:")
        marker = content.find("\nResult:", expected + 1) if expected >= 0 else -1
        if marker < 0:
            return [content] if content.strip() else []
        return [content] if content[marker + len("\nResult:") :].strip() else []

    def remember(self, content: str, *args: Any, **fields: Any) -> MemoryRecord | None:
        self._save([content], fields.get("agent_role"))
        return MemoryRecord(content=content)

    def remember_many(self, contents: list[str], *args: Any, **fields: Any) -> list[MemoryRecord]:
        self._save(contents, fields.get("agent_role"))
        return [MemoryRecord(content=content) for content in contents]

    def _save(self, contents: list[str], role: str | None) -> None:
        contents = [c for c in contents if c.strip()]
        if not contents:
            return
        session = _session.get() or ""
        items: list[Any] = [
            {"id": _id(session, role or "", text), "kind": "note", "text": text}
            for text in contents
        ]
        try:
            saved = self._current().add(items, session=session or None, author=role or None)
        except AlexeinError as error:
            log.warning("Alexein save failed: %s", error)
            raise
        if saved.failed:
            log.warning("Alexein unavailable, %d saves skipped", len(items))

    def forget(self, *args: Any, **kwargs: Any) -> int:
        raise NotImplementedError(
            "forget in Alexein with the client: Memory().user(user_id).forget(...)"
        )

    def reset(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("memory in Alexein is not reset from a crew")

    def tools(self, user_id: str, write: bool = False) -> list[BaseTool]:
        """`memory_search` and `memory_open` for one app user's agent, and `memory_add` with
        `write`: the user is fixed here, by your code, and never asked of the model."""
        checked_user(user_id)  # raises now for an id memory cannot hold
        made: list[BaseTool] = [_Search(owner=self, user_id=user_id)]
        made.append(_Open(owner=self, user_id=user_id))
        return [*made, _Add(owner=self, user_id=user_id)] if write else made

    def save_result(self, user_id: str, output: Any) -> None:
        """Keep what a finished crew found, under `user_id`: a crew's output, or text."""
        text = str(getattr(output, "raw", output) or "").strip()
        if not text:
            return
        item: Any = {"id": _id(user_id, text), "kind": "note", "text": text}
        try:
            if self._client().user(user_id).add(item).failed:
                log.warning("Alexein unavailable, result not saved")
        except AlexeinError as error:
            shared.ride_out(error, self.strict)


def _within(lines: list[tuple[str, str]], limit: int, room: int) -> list[tuple[str, str]]:
    """At most `limit` lines, whole ones only, within `room` characters in all (a single line
    longer than that is cut)."""
    kept: list[tuple[str, str]] = []
    total = 0
    for text, ref in lines[:limit]:
        text = text[:room]
        total += len(text)
        if kept and total > room:
            break
        kept.append((text, ref))
    return kept


# ---------------------------------------------------------------------------------- tools --


class _Query(BaseModel):
    query: str = Field(description="What to look up, in plain language")


class _Ref(BaseModel):
    ref: str = Field(description="A ref memory_search gave")


class _Note(BaseModel):
    text: str = Field(description="One plain sentence to remember")


class _Tool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    owner: AlexeinMemory = Field(exclude=True)
    user_id: str = Field(exclude=True)

    def _user(self) -> User:
        return self.owner._client().user(self.user_id)  # pyright: ignore[reportPrivateUsage]

    def _told(self, error: AlexeinError) -> str:
        return shared.told(error, self.owner.strict)


class _Search(_Tool):
    name: str = "memory_search"
    description: str = shared.SEARCH_DESCRIPTION
    args_schema: type[BaseModel] = _Query

    def _run(self, query: str) -> str:
        try:
            found = self._user().search(query[-shared.MAX_QUERY :], fast=self.owner.fast)
        except NotFoundError:
            return shared.NOTHING_FOUND
        except AlexeinError as error:
            return self._told(error)
        return shared.found_text(found, self.owner.max_chars)


class _Open(_Tool):
    name: str = "memory_open"
    description: str = shared.OPEN_DESCRIPTION
    args_schema: type[BaseModel] = _Ref

    def _run(self, ref: str) -> str:
        try:
            return shared.opened_text(self._user().open(ref))
        except AlexeinError as error:
            return self._told(error)


class _Add(_Tool):
    name: str = "memory_add"
    description: str = shared.ADD_DESCRIPTION
    args_schema: type[BaseModel] = _Note

    def _run(self, text: str) -> str:
        try:
            saved = self._user().add(text, kind="note", session=_session.get())
        except AlexeinError as error:
            return self._told(error)
        return shared.UNAVAILABLE if saved.failed else shared.SAVED


# One memory for every run - it holds no user - and for a JSON crew to point at:
# `"memory": {"python": "alexein.crewai.alexein_memory"}`.
alexein_memory = AlexeinMemory()


def whose(inputs: dict[str, Any]) -> dict[str, Any]:
    """`before_kickoff_callbacks=[whose]`: the default memory's `whose`. A function rather than
    a bound method, as CrewAI's checkpoints keep only module-level callbacks; for a memory of
    your own, wrap its `whose` the same way."""
    return alexein_memory.whose(inputs)


def memory_tools(user_id: str, write: bool = False) -> list[BaseTool]:
    """The default memory's tools for one app user: `memory_search`, `memory_open`, and
    `memory_add` with `write`."""
    return alexein_memory.tools(user_id, write=write)


def save_result(user_id: str, output: Any) -> None:
    """Keep what a finished crew found, under `user_id`, in the default memory."""
    alexein_memory.save_result(user_id, output)
