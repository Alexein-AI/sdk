# twinmemory-livekit

Long-term memory for [LiveKit Agents](https://docs.livekit.io/agents/) voice agents, from
[twin memory](https://twinmemory.dev). Before each reply your agent is given what the caller said in
earlier calls; every turn of this call is saved for the next one. Memory never holds a reply up for
long, and never stops one.

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
    if memory.user_id is None:
        memory.bind(participant=await ctx.wait_for_participant())

    session = AgentSession(
        stt=inference.STT("deepgram/nova-3"),
        llm=inference.LLM("openai/gpt-4.1-mini"),
        tts=inference.TTS("cartesia/sonic-3"),
    )
    agent = TwinMemoryAgent(memory, instructions="You are a friendly voice assistant.")
    await session.start(room=ctx.room, agent=agent)


if __name__ == "__main__":
    cli.run_app(server)
```

That is the whole integration. A caller who said last week that they moved to Lisbon gets an agent
that knows it today.

## Whose memory a call is

A call reads and writes one end user's memory, and you decide whose; nothing said in the call can
change it.

- **From the job's metadata**, when your backend dispatches the agent:
  `metadata=json.dumps({"twinmemory_user_id": "dana"})`. `TwinMemory.from_job(ctx)` reads it
  (`metadata_key=` to use another key).
- **From the participant**: `memory.bind(participant=...)` uses their LiveKit identity, which your
  token server set. An identity twin memory cannot use as an id as it is (`dana@acme.dev`) becomes
  a readable part and a hash of it, so two identities never share a memory.
- **From your own records**: `memory.bind(user_id="...")`.

A phone (SIP) participant's identity is their number, which a caller can spoof, so `bind` refuses
it: look the caller up and bind your own id, or pass `trust_sip=True`. Turns said before `bind`
wait, and are saved under the user once they are known.

## How it works

**Recall, before each reply.** The user's latest words are searched for in their memory of earlier
calls, and what is found goes into the prompt just before those words, inside `<memory>`, for this
reply only:

- It runs in `llm_node`, so it keeps LiveKit's preemptive generation (on by default, and lost when
  `on_user_turn_completed` changes the turn) and it covers typed turns, which that hook never sees.
  One lookup is shared by the early reply, the confirmed one and the model call after a tool runs.
- It searches earlier calls only: the model already has this one.
- It gets `recall_timeout` seconds (0.5 by default). A fast search answers in tens of
  milliseconds, so the limit only ever cuts off an outage: then the reply goes ahead without memory.
- Small talk ("thanks", "okay") is not searched. A short answer ("the second one") is searched with
  the question it answers.

**Capture, every turn.** Each user and assistant message LiveKit commits to the history is saved,
typed or spoken, from whichever agent is speaking; an interrupted reply is saved as far as it was
actually spoken, and marked. One writer saves them in order. Each item's id is the call and
LiveKit's id for the message, so a retry replaces rather than duplicates. While memory is down,
turns wait and are retried; when the call ends, what is left is saved within 5 seconds, inside
LiveKit's shutdown window.

## Your own agent

`TwinMemoryAgent` takes every keyword an `Agent` does. With an agent class of your own, add two
lines:

```python
class Receptionist(Agent):
    def __init__(self, memory: TwinMemory) -> None:
        super().__init__(instructions="...", tools=memory.tools())
        self.memory = memory

    async def on_enter(self) -> None:
        self.memory.attach(self.session)

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

- `search_memory(query)`, a deeper look when the recalled context is not enough;
- `remember(note)`, to save something the user asks to be remembered.

When memory is down they answer in a sentence the agent can say, rather than fail.

## Settings

```python
TwinMemory(
    user_id=None,  # or bind() later
    memory=None,  # a twinmemory.AsyncMemory; by default one from the environment
    session_id=None,  # the call's name in memory; from_job uses the job id
    recall_timeout=0.5,  # seconds a reply waits for memory at most
    fast=True,  # False: memory's model filter judges each recall (paid, slower)
)
```

If you pass your own `AsyncMemory`, make it with `max_retries=0`: the client's back-off would
spend the recall time on retries.

`memory.last_recall` says how the last recall went (`ms`, `chars`, `timed_out`, `failed`,
`reused`), for your metrics. The `twinmemory.livekit` logger warns once per call when memory is
unreachable, and logs an error once if the key is refused.

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
- A realtime model (speech to speech) has no `llm_node`. With LiveKit's own turn detection the
  agent recalls in `on_user_turn_completed`; with the model's server-side turn detection that hook
  is skipped too, so turns are saved but not recalled.
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
```

`tests/test_session.py` drives whole turns through a real `AgentSession`, typed and spoken, with a
scripted LLM and twin memory in process. `e2e/` runs the same in a real LiveKit room.
