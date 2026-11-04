"""Long-term memory for a LangGraph graph: `pip install "alexein[langgraph]"`.

```python
from alexein.langgraph import AlexeinMemory, MemoryContext, MemoryState

memory = AlexeinMemory()
builder = StateGraph(MemoryState, context_schema=MemoryContext)
builder.add_node("recall", memory.recall)      # what memory holds for the latest message
builder.add_node("agent", agent)               # put memory.prompt(state) in its system prompt
builder.add_node("remember", memory.remember)  # save the turn
builder.add_edge(START, "recall")
builder.add_edge("recall", "agent")
builder.add_edge("agent", "remember")

graph.invoke(inputs, config={"configurable": {"thread_id": "t-1"}}, context={"user_id": "dana"})
```

Or tools the model calls when it decides to: `create_agent(model, tools=memory.tools())`.

Whose memory is read is decided by your code, never by the model: the user id comes from the
run's `context` (`{"user_id": ...}`, or any object with a `user_id`); a tool also takes
`config["configurable"]["user_id"]`. The thread id is the session what is saved belongs to.

The nodes run under `invoke` and `ainvoke` alike; `arecall` and `aremember` are their async
counterparts, for an `AsyncMemory`. `recall`, `remember`, `memory_prompt` and `memory_tools` at
module level use one `AlexeinMemory()` for the process, which reads ALEXEIN_API_KEY on first use.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from typing import Any, TypedDict

from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.graph import MessagesState  # pyright: ignore[reportMissingTypeStubs]
from langgraph.runtime import Runtime
from typing_extensions import NotRequired

from alexein import _integration as shared
from alexein._async_user import AsyncUser
from alexein._client import AsyncMemory, Memory
from alexein._errors import AlexeinError, NotFoundError
from alexein._memories import SearchResult
from alexein._types import Item
from alexein._user import User

__all__ = [
    "AlexeinMemory",
    "MemoryContext",
    "MemoryState",
    "arecall",
    "aremember",
    "memory_prompt",
    "memory_tools",
    "recall",
    "remember",
]

# What a node or a tool asks of a user's memory (`User` or `AsyncUser`), and makes of the answer.
Ask = Callable[[Any], Any]
Show = Callable[[Any], str]


class MemoryState(MessagesState):
    """Your graph's state with room for what `recall` found. Subclass it, or add a
    `memory: NotRequired[str]` key to a state of your own."""

    memory: NotRequired[str]


class MemoryContext(TypedDict):
    """Whose memory a run reads. Pass it as `context_schema=`, or add `user_id: str` to a
    context schema you already have."""

    user_id: str


def _user_id(context: Any, config: RunnableConfig | None) -> str:
    found = shared.field_of(context, "user_id")
    if not found and config:
        found = (config.get("configurable") or {}).get("user_id")
    if not found:
        raise shared.missing_user(
            'run the graph with context={"user_id": "..."}, or '
            'config={"configurable": {"user_id": "..."}}'
        )
    return str(found)


def _run_thread(runtime: Runtime[Any]) -> str | None:
    """The thread a node runs in, as LangGraph's runtime says it: the nodes take LangGraph's
    typed `(state, *, runtime)` shape, which carries the run's context and its thread, and no
    config."""
    found = getattr(getattr(runtime, "execution_info", None), "thread_id", None)
    return str(found) if found else None


def _thread(config: RunnableConfig | None) -> str | None:
    found = ((config or {}).get("configurable") or {}).get("thread_id")
    return str(found) if found else None


def _last_human(messages: list[AnyMessage]) -> int:
    return next(
        (n for n in reversed(range(len(messages))) if isinstance(messages[n], HumanMessage)), -1
    )


def _asked(messages: list[AnyMessage]) -> str:
    """The user's latest message, or "" when there is none."""
    at = _last_human(messages)
    return messages[at].text.strip() if at >= 0 else ""


def _turn(messages: list[AnyMessage], thread: str | None) -> list[Item]:
    """The user's latest message and the last final reply after it, as items. Tool calls and
    tool results are not saved."""
    at = _last_human(messages)
    replies = [m for m in messages[at + 1 :] if isinstance(m, AIMessage) and not m.tool_calls]
    said = [(messages[at], "user")] if at >= 0 else []
    said += [(replies[-1], "assistant")] if replies else []
    return [_item(m, role, thread) for m, role in said if m.text.strip()]


def _item(message: AnyMessage, role: str, thread: str | None) -> Item:
    """Kept under the message's own id, so running a turn again edits what was saved."""
    said = f"{thread}|{role}|{message.text}"
    return Item(
        id=message.id or hashlib.sha256(said.encode()).hexdigest()[:24],
        role=role,
        text=message.text,
    )


class AlexeinMemory:
    """Memory for a graph: `recall` and `remember` nodes, `prompt(state)` for your model, and
    `tools()` for it to call.

    `client` is a `Memory`, or an `AsyncMemory` for the async nodes; without one, each is made
    on first use, failing open, with a 10 s timeout. `fast` answers sooner and free, a little
    less precisely. `max_chars` bounds what goes into a prompt. `strict` raises when memory is
    down, where by default a turn goes on without it. A wrong key raises either way."""

    def __init__(
        self,
        client: Memory | AsyncMemory | None = None,
        *,
        fast: bool = False,
        max_chars: int = 4000,
        strict: bool = False,
    ) -> None:
        self.fast = fast
        self.max_chars = max_chars
        self.strict = strict
        self._sync = client if isinstance(client, Memory) else None
        self._async = client if isinstance(client, AsyncMemory) else None
        self._tools: dict[bool, list[BaseTool]] = {}

    def user(self, context: Any, config: RunnableConfig | None = None) -> User:
        """The app user a run is for, from its context or config."""
        user_id = _user_id(context, config)  # first: a run with no user says so
        if self._sync is None:
            if self._async is not None:
                raise TypeError(
                    "this AlexeinMemory holds an AsyncMemory: add arecall and aremember as "
                    "nodes and run the graph with ainvoke, or give it a Memory"
                )
            self._sync = shared.made("langgraph", self.strict)
        return self._sync.user(user_id)

    def auser(self, context: Any, config: RunnableConfig | None = None) -> AsyncUser:
        """`user`, for an `AsyncMemory`."""
        user_id = _user_id(context, config)
        if self._async is None:
            self._async = shared.made_async("langgraph", self.strict)
        return self._async.user(user_id)

    # ------------------------------------------------------------------------ nodes --

    def recall(self, state: MemoryState, *, runtime: Runtime[Any]) -> dict[str, Any]:
        """Node: what memory holds for the user's latest message, into `state["memory"]`."""
        asked = _asked(state["messages"])
        if not asked:
            return {"memory": ""}
        found = self._node(runtime, self._search(asked))
        return {"memory": self._context(found)}

    async def arecall(self, state: MemoryState, *, runtime: Runtime[Any]) -> dict[str, Any]:
        """`recall`, as an async node."""
        if self._sync is not None:
            return await asyncio.to_thread(lambda: self.recall(state, runtime=runtime))
        asked = _asked(state["messages"])
        if not asked:
            return {"memory": ""}
        found = await self._anode(runtime, self._search(asked))
        return {"memory": self._context(found)}

    def remember(self, state: MemoryState, *, runtime: Runtime[Any]) -> dict[str, Any]:
        """Node: save this turn - the user's latest message and the final reply to it - under
        each message's id, so a turn run again edits rather than duplicates. Tool calls and
        tool results are not saved. Needs a key that writes."""
        thread = _run_thread(runtime)
        if items := _turn(state["messages"], thread):
            self._node(runtime, lambda user: user.add(items, session=thread))
        return {}

    async def aremember(self, state: MemoryState, *, runtime: Runtime[Any]) -> dict[str, Any]:
        """`remember`, as an async node."""
        if self._sync is not None:
            return await asyncio.to_thread(lambda: self.remember(state, runtime=runtime))
        thread = _run_thread(runtime)
        if items := _turn(state["messages"], thread):
            await self._anode(runtime, lambda user: user.add(items, session=thread))
        return {}

    def prompt(self, state: MemoryState | dict[str, Any]) -> str:
        """What `recall` found, as a block for your system prompt; "" when it found nothing."""
        return shared.prompt(state.get("memory") or "")

    def _search(self, query: str) -> Ask:
        return lambda user: user.search(query[-shared.MAX_QUERY :], fast=self.fast)

    def _context(self, found: SearchResult | None) -> str:
        return found.context(self.max_chars) if found is not None else ""

    def _node(self, runtime: Runtime[Any], ask: Ask) -> Any:
        user = self.user(runtime.context)
        try:
            return ask(user)
        except NotFoundError:  # nothing saved for this user yet
            return None
        except AlexeinError as error:
            shared.ride_out(error, self.strict)
            return None

    async def _anode(self, runtime: Runtime[Any], ask: Ask) -> Any:
        user = self.auser(runtime.context)
        try:
            return await ask(user)
        except NotFoundError:
            return None
        except AlexeinError as error:
            shared.ride_out(error, self.strict)
            return None

    # ------------------------------------------------------------------------ tools --

    def tools(self, write: bool = False) -> list[BaseTool]:
        """`memory_search` and `memory_open` for a model to call, and `memory_add` with `write`.
        The user comes from the run, never from the model; each runs under invoke and ainvoke."""
        if write not in self._tools:
            self._tools[write] = self._made_tools(write)
        return self._tools[write]

    def _tool(self, runtime: ToolRuntime[Any, Any], ask: Ask, show: Show) -> str:
        user = self.user(runtime.context, runtime.config)
        try:
            return show(ask(user))
        except AlexeinError as error:
            return shared.told(error, self.strict)

    async def _atool(self, runtime: ToolRuntime[Any, Any], ask: Ask, show: Show) -> str:
        if self._sync is not None:
            return await asyncio.to_thread(self._tool, runtime, ask, show)
        user = self.auser(runtime.context, runtime.config)
        try:
            return show(await ask(user))
        except AlexeinError as error:
            return shared.told(error, self.strict)

    def _made_tools(self, write: bool) -> list[BaseTool]:
        # `runtime` is filled in by LangGraph and never shown to the model.
        def found(answer: SearchResult) -> str:
            return shared.found_text(answer, self.max_chars)

        def search(query: str, runtime: ToolRuntime[Any, Any]) -> str:
            return self._tool(runtime, self._search(query), found)

        async def asearch(query: str, runtime: ToolRuntime[Any, Any]) -> str:
            return await self._atool(runtime, self._search(query), found)

        def open_(ref: str, runtime: ToolRuntime[Any, Any]) -> str:
            return self._tool(runtime, lambda user: user.open(ref), shared.opened_text)

        async def aopen(ref: str, runtime: ToolRuntime[Any, Any]) -> str:
            return await self._atool(runtime, lambda user: user.open(ref), shared.opened_text)

        def note(text: str, runtime: ToolRuntime[Any, Any]) -> Ask:
            session = _thread(runtime.config)
            return lambda user: user.add(text, kind="note", session=session)

        def saved(answer: Any) -> str:
            return shared.UNAVAILABLE if answer.failed else shared.SAVED

        def add(text: str, runtime: ToolRuntime[Any, Any]) -> str:
            return self._tool(runtime, note(text, runtime), saved)

        async def aadd(text: str, runtime: ToolRuntime[Any, Any]) -> str:
            return await self._atool(runtime, note(text, runtime), saved)

        def made(name: str, description: str, func: Any, coroutine: Any) -> BaseTool:
            return StructuredTool.from_function(
                func=func, coroutine=coroutine, name=name, description=description
            )

        tools = [
            made("memory_search", shared.SEARCH_DESCRIPTION, search, asearch),
            made("memory_open", shared.OPEN_DESCRIPTION, open_, aopen),
        ]
        if write:
            tools.append(made("memory_add", shared.ADD_DESCRIPTION, add, aadd))
        return tools


_default = AlexeinMemory()
recall = _default.recall
arecall = _default.arecall
remember = _default.remember
aremember = _default.aremember
memory_prompt = _default.prompt


def memory_tools(write: bool = False) -> list[BaseTool]:
    """The default memory's tools: `memory_search`, `memory_open`, and `memory_add` with
    `write`."""
    return _default.tools(write=write)
