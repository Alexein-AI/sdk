"""The voice agent worker that e2e/voice.py and e2e/talk.py run: the package's README pattern with
real STT, LLM and TTS (OpenAI's, or OpenRouter's) and Silero VAD. Not meant to be run by hand,
though it can be:

    uv run --with "livekit-plugins-openai~=1.8" --with "livekit-plugins-silero~=1.8" \
        python e2e/voice_worker.py start --url ws://localhost:7880 \
        --api-key devkey --api-secret secret

with VOICE_API_KEY (else OPENAI_API_KEY), ALEXEIN_API_KEY and ALEXEIN_API_URL set, and
E2E_EVENTS=<file.jsonl> for the events. VOICE_BASE_URL points every model at an OpenAI-compatible
host (OpenRouter's https://openrouter.ai/api/v1), VOICE_LLM / VOICE_STT / VOICE_TTS name the
models, and VOICE_TTS=say speaks with macOS `say` instead, which needs no key.

Each call's memory mode comes from the dispatch's metadata, `{"mode": "auto"}`, `"tools"` or
`"off"` (a plain `Agent`, no memory: the latency baseline), else from VOICE_MODE.
Every event the driver asserts on is one JSON line in E2E_EVENTS, written by the job process that
saw it.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import uuid
import wave
from pathlib import Path
from typing import Any

from livekit.agents import (
    DEFAULT_API_CONNECT_OPTIONS,
    Agent,
    AgentServer,
    AgentSession,
    APIConnectOptions,
    JobContext,
    JobProcess,
    cli,
    llm,
    tts,
)
from livekit.plugins import openai, silero

from alexein_livekit import AlexeinMemory, AlexeinMemoryAgent

AGENT_NAME = os.environ.get("E2E_AGENT_NAME", "alexein-voice-e2e")
EVENTS = os.environ.get("E2E_EVENTS", "")
DEFAULT_MODE = os.environ.get("VOICE_MODE", "auto")
LLM_MODEL = os.environ.get("VOICE_LLM", "gpt-4.1-mini")
STT_MODEL = os.environ.get("VOICE_STT", "gpt-4o-mini-transcribe")
TTS_MODEL = os.environ.get("VOICE_TTS", "gpt-4o-mini-tts")
TTS_VOICE = os.environ.get("VOICE_TTS_VOICE", "alloy")
BASE_URL = os.environ.get("VOICE_BASE_URL") or None  # None: api.openai.com
API_KEY = os.environ.get("VOICE_API_KEY") or os.environ.get("OPENAI_API_KEY")
HOST = {k: v for k, v in (("base_url", BASE_URL), ("api_key", API_KEY)) if v}
INSTRUCTIONS = (
    "You are a friendly voice assistant on a phone call. Answer in one or two short sentences, "
    "in plain spoken words with no lists or formatting. Read any code or number out digit by "
    "digit, for example 'two five eight one'."
)


def emit(event: str, **fields: Any) -> None:
    line = json.dumps({"ev": event, "t": time.time(), **fields}, default=str)
    if EVENTS:
        with open(EVENTS, "a") as f:  # one short append per line; job processes share the file
            f.write(line + "\n")
    print("E2E " + line, flush=True)


def dump(chat_ctx: llm.ChatContext) -> list[list[str]]:
    """The context as the model is given it: [role or item type, text]."""
    out: list[list[str]] = []
    for it in chat_ctx.items:
        if it.type == "message":
            out.append([it.role, it.text_content or ""])
        elif it.type == "function_call":
            out.append(["function_call", f"{it.name}({it.arguments})"])
        elif it.type == "function_call_output":
            out.append(["function_call_output", f"{it.name}: {it.output}"])
    return out


def recall_of(memory: AlexeinMemory | None) -> dict[str, Any] | None:
    r = memory.last_recall if memory is not None else None
    if r is None:
        return None
    return {
        "ms": round(r.ms, 2),
        "chars": r.chars,
        "timed_out": r.timed_out,
        "failed": r.failed,
        "reused": r.reused,
    }


class SayTTS(tts.TTS):
    """macOS `say` as a LiveKit TTS: free, no key, about 0.3 s to the first sample. The fallback
    for a host whose speech endpoint the OpenAI plugin cannot use."""

    def __init__(self, voice: str = "Samantha", rate: int = 24000) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False), sample_rate=rate, num_channels=1
        )
        self.voice = voice

    @property
    def model(self) -> str:
        return "say"

    @property
    def provider(self) -> str:
        return "macOS"

    def synthesize(
        self, text: str, *, conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS
    ) -> tts.ChunkedStream:
        return _SayStream(tts=self, input_text=text, conn_options=conn_options)


class _SayStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        engine: SayTTS = self._tts  # type: ignore[assignment]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "say.wav"
            proc = await asyncio.create_subprocess_exec(
                "say", "-v", engine.voice, "-o", str(out), "--file-format=WAVE",
                f"--data-format=LEI16@{engine.sample_rate}", self.input_text,
            )  # fmt: skip
            await proc.wait()
            with wave.open(str(out)) as w:
                pcm = w.readframes(w.getnframes())
        output_emitter.initialize(
            request_id=uuid.uuid4().hex,
            sample_rate=engine.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
        )
        output_emitter.push(pcm)
        output_emitter.flush()


class LoggedLLM(openai.LLM):
    """OpenAI's LLM, logging the exact context and tools each model call is given: memory has
    already been placed in it by then, since `enrich` runs before `Agent.default.llm_node`."""

    def __init__(self, base: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base = base
        self.memory: AlexeinMemory | None = None

    def chat(self, *, chat_ctx: llm.ChatContext, tools: list[llm.Tool] | None = None, **kw: Any):  # type: ignore[override]
        context = dump(chat_ctx)
        emit(
            "llm_call",
            **self.base,
            context=context,
            memory_blocks=[t for r, t in context if r == "assistant" and "<memory>" in t],
            tools=[getattr(t, "id", None) or getattr(t, "name", str(t)) for t in tools or []],
            recall=recall_of(self.memory),
        )
        return super().chat(chat_ctx=chat_ctx, tools=tools, **kw)


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server = AgentServer(num_idle_processes=2, port=0, setup_fnc=prewarm)


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    room = ctx.job.room.name
    base = {"room": room, "job": ctx.job.id}
    try:
        meta = json.loads(ctx.job.metadata or "{}")
    except ValueError:
        meta = {}
    mode = meta.get("mode") or DEFAULT_MODE

    # ---- the README pattern
    memory: AlexeinMemory | None = None
    if mode != "off":
        # mode= only where it is not the default, so "auto" runs on a package without modes too
        memory = AlexeinMemory.from_job(ctx, **({} if mode == "auto" else {"mode": mode}))
    emit("job_start", **base, mode=mode, metadata=ctx.job.metadata)
    await ctx.connect()
    participant = await ctx.wait_for_participant()
    if memory is not None:
        memory.bind(participant=participant)
    emit(
        "bound",
        **base,
        mode=mode,
        identity=participant.identity,
        user_id=memory.user_id if memory else None,
        memory_mode=getattr(memory, "mode", None),
    )

    model = LoggedLLM(base, model=LLM_MODEL, temperature=0.2, **HOST)
    model.memory = memory
    session = AgentSession(
        # non-streaming: Silero VAD cuts each utterance, and only speech is sent to be transcribed
        stt=openai.STT(model=STT_MODEL, use_realtime=False, **HOST),
        llm=model,
        tts=SayTTS()
        if TTS_MODEL == "say"
        else openai.TTS(model=TTS_MODEL, voice=TTS_VOICE, **HOST),
        vad=ctx.proc.userdata["vad"],
        # Silero VAD ends the turn. LiveKit's default, inference.TurnDetector(), asks LiveKit
        # Cloud and falls back to a local model, which a dev server makes a coin toss.
        turn_handling={"turn_detection": "vad"},
    )
    if memory is not None:
        memory.attach(session)

    @session.on("user_state_changed")
    def _user_state(ev: Any) -> None:
        emit("user_state", **base, old=ev.old_state, new=ev.new_state)

    @session.on("agent_state_changed")
    def _agent_state(ev: Any) -> None:
        emit("agent_state", **base, old=ev.old_state, new=ev.new_state)

    @session.on("user_input_transcribed")
    def _heard(ev: Any) -> None:
        if ev.is_final:
            emit("stt", **base, text=ev.transcript)

    @session.on("conversation_item_added")
    def _item(ev: Any) -> None:
        it = ev.item
        emit(
            "item",
            **base,
            type=it.type,
            role=getattr(it, "role", None),
            text=getattr(it, "text_content", None),
            metrics=dict(getattr(it, "metrics", None) or {}),
            interrupted=getattr(it, "interrupted", None),
        )

    @session.on("function_tools_executed")
    def _tools(ev: Any) -> None:
        emit(
            "tools",
            **base,
            calls=[{"name": c.name, "arguments": c.arguments} for c in ev.function_calls],
            outputs=[{"name": o.name, "output": o.output} for o in ev.function_call_outputs],
        )

    @session.on("error")
    def _error(ev: Any) -> None:
        emit("error", **base, error=repr(getattr(ev, "error", ev))[:500])

    @session.on("close")
    def _close(ev: Any) -> None:
        emit("session_close", **base, reason=getattr(ev.reason, "value", str(ev.reason)))

    async def _on_shutdown(reason: str) -> None:
        # registered after from_job's memory.aclose, so this runs once memory has closed
        emit(
            "shutdown",
            **base,
            reason=reason,
            closed=getattr(memory, "_closed", None),
            usage=_usage(session),
        )

    ctx.add_shutdown_callback(_on_shutdown)

    agent: Agent = (
        AlexeinMemoryAgent(memory, instructions=INSTRUCTIONS)
        if memory is not None
        else Agent(instructions=INSTRUCTIONS)
    )
    await session.start(room=ctx.room, agent=agent, record=False)
    emit("started", **base, mode=mode, agent=type(agent).__name__)


def _usage(session: AgentSession) -> Any:
    """What the session spent, per model, for the driver's cost estimate."""
    try:
        usage = session.usage
        return [u.model_dump() if hasattr(u, "model_dump") else vars(u) for u in usage.model_usage]
    except Exception as e:  # a newer or older LiveKit names it differently: say so, go on
        return repr(e)[:200]


if __name__ == "__main__":
    cli.run_app(server)
