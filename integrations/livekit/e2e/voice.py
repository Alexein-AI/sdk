"""alexein-livekit by voice: real speech into a real LiveKit room, a real agent (OpenAI STT, LLM
and TTS, Silero VAD) answering aloud, and its answer checked by transcribing the audio it spoke.

    cd integrations/livekit && uv run --with "livekit-plugins-openai~=1.8" \
        --with "livekit-plugins-silero~=1.8" python e2e/voice.py            # exit 0 = all held

Needs what e2e/room.py needs (the LiveKit dev server, the Alexein API and a key that writes, which
also deletes the app users the run made), plus OPENAI_API_KEY or OPENROUTER_API_KEY (from the
environment, or $VOICE_ENV, by default the .livekit-test.env beside the repositories; OpenAI when
both are set), and macOS `say` and `afconvert` for the caller's voice. Keys are never printed.

The caller is a participant with a microphone track that sends 10 ms frames at real-time pace for
the whole call, silence between utterances, as a real microphone does; each utterance is `say`
output, then the driver waits for the agent to answer and fall quiet. The agent's audio track is
recorded; each answer is cut from it, written to a WAV and transcribed, and that is what is checked.
`lk.transcription` is read too, as a second signal.

  auto:     call 1, a new user, says a locker code and one more line, hangs up; the driver polls
            memory until the code is searchable; call 2 asks for it. The spoken answer must hold
            4417, and the worker must show the recall and a <memory> block in the model's context.
            Then a baseline call with memory off (a plain Agent) says the same lines, for latency.
  tools:    a new user; call 1 asks the agent to remember a colour (memory_add must be called),
            call 2 asks for it (memory_search must be called, and the answer must say teal).
Every turn reports the time from the end of the caller's audio to the agent's first audible frame.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
import wave
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from alexein import AsyncMemory, NotFoundError
from livekit import api, rtc
from room import Events, read_env  # e2e/room.py, beside this file

from alexein_livekit import participant_id

warnings.filterwarnings("ignore", message="The HMAC key")  # the 6-byte dev secret
HERE = Path(__file__).resolve().parent
LK_URL = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
LK_KEY = os.environ.get("LIVEKIT_API_KEY", "devkey")
LK_SECRET = os.environ.get("LIVEKIT_API_SECRET", "secret")
AGENT_NAME = "alexein-voice-e2e"
ENV_FILE = os.environ.get("E2E_ENV", "")
VOICE_ENV = os.environ.get("VOICE_ENV", str(HERE.parents[3] / ".livekit-test.env"))
# Each model through LiveKit's OpenAI plugin; OpenRouter is OpenAI-compatible at its base URL.
# OpenAI is used when both keys are there. VOICE_LLM, VOICE_STT, VOICE_TTS (or "say") and
# VOICE_JUDGE_STT override a model; VOICE_PROVIDER picks the provider.
PROVIDERS: dict[str, dict[str, str]] = {
    "openai": {
        "key": "OPENAI_API_KEY", "base_url": "https://api.openai.com/v1",
        "llm": "gpt-4.1-mini", "stt": "gpt-4o-mini-transcribe", "tts": "gpt-4o-mini-tts",
        "judge": "gpt-4o-transcribe",
    },
    "openrouter": {
        "key": "OPENROUTER_API_KEY", "base_url": "https://openrouter.ai/api/v1",
        # OpenRouter serves no OpenAI TTS model (openai/gpt-4o-mini-tts "does not exist", and
        # its Voxtral TTS answered 404 on 2026-10-23), so the agent speaks with macOS `say`
        "llm": "openai/gpt-4.1-mini", "stt": "openai/gpt-4o-mini-transcribe", "tts": "say",
        "judge": "openai/gpt-4o-transcribe",
    },
}  # fmt: skip
RATE = 24000
FRAME = RATE // 100  # 10 ms
AUDIBLE = 300  # peak, of 32767: about -40 dBFS, above the codec's comfort noise
QUIET_S = 1.5  # an answer is over once the agent has been listening this long

FACT = "Hi, my locker code at the Alfama gym is four four one seven."
FACT2 = "I usually train there on Tuesday evenings."
QUESTION = "What is my locker code at the gym?"
REMEMBER = "Please remember that my favourite colour is teal."
ASK_COLOUR = "What is my favourite colour?"

FAILURES: list[str] = []


def _quiet(hook: Any) -> Any:
    """livekit.rtc's FfiHandle.__del__ asserts, harmlessly, for every handle collected after its
    room has gone; a long run prints hundreds of them. Every other unraisable error still shows."""

    def unraisable(u: Any) -> None:
        if not (isinstance(u.exc_value, AssertionError) and "FfiHandle" in repr(u.object)):
            hook(u)

    return unraisable


sys.unraisablehook = _quiet(sys.unraisablehook)


def say(msg: str) -> None:
    print(f"[voice {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def check(ok: bool, what: str) -> bool:
    say(("  ok   " if ok else "  FAIL ") + what)
    if not ok:
        FAILURES.append(what)
    return ok


_WORDS = (
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen"
)
_ONES = {w: i for i, w in enumerate(_WORDS.split()) if i < 10}
_TEENS = {w: i for i, w in enumerate(_WORDS.split()) if i >= 10}
_TENS = {
    w: 20 + 10 * i
    for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split())  # noqa: SIM905
}


def digits(text: str) -> str:
    """The digits `text` says, as runs: "four, four, one, seven", "4-4-1-7" and "forty-four
    seventeen" are all "4417"; any other word breaks a run."""
    toks = re.findall(r"[a-z]+|\d+", text.lower())
    out: list[str] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.isdigit():
            out.append(t)
        elif t in _TENS:
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            if _ONES.get(nxt, 0) > 0:
                out.append(str(_TENS[t] + _ONES[nxt]))
                i += 1
            else:
                out.append(str(_TENS[t]))
        elif t in _TEENS:
            out.append(str(_TEENS[t]))
        elif t in _ONES:
            out.append(str(_ONES[t]))
        else:
            out.append(" ")
        i += 1
    return re.sub(r" +", " ", "".join(out))


def holds_code(text: str, code: str = "4417") -> bool:
    return code in digits(text)


# ------------------------------------------------------------------------- the caller's voice --


def speech(text: str, cache: Path) -> np.ndarray:
    """`text` in macOS's Samantha voice, as 24 kHz mono int16."""
    name = hashlib.sha1(text.encode()).hexdigest()[:12]
    aiff, wav = cache / f"say-{name}.aiff", cache / f"say-{name}.wav"
    if not wav.exists():
        subprocess.run(["say", "-v", "Samantha", "-o", str(aiff), text], check=True)
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", f"LEI16@{RATE}", str(aiff), str(wav)], check=True
        )
    with wave.open(str(wav)) as w:
        assert w.getframerate() == RATE and w.getsampwidth() == 2, (w.getparams(), wav)
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getnchannels() > 1:
            pcm = pcm.reshape(-1, w.getnchannels()).mean(axis=1).astype(np.int16)
    return pcm


def write_wav(path: Path, pcm: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.astype(np.int16).tobytes())


async def transcribe(http: httpx.AsyncClient, env: dict[str, str], path: Path) -> str:
    """What was said in `path`, by the provider's transcription API (OpenAI's multipart form)."""
    for attempt in range(3):
        r = await http.post(
            f"{env['VOICE_BASE_URL']}/audio/transcriptions",
            headers={"Authorization": f"Bearer {env['VOICE_API_KEY']}"},
            files={"file": (path.name, path.read_bytes(), "audio/wav")},
            data={"model": env["VOICE_JUDGE_STT"], "language": "en"},
            timeout=60,
        )
        if r.status_code < 500 and r.status_code != 429:
            break
        await asyncio.sleep(1 + attempt)
    if r.status_code != 200:
        raise AssertionError(f"transcription failed: HTTP {r.status_code} {r.text[:200]}")
    return str(r.json().get("text", "")).strip()


# ------------------------------------------------------------------------------ one call --


class VoiceCall:
    """One caller in one room: dispatches the agent, publishes a microphone, records the agent."""

    def __init__(self, room: str, identity: str, mode: str, out: Path) -> None:
        self.room_name, self.identity, self.mode, self.out = room, identity, mode, out
        self.room = rtc.Room()
        self.agent: str | None = None
        self.state = "initializing"
        self.state_at = time.perf_counter()
        self.states: list[tuple[float, str]] = []
        self.ready = asyncio.Event()
        self.mic_heard = asyncio.Event()
        self.agent_audio = asyncio.Event()
        self.frames: list[tuple[float, np.ndarray]] = []  # (arrival, 10 ms of the agent's audio)
        self.texts: list[tuple[float, str, str]] = []  # (arrival, sender, text) on lk.transcription
        self.turns: list[dict[str, Any]] = []
        self._pending: np.ndarray | None = None
        self._spoken = asyncio.Event()
        self._speech_end = 0.0
        self._tasks: set[asyncio.Task[Any]] = set()

    def _spawn(self, coro: Any) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    def _agent_state(self, p: rtc.RemoteParticipant) -> None:
        if p.kind != rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
            return
        self.agent = p.identity
        state = p.attributes.get("lk.agent.state", "")
        if state and state != self.state:
            self.state, self.state_at = state, time.perf_counter()
            self.states.append((self.state_at, state))
        (self.ready.set if self.state == "listening" else self.ready.clear)()

    def _on_track(
        self, track: rtc.Track, _pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant
    ) -> None:
        if (
            p.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
            and track.kind == rtc.TrackKind.KIND_AUDIO
        ):
            self.agent_audio.set()
            self._spawn(self._record(track))

    async def _record(self, track: rtc.Track) -> None:
        stream = rtc.AudioStream(track, sample_rate=RATE, num_channels=1)
        try:
            async for ev in stream:
                pcm = np.frombuffer(ev.frame.data, dtype=np.int16).copy()
                self.frames.append((time.perf_counter(), pcm))
        finally:
            await stream.aclose()

    async def _mic(self, source: rtc.AudioSource) -> None:
        """A microphone that is always on: 10 ms frames at real-time pace, silence unless an
        utterance is queued."""
        silence = np.zeros(FRAME, dtype=np.int16)
        t0, n = time.perf_counter(), 0
        while True:
            pcm, last = silence, False
            if self._pending is not None:
                pcm, self._pending = self._pending[:FRAME], self._pending[FRAME:]
                if len(self._pending) == 0:
                    self._pending, last = None, True
                if len(pcm) < FRAME:
                    pcm = np.concatenate([pcm, silence[: FRAME - len(pcm)]])
            frame = rtc.AudioFrame(pcm.tobytes(), RATE, 1, FRAME)
            await source.capture_frame(frame)
            if last:  # the moment the utterance's last sample is due out of the source
                self._speech_end = time.perf_counter() + source.queued_duration
                self._spoken.set()
            n += 1
            delay = t0 + n * 0.01 - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)

    async def __aenter__(self) -> VoiceCall:
        lk = api.LiveKitAPI(
            url=LK_URL.replace("ws", "http", 1), api_key=LK_KEY, api_secret=LK_SECRET
        )
        try:
            await lk.room.create_room(
                api.CreateRoomRequest(name=self.room_name, empty_timeout=30, departure_timeout=5)
            )
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(
                    agent_name=AGENT_NAME,
                    room=self.room_name,
                    metadata=json.dumps({"mode": self.mode}),
                )
            )
        finally:
            await lk.aclose()
        token = (
            api.AccessToken(LK_KEY, LK_SECRET)
            .with_identity(self.identity)
            .with_grants(api.VideoGrants(room_join=True, room=self.room_name))
            .to_jwt()
        )
        self.room.on("participant_connected", self._agent_state)
        self.room.on("participant_attributes_changed", lambda _c, p: self._agent_state(p))
        self.room.on("track_subscribed", self._on_track)
        self.room.on("local_track_subscribed", lambda _t: self.mic_heard.set())

        def on_text(reader: rtc.TextStreamReader, sender: str) -> None:
            async def read() -> None:
                text = await reader.read_all()
                if text.strip():
                    self.texts.append((time.perf_counter(), sender, text.strip()))

            self._spawn(read())

        self.room.register_text_stream_handler("lk.transcription", on_text)
        t0 = time.perf_counter()
        await self.room.connect(LK_URL, token)
        for p in self.room.remote_participants.values():
            self._agent_state(p)
            for pub in p.track_publications.values():
                if pub.track is not None:
                    self._on_track(pub.track, pub, p)
        source = rtc.AudioSource(RATE, 1, queue_size_ms=100)
        mic = rtc.LocalAudioTrack.create_audio_track("microphone", source)
        await self.room.local_participant.publish_track(
            mic, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        self._spawn(self._mic(source))
        await asyncio.wait_for(self.ready.wait(), 30)
        await asyncio.wait_for(self.mic_heard.wait(), 10)  # the agent is subscribed to the mic
        await asyncio.wait_for(self.agent_audio.wait(), 10)  # and we to the agent's voice
        self.ready_ms = (time.perf_counter() - t0) * 1000
        return self

    async def speak(self, text: str, pcm: np.ndarray, timeout: float = 40) -> dict[str, Any]:
        """Say `pcm` into the mic, then wait for the agent to answer and fall quiet."""
        await asyncio.wait_for(self.ready.wait(), timeout)
        self._spoken.clear()
        self._pending = pcm
        await asyncio.wait_for(self._spoken.wait(), len(pcm) / RATE + 5)
        end = self._speech_end
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            spoke = any(t > end and s == "speaking" for t, s in self.states)
            quiet = self.state == "listening" and time.perf_counter() - self.state_at >= QUIET_S
            if spoke and quiet:
                break
            await asyncio.sleep(0.05)
        done = time.perf_counter()
        got = [(t, f) for t, f in self.frames if end <= t <= done]
        loud = [i for i, (_, f) in enumerate(got) if int(np.abs(f).max(initial=0)) >= AUDIBLE]
        audible = got[loud[0]][0] if loud else None
        # the answer, from 0.3 s before its first audible frame to 0.3 s after its last: the
        # track carries silent frames all the time, and the judge need not hear them
        got = got[max(0, loud[0] - 30) : loud[-1] + 30] if loud else []
        n = len(self.turns) + 1
        wav = self.out / f"{self.room_name}-turn{n}.wav"
        write_wav(wav, np.concatenate([f for _, f in got]) if got else np.zeros(0, np.int16))
        turn = {
            "n": n,
            "said": text,
            "wav": wav,
            "end": end,
            "first_audible_ms": None if audible is None else round((audible - end) * 1000),
            "reply_s": round(sum(len(f) for _, f in got) / RATE, 2),
            "answered": any(t > end and s == "speaking" for t, s in self.states),
            "text_stream": " ".join(
                x for t, s, x in self.texts if s == self.agent and end <= t <= done + 1
            ),
            "heard": " ".join(
                x for t, s, x in self.texts if s == self.identity and t >= end - 1 and t <= done
            ),
        }
        self.turns.append(turn)
        return turn

    async def __aexit__(self, *_: object) -> None:
        self.left_at = time.time()
        for t in list(self._tasks):
            t.cancel()
        await self.room.disconnect()
        # the whole call as the caller heard it, for a human to listen to
        if self.frames:
            write_wav(
                self.out / f"{self.room_name}-agent.wav",
                np.concatenate([f for _, f in self.frames]),
            )


# ------------------------------------------------------------------------------ the checks --


class Run:
    def __init__(
        self,
        ev: Events,
        memory: AsyncMemory,
        http: httpx.AsyncClient,
        env: dict[str, str],
        out: Path,
    ) -> None:
        self.ev, self.memory, self.http, self.env, self.out = ev, memory, http, env, out
        self.latency: dict[str, list[int]] = {}
        self.rooms: list[str] = []
        self.users: list[str] = []
        self.judged_s = 0.0

    async def call(
        self, mode: str, identity: str, label: str, lines: list[str]
    ) -> tuple[VoiceCall, list[dict[str, Any]]]:
        room = f"voice-{label}-{uuid.uuid4().hex[:6]}"
        self.rooms.append(room)
        say(f"{label}: room {room}, identity {identity}, mode {mode}")
        async with VoiceCall(room, identity, mode, self.out) as c:
            say(f"  agent ready in {c.ready_ms:.0f} ms")
            for line in lines:
                t = await c.speak(line, speech(line, self.out))
                t["spoken"] = (
                    await transcribe(self.http, self.env, t["wav"])
                    if t["answered"] and t["reply_s"]
                    else ""
                )
                self.judged_s += t["reply_s"]
                heard = [e["text"] for e in self.ev.all(room, "stt")]
                say(
                    f"  said {line!r}\n"
                    f"        agent STT heard: {heard[-1] if heard else None!r}\n"
                    f"        agent said (transcribed audio): {t['spoken']!r}\n"
                    f"        agent said (lk.transcription): {t['text_stream']!r}\n"
                    f"        end of speech -> first audible agent audio: "
                    f"{t['first_audible_ms']} ms, reply {t['reply_s']} s"
                )
                check(
                    t["answered"] and bool(t["spoken"]),
                    f"{label}: the agent answered {line[:30]!r} aloud",
                )
                if t["first_audible_ms"] is not None:
                    self.latency.setdefault(mode, []).append(t["first_audible_ms"])
        if mode != "off":
            await self.shutdown(room)  # the job's last write is done once it has shut down
            errors = self.package_errors(room)
            check(not errors, f"{label}: alexein.livekit logged no error ({errors[:2]})")
        return c, c.turns

    def package_errors(self, room: str) -> list[str]:
        """What the package logged at ERROR for this call's job, as `alexein.livekit` says it."""
        out = []
        for line in (self.out / "worker.log").read_text(errors="replace").splitlines():
            if '"alexein.livekit"' in line and '"ERROR"' in line and room in line:
                try:
                    out.append(json.loads(line)["message"])
                except ValueError:
                    out.append(line[:200])
        return out

    async def shutdown(self, room: str) -> dict[str, Any]:
        e = await self.ev.wait(lambda: self.ev.all(room, "shutdown"), 30, f"job shutdown in {room}")
        return e[0]

    async def searchable(
        self, user: str, queries: list[str], ok: Any, timeout: float = 30
    ) -> tuple[float, str] | None:
        """Seconds until one of `queries` finds a memory `ok` accepts, and that query."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            for query in queries:
                try:
                    # Bound by participant: the identity's own namespace (participant_id).
                    r = await self.memory.user(participant_id(user)).search(query, fast=True)
                    if any(ok(m.text) for m in r.memories):
                        return round(time.monotonic() - t0, 1), query
                except NotFoundError:
                    pass
            await asyncio.sleep(0.5)
        return None

    async def auto(self, baseline: bool) -> None:
        user = f"voice-auto-{uuid.uuid4().hex[:8]}"
        self.users += [user, participant_id(user)]
        c1, _ = await self.call("auto", user, "auto-call1", [FACT, FACT2])
        r1 = c1.room_name
        b = self.ev.all(r1, "bound")
        check(
            bool(b) and b[0]["user_id"] == participant_id(user),
            f"auto call 1 bound to {user} ({b[:1] and b[0]['user_id']})",
        )
        heard = " ".join(e["text"] for e in self.ev.all(r1, "stt"))
        check(holds_code(heard), f"the agent's STT heard the code as 4417 ({heard[:80]!r})")
        shut = await self.shutdown(r1)
        check(shut.get("closed") is True, "auto call 1 ended with memory closed (turns flushed)")
        t = await self.searchable(user, ["locker code at the Alfama gym"], holds_code)
        check(t is not None, f"the code is searchable in memory ((s, query) after the call: {t})")

        c2, t2 = await self.call("auto", user, "auto-call2", [QUESTION])
        r2 = c2.room_name
        spoken = t2[0]["spoken"]
        check(holds_code(spoken), f"call 2 spoken answer holds 4417 ({spoken!r})")
        check(
            holds_code(t2[0]["text_stream"]),
            f"call 2 lk.transcription holds 4417 ({t2[0]['text_stream']!r})",
        )
        calls = [
            e
            for e in self.ev.all(r2, "llm_call")
            if any(r == "user" and "locker" in x.lower() for r, x in e["context"])
        ]
        check(bool(calls), f"the model was called for the question ({len(calls)} calls)")
        if calls:
            last = calls[-1]
            rec = last["recall"]
            check(
                rec is not None and not rec["timed_out"] and not rec["failed"] and rec["chars"] > 0,
                f"memory.last_recall shows the recall ({rec})",
            )
            blocks = last["memory_blocks"]
            check(
                len(blocks) == 1 and holds_code(blocks[0]),
                f"the model's context had one <memory> block holding 4417 ({len(blocks)} blocks)",
            )
            check(
                "memory_add" not in last["tools"],
                f"auto mode gives no memory_add tool ({last['tools']})",
            )
        await self.shutdown(r2)

        if baseline:
            plain = f"voice-plain-{uuid.uuid4().hex[:8]}"
            self.users += [plain, participant_id(plain)]
            c3, _ = await self.call("off", plain, "baseline", [FACT, FACT2, QUESTION])
            check(
                not any(e["memory_blocks"] for e in self.ev.all(c3.room_name, "llm_call")),
                "baseline (memory off) had no <memory> block",
            )
            await self.shutdown(c3.room_name)

    async def tools(self) -> None:
        user = f"voice-tools-{uuid.uuid4().hex[:8]}"
        self.users += [user, participant_id(user)]
        c1, _ = await self.call("tools", user, "tools-call1", [REMEMBER])
        r1 = c1.room_name
        b = self.ev.all(r1, "bound")
        check(
            bool(b) and b[0]["user_id"] == participant_id(user) and b[0]["memory_mode"] == "tools",
            f"tools call 1 bound to {user} in tools mode ({b[:1]})",
        )
        used = [c for e in self.ev.all(r1, "tools") for c in e["calls"]]
        say(f"  tool calls: {used}")
        adds = [c for c in used if c["name"] == "memory_add"]
        check(
            any("teal" in c["arguments"].lower() for c in adds),
            f"the model called memory_add with teal ({[c['arguments'] for c in adds]})",
        )
        check(
            not any(e["memory_blocks"] for e in self.ev.all(r1, "llm_call")),
            "tools mode put no <memory> block in the context",
        )
        await self.shutdown(r1)
        # both spellings: the caller says "favourite colour", the STT writes "favorite color", and
        # a fast search for the one has not found a note in the other
        t = await self.searchable(
            user, ["favourite colour", "favorite color"], lambda s: "teal" in s.lower()
        )
        check(t is not None, f"teal is searchable in memory ((s, query) after the call: {t})")

        c2, t2 = await self.call("tools", user, "tools-call2", [ASK_COLOUR])
        r2 = c2.room_name
        used = [c for e in self.ev.all(r2, "tools") for c in e["calls"]]
        say(f"  tool calls: {used}")
        check(any(c["name"] == "memory_search" for c in used), "the model called memory_search")
        spoken = t2[0]["spoken"]
        check("teal" in spoken.lower(), f"call 2 spoken answer says teal ({spoken!r})")
        check("teal" in t2[0]["text_stream"].lower(), "call 2 lk.transcription says teal")
        await self.shutdown(r2)

    def usage(self) -> dict[str, float]:
        """Per-model totals the jobs reported at shutdown."""
        tot: dict[str, float] = {}
        for e in self.ev.all(ev="shutdown"):
            if e["room"] not in self.rooms or not isinstance(e.get("usage"), list):
                continue
            for u in e["usage"]:
                m = u.get("model", "?")
                for k in (
                    "input_tokens",
                    "input_cached_tokens",
                    "output_tokens",
                    "audio_duration",
                    "characters_count",
                ):
                    if u.get(k):
                        tot[f"{m}.{k}"] = tot.get(f"{m}.{k}", 0) + u[k]
        return tot


def cost(tot: dict[str, float], judged_s: float) -> float:
    """US dollars, at list prices: gpt-4.1-mini $0.40/M in ($0.10 cached), $1.60/M out;
    gpt-4o-mini-transcribe $0.003/min; gpt-4o-mini-tts about $0.015/min of audio; the judge's
    gpt-4o-transcribe $0.006/min."""
    usd = 0.0
    for k, v in tot.items():
        model, field = k.rsplit(".", 1)
        if "4.1-mini" in model:
            usd += (
                {"input_tokens": 0.40, "input_cached_tokens": -0.30, "output_tokens": 1.60}.get(
                    field, 0
                )
                * v
                / 1e6
            )
        elif "transcribe" in model and field == "audio_duration":
            usd += 0.003 * v / 60
        elif "tts" in model and field == "audio_duration":
            usd += 0.015 * v / 60
    return usd + 0.006 * judged_s / 60


async def cleanup(memory: AsyncMemory, users: list[str]) -> None:
    """Erase each app user the run made, whole, with the key that wrote them."""
    for u in users:
        try:
            erased = (await memory.user(u).delete()).deleted
        except NotFoundError:
            erased = False  # nothing was ever added for it
        say(f"cleanup: app user {u} erased: {erased}")


def start_worker(env: dict[str, str], out: Path) -> subprocess.Popen[bytes]:
    log = open(out / "worker.log", "w")  # noqa: SIM115 - the worker outlives any block
    return subprocess.Popen(
        [sys.executable, str(HERE / "voice_worker.py"), "start", "--url", LK_URL,
         "--api-key", LK_KEY, "--api-secret", LK_SECRET, "--log-level", "info"],
        stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True,
    )  # fmt: skip


async def registered(worker: subprocess.Popen[bytes], out: Path, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout  # a first run after install can take a minute to import
    while "registered worker" not in (out / "worker.log").read_text(errors="replace"):
        if worker.poll() is not None or time.monotonic() > deadline:
            raise AssertionError(
                f"worker did not register (exit {worker.poll()}), see {out}/worker.log"
            )
        await asyncio.sleep(0.2)


def stop_worker(worker: subprocess.Popen[bytes]) -> int:
    worker.send_signal(signal.SIGINT)
    try:
        return worker.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(worker.pid, signal.SIGKILL)
        FAILURES.append("worker did not stop on SIGINT within 30 s")
        return worker.wait()


def environment() -> dict[str, str]:
    """The worker's environment: memory's key and URL, and the model provider's key, from the
    environment or their KEY=VALUE files, with VOICE_* naming the provider's URL, key and models.
    OpenAI when its key is there, else OpenRouter. Never printed."""
    env = dict(os.environ)
    for k, v in read_env(ENV_FILE, "ALEXEIN_API_URL", "ALEXEIN_API_KEY").items():
        env.setdefault(k, v)
    for k, v in read_env(VOICE_ENV, "OPENAI_API_KEY", "OPENROUTER_API_KEY").items():
        env.setdefault(k, v)
    name = env.get("VOICE_PROVIDER") or next(
        (n for n, p in PROVIDERS.items() if env.get(p["key"])), "openai"
    )
    p = PROVIDERS[name]
    env["VOICE_PROVIDER"] = name
    env["VOICE_API_KEY"] = env.get(p["key"], "")
    env.setdefault("VOICE_BASE_URL", p["base_url"])
    for k in ("llm", "stt", "tts"):
        env.setdefault(f"VOICE_{k.upper()}", p[k])
    env.setdefault("VOICE_JUDGE_STT", p["judge"])
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", choices=["auto", "tools", "all"], default="all")
    ap.add_argument("--no-baseline", action="store_true", help="skip the memory-off latency call")
    ap.add_argument("--keep-users", action="store_true", help="skip deleting the e2e users")
    args = ap.parse_args()

    env = environment()
    for k, where in (("ALEXEIN_API_KEY", ENV_FILE), ("VOICE_API_KEY", VOICE_ENV)):
        if not env.get(k):
            say(f"FAIL: no {k} (or OPENAI_API_KEY / OPENROUTER_API_KEY) in the env or {where}")
            return 1
    say(
        f"provider {env['VOICE_PROVIDER']}: LLM {env['VOICE_LLM']}, STT {env['VOICE_STT']}, "
        f"TTS {env['VOICE_TTS']}, judge {env['VOICE_JUDGE_STT']}"
    )
    os.environ.update({k: env[k] for k in ("ALEXEIN_API_URL", "ALEXEIN_API_KEY") if k in env})
    try:
        httpx.get(LK_URL.replace("ws", "http", 1), timeout=3).raise_for_status()
    except Exception as e:
        say(f"FAIL: LiveKit server not reachable at {LK_URL} ({e}); start livekit-dev")
        return 1

    out = Path(tempfile.mkdtemp(prefix="alexein-livekit-voice-"))
    events = out / "events.jsonl"
    env.update({"E2E_EVENTS": str(events), "E2E_AGENT_NAME": AGENT_NAME,
                "PYTHONWARNINGS": "ignore", "PYTHONUNBUFFERED": "1"})  # fmt: skip
    say(f"logs, recordings and transcripts in {out}")
    t0 = time.perf_counter()
    worker = start_worker(env, out)
    run: Run | None = None

    async def go() -> None:
        nonlocal run
        await registered(worker, out)
        say(f"worker registered in {(time.perf_counter() - t0) * 1000:.0f} ms")
        memory = AsyncMemory(integration="livekit")
        async with httpx.AsyncClient() as http:
            run = Run(Events(events), memory, http, env, out)
            try:
                if args.scenario in ("auto", "all"):
                    say("---- scenario 1: auto mode")
                    await run.auto(baseline=not args.no_baseline)
                if args.scenario in ("tools", "all"):
                    say("---- scenario 2: tools mode")
                    await run.tools()
            finally:
                if not args.keep_users:
                    await cleanup(memory, run.users)
                await memory.close()

    try:
        asyncio.run(go())
    except Exception as e:  # any failure is a FAIL with a reason, never a bare traceback
        FAILURES.append(f"{type(e).__name__}: {e}")
        say(f"FAIL: {type(e).__name__}: {e}")
    finally:
        say(f"worker stopped (exit {stop_worker(worker)})")

    if run is not None:
        say("---- latency: end of the caller's audio -> first audible agent audio, per turn (ms)")
        for mode, ms in run.latency.items():
            s = sorted(ms)
            say(f"  {mode:>5}: {ms}  median {s[len(s) // 2]} ms" if s else f"  {mode}: none")
        for e in run.ev.all(ev="item"):
            if e["room"] in run.rooms and e.get("metrics") and e["role"] in ("user", "assistant"):
                m = {
                    k: round(v, 3)
                    for k, v in e["metrics"].items()
                    if isinstance(v, (int, float)) and ("delay" in k or "tt" in k or "e2e" in k)
                }
                if m:
                    say(f"  worker [{'-'.join(e['room'].split('-')[1:3])}] {e['role']}: {m}")
        for e in run.ev.all(ev="llm_call"):
            if e["room"] in run.rooms and e.get("recall"):
                said = next((x for r, x in reversed(e["context"]) if r == "user"), "")
                say(
                    f"  recall [{'-'.join(e['room'].split('-')[1:3])}] {said[:40]!r}: {e['recall']}"
                )
        tot = run.usage()
        say(f"---- usage: { {k: round(v, 1) for k, v in tot.items()} }")
        usd = cost(tot, run.judged_s)
        say(f"---- estimated cost: ${usd:.4f} (list prices; judge audio {run.judged_s:.1f} s)")
    say(
        "RESULT: "
        + ("PASS" if not FAILURES else f"FAIL ({len(FAILURES)}): " + " | ".join(FAILURES))
    )
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)  # skip teardown: livekit.rtc's FfiHandle.__del__ asserts after the FFI is gone
