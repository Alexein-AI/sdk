"""Stand-ins for everything a call needs but the code under test: a scripted LLM, a scripted
speech-to-text with silent audio (so a spoken turn, preemptive generation included, runs with no
room and no keys), and Alexein's memory API as an in-process HTTP service behind the real client.

LiveKit publishes no fake LLM; this one follows the one in livekit/agents' own tests.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from alexein import AsyncMemory
from livekit import rtc
from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    LanguageCode,
    NotGivenOr,
)
from livekit.agents.llm import (
    LLM,
    ChatChunk,
    ChatContext,
    ChoiceDelta,
    FunctionToolCall,
    LLMStream,
    Tool,
    ToolChoice,
)
from livekit.agents.stt import (
    STT,
    RecognizeStream,
    SpeechData,
    SpeechEvent,
    SpeechEventType,
    STTCapabilities,
)
from livekit.agents.utils.audio import AudioBuffer
from livekit.agents.voice.io import AudioInput

# --------------------------------------------------------------------------------- LLM --


def seen(chat_ctx: ChatContext) -> list[tuple[str, str]]:
    """A context as (role, text) pairs, or (item type, "") for what is not a message."""
    return [
        (i.role, i.text_content or "") if i.type == "message" else (i.type, "")
        for i in chat_ctx.items
    ]


Reply = Callable[[ChatContext], "str | list[FunctionToolCall]"]


class FakeLLM(LLM):
    """Replies `reply`, or what `reply_fn` makes of the context; keeps each context it was given."""

    def __init__(self, *, reply: str = "ok", reply_fn: Reply | None = None) -> None:
        super().__init__()
        self.reply, self.reply_fn = reply, reply_fn
        self.calls: list[list[tuple[str, str]]] = []

    @property
    def model(self) -> str:
        return "fake-llm"

    @property
    def provider(self) -> str:
        return "fake"

    def chat(
        self,
        *,
        chat_ctx: ChatContext,
        tools: list[Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> LLMStream:
        self.calls.append(seen(chat_ctx))
        return _Stream(self, chat_ctx=chat_ctx, tools=tools or [], conn_options=conn_options)


class _Stream(LLMStream):
    def __init__(
        self, llm: FakeLLM, *, chat_ctx: ChatContext, tools: list[Tool], conn_options: Any
    ) -> None:
        super().__init__(llm, chat_ctx=chat_ctx, tools=tools, conn_options=conn_options)
        self._fake = llm

    def _send(self, **delta: Any) -> None:
        chunk = ChatChunk(id=f"fake_{id(self)}", delta=ChoiceDelta(role="assistant", **delta))
        self._event_ch.send_nowait(chunk)

    async def _run(self) -> None:
        out = self._fake.reply_fn(self._chat_ctx) if self._fake.reply_fn else self._fake.reply
        if isinstance(out, list):
            self._send(tool_calls=out)
        else:
            self._send(content=out)


# ------------------------------------------------------------------------------ voice --


class SilentAudioInput(AudioInput):
    """Silent 10 ms frames, forever, so the speech-to-text stream is opened and kept open."""

    def __init__(self) -> None:
        super().__init__(label="silence")

    async def __anext__(self) -> rtc.AudioFrame:
        await asyncio.sleep(0.01)
        return rtc.AudioFrame(
            data=b"\x00\x00" * 160, sample_rate=16000, num_channels=1, samples_per_channel=160
        )


class ScriptedSTT(STT):
    """Speech-to-text that hears what a test says it heard."""

    def __init__(self) -> None:
        super().__init__(capabilities=STTCapabilities(streaming=True, interim_results=True))
        self._streams: list[_Heard] = []
        self._ready = asyncio.Event()

    async def _recognize_impl(self, buffer: AudioBuffer, **_: Any) -> SpeechEvent:
        return SpeechEvent(type=SpeechEventType.FINAL_TRANSCRIPT, alternatives=[])

    def stream(self, **_: Any) -> RecognizeStream:  # pyright: ignore[reportIncompatibleMethodOverride]
        heard = _Heard(stt=self, conn_options=DEFAULT_API_CONNECT_OPTIONS)
        self._streams.append(heard)
        self._ready.set()
        return heard

    async def user_says(self, text: str, *, gap: float = 0.05) -> None:
        """Start of speech, an interim, the preflight that starts a preemptive reply, the final
        transcript and the end of speech, `gap` seconds apart."""
        await asyncio.wait_for(self._ready.wait(), 5)
        heard = self._streams[-1]
        for kind in (
            SpeechEventType.START_OF_SPEECH,
            SpeechEventType.INTERIM_TRANSCRIPT,
            SpeechEventType.PREFLIGHT_TRANSCRIPT,
            SpeechEventType.FINAL_TRANSCRIPT,
            SpeechEventType.END_OF_SPEECH,
        ):
            spoken = kind not in (SpeechEventType.START_OF_SPEECH, SpeechEventType.END_OF_SPEECH)
            alternatives = [SpeechData(text=text, language=LanguageCode("en"))] if spoken else []
            heard._event_ch.send_nowait(SpeechEvent(type=kind, alternatives=alternatives))  # pyright: ignore[reportPrivateUsage]
            await asyncio.sleep(gap)


class _Heard(RecognizeStream):
    async def _run(self) -> None:
        async for _ in self._input_ch:
            pass


# ----------------------------------------------------------------------------- memory --


@dataclass
class MemoryService:
    """Alexein's /v2/memory/search, latest, open and add, in process. `hits` and `known` are what
    every search answers; `delay` holds each answer; `status` answers every call with that
    error."""

    hits: list[str] = field(default_factory=list[str])
    known: list[str] = field(default_factory=list[str])
    recent: list[str] = field(default_factory=list[str])  # what `latest` answers, newest first
    delay: float = 0.0
    status: int | None = None
    new_user: bool = False
    garbage: bool = False  # answer 200 with an HTML page, as a proxy or captive portal does
    reject: str | None = None  # refuse, 422, any add with an item holding this text
    flaky: str | None = None  # the first add of this item id alone answers 503
    searches: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    latests: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    opens: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    added: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    users: list[str] = field(default_factory=list[str])

    def client(self) -> AsyncMemory:
        """A client as `AlexeinMemory` makes its own: no retries of the client's own."""
        http = httpx.AsyncClient(transport=httpx.MockTransport(self._answer))
        return AsyncMemory(
            api_key="tm_test", base_url="http://memory.test", http_client=http, max_retries=0
        )

    def texts(self) -> list[tuple[str, str]]:
        return [(i.get("role", ""), i["text"]) for i in self.added]

    def excerpts(self) -> dict[str, str]:
        """Every excerpt this memory answers, by ref: `hits` as p0.., `recent` as r0.."""
        found = {f"p{n}": text for n, text in enumerate(self.hits)}
        return found | {f"r{n}": text for n, text in enumerate(self.recent)}

    async def _answer(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content or b"{}")
        self.users.append(request.headers.get("X-Alexein-User", ""))
        route = request.url.path.rsplit("/", 1)[-1]
        assert request.url.path == f"/v2/memory/{route}", request.url.path
        {"search": self.searches, "latest": self.latests, "open": self.opens}.get(route, []).append(
            body
        )
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.status is not None:
            return httpx.Response(self.status, json={"detail": f"status {self.status}"})
        if self.garbage:
            return httpx.Response(200, text="<html>Sign in to the guest Wi-Fi</html>")
        if route == "add":
            return self._add(body)
        if self.new_user and route != "search":
            # Search answers an app user nothing was added for empty; the other reads, 404.
            return httpx.Response(404, json={"detail": "no memory for app user 'dana' yet"})
        if route == "latest":
            shown = [_excerpt(f"r{n}", t) for n, t in enumerate(self.recent)]
            return httpx.Response(200, json={"memories": shown})
        if route == "open":
            text = self.excerpts().get(body["ref"])
            if text is None:
                return httpx.Response(404, json={"detail": "no memory by that ref"})
            return httpx.Response(200, json={"memory": _excerpt(body["ref"], text)})
        # A narrowed search (`filters`, `after`, ...) answers facts and excerpts, no known lines.
        known = [] if self.new_user or body.get("filters") else self.known
        hits = [] if self.new_user else self.hits
        memories = [{"type": "known", "text": k} for k in known]
        memories += [_excerpt(f"p{n}", text) for n, text in enumerate(hits)]
        found = {"query": body["query"], "answerable": None, "notes": [], "memories": memories}
        return httpx.Response(200, json=found)

    def _add(self, body: dict[str, Any]) -> httpx.Response:
        if self.flaky and [i.get("id") for i in body["items"]] == [self.flaky]:
            self.flaky = None
            return httpx.Response(503, json={"detail": "busy"})
        if any(_nameless_self(i) for i in body["items"]):
            # The service's own rule: an author that says self needs a name, an id or a role.
            return httpx.Response(422, json={"detail": "an author that says self needs a role"})
        if self.reject and any(self.reject in i["text"] for i in body["items"]):
            return httpx.Response(422, json={"detail": "an item is too long"})
        self.added.extend(body["items"])
        self.new_user = False
        ids = [{"id": i.get("id", ""), "status": "queued"} for i in body["items"]]
        return httpx.Response(200, json={"items": ids, "waiting": len(ids)})


def _excerpt(ref: str, text: str) -> dict[str, Any]:
    return {
        "type": "excerpt",
        "ref": ref,
        "text": text,
        "date": None,
        "added_at": None,
        "session": None,
        "roles": [],
    }


def _nameless_self(item: dict[str, Any]) -> bool:
    author = item.get("author")
    if not isinstance(author, dict) or not author.get("self"):
        return False
    return not (author.get("name") or author.get("id") or item.get("role"))
