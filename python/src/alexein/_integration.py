"""What the framework integrations share: the client each makes for itself, what a model is told,
and how a memory outage is ridden out. Imports no framework."""

from __future__ import annotations

import logging
from typing import Any

from alexein._client import AsyncMemory, Memory
from alexein._errors import AlexeinError, InvalidRequestError, NotFoundError
from alexein._memories import Excerpt, Known, Opened, SearchResult

log = logging.getLogger("alexein")

# Seconds a call to memory may take before a turn goes on without it.
TIMEOUT = 10.0
# The longest question memory takes, in characters. A longer one - a pasted email - is searched
# by its end, where its question usually is.
MAX_QUERY = 2000

UNAVAILABLE = "Memory is unavailable right now; carry on without it."
NOTHING_FOUND = "Nothing remembered about that."
NOTHING_YET = "Nothing has been remembered for this user yet."
NO_SUCH_REF = "Memory holds nothing by that ref; use one memory_search gave."
SAVED = "Saved."
# What goes before what memory found, in a prompt.
HEADING = (
    "What you remember about this user from earlier conversations. Use it where it helps; the "
    "conversation itself takes precedence where they differ.\n\n"
)

SEARCH_DESCRIPTION = (
    "Search what you remember about this user: what they said, did and decided in earlier "
    "conversations. Ask in plain language. Ends with the refs of what it found, to read whole "
    "with memory_open."
)
OPEN_DESCRIPTION = "Read one remembered memory whole, by a ref memory_search gave."
ADD_DESCRIPTION = (
    "Remember something about this user for later conversations: a preference, a fact about "
    "them, a decision. Write it as one plain sentence. Never save passwords, keys or secrets."
)


def made(integration: str, strict: bool, timeout: float = TIMEOUT) -> Memory:
    """The client an integration makes on first use, so importing it needs no key."""
    return Memory(fail_open=not strict, integration=integration, timeout=timeout)


def made_async(integration: str, strict: bool, timeout: float = TIMEOUT) -> AsyncMemory:
    return AsyncMemory(fail_open=not strict, integration=integration, timeout=timeout)


def field_of(context: Any, name: str) -> Any:
    """A field of a run's context: a dict's key, or any object's attribute."""
    if isinstance(context, dict):
        return context.get(name)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return getattr(context, name, None)


def ride_out(error: AlexeinError, strict: bool) -> None:
    """Raise `error` unless it is an outage and the integration is not strict; then log it."""
    if strict or not error.outage:
        raise error
    log.warning("Alexein unavailable: %s", error)


def prompt(found: str) -> str:
    """What recall found, as a block for a system prompt; empty when it found nothing."""
    return HEADING + found if found else ""


def found_text(found: SearchResult | None, max_chars: int) -> str:
    """What `memory_search` answers a model: the context, then the refs of what it holds."""
    if found is None:
        return NOTHING_FOUND
    if found.failed:
        return UNAVAILABLE
    text = found.context(max_chars)
    if not text:
        return NOTHING_FOUND
    refs = [m.ref for m in found.fitting(max_chars) if not isinstance(m, Known)]
    if refs:
        listed = "\n".join(f"- {ref}" for ref in dict.fromkeys(refs))
        text += f"\n\nTo read one whole, memory_open:\n{listed}"
    return text


def _dated(excerpt: Excerpt) -> str:
    return f"{excerpt.date[:10]}: {excerpt.text}" if excerpt.date else excerpt.text


def opened_text(opened: Opened) -> str:
    """What `memory_open` answers a model: the excerpt whole, or the fact and its sources."""
    if isinstance(opened.memory, Excerpt):
        return _dated(opened.memory)
    if not opened.sources:
        return opened.memory.text
    sources = "\n\n".join(_dated(s) for s in opened.sources)
    return f"{opened.memory.text}\n\nLearned from:\n\n{sources}"


def told(error: AlexeinError, strict: bool) -> str:
    """What a model is told when a read tool fails: memory is down, nothing is held, or what
    was wrong with what it asked, so it can carry on or try again. A wrong key, or an outage
    under `strict`, raises: those are the developer's to fix."""
    if isinstance(error, NotFoundError):
        return NO_SUCH_REF if "ref" in (error.detail or "") else NOTHING_YET
    if isinstance(error, InvalidRequestError):
        return f"That did not work: {error.detail or error}"
    ride_out(error, strict)
    return UNAVAILABLE


def missing_user(how: str) -> ValueError:
    return ValueError(f"Alexein needs to know whose memory this is: {how}")
