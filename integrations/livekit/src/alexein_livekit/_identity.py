"""Whose memory a call reads and writes: an app user id taken from the participant, or from job
metadata your backend wrote, never from anything said in the call.

Not authentication. A participant's identity is set by your token server and a job's metadata by
whoever dispatched it, so each is exactly as trustworthy as that. LiveKit only asks an identity to
be unique within its room: a token server that names every caller "guest", or takes the identity
from the client's request, puts every caller in one memory, or lets one pick another's. So a
participant's memory is its own namespace, `lk-` and a hash, which no id your backend writes can
meet, unless you say they share (`share_identity`); your own user id, bound or in job metadata, is
the way to one memory across your apps. A phone caller's identity (SIP, or a connector such as
WhatsApp) is a number the caller can spoof, and is not used unless you say so.
"""

from __future__ import annotations

import hashlib
import json
import re

from livekit import rtc

# Alexein's app user ids (the `X-Alexein-User` header), as the client checks them before it sends
# one: 1 to 35 letters, digits, `.`, `_` and `-`, starting with a letter or digit. One of your own
# that passes is used as it is, the same memory your backend writes to; any other is hashed.
_USABLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,34}")
# What this module makes: an identity that already looks like one is hashed again, so nobody can
# pick an identity that lands in somebody else's memory.
_MADE = re.compile(r"lk-[0-9a-f]{24}")
_PHONE = (rtc.ParticipantKind.PARTICIPANT_KIND_SIP, rtc.ParticipantKind.PARTICIPANT_KIND_CONNECTOR)


def app_user_id(identity: str) -> str:
    """`identity` as an app user id: itself when it passes the client's id check (`_USABLE`: 35
    characters at most), else `lk-` and a hash of it (27 characters), which names nobody's number
    or address and that no other identity maps to."""
    if not identity:
        raise ValueError("an empty identity names nobody")
    if _USABLE.fullmatch(identity) and not _MADE.fullmatch(identity):
        return identity
    return participant_id(identity)


def participant_id(identity: str) -> str:
    """The app user id a LiveKit `identity` is given: `lk-` and a hash of it, in a namespace no id
    your backend writes can meet. Your backend can call this too, to reach the same memory."""
    if not identity:
        raise ValueError("an empty identity names nobody")
    return "lk-" + hashlib.sha256(identity.encode()).hexdigest()[:24]


def from_participant(
    participant: rtc.Participant, *, trust_phone: bool = False, share_identity: bool = False
) -> str | None:
    """The app user id for the person behind `participant`: `participant_id`, or with
    `share_identity` the identity itself where it is a usable id (`app_user_id`), so it is the
    memory your backend writes to under that id. None for a phone caller unless `trust_phone`,
    and for anything that is not a person (an agent, an ingress, a bridge)."""
    if participant.kind in _PHONE and not trust_phone:
        return None
    if participant.kind not in (*_PHONE, rtc.ParticipantKind.PARTICIPANT_KIND_STANDARD):
        return None
    identity = participant.identity
    return app_user_id(identity) if share_identity else participant_id(identity)


def from_metadata(metadata: str, key: str) -> str | None:
    """The user id that job metadata holding a JSON object names under `key`; None for metadata
    that is empty, not JSON, or has no such key."""
    try:
        data: object = json.loads(metadata) if metadata else None
    except ValueError:
        return None
    found = data.get(key) if isinstance(data, dict) else None
    if not isinstance(found, str) or not found:
        return None
    # Your backend wrote it, so an id it already holds - one this module made included - is kept.
    return found if _USABLE.fullmatch(found) else app_user_id(found)
