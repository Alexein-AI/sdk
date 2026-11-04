# pyright: reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportUntypedFunctionDecorator=false
# The OpenAI Agents SDK and CrewAI are never installed together (pyproject.toml): where the SDK is
# not, its types are unknown, and these checks would fail on that alone.
"""Long-term memory for the OpenAI Agents SDK: `pip install "alexein[openai-agents]"`.

```python
from alexein.openai_agents import AlexeinMemory, MemoryContext

memory = AlexeinMemory()
agent = Agent(name="Assistant", tools=memory.tools())
result = await Runner.run(
    agent,
    message,
    context=MemoryContext(user_id="dana", session_id="conv-7"),
    run_config=RunConfig(call_model_input_filter=memory.recall),
)
await memory.remember(result)
```

`recall` searches once a turn, with the user's latest message, and adds what it finds to the
instructions of every model call in that turn, so it never lands in your session or history.
Already using a `call_model_input_filter`? Run both:

```python
async def both(data: CallModelData[Any]) -> ModelInputData:
    data.model_data = await memory.recall(data)
    return await yours(data)
```

Whose memory is read is decided by your code, never by the model: pass the user's id in the
run's context, as `MemoryContext` or any context with a `user_id` (and, if you like, a
`session_id`, which groups what is saved by conversation). `recall`, `remember` and
`memory_tools` at module level use one `AlexeinMemory()`, which reads ALEXEIN_API_KEY on first
use.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from agents import (
    ItemHelpers,
    RunContextWrapper,
    Tool,
    TResponseInputItem,
    function_tool,
)
from agents.result import RunResultBase
from agents.run import CallModelData, ModelInputData

from alexein import _integration as shared
from alexein._async_user import AsyncUser
from alexein._client import AsyncMemory
from alexein._errors import (
    AlexeinError,
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
)
from alexein._memories import SearchResult
from alexein._types import Item

__all__ = ["AlexeinMemory", "MemoryContext", "memory_tools", "recall", "remember"]

# How many runs' recalls are kept for the model calls after a turn's first.
_KEPT = 1000


@dataclass
class MemoryContext:
    """Whose memory a run reads: pass it as `context=` to `Runner.run`, or give a context of
    your own a `user_id` (and, if you like, a `session_id`)."""

    user_id: str
    session_id: str | None = None


def _text(item: Any) -> str:
    """What a message says, whether its content is a string or a list of parts."""
    content = shared.field_of(item, "content") if isinstance(item, dict) else None
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [shared.field_of(p, "text") for p in content]  # pyright: ignore[reportUnknownVariableType]
    return "\n".join(p for p in parts if isinstance(p, str))


def _role(item: Any) -> Any:
    return shared.field_of(item, "role") if isinstance(item, dict) else None


def _asked(items: list[TResponseInputItem]) -> str | None:
    """The user's message when this model call is a turn's first - the input ends with it, or
    with developer or system messages after it - else None."""
    for item in reversed(items):
        role = _role(item)
        if role in ("developer", "system"):
            continue
        return _text(item).strip() if role == "user" else None
    return None


def _answer(output: Any) -> str:
    """The final output as text: a string as it is, structured output as JSON."""
    if output is None or isinstance(output, str):
        return output or ""
    dump = getattr(output, "model_dump_json", None)
    return str(dump()) if callable(dump) else json.dumps(output, default=str)


def _turn(result: RunResultBase) -> str:
    """What sets this run's saves apart from another's with the same words: the model's response
    id, or - from a model that gives none, as Chat Completions does - one made for this result,
    so that saving it again still edits rather than adds."""
    found = result.raw_responses[-1].response_id if result.raw_responses else None
    if not found:
        found = getattr(result, "_alexein_turn", None) or uuid.uuid4().hex
        result._alexein_turn = found  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue]
    return str(found)


def _item(text: str, role: str, turn: str, author: str | None) -> Item:
    item = Item(
        id=hashlib.sha256(f"{turn}|{role}|{text}".encode()).hexdigest()[:24], role=role, text=text
    )
    if author:
        item["author"] = author
    return item


class AlexeinMemory:
    """Memory for agents: `recall` as the run's `call_model_input_filter`, `remember(result)`
    after a run, and `tools()` for a model to call.

    `client` is an `AsyncMemory`; without one, one is made on first use, failing open, with a
    10 s timeout. `fast` answers sooner and free, a little less precisely. `max_chars` bounds
    what goes into the instructions. `strict` raises when memory is down, where by default a
    turn goes on without it. A wrong key raises either way. `timeout` is the seconds each attempt
    of the client made on first use may take."""

    def __init__(
        self,
        client: AsyncMemory | None = None,
        *,
        fast: bool = False,
        max_chars: int = 4000,
        strict: bool = False,
        timeout: float = shared.TIMEOUT,
    ) -> None:
        self.fast = fast
        self.max_chars = max_chars
        self.strict = strict
        self.timeout = timeout
        self._client = client
        # What `recall` found for each run - its context object - and user, for the model calls
        # after a turn's first (a tool loop, a handoff), whose input no longer ends with the
        # user's message. Per run, so two turns in flight for one user keep their own.
        self._recalled: dict[tuple[int, str], str] = {}
        self._tools: dict[bool, list[Tool]] = {}

    def user(self, context: Any) -> AsyncUser:
        """The app user a run is for, from its context; never from the model."""
        found = shared.field_of(context, "user_id")
        if not found:
            raise shared.missing_user(
                'run the agent with context=MemoryContext(user_id="..."), or a context that '
                "has a user_id"
            )
        if self._client is None:
            self._client = shared.made_async("openai-agents", self.strict, self.timeout)
        return self._client.user(str(found))

    async def _search(self, user: AsyncUser, query: str) -> SearchResult | None:
        try:
            found = await user.search(query[-shared.MAX_QUERY :], fast=self.fast)
        except NotFoundError:  # nothing saved for this user yet
            return None
        except AlexeinError as error:
            shared.ride_out(error, self.strict)
            return None
        return None if found.failed else found

    async def recall(self, data: CallModelData[Any]) -> ModelInputData:
        """`RunConfig(call_model_input_filter=memory.recall)`: before the model, what memory
        holds for the user's latest message, added to the instructions."""
        model = data.model_data
        user = self.user(data.context)
        run = (id(data.context), user.id)
        asked = _asked(model.input)
        if asked is None and run not in self._recalled:
            # A run resumed after an approval, or in another process: nothing kept for it.
            said = [_text(i).strip() for i in model.input if _role(i) == "user"]
            asked = said[-1] if said else None
        if asked is not None:
            found = await self._search(user, asked) if asked else None
            text = found.context(self.max_chars) if found else ""
            self._recalled.pop(run, None)  # to the end, so the oldest are dropped first
            self._recalled[run] = shared.prompt(text)
            while len(self._recalled) > _KEPT:
                self._recalled.pop(next(iter(self._recalled)))
        if block := self._recalled.get(run, ""):
            given = model.instructions
            model.instructions = f"{given}\n\n{block}" if given else block
        return model

    async def remember(self, result: RunResultBase) -> None:
        """Save the turn a run answered - the user's latest message and the final answer - under
        the agent's name. Call it once the run is done (for `run_streamed`, once its events are
        consumed). Saving the same result again edits what was saved rather than adding a copy.
        Tool calls and their results are not saved, and a run paused for an approval saves
        nothing: save the run that resumes it. Needs a key that writes."""
        if getattr(result, "interruptions", None):
            return
        context = result.context_wrapper.context
        session = shared.field_of(context, "session_id")
        said = ItemHelpers.input_to_new_input_list(result.input)
        asked = next((_text(i) for i in reversed(said) if _role(i) == "user"), "")
        turn = f"{session}|{_turn(result)}"
        given = (
            (asked, "user", None),
            (_answer(result.final_output), "assistant", result.last_agent.name),
        )
        items = [_item(text, role, turn, author) for text, role, author in given if text.strip()]
        if not items:
            return
        user = self.user(context)
        try:
            await user.add(items, session=str(session) if session else None)
        except AlexeinError as error:
            shared.ride_out(error, self.strict)

    def tools(self, write: bool = False) -> list[Tool]:
        """`memory_search` and `memory_open` for a model to call, and `memory_add` with `write`.
        The user comes from the run's context, never from the model."""
        if write not in self._tools:
            self._tools[write] = self._made_tools(write)
        return self._tools[write]

    def _made_tools(self, write: bool) -> list[Tool]:
        # The context is filled in by the Runner and never shown to the model.
        def tool(description: str) -> Any:
            return function_tool(
                description_override=description, failure_error_function=self._failed
            )

        @tool(shared.SEARCH_DESCRIPTION)
        async def memory_search(ctx: RunContextWrapper[Any], query: str) -> str:
            """Args:
            query: What to look up, in plain language.
            """
            user = self.user(ctx.context)
            try:
                found = await user.search(query[-shared.MAX_QUERY :], fast=self.fast)
            except NotFoundError:
                return shared.NOTHING_FOUND
            return shared.found_text(found, self.max_chars)

        @tool(shared.OPEN_DESCRIPTION)
        async def memory_open(ctx: RunContextWrapper[Any], ref: str) -> str:
            """Args:
            ref: A ref memory_search gave.
            """
            return shared.opened_text(await self.user(ctx.context).open(ref))

        @tool(shared.ADD_DESCRIPTION)
        async def memory_add(ctx: RunContextWrapper[Any], text: str) -> str:
            """Args:
            text: One plain sentence.
            """
            session = shared.field_of(ctx.context, "session_id")
            user = self.user(ctx.context)
            saved = await user.add(text, kind="note", session=str(session) if session else None)
            return shared.UNAVAILABLE if saved.failed else shared.SAVED

        tools: list[Tool] = [memory_search, memory_open]
        return [*tools, memory_add] if write else tools

    def _failed(self, ctx: RunContextWrapper[Any], error: Exception) -> str:
        """What the model is told when a tool fails: memory is down, nothing is held, or what
        was wrong with what it asked. A wrong key, a run with no user, or an outage under
        `strict` raises: those are yours to fix."""
        yours = isinstance(error, (AuthenticationError, PermissionDeniedError))
        if yours or not shared.field_of(ctx.context, "user_id"):
            raise error
        if isinstance(error, AlexeinError):
            return shared.told(error, self.strict)
        return f"That did not work: {error}"


_default = AlexeinMemory()
recall = _default.recall
remember = _default.remember


def memory_tools(write: bool = False) -> list[Tool]:
    """The default memory's tools: `memory_search`, `memory_open`, and `memory_add` with
    `write`."""
    return _default.tools(write=write)
