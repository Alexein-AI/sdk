# Real-room end-to-end test

`room.py` runs alexein-livekit in a real LiveKit room against the real Alexein API. It is text in and text out, with `tests/fakes.py`'s `FakeLLM` standing in for a model, so no STT, TTS or LLM keys are needed.

Every timing and result on this page was measured on 2026-10-23, before the package moved to the `alexein` 0.3 client and the API's `/v2` routes; the harness has been ported since, and not yet run again.

```bash
cd integrations/livekit && uv run python e2e/room.py          # exit 0 = every check held
uv run python e2e/room.py --keep-users                    # leave the e2e users in memory to inspect
```

## Needs
- **LiveKit dev server** on `ws://localhost:7880` with key `devkey` and secret `secret`, for example:
  `docker run -d --name livekit-dev -p 127.0.0.1:7880:7880 -p 127.0.0.1:7881:7881 -p 127.0.0.1:7882:7882/udp livekit/livekit-server --dev --bind 0.0.0.0 --node-ip 127.0.0.1`
- **The Alexein API** at `ALEXEIN_API_URL` (a local stack: `http://localhost:8210`) with a key that writes in `ALEXEIN_API_KEY`. They are read from the environment, or else from the KEY=VALUE file at `$E2E_ENV`. The same key deletes the app users the test made, at the end (`user.delete()`).
- No extra dependencies: `livekit-api` comes with `livekit-agents`, and `httpx` comes with `alexein`.

The key is never printed. Logs go to a fresh temp dir, whose path is printed first: `events.jsonl` (one line per agent-side event) and `worker.log`.

## What it does
`worker.py` is the README pattern exactly: `AlexeinMemory.from_job(ctx)`, then `await ctx.connect()`, then `bind(participant=…)` if the metadata named no user, then `AgentSession(llm=FakeLLM(...))` in text mode with `AlexeinMemoryAgent(memory, memory_tools=False)`. The fake LLM replies `MEMORY-SEEN:yes` or `MEMORY-SEEN:no`. It logs the full context it was given and `memory.last_recall` to `events.jsonl`.

There are three calls for one fresh user, `e2e-<hex>`. Each call gets a new room and so a new job:

1. **Call 1** uses identity `e2e-<hex>` and no metadata, so the user is bound from the participant. It says "My locker code at the Alfama gym is 4417." plus one more turn, then leaves.
   - Both replies are `MEMORY-SEEN:no`.
   - The session-close flush leaves 0 turns unsaved.
   - The driver polls `search()` until the fact is found (allowed 15 s).
2. **Call 2** uses the same identity. Turn 1 says a call-2 marker ("ultramarine"). The driver waits until that turn is searchable, then asks "What is my locker code at the gym?". That question's LLM context must have:
   - exactly one `<memory>` block, sitting just before the question;
   - `4417` inside the block;
   - none of call 2's own turns inside the block, even though the marker was already in memory;
   - no copy of the fact outside the block.
3. **Call 3** uses participant `kiosk-<hex>` and dispatch metadata `{"alexein_user_id": "e2e-<hex>"}`.
   - The user is bound from the metadata at `from_job`, before connect.
   - Recall shows the fact.
   - Nothing is saved under the kiosk identity, whose `latest` still answers 404.

Afterwards it checks what was saved:
- 3 sessions, one per call (each excerpt's `session`, the job's id);
- the question saved twice, once each by calls 2 and 3;
- `4417` saved once;
- no recalled `<memory>` text saved as a turn;
- every job shut down with `memory.aclose` already run.

## Timings (3 runs, 2026-10-23, local stack)
- Recall (`last_recall.ms`) is 3–41 ms per turn. Every value over 30 ms came in call 1, the new user's first searches. Nothing timed out.
- Round trip from typing to the reply arriving is 8–68 ms (8–42 ms in the final 3 runs).
- A turn becomes searchable 3.9–4.7 s after it is said (the call-2 marker, polled from the moment it was said). The call-1 fact was found within 2.7–4.6 s.
- A full run takes about 15 s.

## Notes
- LiveKit tells the agent that the participant left about 2.6 s after the client disconnects. By then capture has usually saved every turn, so the close-time flush finds nothing left; it is not under load in this test.
- Rooms are made with `departure_timeout=5` so each job ends 5 s after the user leaves, rather than the server's default 20 s.
- Memory from a call that ended under about 5 s ago can be partial. For example, call 3 saw call 2's first two turns but not its last two.

# Voice end-to-end test

`voice.py` is the same kind of test with real voices. A caller speaks into a real LiveKit room, and a real agent hears, thinks and answers aloud, with Silero VAD ending each turn. What the agent said is checked by recording its audio track and transcribing it; the `lk.transcription` text stream is checked as a second signal.

Every model goes through LiveKit's OpenAI plugin:

| | OpenAI (`OPENAI_API_KEY`) | OpenRouter (`OPENROUTER_API_KEY`) |
|---|---|---|
| LLM | `gpt-4.1-mini` | `openai/gpt-4.1-mini` |
| STT, non-streaming | `gpt-4o-mini-transcribe` | `openai/gpt-4o-mini-transcribe` |
| TTS | `gpt-4o-mini-tts` | macOS `say` (`SayTTS` in `voice_worker.py`) |
| judge (transcribes the agent's audio) | `gpt-4o-transcribe` | `openai/gpt-4o-transcribe` |

OpenAI is used when both keys are set. OpenRouter has no OpenAI TTS: `openai/gpt-4o-mini-tts` "does not exist", and its Voxtral TTS answered 404 on 2026-10-23. So with OpenRouter the agent speaks with `say`, which is free and needs no key. `VOICE_PROVIDER`, `VOICE_LLM`, `VOICE_STT`, `VOICE_TTS` (or `say`) and `VOICE_JUDGE_STT` override the defaults.

```bash
cd integrations/livekit
uv run --with "livekit-plugins-openai~=1.8" --with "livekit-plugins-silero~=1.8" python e2e/voice.py
#   --scenario auto|tools|all (default all)   --no-baseline   --keep-users
```

Exit 0 means every check held. The plugins come in through `uv run --with` only, matching livekit-agents 1.8.x; nothing is added to `pyproject.toml`.

## Needs
- Everything `room.py` needs (above).
- **`OPENAI_API_KEY` or `OPENROUTER_API_KEY`**, from the environment or else from the KEY=VALUE file at `$VOICE_ENV` (default `../.livekit-test.env`, beside the repositories). It is never printed.
- **macOS `say` and `afconvert`**, which make the caller's voice (Samantha, 24 kHz 16-bit).

Everything goes to a fresh temp dir, whose path is printed first: `events.jsonl`, `worker.log`, every `say` clip, each answer as `<room>-turn<n>.wav`, and each call's whole agent track as `<room>-agent.wav`, so you can listen to what was checked.

## How it works
- **The worker** is `voice_worker.py`, which follows the README pattern: `AlexeinMemory.from_job(ctx, mode=...)`, `await ctx.connect()`, `bind(participant=...)`, `memory.attach(session)` and `AlexeinMemoryAgent`.
  - The mode comes from the dispatch metadata, `{"mode": "auto" | "tools" | "off"}`. `off` is a plain `Agent` with no memory, the latency baseline.
  - The LLM is OpenAI's, wrapped so that each model call logs the exact context and tools it was given, plus `memory.last_recall`. Recall has already placed its `<memory>` block by then.
  - Tool calls are logged from `function_tools_executed`. The user's STT text, each conversation item with its `metrics`, agent and user state changes, errors and the session's `usage` at shutdown are logged too.
  - Turn detection is pinned to `"vad"`. LiveKit 1.8's default, `inference.TurnDetector()`, asks LiveKit Cloud and falls back to a local model, which a dev server makes a coin toss.
- **The caller** has a microphone that is always on: an `rtc.AudioSource` track sending 10 ms frames at real-time pace (`queue_size_ms=100`). It sends silence between utterances, as a real microphone does, so the VAD always hears the silence that ends a turn.
  - An utterance is a `say` clip. The end of the caller's audio is when its last sample leaves the source.
  - An answer is over once the agent has spoken and then been `listening` for 1.5 s. A tool call's thinking pause does not end it.
- **Latency** is the time from the end of the caller's audio to the first audible frame (peak ≥ 300, about −40 dBFS) on the agent's track, as the caller receives it. The track carries frames all the time, silent ones included, so the first frame of any kind says nothing.

## Scenarios
1. **auto**
   - Call 1, a fresh user `voice-auto-<hex>`: "Hi, my locker code at the Alfama gym is four four one seven." and "I usually train there on Tuesday evenings.", then hang up.
   - Checked: both lines are answered aloud; the agent's STT heard 4417; the job ends with memory closed; the code becomes searchable.
   - Call 2, same user, new room: "What is my locker code at the gym?"
   - Checked: the spoken answer and `lk.transcription` both hold 4417 (digits, or digit words); `last_recall` shows a recall that neither timed out nor failed; the model's context had one `<memory>` block holding 4417; there was no `memory_add` tool.
   - Then a **baseline** call with memory off says all three lines, for latency only.
2. **tools**, a fresh user `voice-tools-<hex>`
   - Call 1: "Please remember that my favourite colour is teal."
   - Checked: the user is bound in tools mode; the model calls `memory_add` with teal; no `<memory>` block is ever placed; after the call, teal is searchable.
   - Call 2: "What is my favourite colour?"
   - Checked: the model calls `memory_search`, and the spoken answer says teal.

At the end it deletes the app users it made, with the same key, and prints per-turn latency for each mode, the worker's per-turn `metrics`, the models' usage and an estimated cost at list prices.

## Talking to it yourself
```bash
uv run --with "livekit-plugins-openai~=1.8" --with "livekit-plugins-silero~=1.8" \
  python e2e/talk.py --identity dana --mode auto      # or --mode tools, --mode off
```
Then open http://localhost:8765 and press **Start call**.
- `talk.py` starts the same worker. For each press it makes a new room, dispatches the agent with the mode, and mints a token for the identity. Hang up and call again for "call 2".
- `talk.html` uses livekit-client 2.22.3 from jsDelivr. It connects to `ws://localhost:7880`, publishes the microphone (localhost is a secure context), plays the agent and shows both sides' `lk.transcription` as they stream.
- What the agent heard and said, its tool calls and its recalls are printed in the terminal.
- `--port` serves somewhere other than 8765. Ctrl-C stops the page server and the worker.
- Tested headless with Playwright and Chrome's fake microphone fed a `say` WAV (`--use-fake-ui-for-media-stream --use-file-for-fake-audio-capture=q.wav%noloop`). The page connected in 1.4 s, the agent heard "Hi there, what can you help me with today?" and answered aloud, and both lines showed in the page.
- Users made this way stay in memory, under `participant_id(<identity>)` (`lk-` and a hash): the
  page binds the participant. Delete one with `AsyncMemory().user(participant_id("dana")).delete()`.

## Results (2026-10-23, OpenRouter, local LiveKit and memory API)
- **4 full runs**, about 3 minutes each.
  - Runs 3 and 4 passed every check, 30 of 30.
  - In runs 1 and 2 every auto check passed, and tools mode failed for reasons since fixed:
    - Run 1 found the package bug in `memory_add` (a note with `author={"self": true}` and no role was refused with a 422 after the tool had said "Saved."); fixed in `ae13327`.
    - Run 2's teal poll searched "favourite colour", which a fast search did not match to the note "My favorite color is teal." in 30 s. The poll now tries both spellings, and "favorite color" finds it at once.
- **The agent's STT** heard the code as "4417" every time, and "Alfama" variously as AlphaMu, Alphama or Alpha. In auto call 2 the agent said it back every run: "Your locker code at the Alfama gym is 4417."
- **Recall**: `last_recall.ms` 15–20 ms, 630–741 characters, never timed out.
- **Writes**: everything was searchable as soon as the call's job had shut down (0.0 s of polling).
- **Cost**: $0.006–0.007 a run at list prices (about 3,300 input and 230 output tokens of gpt-4.1-mini, 28 s of STT audio, 35–40 s of judged audio; `say` is free).

Latency, in seconds: the medians over runs 1–4 of the worker's `e2e_latency`, which agrees with the caller-side measure to within about 0.2 s. "Cold" is a job's first turn.

| turn | auto | memory off | tools |
|---|---|---|---|
| cold, a statement | 6.59 (the model calls `memory_search` itself) | 5.10 | 6.08 (`memory_add`) |
| warm, a statement | 5.28 (the model calls `memory_search` itself) | 4.19 | |
| cold, the question | 4.80 (recall, no tool call) | 5.10 | 6.32 (`memory_search`) |
| warm, the question | | 3.77 | |

- Recall adds nothing that can be measured: a cold question with recall (4.80 s) is no slower than a cold turn without memory (5.10 s).
- What costs about 1.1–1.5 s is the extra model round trip when the model calls a memory tool. In auto mode gpt-4.1-mini called `memory_search` on both of call 1's statements in all 4 runs.
- The rest is the pipeline: STT `transcription_delay` 1.7–4.8 s through OpenRouter (median 2.3–3.0 s, including the VAD's 0.55 s of silence), LLM first token 0.8–1.9 s, `say` first audio 0.55 s.

# Scenarios with a real model

`scenarios.py` is twenty callers who ring back, typed through the same `AgentSession` and
`AlexeinMemoryAgent` with a real model (gpt-4.1-mini, through OpenAI or OpenRouter) and the real
memory API, in both modes. Each is two or three calls by a fresh app user; between calls it waits
until memory holds the last one. The checks are on what the agent answered in the last call and
on what memory holds; a failure prints every call, every reply and every tool the model used.

```bash
cd integrations/livekit
set -a; . ../../../.livekit-test.env; set +a     # OPENROUTER_API_KEY or OPENAI_API_KEY
export ALEXEIN_API_KEY=tm_... ALEXEIN_API_URL=http://localhost:8210
uv run --with "livekit-plugins-openai~=1.8" python e2e/scenarios.py   # --mode auto|tools, -k NAME
```

What it found, and what was fixed for it, run by run (2026-10-23, OpenRouter, local stack):

| Run | Passed | Found |
|---|---|---|
| 1 | 25/32 | a moved appointment answered with the old date; "suggest a dinner" missed "I'm vegetarian" (words do not match); tools mode left out booking times and order numbers |
| 2 | 30/32 | an agent copied its own recalled "BANANA" replies; tools mode did not search before suggesting |
| 3 | 36/39 | tools mode saved a card number when told not to; "what do you know about me" lost the oldest fact |
| 4-7 | 37/39, 15/20, 20/20, 19/20 | tools mode said "I've noted that" and saved nothing; facts kept no time, so "moved to Lisbon" lost to "lives in Berlin" |
| final | 38/39, then 5/5 on the last failure | the model saved that it was asked not to save a medication |

The model's own judgement is what tools mode depends on; auto mode passed every scenario on
every run since run 2's fixes.
