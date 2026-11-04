"""The memory tools a model calls when it decides to: `memory_search`, `memory_open` and, in tools
mode, `memory_add` - the names the hosted MCP server's tools and the client's integrations
(`alexein.langgraph`, `alexein.openai_agents`) have.

Every tool acts on the call's bound user, whom the model never names, and answers in words an
agent can say aloud when memory is down. An add waits briefly for the save, so the model is never
told "Saved." for a fact memory refused; one memory is too slow for is left to the call's writer,
which keeps trying.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from alexein import AlexeinError, Excerpt, InvalidRequestError, Item, NotFoundError, Opened
from livekit.agents import llm

from alexein_livekit._capture import saved_text
from alexein_livekit._lines import said

if TYPE_CHECKING:
    from alexein_livekit._memory import AlexeinMemory

NOT_SAVED = "I couldn't save that just now."
_OPEN_CHARS = 3000
UNAVAILABLE = "I couldn't reach my memory just now."
NOTHING = "Nothing remembered about that."
UNKNOWN = "I don't know who I'm talking to yet, so I have no memory to use."

# Said to the model in auto mode, after your instructions. Told nothing, gpt-4.1-mini searched on
# every statement a caller made in a real voice test, a model round trip of 1 to 1.5 s each, for
# what recall had put in front of it already.
AUTO_GUIDE = (
    "Before each reply you are given, as a quoted memory block, what you remember of this caller's "
    "earlier calls. Call memory_search only when they ask about something from before that is "
    "not in it - never to save or to check what they have just told you."
)

# Said to the model in tools mode, after your instructions: the tools are its only memory there,
# and a model that is not told when to save rarely does (n8n's Add tool says as much).
# Told the rules alone, a small model left out details and said "I've noted that" with nothing
# saved; the examples are what it follows.
GUIDE = (
    "You have a long-term memory of this caller, across calls; nothing you are told is kept "
    "unless you save it. Before you answer anything where what you know of them could matter - a "
    "suggestion, a recommendation, their plans, bookings or preferences, what was said before - "
    "call memory_search first. Whenever they tell you something new, call memory_add straight "
    "away, before you reply, without being asked and without saying so: one fact per call. "
    "Save facts about them and the details of what they ask for, even before it is confirmed. "
    "For example: 'Book a table for four on Friday at 8' -> memory_add('Asked to book a table "
    "for four, this Friday at 8pm'). 'My order number is A-7781, the blender is broken' -> "
    "memory_add('Order A-7781: the blender arrived broken, a refund asked for'). 'Lisbon or "
    "Porto? The second one' -> memory_add('Chose Porto for the May trip'). 'I just moved to "
    "Lisbon' -> memory_add('Lives in Lisbon now, moved from Berlin'). Saying you have noted "
    "something is not saving it: only memory_add saves. Never save passwords, card numbers or "
    "other secrets, nor anything they ask you not to keep, nor even that they asked - but do "
    "save the other facts said "
    "alongside one: 'My card is 4111 ..., and I like a window seat' -> memory_add('Prefers a "
    "window seat')."
)


_SEARCH = (
    "Search your long-term memory of this caller: what they said, did and decided in earlier "
    'calls. Ask in plain words, for example "where do they live". Ends with the refs of what it '
    "found, to read one whole with memory_open."
)
_SEARCH_FURTHER = (
    "Look further into your memory of this caller's earlier calls, when they ask about "
    "something from before that the memory block you were given does not hold. Ask in plain words. "
    "Ends with the refs of what it found, to read one whole with memory_open."
)


def tools(memory: AlexeinMemory, *, write: bool) -> list[llm.FunctionTool]:
    """`memory_search` and `memory_open`, and `memory_add` with `write`."""

    s = memory.settings

    async def memory_search(query: str) -> str:
        user = memory.user
        if user is None:
            return UNKNOWN
        # Earlier calls only, as recall, unless search_current_call: the model has this one.
        search = user.search(query[:1000], fast=s.tool_fast, **memory.where())
        try:
            found = await asyncio.wait_for(search, s.tool_timeout)
        except NotFoundError:
            return NOTHING
        except Exception:
            return UNAVAILABLE
        if found.failed:
            return UNAVAILABLE
        hits = [*found.excerpts, *memory.recent]  # the last calls too: they hold what goes unnamed
        lines = said(memory.known, hits, query, agent=True, max_chars=s.recall_max_chars)
        if not lines:
            return NOTHING
        refs = "\n".join(f"- {ref}" for ref in dict.fromkeys(h.ref for h in hits if h.ref))
        return "\n".join(f"- {line}" for line in lines) + (
            f"\n\nTo read one whole, memory_open:\n{refs}" * bool(refs)
        )

    @llm.function_tool
    async def memory_open(ref: str) -> str:
        """Read one remembered conversation or note whole, by a ref memory_search gave."""
        user = memory.user
        if user is None:
            return UNKNOWN
        try:
            found = await asyncio.wait_for(user.open(ref.strip()), s.tool_timeout)
        except (NotFoundError, InvalidRequestError):  # a ref memory never gave, or not a ref
            return NOTHING
        except Exception:
            return UNAVAILABLE
        return (opened_text(found) or NOTHING)[:_OPEN_CHARS]

    @llm.function_tool
    async def memory_add(text: str) -> str:
        """Save one new fact about this caller to your long-term memory, for later calls: a
        preference, a fact about them, a plan, a decision, a name, a date or a number. Call it
        on your own, without being asked, whenever they say something new; one fact per call,
        as one sentence in their words. Never save passwords, card numbers or other secrets."""
        user = memory.user
        if user is None:
            return UNKNOWN
        text = saved_text("user", " ".join(text.split()), s)[: s.note_max_chars]
        if not text:
            return "There was nothing to save."
        note = _note(text, memory.session_id, len(memory.noted))
        try:
            saved = await asyncio.wait_for(user.add([note]), s.save_timeout)
        except AlexeinError as error:
            if not error.outage:
                return NOT_SAVED  # refused: saying "Saved." would be a lie the caller hears
            saved = None
        except Exception:  # slow, or not the service's answer: the writer keeps trying
            saved = None
        if saved is None or saved.failed:
            memory.note(note)  # its id makes a second landing of the first attempt a no-op
        memory.noted.append(text)  # saved, or queued to be: never one memory refused
        return "Saved."

    search = llm.function_tool(memory_search, description=_SEARCH if write else _SEARCH_FURTHER)
    return [search, memory_open, memory_add] if write else [search, memory_open]


def opened_text(opened: Opened) -> str:
    """What `memory_open` answers: the excerpt whole, or the fact and the excerpts it was learned
    from. An excerpt's text says when it was said."""
    if isinstance(opened.memory, Excerpt) or not opened.sources:
        return opened.memory.text
    sources = "\n\n".join(e.text for e in opened.sources)
    return f"{opened.memory.text}\n\nLearned from:\n\n{sources}"


def _note(text: str, session: str, nth: int) -> Item:
    """A saved fact as a line the agent wrote in this call, at the time it wrote it, so facts from
    different calls are told apart by when, and a call's facts stay together. The same fact said
    twice in a call is one: its id is the call and the words. No author: the agent wrote it down,
    and an author marked `self` with no role is refused."""
    digest = hashlib.sha256(text.lower().encode()).hexdigest()[:16]
    return Item(
        id=f"lk:{session}:note:{digest}",
        kind="message",
        role="assistant",
        text=f"Noted: {text}",
        session=session,
        at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        metadata={"livekit": "memory_add", "fact": nth},
    )
