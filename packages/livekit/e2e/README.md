# Real-room end-to-end test

`room.py` runs twinmemory-livekit in a real LiveKit room against the real twin memory API. It is text in and text out, with `tests/fakes.py`'s `FakeLLM` standing in for a model, so no STT, TTS or LLM keys are needed.

```bash
cd packages/livekit && uv run python e2e/room.py          # exit 0 = every check held
uv run python e2e/room.py --keep-users                    # leave the e2e users in memory to inspect
```

## Needs
- **LiveKit dev server** on `ws://localhost:7880` with key `devkey` and secret `secret`, for example:
  `docker run -d --name twin-livekit-dev -p 127.0.0.1:7880:7880 -p 127.0.0.1:7881:7881 -p 127.0.0.1:7882:7882/udp livekit/livekit-server --dev --bind 0.0.0.0 --node-ip 127.0.0.1`
- **twin memory** at `TWIN_MEMORY_BASE_URL` with a writing key in `TWIN_MEMORY_API_KEY`. They are read from the environment, or else from the KEY=VALUE file at `$E2E_ENV`.
- **`MEMORY_CONTROL_SECRET`**, read from `$E2E_CONTROL_ENV` (default `../twin-memory-frontend/.env`). It is used to delete the users the test made, through `DELETE /v1/control/accounts?org=livekit-dev&project=dev&user=…`.
- No extra dependencies: `livekit-api` comes with `livekit-agents`, and `httpx` comes with `twinmemory`.

The key and the secret are never printed. Logs go to a fresh temp dir, whose path is printed first: `events.jsonl` (one line per agent-side event) and `worker.log`.

## What it does
`worker.py` is the README pattern exactly: `TwinMemory.from_job(ctx)`, then `await ctx.connect()`, then `bind(participant=…)` if the metadata named no user, then `AgentSession(llm=FakeLLM(...))` in text mode with `TwinMemoryAgent(memory, memory_tools=False)`. The fake LLM replies `MEMORY-SEEN:yes` or `MEMORY-SEEN:no`. It logs the full context it was given and `memory.last_recall` to `events.jsonl`.

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
3. **Call 3** uses participant `kiosk-<hex>` and dispatch metadata `{"twinmemory_user_id": "e2e-<hex>"}`.
   - The user is bound from the metadata at `from_job`, before connect.
   - Recall shows the fact.
   - Nothing is saved under the kiosk identity, which still gets a 404 from memory.

Afterwards it checks what was saved:
- 3 threads, one per call;
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
