"""Whose memory a call reads and writes: an end user id taken from the participant, or from job
metadata your backend wrote, never from anything said in the call.

Not authentication. A participant's identity is set by your token server and a job's metadata by
whoever dispatched it, so each is exactly as trustworthy as that. A phone caller's identity
(SIP, or a connector such as WhatsApp) is a number the caller can spoof, and is not used unless you
say so.
"""

from __future__ import annotations

import hashlib
import json
import re

from livekit import rtc

# twin memory's end user ids (the `X-Twin-Account` header). The service caps the whole account
# name, `<org>.<project>.<id>`, at 64 characters, so an id made here stays well under that.
_USABLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}")
# What this module makes: an identity that already looks like one is hashed again, so nobody can
# pick an identity that lands in somebody else's memory.
_MADE = re.compile(r"lk-[0-9a-f]{24}")
_PHONE = (rtc.ParticipantKind.PARTICIPANT_KIND_SIP, rtc.ParticipantKind.PARTICIPANT_KIND_CONNECTOR)


def account_id(identity: str) -> str:
    """`identity` as an end user id: itself when it is short and plain, else `lk-` and a hash of
    it, which names nobody's number or address and that no other identity maps to."""
    if not identity:
        raise ValueError("an empty identity names nobody")
    if _USABLE.fullmatch(identity) and not _MADE.fullmatch(identity):
        return identity
    return "lk-" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def from_participant(participant: rtc.Participant, *, trust_phone: bool = False) -> str | None:
    """The end user id for the person behind `participant`; None for a phone caller unless
    `trust_phone`, and for anything that is not a person (an agent, an ingress, a bridge)."""
    if participant.kind in _PHONE:
        return account_id(participant.identity) if trust_phone else None
    if participant.kind != rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD:
        return None
    return account_id(participant.identity)


def from_metadata(metadata: str, key: str) -> str | None:
    """The user id that job metadata holding a JSON object names under `key`; None for metadata
    that is empty, not JSON, or has no such key."""
    try:
        data: object = json.loads(metadata) if metadata else None
    except ValueError:
        return None
    found = data.get(key) if isinstance(data, dict) else None
    return account_id(found) if isinstance(found, str) and found else None
