"""What decides whether a model call is given memory, and what it may see: a turn worth looking
up, the memories that bear on it, text that cannot pass for markup, and a query with no secret in
it. Imports nothing but the standard library. `@alexein/sdk`'s `wrap/gate.ts` is the same."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Words a go-ahead, a thank-you or a greeting is made of. A message of these alone (and perhaps
# one name: "Thanks Claude!") asks nothing memory could answer.
ACK_WORDS = frozenset(
    """
    thanks thank thx ty you so much very many ok okay kk yes yeah yep yup no nope nah sure great
    cool nice perfect perfectly awesome good fine lgtm works worked working got it sounds sound
    looks look please do go ahead continue proceed done alright right wonderful excellent amazing
    brilliant appreciated appreciate cheers hi hello hey bye goodbye that this thats all for now
    then will lol haha the and just really too again also well indeed exactly correct agreed
    agree understood makes sense love is was that's
    """.split()  # noqa: SIM905 - a word list reads better as words
)
# The words such a message opens with, when it adds one name of its own ("Thanks Claude").
ACK_OPENERS = frozenset(
    """
    thanks thank thx ty ok okay kk yes yeah yep yup no nope nah sure great cool nice perfect
    awesome good fine lgtm sounds looks got hi hello hey cheers lol haha alright
    """.split()  # noqa: SIM905 - a word list reads better as words
)
_WORDS = re.compile(r"[a-z]+")


def worth_recall(said: str) -> bool:
    """Whether the user's message is worth a lookup: anything but a slash command, and a message
    that is only a go-ahead, a thank-you or a greeting ("thanks!", "ok, do it", "sounds good",
    "Thanks Claude, that worked perfectly", "👍"). A question always is, and so is anything
    about the user ("What do you know about me?")."""
    said = said.strip()
    if not said or said.startswith("/"):
        return False
    if "?" in said:
        return True
    words = _WORDS.findall(said.lower())
    extra = [w for w in words if len(w) > 1 and w not in ACK_WORDS]
    if not extra:
        return False
    return not (len(extra) == 1 and words[0] in ACK_OPENERS)


def mark(memory: Any, raw: dict[str, Any]) -> str:
    """What a memory is known by, so it is shown once in a session: its ref, else its words."""
    ref = raw.get("ref") or getattr(memory, "ref", None)
    return str(ref) if ref else " ".join(str(getattr(memory, "text", "")).split())[:200]


def relevant(
    memories: list[tuple[Any, dict[str, Any]]], shown: set[str] | frozenset[str]
) -> list[tuple[Any, dict[str, Any]]]:
    """Of a search's memories, in the order memory ranked them, those to show: the lines the API
    lists after the excerpts - the rest of what it holds, which bore on nothing asked - left out,
    and none shown before in this session."""
    kept: list[tuple[Any, dict[str, Any]]] = []
    past = False
    for memory, raw in memories:
        kind = raw.get("type") or getattr(memory, "type", None)
        if kind == "excerpt":
            past = True
        elif past:
            continue
        if mark(memory, raw) not in shown:
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
