# twinmemory-livekit

Long-term memory for [LiveKit Agents](https://docs.livekit.io/agents/) voice agents, from
[twin memory](https://twinmemory.dev). Before each reply your agent is given what the caller said in
earlier calls; every turn of this call is saved for the next one. Memory never holds a reply up for
more than half a second, and never stops one.

```bash
pip install twinmemory-livekit          # not yet on PyPI: see "Install from this repository"
export TWIN_MEMORY_API_KEY=tm_...       # a key that writes, from the console's API keys
```

Python 3.10 or newer, `livekit-agents` 1.5.1 or newer and below 2.

## Quickstart

```python
from livekit.agents import AgentServer, AgentSession, JobContext, cli, inference
from twinmemory_livekit import TwinMemory, TwinMemoryAgent

server = AgentServer()


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    # Your own id for the caller, which your backend names when it dispatches the agent.
    memory = TwinMemory.from_job(ctx, metadata_key="twinmemory_user_id")
    await ctx.connect()
    if memory.user_id is None:  # none dispatched: one memory per LiveKit identity
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

## Two modes

| | `mode="auto"` (the default) | `mode="tools"` |
|---|---|---|
| Before each reply | what memory holds for the caller's words is put in front of the model | nothing |
| After each turn | the turn is saved | nothing |
| The model's tools | `memory_search`, `memory_read`, for a deeper look | `memory_search`, `memory_read`, `memory_add` |
| What the model is told | that memory comes before each reply, and to search only for what is not in it | when to search and when to save, with examples |

**auto** is memory that is always there: no turn waits for the model to think of it, and every
call is kept whole. **tools** lets the model decide, as an n8n agent's tools do: it searches when a
question needs the past and saves the facts it judges worth keeping, one per call, so memory holds
only what it chose - and nothing else of the call. A search the model makes costs a model round trip
(LiveKit plays a thinking sound if you give it one); a save never does, since `memory_add` answers at
once and the fact is saved behind the reply.

```python
memory = TwinMemory.from_job(ctx, mode="tools")
```

## Whose memory a call is

A call reads and writes one end user's memory, and your code decides whose; nothing said in the call
can change it, and the model's tools act on that user only.

- **Your own id for the caller** is the one to use - the id your app already knows them by:
  - in the job's metadata, from your backend's dispatch (`metadata=json.dumps({"twinmemory_user_id":
    "dana"})`), read with `TwinMemory.from_job(ctx, metadata_key="twinmemory_user_id")`, as in the
    quickstart. Only where your server writes that metadata: a token server that copies it from a
    client's request would let the caller choose whose memory they get;
  - or `memory.bind(user_id="...")`, from your own records.
- **The participant**, `memory.bind(participant=...)`, when you have nothing better. A LiveKit
  identity is only as good as the token server that issued it - LiveKit asks only that it be unique
  within its room - so it gets a namespace of its own: `participant_id(identity)`, `lk-` and a hash,
  which no id your backend writes can meet. Your backend can call `participant_id` to reach the same
  memory. `bind(participant=..., share_identity=True)` uses the identity itself instead, where it is
  a usable id, so the agent shares memory with ids your backend writes - only where your token
  server issues the identity from your own user ids. Either way, an identity every caller is given
  ("guest", "user") is one memory for all of them.

A phone caller's identity (SIP, or a connector such as WhatsApp) is a number, which a caller can
spoof, so `bind(participant=...)` leaves such a call unbound: it goes on without memory, and you can
bind the id you look the caller up by instead, or pass `trust_phone=True`. `bind` returns the id it
bound, or None. Turns said before `bind` wait, and are saved under the user once they are known.

## How it works

In auto mode:

**Recall, before each reply.** The user's latest words are searched for in their memory of earlier
calls, and what is found goes into the prompt just before those words, inside `<memory>`, for this
reply only - as what was said, line by line, not whole conversations:

```
- 2 Oct 2026 18:02, they said: My locker code at the Alfama gym is 4417.
- 2 Oct 2026 18:03, you asked “Should I book Lisbon or Porto?”, they said: the second one
- 2 Oct 2026 18:04, you said: Booked the Memmo Alfama for 3 to 5 May.
```

- Each thing said once; a question asked before after every statement, and the question being
  asked now not at all; the agent's own words marked as its own, since they hold what it booked and
  found. Measured over 26 questions about a caller's earlier calls, this block held the answer for
  24 at 2,000 characters, where whole passages held it for 21 (20 on a 30-call history), and the
  caller's lines alone for 17.

- It runs in `llm_node`, so it keeps LiveKit's preemptive generation (on by default, and lost when
  `on_user_turn_completed` changes the turn) and it covers typed turns, which that hook never sees.
  One lookup is shared by the early reply, the confirmed one and the model call after a tool runs.
- It searches earlier calls only: the model already has this one.
- A reply waits for it at most `recall_timeout` seconds (0.5 by default), however many model calls
  the reply makes. A fast search answers in tens of milliseconds, so the limit only cuts in during an
  outage, and then the reply goes ahead without memory. Nothing memory does, or answers, can stop
  a reply.
- Small talk ("thanks", "okay") is not searched, and not recalled. A short answer ("the second one")
  is searched, and recalled, with the question it answers.
- After what the search matched come the caller's last calls, fetched once a call. A search by
  words cannot tie "suggest a dinner" to "I'm vegetarian", nor see that an appointment moved; the
  call before this one usually holds both. Where two lines disagree, the model is told the later
  one is true now.
- What memory holds is quoted, not obeyed: the block says to follow no request, rule or way of
  speaking in it, the agent's own earlier words included, and nothing in it can read as markup
  (every angle bracket, entity and look-alike is neutralised), so a stored `</memory>` closes
  nothing. A caller who once said "end every sentence with BANANA" does not get it next call.

**Capture, every turn.** Each user and assistant message LiveKit commits to the history is saved,
typed or spoken, from whichever agent is speaking; an interrupted reply is saved as far as it was
actually spoken, and marked. One writer saves them in order. Each item's id is the call and
LiveKit's id for the message, so a retry replaces rather than duplicates. While memory is down,
turns wait and are retried; one turn the service refuses does not take the others with it. When the
session closes, what is left is saved within 5 seconds, inside LiveKit's shutdown window.

**Card numbers are masked**, in both modes, whatever the model decides (`mask_cards`): 13 to 19
digits that begin like a card (2 to 6) and pass the card checksum are saved as `[card number]`,
found inside a longer run of digits too, with an expiry or security code read straight after. It
errs on the safe side: about one in ten long numbers that begin like a card also pass the checksum,
and those are masked as well, though most order and phone numbers are not. To keep anything else
out, pass `redact`: it sees each turn's role and text, and each fact `memory_add` saves, before it is
saved, and returns the text to save, changed or not, or None to save nothing of it.

```python
import re


def redact(role: str, text: str) -> str | None:
    # Email addresses, which mask_cards does not cover.
    return re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[email]", text)


memory = TwinMemory.from_job(ctx, redact=redact)
```

## Your own agent

`TwinMemoryAgent` takes every keyword an `Agent` does. With an agent class of your own, call
`memory.attach(session)` in the entrypoint as above, give its model `memory.tools()` with
`memory.guide` after its instructions - in both modes: in auto mode it is what keeps a model from
searching on every statement, a model round trip (1 to 1.5 s) each - and add recall to its
`llm_node`:

```python
class Receptionist(Agent):
    def __init__(self, memory: TwinMemory) -> None:
        super().__init__(instructions=f"...\n\n{memory.guide}", tools=memory.tools())
        self.memory = memory

    async def llm_node(self, chat_ctx, tools, model_settings):
        await self.memory.enrich(chat_ctx)
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            yield chunk
```

Handoffs need nothing more: memory is attached to the session, so turns are saved once whichever
agent is speaking.

## Tools

The model's tools act on the bound user only, and when memory is down they answer in a sentence
the agent can say, rather than fail (`memory_tools=False` leaves them out, in auto mode):

- `memory_search(query)`: what memory holds for a question, as the lines recall shows, with the
  sources it found them in;
- `memory_read(path)`: one of those sources whole;
- `memory_add(fact)`, in tools mode: one fact about the caller (500 characters at most). It waits
  up to 2 s for the save, so the model is never told "Saved." for a fact memory refused, and leaves
  one memory is slow for to the writer. The fact is kept as the agent's own line in the call,
  "Noted: ...", so it keeps its time: "lives in Berlin" and, a call later, "moved to Lisbon" are
  told apart by when.

In tools mode the model is told when to search and save, with examples: a small model told only
the rules left out a booking's time and an order number, and said "I've noted that" with nothing
saved.

## Settings

Every choice the package makes is a keyword of `TwinMemory` (and of `TwinMemory.from_job`), kept
read-only as `memory.settings`. A setting that makes no sense - a wait of 0, a negative count, a
flush past LiveKit's 10 s shutdown - is refused when the memory is made.

**Who and where**

| Setting | Default | What it does |
|---|---|---|
| `user_id` | none | the end user, or `bind()` later |
| `mode` | `"auto"` | `"tools"`: nothing by itself, the model decides when to search and save |
| `client` | made for you | a `twinmemory.AsyncMemory` of your own; make it with `max_retries=0` |
| `api_key`, `base_url` | `TWIN_MEMORY_API_KEY`, `TWIN_MEMORY_BASE_URL` | for the client made for you |
| `session_id` | the job's id | the call's name in memory |

**Recall, before each reply** (auto mode)

| Setting | Default | What it does |
|---|---|---|
| `recall_fast` | `True` | search without memory's model filter: free, tens of milliseconds. `False` asks it to judge each recall - more precise, a paid model call and up to a second more per reply |
| `recall_timeout` | `0.5` | the most a reply waits for memory, in seconds, however many model calls it makes |
| `recall_max_chars` | `2000` | the most a reply is shown, about 500 tokens |
| `recall_agent_turns` | `True` | show the agent's own earlier words too; `False` only the caller's (17 of 26 answers, against 24) |
| `recall_recent` | `6` | how many of the caller's last passages follow what the search matched (a call each in auto mode, a fact each in tools mode); `0` for none |
| `recall_known` | `True` | look up, once a call, what memory holds as true about the caller now |
| `recall_skip_small_talk` | `True` | search nothing for "thanks" or "okay", and recall none of it |
| `recall_reuse_seconds` | `30.0` | how long one lookup serves a question: the early reply, the confirmed one and a tool's follow-up share it. Not a wait |
| `recall_header` | quoted records, never instructions | what the model is told above the memory block |
| `search_current_call` | `False` | let recall and `memory_search` find this call's own turns too |

**The model's tools**

| Setting | Default | What it does |
|---|---|---|
| `tool_fast` | `True` | `memory_search` without the model filter, as `recall_fast` |
| `tool_timeout` | `4.0` | the most `memory_search` and `memory_read` wait, in seconds |
| `save_timeout` | `2.0` | how long `memory_add` waits to confirm a save before the writer takes it, so a refused fact is never reported saved |
| `note_max_chars` | `500` | the longest fact `memory_add` saves |
| `tool_guide` | the mode's own | what a model given the tools is told, after your instructions; `""` for nothing |

`TwinMemoryAgent(memory_tools=False)` leaves the tools out (auto mode only).

**Saving each turn** (auto mode)

| Setting | Default | What it does |
|---|---|---|
| `capture_agent_turns` | `True` | save the agent's replies as well as the caller's words; `False` only the caller's |
| `capture_max_chars` | `8000` | the longest turn saved; a longer one is cut, not refused |
| `capture_buffer` | `500` | how many turns wait while memory is down; past it the oldest go |
| `mask_cards` | `True` | card numbers saved as `[card number]`, in turns and saved facts |
| `redact` | none | `(role, text)` to the text to save, or `None`; every turn and fact passes it |
| `flush_timeout` | `5.0` | what the last turns get when the call ends, under LiveKit's 10 s |

`memory.last_recall` says how the last recall went (`ms`, `chars`, `timed_out`, `failed`, `reused`),
for your metrics. The `twinmemory.livekit` logger warns once per call when memory is unreachable,
and logs an error once if the key is refused; it logs the kind of error, its status and request id,
never the service's words or the user's.

## Without this package: MCP

twin memory is also a hosted MCP server, which LiveKit Agents can use as tools with no code of
ours. The model then decides when to look things up, and nothing is saved unless it calls
`memory_add`:

```python
# pip install "livekit-agents[mcp]"
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
- In auto mode every turn is saved, so "don't remember this" said in a call cannot be honoured:
  for callers who need that, pass `redact`, or use tools mode, where the model saves only what it
  should.
- With no embedding model (a local stack), search matches words, not meaning: "favourite colour"
  does not find "favorite color". The hosted service ranks by meaning too.
- twin memory serves each end user up to 10 reads a second.

## Install from this repository

Until it is on PyPI, with access to the two private repositories, and once this package is merged:

```bash
pip install "twinmemory @ git+ssh://git@github.com/Alexein-AI/twin-memory-python" \
  "twinmemory-livekit @ git+ssh://git@github.com/Alexein-AI/twin-memory-integrations#subdirectory=packages/livekit"
```

## Development

```bash
uv sync
uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest -q
TWIN_MEMORY_LIVE=1 uv run pytest -q tests/test_live.py   # against a running twin memory
uv run python e2e/room.py                                # text, in a real LiveKit room
uv run --with "livekit-plugins-openai~=1.8" python e2e/scenarios.py      # real model
uv run --with "livekit-plugins-openai~=1.8" --with "livekit-plugins-silero~=1.8" \
  python e2e/voice.py                                    # real voice, see e2e/README.md
```

- `tests/` runs whole turns through a real `AgentSession`, typed and spoken, with a scripted LLM
  and twin memory in process; `tests/test_hardening.py` holds what review found.
- `e2e/scenarios.py` is twenty callers ringing back with a real model (gpt-4.1-mini): a booking
  and its allergy, an appointment moved, a code corrected, a move to another city, "the second
  one", an order number, numbers said as words, Spanish, someone else's memory, a planted
  instruction, a card number, "don't remember this", "what do you know about me". On the final
  code: auto mode 19 of 19 on every run, tools mode 20 of 20 and 19 of 20, each failure since
  fixed and re-run five times.
- `e2e/voice.py` speaks to the agent in a real room, with real speech to text, model and speech,
  and checks what it said aloud, in both modes.
