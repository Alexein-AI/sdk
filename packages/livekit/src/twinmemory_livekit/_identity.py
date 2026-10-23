"""Whose memory a call reads and writes: an end user id taken from the job's metadata or from the
participant, never from anything said in the call.

Not authentication. A participant's identity and a job's metadata are set by your token server and
your dispatch, so they are exactly as trustworthy as those. A SIP participant's identity is the
caller's phone number, which a caller can spoof, so it is refused unless you say otherwise.
"""

from __future__ import annotations

import hashlib
import json
import re

from livekit import rtc

# twin memory's end user ids (the `X-Twin-Account` header): what the client checks before sending.
_USABLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def account_id(identity: str) -> str:
    """`identity` as an end user id: itself when twin memory can use it as one, else a readable
    part of it and a hash of the whole. `dana@acme.dev` and `dana-acme.dev` stay two people, where
    replacing the characters alone would make them one."""
    if _USABLE.fullmatch(identity):
        return identity
    if not identity:
        raise ValueError("an empty identity names nobody")
    readable = _UNSAFE.sub("-", identity).strip("-._")[:40] or "lk"
    digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return f"{readable}-{digest}"


def from_participant(participant: rtc.Participant, *, trust_sip: bool = False) -> str:
    """The end user id for the person behind `participant`."""
    if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP and not trust_sip:
        raise ValueError(
            f"participant {participant.identity!r} joined by phone, and a phone number can be "
            "spoofed: look the caller up in your own records and bind(user_id=...), or pass "
            "trust_sip=True to use the number as the user id"
        )
    return account_id(participant.identity)


def from_metadata(metadata: str, key: str) -> str | None:
    """The user id that job metadata holding a JSON object names under `key`; None for metadata
    that is empty, not JSON, or has no such key."""
    try:
        data: object = json.loads(metadata) if metadata else None
    except ValueError:
        return None
    found = data.get(key) if isinstance(data, dict) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return account_id(found) if isinstance(found, str) and found else None
