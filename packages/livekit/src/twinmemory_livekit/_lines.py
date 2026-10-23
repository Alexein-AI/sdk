"""What earlier conversations said, line by line: the passages a search found, cut back into the
turns they hold, so a reply is shown what the caller said and not whole conversations.

A passage is one stretch of a conversation, "**user** 11:25 · ..." after a "Context: ..., 23 Oct
2026. ..." header (the engine's `passages.turn`). Kept: each distinct thing said once, the agent's
words marked as its own ("you said"), a short reply with the question it answers ("the second
one"), and statements ahead of questions - a question asked before is no answer to the one asked
now: measured over 26 questions at 2,000 characters, 24 held the answer this way, 17 without.
Not a summary: every line is said as it was said, or left out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from twinmemory import Hit

_TURN = re.compile(r"\*\*([^*]{1,64})\*\* ((?:\d{1,2} \w{3} \d{4} )?\d{1,2}:\d{2}) · ")
_DAY = re.compile(r"^Context: [^,]*, (\d{1,2} \w{3} \d{4})")
# A note's or a document's header: where and when, then its title, which repeats its first words.
_HEADER = re.compile(r"^Context: [^,]*, \d{1,2} \w{3} \d{4}\. ")
_ASKED_CHARS = 200
_AGENT = "assistant"
_SHORT = 4
_WORDS = re.compile(r"[a-z0-9']+")
_SMALL_TALK = frozenset(
    {"hi", "hello", "hey", "thanks", "thank", "you", "ok", "okay", "bye", "goodbye", "cheers"}
    | {"hmm", "um", "uh", "mhm", "right", "cool", "great", "yes", "no", "yeah", "sure"}
)


@dataclass(frozen=True)
class Line:
    text: str
    rank: int
    asked: bool


def _turns(text: str) -> list[tuple[str, str, str]]:
    """(speaker, time, words) for each turn in a passage; one unnamed turn for a note."""
    marks = list(_TURN.finditer(text))
    if not marks:
        body = _untitled(_HEADER.sub("", text, count=1).strip())
        return [("", "", body)] if body else []
    turns: list[tuple[str, str, str]] = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        turns.append((mark.group(1), mark.group(2), text[mark.end() : end].strip()))
    return turns


def _untitled(body: str) -> str:
    """A note's text without the title in front of it that only repeats its opening words."""
    for at in (m.start() for m in re.finditer(r"\. ", body)):
        title, rest = body[:at], body[at + 2 :]
        if _key(rest).startswith(_key(title)):
            return rest
    return body


def _key(text: str) -> str:
    return " ".join(_WORDS.findall(text.lower()))


def _lines(hit: Hit, rank: int, agent: bool, skip_small_talk: bool = True) -> list[Line]:
    day = (m.group(1) + " ") if (m := _DAY.match(hit.text)) else ""
    turns = _turns(" ".join(hit.text.split()))
    out: list[Line] = []
    small_talk = False  # the caller's last words were only that, so the answer to them is too
    for i, (speaker, time, words) in enumerate(turns):
        said_by_agent = speaker == _AGENT
        if not words or (said_by_agent and (not agent or small_talk)):
            continue
        when = f"{day}{time}".strip() if len(time) <= 5 else time
        who = "you said" if said_by_agent else "noted" if not speaker else "they said"
        line = f"{when}, {who}: {words}" if when else words
        before = turns[i - 1] if i else None
        answering = before is not None and before[0] == _AGENT and before[2].endswith("?")
        if not said_by_agent and answering and len(words.split()) < _SHORT:
            assert before is not None
            line = f"{when}, you asked “{before[2][-_ASKED_CHARS:]}”, they said: {words}"
        elif (
            skip_small_talk
            and not said_by_agent
            and set(_WORDS.findall(words.lower())) <= _SMALL_TALK
        ):
            small_talk = True
            continue
        if not said_by_agent:
            small_talk = False
        out.append(Line(line, rank, words.rstrip().endswith("?")))
    return out


def said(
    known: list[str],
    hits: list[Hit],
    query: str,
    *,
    agent: bool,
    max_chars: int,
    skip_small_talk: bool = True,
) -> list[str]:
    """What is known, then the lines of `hits` that tell something, best first, as many as fit
    in `max_chars`: each distinct thing said once, a question asked before after every
    statement, and the question being asked now not at all."""
    seen = {_key(query)}
    lines: list[Line] = []
    for rank, hit in enumerate(hits):
        for line in _lines(hit, rank, agent, skip_small_talk):
            key = _key(line.text.split(": ", 1)[-1])
            if key and key not in seen:
                seen.add(key)
                lines.append(line)
    lines.sort(key=lambda line: (line.asked, line.rank))
    out = [" ".join(k.split()) for k in known]
    used = sum(len(line) + 3 for line in out)
    for line in lines:
        if used + len(line.text) + 3 <= max_chars:
            out.append(line.text)
            used += len(line.text) + 3
    return out
