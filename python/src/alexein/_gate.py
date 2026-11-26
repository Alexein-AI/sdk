"""What decides whether a model call is given memory, and what it may see: a turn worth looking
up, the memories that bear on it, text that cannot pass for markup, and a query with no secret in
it. Imports nothing but the standard library. `@alexein/sdk`'s `wrap/gate.ts` is the same."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Words that say nothing about a topic: how questions and requests are asked, and code's own
# keywords. A topic is the rest (`terms`).
STOP = frozenset(
    """
    about above after again against all also always and another any anything are around because
    been before being below between both but can cannot could did does doing done down during
    each either else even ever every few for from further get gets getting give going gone got
    had has have having her here hers him his how however into its itself just keep know last
    least less let lets like likely look looks made make makes many may maybe might mine more
    most much must need needs never new next not now off once one only onto other others our
    ours out over own please put quite rather really right said same say says see seem seems set
    shall she should show since some something still such sure take than thank thanks that the
    their theirs them then there these they thing things think this those though through too
    try under until upon use used uses using very want wants was way well were what whatever
    when where whether which while who whom whose why will with within without would yes yet
    you your yours yourself okay hello hey hi
    const var function return import export class def self true false null none async await
    type interface string number int str bool void public private static elif while try catch
    except raise throw lambda yield pass break continue new this from
    """.split()  # noqa: SIM905 - a word list reads better as words
)
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_CAMEL = re.compile(r"([a-z0-9])([A-Z])")
# A go-ahead or a thank-you: no question to look up, unless it goes on to name a topic at length.
_ACK = re.compile(
    r"^\s*(?:yes|yeah|yep|no|nope|ok|okay|sure|thanks|thank you|great|cool|nice|perfect|go ahead"
    r"|continue|proceed|do it|sounds good|lgtm|looks good)\b",
    re.I,
)


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def terms(text: str) -> set[str]:
    """A text's topic words: lower case, camelCase split, short and common words left out, a
    plural or a tense cut back to its stem."""
    out: set[str] = set()
    for word in _WORD.findall(_CAMEL.sub(r"\1 \2", text or "")):
        word = word.lower()
        if len(word) >= 3 and word not in STOP:
            out.add(_stem(word))
    return out


def _matches(term: str, words: set[str]) -> bool:
    return term in words or (
        len(term) >= 5 and any(w[:5] == term[:5] for w in words if len(w) >= 5)
    )


def overlap(wanted: set[str], text: str) -> int:
    words = terms(text)
    return sum(1 for term in wanted if _matches(term, words))


def worth_recall(said: str) -> bool:
    """Whether the user's message is worth a lookup: it names a topic, and is not a go-ahead or a
    thank-you ("thanks!", "ok, do it", "sounds good") with few words of its own."""
    said = said.strip()
    if not said or said.startswith("/"):
        return False
    named = terms(said)
    if not named:
        return False
    return not (_ACK.match(said) and len(named) < 6)


def mark(memory: Any, raw: dict[str, Any]) -> str:
    """What a memory is known by, so it is shown once in a session: its ref, else its words."""
    ref = raw.get("ref") or getattr(memory, "ref", None)
    return str(ref) if ref else " ".join(str(getattr(memory, "text", "")).split())[:200]


def relevant(
    memories: list[tuple[Any, dict[str, Any]]], query: str, shown: set[str] | frozenset[str]
) -> list[tuple[Any, dict[str, Any]]]:
    """Of a search's memories, in order, those that bear on `query`: the lines the API lists after
    the excerpts - the rest of what it holds, which bore on nothing asked - left out; of the rest,
    those sharing a topic word with the query (two for a query of more than three), and not shown
    before in this session."""
    wanted = terms(query)
    if not wanted:
        return []
    need = 1 if len(wanted) <= 3 else 2
    kept: list[tuple[Any, dict[str, Any]]] = []
    past = False
    for memory, raw in memories:
        kind = raw.get("type") or getattr(memory, "type", None)
        if kind == "excerpt":
            past = True
        elif past:
            continue
        if mark(memory, raw) in shown:
            continue
        if overlap(wanted, str(getattr(memory, "text", ""))) >= need:
            kept.append((memory, raw))
    return kept


# Every character a model may read as an angle bracket - the ASCII ones, their fullwidth, small,
# vertical, mathematical, ornamental and quotation-mark forms - made a parenthesis, which no tag
# is written with; and the ampersand that starts an entity. Format characters (zero-width,
# bidi, tag characters) are dropped, and every other control or line break is a space.
_OPENS = (
    "\u003c\u00ab\u2039\u02c2\u1438\u2329\u27e8\u27ea\u276c\u276e\u2770\u2991\u29fc"
    "\u3008\u300a\ufe3d\ufe3f\ufe64\uff1c\u226a"
)
_CLOSES = (
    "\u003e\u00bb\u203a\u02c3\u1433\u232a\u27e9\u27eb\u276d\u276f\u2771\u2992\u29fd"
    "\u3009\u300b\ufe3e\ufe40\ufe65\uff1e\u226b"
)
_MARKUP = str.maketrans({c: "(" for c in _OPENS} | {c: ")" for c in _CLOSES} | {"&": "+"})


def inert(text: str) -> str:
    """`text` on one line, as it cannot be read as markup or hide anything unseen."""
    kept = "".join(
        " " if unicodedata.category(c) == "Cc" else c
        for c in text
        if unicodedata.category(c) != "Cf"
    )
    return " ".join(kept.translate(_MARKUP).split())


# Secrets, by their shape: never sent as a search. Simple patterns, as a backstop.
_SECRET = "[secret]"
_SECRETS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
            re.S,
        ),
        _SECRET,
    ),
    (
        re.compile(
            r"\b(?:sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{16,}"
            r"|tm_[A-Za-z0-9_\-]{12,}"
            r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
            r"|glpat-[A-Za-z0-9_\-]{16,}"
            r"|xox[abposr]-[A-Za-z0-9\-]{10,}"
            r"|(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"
            r"|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}"
            r"|AIza[0-9A-Za-z_\-]{30,}"
            r"|npm_[A-Za-z0-9]{30,}"
            r"|pypi-[A-Za-z0-9_\-]{40,}"
            r"|hf_[A-Za-z0-9]{30,})"
        ),
        _SECRET,
    ),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), _SECRET),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=\-]{12,}"), r"\1 " + _SECRET),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):[^\s@/]+@"), r"\1:" + _SECRET + "@"),
    (
        re.compile(
            r"(?i)([\"']?[A-Za-z0-9_\-]*(?:passw(?:or)?d|passwd|pwd|secret|token|api[_\-]?key"
            r"|access[_\-]?key|private[_\-]?key|credential|auth[_\-]?key)[A-Za-z0-9_\-]*[\"']?"
            r"\s*[:=]\s*)(\"[^\"\n]*\"|'[^'\n]*'|[^\s,;\"'}{)]+)"
        ),
        r"\1" + _SECRET,
    ),
]
# A run of digits as people write one: groups split by single spaces, dashes or dots.
_DIGITS = re.compile(r"(?<![\w])\+?\d(?:[ .\-]?\d){6,}(?![\w])")


def _luhn(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def _number(found: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", found.group())
    if 13 <= len(digits) <= 19 and _luhn(digits):
        return "[card number]"
    # Nine digits at least, or a leading +: a date (2026-10-01) has eight.
    if len(digits) <= 15 and (len(digits) >= 9 or found.group().startswith("+")):
        return "[phone number]"
    return found.group()


def query_text(text: str, redact: bool) -> str:
    """A search query with no key, token or password in it; with `redact`, no card or phone
    number either."""
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return _DIGITS.sub(_number, text) if redact else text
