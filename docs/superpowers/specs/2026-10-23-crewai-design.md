# `twinmemory-cli init crewai` - design

2026-10-23. Branch `crewai` of twin-memory-integrations, built on `langgraph-cli` (PR #3).

## Intent

A CrewAI developer adds twin memory to a crew the way a LangGraph developer already can: one command,
`uvx twinmemory-cli init crewai`, writes a `memory.py` into their project as code they own (in the manner
of shadcn), and a few lines in their crew turn it on. From then on, every task in the crew remembers
what that end user said before, and what the crew learned is saved for next time - without the
developer writing glue code. The user whose memory it is comes from the developer's code (the run's
inputs), never from the model.

Why now: the docs' CrewAI page promises a packaged integration ("Soon"); LangGraph's is built and
rehearsed; CrewAI is the next framework on the integrations page.

## Goals

- `twinmemory-cli init crewai`, `create crewai <name>`, and `doctor` for CrewAI, in the existing
  Python `twinmemory-cli` (`packages/python`), sharing its project detection, key setup, install,
  `--dry-run` and conventions with `init langgraph`.
- **Automatic memory by default.** With the written `TwinMemory` passed as the crew's memory, CrewAI's
  own memory machinery runs on twin memory: recall before every task, save after every task, and the
  "Search memory" / "Save to memory" tools it gives every agent.
- **Both kinds of CrewAI project**: classic Python crews (`@CrewBase` in `src/<pkg>/crew.py`) and JSON
  crews (`crew.jsonc`, CrewAI's default since `crewai create` changed).
- A **tools-only fallback preset** (`--tools-only`): memory tools with the user fixed in code, plus
  `save_result()` for after a run - the approach Mem0 and Zep use - for crews that do not use CrewAI's
  memory slot, or for when the automatic route breaks.
- Same standards as LangGraph: fails open when memory is down, a wrong key still raises; the written
  file passes ruff at 88 columns; tests run real crews against a recorded memory API with a stand-in
  model; the release rehearsal gains CrewAI steps; the docs page is rewritten.

## Non-goals

- JavaScript. CrewAI is Python only; there is no `npx ... init crewai`.
- CrewAI Flows (`[tool.crewai] type = "flow"`). `init` says so and stops.
- Editing the developer's `crew.py` or `crew.jsonc`. Like LangGraph, `init` writes its own file and
  prints the lines to add.
- Publishing. Everything stays local until the packages are released (as for LangGraph).

## Anti-goals (would make it a failure even if it works)

- One end user's memories reaching another's run - by a shared object, a race, or a model naming a
  user. A wrong user is worse than no memory.
- Memory being down stopping a crew.
- A CrewAI release silently breaking memory: if the extension point changes, `init`/`doctor` and the
  written file must say so, not quietly stop remembering.

## What CrewAI is today (verified from crewai 1.15.28 source)

The builder should re-verify against the version pinned at build time; CrewAI ships nightly.

- Memory was rewritten in 1.x: one `crewai.memory.Memory` (pydantic model, `memory_kind="memory"`)
  replaces short-term/long-term/entity/external memory and `memory_config`; anything online describing
  those is stale. `Crew(memory=...)` and `Agent(memory=...)` take `bool | Memory | MemoryScope |
  MemorySlice` (a discriminated union on `memory_kind`). `memory=True` builds a LanceDB-backed
  `Memory`.
- At run time (crewai/agent/core.py `_retrieve_memory_context`): before each task, `memory.recall(
  task.description, limit=5)` - the description with inputs filled in - and the matches go into the
  task prompt under "# Memories from past conversations". Failures there are swallowed.
- After each task's final answer (agents/agent_builder/base_agent_executor.py `_save_to_memory`): the
  text `Task: … / Agent: <role> / Expected result: … / Result: …` goes through
  `memory.extract_memories(raw)` (an LLM call), then `memory.remember_many(extracted, agent_role=…,
  root_scope=…)`, normally on a background thread pool; the crew drains pending writes before it
  finishes. Skipped when the memory is `read_only` or the output is a delegation.
- With memory set, every agent gets "Search memory" (`recall(q, limit=20)`) and "Save to memory"
  (`remember(content)`, which must return a `MemoryRecord`; the tool reads `.scope` and `.importance`).
- `StorageBackend` (the documented extension point) searches by embedding vector, not text, so it does
  not fit twin memory. What fits, and was run successfully: subclass `Memory`, override `recall`,
  `remember`, `remember_many` and `extract_memories`, and pass a dummy `storage=` so LanceDB is never
  built. This is **not a documented extension point** - hence the version guard below.
- Crew inputs are not passed to memory. `@before_kickoff` (classic) / `before_kickoff_callbacks` (JSON)
  receive the inputs before interpolation and may change them.
- JSON crews reference Python objects as `{"python": "module.attr"}` for `memory` (must resolve to an
  instance) and for `before_kickoff_callbacks` / `after_kickoff_callbacks`; one module-level object is
  therefore shared by every run of that crew in the process.
- Project detection: `pyproject.toml` has `[tool.crewai]` with `type = "crew"` (or `"flow"`); a JSON
  crew also has `definition = "crew.jsonc"` and no `src/`; a classic crew has `src/<pkg>/crew.py` with
  `@CrewBase`. Fallback signal: a `crewai` dependency.

## The written file: `memory.py`

Beside the crew (`src/<pkg>/memory.py` classic; next to `crew.jsonc` for JSON). Like LangGraph's file,
it is plain code the developer owns, with `FAST`, `STRICT`, `MAX_CHARS` and `TIMEOUT` at the top, a
client made lazily with `Memory(fail_open=not STRICT, integration="crewai", timeout=TIMEOUT)` from
`twinmemory`, and the user id never taken from a model.

**Default (automatic) - `TwinMemory`**, a subclass of `crewai.memory.Memory`:

- `user_id: str | None`. Set per run from the inputs (below). Any call with no user set raises a clear
  error naming how to pass it.
- `recall(query, …)` → twin memory `search` (fast per `FAST`) → a list of CrewAI `MemoryMatch`es built
  from the brief's known lines, facts and passages, best first, capped at `limit`. Memory down
  (fail-open) → `[]`. No memory yet (404) → `[]`.
- `extract_memories(content)` → `[content]`: no model call; twin memory does its own reading. This also
  saves the developer one LLM call per task.
- `remember(content, …)` / `remember_many(contents, …)` → twin memory `add`, as notes, with the agent's
  role as `author` where CrewAI gives one, the run as the `session` (one id per kickoff), and stable
  item ids so a retried save does not duplicate. `remember` returns a `MemoryRecord` (the Save tool
  reads it). Memory down → a record is still returned and the save is skipped, logged.
- `forget`, `reset`, `update` and the rest: no-ops or clear `NotImplementedError` naming the twin
  memory route to use - the builder chooses which, but none may touch another user.
- Constructed with a dummy storage so CrewAI's LanceDB is never created.

**Whose memory, per run** (revised after review; see "Decisions made in review" below):

- The user is held **per run**, in a `contextvars.ContextVar`, not on the memory object. One
  `TwinMemory` can then serve many runs, including concurrent runs for different users: each kickoff
  runs in a context of its own (`kickoff_for_each_async` / `akickoff_for_each` go through
  `asyncio.to_thread`, which copies the context), and CrewAI's background saves run in a copy of the
  caller's context (`Memory._submit_save` uses `contextvars.copy_context()`; verified in 1.15.28). So
  there is no shared per-user state to lock, refuse, or leave stuck when a run fails.
- The file's `whose(inputs)` takes `user_id` out of the run's inputs and sets the variable. It is
  required on every run: a kickoff without `user_id` raises at once, before any task runs, so a run
  never inherits the previous run's user in the same thread.
- Classic: `memory = TwinMemory()` as a class attribute of the crew is fine (it holds no user), with a
  `@before_kickoff` method that returns `whose(inputs)`. JSON: `"memory": {"python":
  "memory.twin_memory"}` and `"before_kickoff_callbacks": [{"python": "memory.whose"}]`. No after-kickoff
  callback is needed.
- Tests prove two users never mix: sequential runs, `kickoff_for_each_async` with different users,
  saves on the background pool, and a run that fails part-way followed by a run for another user.

**Checked up front, because CrewAI swallows memory errors.** CrewAI catches every exception from
`recall` (only an event is emitted) and from saving (only a log line), so a wrong key or a missing user
would otherwise quietly turn memory off - an anti-goal. So:

- `whose()` raises when `user_id` is missing (above).
- `whose()` checks the key once per process (`me()`; cached): a key the service does not know raises at
  kickoff; memory being unreachable skips the check (fail open) and it is tried again on the next run.
- Inside `recall` and the saves, the file logs every failure itself (a warning on the `twinmemory`
  logger) before CrewAI swallows it, so a broken memory is visible in the developer's logs.

**`--tools-only` preset:** no `TwinMemory`; `memory_tools(user_id)` returns CrewAI `BaseTool`s ("Search
memory", "Read memory", and "Save to memory" when the key writes) with the user bound in code, and
`save_result(user_id, output)` saves a finished crew's result. `--fast` as for LangGraph. No `--async`
preset (CrewAI's memory calls are synchronous).

## `init crewai`

Same flow and flags as `init langgraph` (`--dir`, `--file`, `--force`, `--no-install`, `--key`,
`--base-url`, `--skip-key`, `--yes`, `--dry-run`, `--sdk`), and:

- Detects the project kind from `[tool.crewai]`: classic or JSON. A Flow, or no CrewAI at all: says so
  and stops (no `--yes` to add CrewAI - a crew is not something `init` can make up; `create` is for
  that).
- Requires the installed `crewai` to be at least the version the subclass was verified against (1.15
  at the time of writing) and, because the extension point is undocumented, warns when the installed
  version is newer than the newest the release was tested with. `doctor` does the same check.
- Installs `twinmemory>=0.2` (and nothing else; the project already has `crewai`).
- Prints, for the project's kind, the exact lines to add (the classic class lines above, or the two
  `crew.jsonc` entries) and how to kick off with `inputs={"user_id": ...}`.

## `create crewai <name>`

A classic crew project, as `crewai create crew --classic` would make it (uv, `[tool.crewai] type =
"crew"`, `src/<pkg>/{crew.py, main.py, config/agents.yaml, config/tasks.yaml}`), with memory already
wired in, the key set up as for LangGraph, and `--model` passed to the agents' `llm`. Whether to
generate the files ourselves or run `crewai create crew --classic` and then `init` is left to the
builder; the result must not depend on the developer having the `crewai` CLI installed beforehand.

## `doctor`

Recognises the CrewAI file (its header names `init crewai`), checks `crewai` is within the tested
range, and checks the key as today.

## Tests and proof

- A real crew (CrewAI's own classes) with a stand-in LLM, against a recorded memory API: recall before
  a task lands in the prompt; a task's result is saved under the right user with the agent's role; the
  Save and Search tools hit twin memory; memory down → the crew finishes; a wrong key raises; two users
  never mix (including the JSON shared-object refusal).
- Every preset's written file passes ruff (as `init langgraph`'s do).
- `init` over a classic and a JSON project made by `crewai create`, a Flow (refused), and an old CrewAI.
- The release rehearsal (`scripts/release-rehearsal/rehearse.py`) gains CrewAI steps that follow the
  rewritten docs page.

## Docs

`content/docs/integrations/crewai.mdx` in twin-memory-frontend is rewritten like the LangGraph page:
what `init crewai` checks and writes, both project kinds, whose memory, failing open, the tools-only
preset, `create`, `doctor`, and the version note.

## Decisions made in review (Claude's calls, for the user to check)

- Per-run user in a context variable instead of a refusal lock: it serves concurrent users safely, and
  a failed run cannot leave memory stuck on one user. This replaces the first draft's "refuse a second
  user on the shared JSON object", which the review showed fails on error paths and does not hold for
  classic crews either (`Crew.copy()` shares the memory object).
- One key check per process at kickoff, skipped when memory is unreachable.
- Failures inside CrewAI's memory calls are logged by the file itself.

## Left to the builder

- How `MemoryMatch` scores and text are built from a brief.
- Session ids and item ids for saves.
- Which unsupported `Memory` methods are no-ops and which raise.
- How `create` makes its project.
- The tested-version upper bound and how it is recorded.
