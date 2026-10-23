# twinmemory-livekit

Long-term memory for [LiveKit Agents](https://docs.livekit.io/agents/) voice agents, from
[twin memory](https://twinmemory.dev). Before each reply your agent is given what the caller said in
earlier calls; every turn of this call is saved for the next one. Memory never holds a reply up for
more than half a second, and never stops one.

```bash
pip install twinmemory-livekit          # not yet on PyPI: see "Install from this repository"
export TWIN_MEMORY_API_KEY=tm_...       # a key that writes, from the console's API keys
```

Python 3.10 or newer, `livekit-agents` 1.5.1 or newer.

## Quickstart

```python
from livekit.agents import AgentServer, AgentSession, JobContext, cli, inference
from twinmemory_livekit import TwinMemory, TwinMemoryAgent

server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    memory = TwinMemory.from_job(ctx)
    await ctx.connect()
    memory.bind(participant=await ctx.wait_for_participant())

    session = AgentSession(
        stt=inference.STT("deepgram/nova-3"),
        llm=inference.LLM("openai/gpt-4.1-mini"),
        tts=inference.TTS("cartesia/sonic-3"),
    )
    memory.attach(session)
    agent = TwinMemoryAgent(memory, instructions="You are a friendly voice assistant.")
    await session.start(room=ctx.room, agent=agent)


if __name__ == "__main__":
    cli.run_app(server)
```

That is the whole integration. A caller who said last week that they moved to Lisbon gets an agent
that knows it today.

## Whose memory a call is

A call reads and writes one end user's memory, and your code decides whose; nothing said in the call
can change it, and the model's tools act on that user only.

- **From the participant**: `memory.bind(participant=...)` uses the identity your token server gave
  them. An identity twin memory can use as an id (letters, digits, `.`, `_` and `-`, up to 64, such
  as `dana` or a UUID) is the end user id as it is, so it is the same memory your backend writes to;
  any other (`dana@acme.dev`) becomes `lk-` and a hash of it, which names no address or number and
  which no other identity can be made to match.
- **From your own records**: `memory.bind(user_id="...")`.
- **From the job's metadata**, when your own backend dispatches the agent with
  `metadata=json.dumps({"twinmemory_user_id": "dana"})`: `TwinMemory.from_job(ctx,
  metadata_key="twinmemory_user_id")`. Only where your server writes that metadata; a token server
  that copies it from a client's request would let the caller choose whose memory they get.

A phone caller's identity (SIP, or a connector such as WhatsApp) is a number, which a caller can
spoof, so `bind(participant=...)` leaves such a call unbound: it goes on without memory, and you can
bind the id you look the caller up by instead, or pass `trust_phone=True`. `bind` returns the id it
bound, or None. Turns said before `bind` wait, and are saved under the user once they are known.

## How it works

**Recall, before each reply.** The user's latest words are searched for in their memory of earlier
calls, and what is found goes into the prompt just before those words, inside `<memory>`, for this
reply only:

- It runs in `llm_node`, so it keeps LiveKit's preemptive generation (on by default, and lost when
  `on_user_turn_completed` changes the turn) and it covers typed turns, which that hook never sees.
  One lookup is shared by the early reply, the confirmed one and the model call after a tool runs.
- It searches earlier calls only: the model already has this one.
- A reply waits for it at most `recall_timeout` seconds (0.5 by default), however many model calls
  the reply makes. A fast search answers in tens of milliseconds, so the limit only cuts in during an
  outage, and then the reply goes ahead without memory. Nothing memory does, or answers, can stop
  a reply.
- Small talk ("thanks", "okay") is not searched. A short answer ("the second one") is searched with
  the question it answers.
- What memory holds is quoted, not obeyed: the block says so, and nothing in it can read as markup
  (every angle bracket, entity, look-alike and invisible character is neutralised), so a stored
  `</memory>` closes nothing.

**Capture, every turn.** Each user and assistant message LiveKit commits to the history is saved,
typed or spoken, from whichever agent is speaking; an interrupted reply is saved as far as it was
actually spoken, and marked. One writer saves them in order. Each item's id is the call and
LiveKit's id for the message, so a retry replaces rather than duplicates. While memory is down,
turns wait and are retried; one turn the service refuses does not take the others with it. When the
session closes, what is left is saved within 5 seconds, inside LiveKit's shutdown window.

To keep something out of memory, pass `redact`: it sees each turn's role and text before it is
saved, and returns the text to save, changed or not, or None to save nothing of it.

```python
def redact(role: str, text: str) -> str | None:
    return re.sub(r"\d{12,19}", "[card number]", text)


memory = TwinMemory.from_job(ctx, redact=redact)
```

## Your own agent

`TwinMemoryAgent` takes every keyword an `Agent` does. With an agent class of your own, call
`memory.attach(session)` in the entrypoint as above, and add recall to its `llm_node`:

```python
class Receptionist(Agent):
    def __init__(self, memory: TwinMemory) -> None:
        super().__init__(instructions="...", tools=memory.tools())
        self.memory = memory

    async def llm_node(self, chat_ctx, tools, model_settings):
        await self.memory.enrich(chat_ctx)
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            yield chunk
```

Handoffs need nothing more: memory is attached to the session, so turns are saved once whichever
agent is speaking.

## Tools

`TwinMemoryAgent` gives the model two tools, which act on the bound user only (`memory_tools=False`
leaves them out):

- `memory_search(query)`, a deeper look when the recalled context is not enough;
- `memory_remember(note)`, to save something the user asks to be remembered (500 characters at most).

When memory is down they answer in a sentence the agent can say, rather than fail.

## Settings

```python
TwinMemory(
    user_id=None,  # or bind() later
    client=None,  # a twinmemory.AsyncMemory of your own; else one from api_key and base_url
    api_key=None,  # else TWIN_MEMORY_API_KEY
    base_url=None,  # else TWIN_MEMORY_BASE_URL, else the hosted service
    session_id=None,  # the call's name in memory; from_job uses the job id
    recall_timeout=0.5,  # seconds a reply waits for memory at most
    fast=True,  # False: memory's model filter judges each recall (paid, slower)
    redact=None,  # (role, text) -> text to save, or None
)
```

If you pass your own `AsyncMemory`, make it with `max_retries=0`: the client's back-off would spend
the recall time on retries.

`memory.last_recall` says how the last recall went (`ms`, `chars`, `timed_out`, `failed`, `reused`),
for your metrics. The `twinmemory.livekit` logger warns once per call when memory is unreachable,
and logs an error once if the key is refused; it logs the kind of error, its status and request id,
never the service's words or the user's.

## Without this package: MCP

twin memory is also a hosted MCP server, which LiveKit Agents can use as tools with no code of
ours. The model then decides when to look things up, and nothing is saved unless it calls
`memory_add`:

```python
from livekit.agents import mcp

tools = [
    mcp.MCPToolset(
        id="twinmemory",
        mcp_server=mcp.MCPServerHTTP(
            url="https://api.twinmemory.dev/v1/mcp",
            headers={"Authorization": f"Bearer {key}", "X-Twin-Account": user_id},
            allowed_tools=["memory_search", "memory_add"],
        ),
    )
]
```

## Limits

- A turn becomes searchable a few seconds after it is saved, so recall covers earlier calls, not
  the last few seconds of this one; the model has those already.
- A realtime (speech to speech) model has no `llm_node`, and LiveKit does not pass a changed turn
  on to one: its turns are saved, but nothing is recalled for it.
- While no participant is linked to the session (after the owner drops unexpectedly), LiveKit
  accepts typed text from anyone in the room, and it is saved as the owner's. Rooms with more than
  one person in them should pass a `text_input_cb` that keeps the owner's text only.
- twin memory serves each end user up to 10 reads a second.

## Install from this repository

Until it is on PyPI, together with the `twinmemory` client it uses:

```bash
pip install "twinmemory @ git+https://github.com/Alexein-AI/twin-memory-python" \
  "twinmemory-livekit @ git+https://github.com/Alexein-AI/twin-memory-integrations#subdirectory=packages/livekit"
```

## Development

```bash
uv sync
uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest -q
TWIN_MEMORY_LIVE=1 uv run pytest -q tests/test_live.py   # against a running twin memory
uv run python e2e/room.py                                # in a real LiveKit room, see e2e/
```

`tests/test_session.py` drives whole turns through a real `AgentSession`, typed and spoken, with a
scripted LLM and twin memory in process; `tests/test_hardening.py` holds what review found.
