"""Follow the integration docs, word for word, against packages published to the rehearsal's
registries and a running memory API - in Python and in TypeScript - and record what each step did.

    python3 scripts/release-rehearsal/rehearse.py [--key tm_...] [--read-key tm_...] [--base-url URL]

Every command a step runs is one the docs print (`uvx alexein-cli ...`, `npx @alexein/cli ...`),
with only the key and the address filled in. Where a step needs a model it uses a stand-in, so
nothing is spent; memory is the real service. Each run writes runs/<time>/report.md and
results.json beside this file, and works in a temporary folder that is removed afterwards (--keep
keeps it).

The key decides what the steps that need one expect. It is asked about once, first, with the
free `GET /v2/me`:
  - a key the service knows: those steps must work (a conversation recalls the one before it);
  - a key it does not know (401): those steps must stop with the 401 the CLIs and the SDKs say;
  - no --key: those steps are skipped, and the report says which. Everything else - installing
    from the registries, create/init writing their files, doctor's other checks, the written code
    importing and the graphs compiling with no key at all - runs either way.

Standard library only, so it runs on any python3.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = "/docs/integrations/langgraph"
NPM = "http://localhost:4873/"
PYPI = "http://localhost:8070/simple/"

# What the service says to a key it did not issue, through the CLIs' key check and the SDKs.
UNKNOWN_KEY = "the service does not know this key"
REJECTED = "401: a bearer this service issued is required"


@dataclass
class Step:
    id: str
    title: str
    docs: str
    command: str
    cwd: str
    code: int = 0
    output: str = ""
    seconds: float = 0.0
    result: str = "FAIL"  # PASS, FAIL or SKIP
    note: str = ""
    checks: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.result == "PASS"


class Run:
    def __init__(self, args: argparse.Namespace, key: str, versions: dict[str, str]) -> None:
        self.args = args
        # "valid", "rejected" (the service answered 401) or "none" (no --key).
        self.key = key
        self.versions = versions
        self.steps: list[Step] = []
        self.work = Path(tempfile.mkdtemp(prefix="alexein-rehearsal-"))
        self.env = dict(os.environ)
        # Nothing of this shell's reaches the steps: no key or address of Alexein's, no registry,
        # no virtual environment, and no model provider's key, so a stand-in can never be
        # bypassed into a real, paid call.
        for name in list(self.env):
            if name.startswith(("ALEXEIN_", "TWIN_MEMORY_", "UV_", "npm_config_", "VIRTUAL_ENV")) or (
                name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MODEL")
            ):
                del self.env[name]
        self.env.update(
            npm_config_registry=NPM,
            npm_config_cache=str(HERE / ".cache" / "npm"),
            npm_config_update_notifier="false",
            npm_config_fund="false",
            npm_config_audit="false",
            UV_INDEX=f"rehearsal={PYPI}",
            UV_CACHE_DIR=str(HERE / ".cache" / "uv"),
            UV_TOOL_DIR=str(HERE / ".cache" / "uv-tools"),
            OPENAI_AGENTS_DISABLE_TRACING="1",
            CREWAI_DISABLE_TELEMETRY="true",
            OTEL_SDK_DISABLED="true",
        )

    # -- what a step expects, by the key it was given ---------------------------------------

    def by_key(self, *, valid: object, rejected: object, none: object) -> object:
        return {"valid": valid, "rejected": rejected, "none": none}[self.key]

    def key_flags(self) -> str:
        """`init`'s and `create`'s key flags: the key and the address, or no key at all."""
        url = self.args.base_url
        return f"--key {self.args.key} --base-url {url}" if self.args.key else f"--skip-key --base-url {url}"

    def key_said(self) -> tuple[str, ...]:
        """What `init` and `create` say of the key they were given."""
        return self.by_key(  # type: ignore[return-value]
            valid=("checked  key: ",),
            rejected=(f"warning  the key did not check out: {UNKNOWN_KEY}",),
            none=("added    ALEXEIN_API_KEY= to .env: fill it in later",),
        )

    # -- steps ------------------------------------------------------------------------------

    def _shown(self, text: str) -> str:
        for secret, name in ((self.args.key, "$KEY"), (self.args.read_key, "$READ_KEY")):
            if secret:
                text = text.replace(secret, name)
        return text

    def step(
        self,
        id: str,
        title: str,
        docs: str,
        command: str,
        cwd: Path,
        *,
        expect_code: int = 0,
        contains: tuple[str, ...] = (),
        lacks: tuple[str, ...] = (),
        files: tuple[str, ...] = (),
        env: dict[str, str] | None = None,
        needs_key: bool = False,
        timeout: int = 900,
    ) -> Step:
        """Run one command the docs print, and check what it said and did. `needs_key`: a step
        whose point is a call memory answers, skipped without a key and expected to be refused
        with a key the service does not know - the caller passes what that refusal says."""
        step = Step(id, title, docs, self._shown(command), self._where(cwd))
        if needs_key and self.key == "none":
            step.result, step.note = "SKIP", "needs a key: run with --key"
            self.steps.append(step)
            print(f"  SKIP  {id:<5} {title} (needs a key)", flush=True)
            return step
        if needs_key and self.key == "rejected":
            step.note = "the key was refused (401): checked that this step says so"
        started = time.monotonic()
        try:
            done = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                env={**self.env, **(env or {})},
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
            code, out = done.returncode, done.stdout + done.stderr
        except subprocess.TimeoutExpired as late:
            code = -1
            said = [x.decode(errors="replace") if isinstance(x, bytes) else (x or "") for x in (late.stdout, late.stderr)]
            out = "".join(said) + f"\n[timed out after {timeout}s]"
        step.seconds = round(time.monotonic() - started, 1)
        step.code = code
        step.output = "\n".join(line for line in self._shown(out).splitlines() if not _noise(line))
        self._check(step, code == expect_code, f"exit code {expect_code}")
        for text in contains:
            self._check(step, text in step.output, f"says {text!r}")
        for text in lacks:
            self._check(step, text not in step.output, f"does not say {text!r}")
        for path in files:
            self._check(step, (cwd / path).exists(), f"wrote {path}")
        step.result = "FAIL" if step.failed else "PASS"
        self.steps.append(step)
        print(f"  {step.result}  {id:<5} {title} ({step.seconds}s)", flush=True)
        return step

    def check(self, step: Step, ok: bool, what: str) -> None:
        """One more check on a step that ran."""
        if step.result == "SKIP":
            return
        self._check(step, ok, what)
        if step.failed and step.result == "PASS":
            step.result = "FAIL"
            print(f"  FAIL  {step.id:<5} {what}", flush=True)

    def _where(self, cwd: Path) -> str:
        try:
            return str(cwd.relative_to(self.work)) or "."
        except ValueError:
            return str(cwd)

    @staticmethod
    def _check(step: Step, ok: bool, what: str) -> None:
        (step.checks if ok else step.failed).append(what)


def _noise(line: str) -> bool:
    """Package managers' chatter that says nothing about our packages."""
    return line.startswith(
        ("npm warn", "npm notice", "Resolved ", "Prepared ", "Audited ", "Downloading ", " Downloaded ", "Installed ")
    ) or (line.startswith((" + ", " - ", " ~ ")) and "==" in line)


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""


# -------------------------------------------------------------------- python: langgraph --

# The graph `create langgraph` made, imported with no key anywhere: the file says importing needs
# none. Its model is made on first use, so none is made here either.
IMPORTS_PY = """
from py_bot import graph as g

print("nodes:", " ".join(sorted(n for n in g.graph.nodes if not n.startswith("__"))))
print("tools:", " ".join(t.name for t in g.TOOLS))
"""

CONVERSE_PY = '''
"""Two conversations through the created graph, its model replaced by a stand-in."""
import time, uuid
from dotenv import load_dotenv

load_dotenv(".env")
from alexein import AlexeinError, Memory
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from py_bot import graph as g

seen = []


class Model(GenericFakeChatModel):
    def _generate(self, messages, *a, **k):
        seen.append(messages[0].content)
        return super()._generate(messages, *a, **k)


model = Model(messages=iter([AIMessage("Noted, Porto in June."), AIMessage("Leila's wedding, in June.")]))
g._model = lambda: model
user = "rehearsal-py-" + uuid.uuid4().hex[:6]


def turn(thread, text):
    return g.graph.invoke({"messages": [HumanMessage(text)]}, config={"configurable": {"thread_id": thread}}, context={"user_id": user})


turn("t-1", "My sister Leila is getting married in Porto in June.")
dana = Memory().user(user)
for _ in range(60):
    try:
        if dana.search("Leila married", fast=True).memories:
            break
    except AlexeinError:
        pass
    time.sleep(0.5)
turn("t-2", "When is Leila getting married?")
print("user:", user)
print("second turn's prompt ends:", repr(seen[-1][-140:]))
print("second turn saw the first:", "Porto" in seen[-1])
'''

OUTAGE_PY = '''
import logging, time
from dotenv import load_dotenv

load_dotenv(".env", override=False)
logging.basicConfig(level=logging.WARNING, format="log: %(name)s %(message)s")
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from py_bot import graph as g

model = GenericFakeChatModel(messages=iter([AIMessage("Happy to help anyway.")]))
g._model = lambda: model
t0 = time.time()
out = g.graph.invoke({"messages": [HumanMessage("Hi")]}, config={"configurable": {"thread_id": "t"}}, context={"user_id": "rehearsal-outage"})
print(f"reply: {out['messages'][-1].text!r} after {time.time() - t0:.1f}s")
'''

APP_GRAPH_PY = '''
from langgraph.graph import START, END, StateGraph, MessagesState


def agent(state: MessagesState) -> dict:
    return {"messages": []}


graph = StateGraph(MessagesState).add_node("agent", agent).add_edge(START, "agent").add_edge("agent", END).compile()
'''

# The wiring `init langgraph` prints, typed in: the nodes around a model node, and the tools.
WIRED_PY = '''
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.memory import MemoryContext, MemoryState, memory


def agent(state: MemoryState) -> dict:
    return {"messages": [AIMessage("ok" + memory.prompt(state))]}


builder = StateGraph(MemoryState, context_schema=MemoryContext)
builder.add_node("recall", memory.recall)
builder.add_node("agent", agent)
builder.add_node("remember", memory.remember)
builder.add_edge(START, "recall")
builder.add_edge("recall", "agent")
builder.add_edge("agent", "remember")
builder.add_edge("remember", END)
graph = builder.compile()
print("compiled:", " ".join(sorted(n for n in graph.nodes if not n.startswith("__"))))
print("tools:", " ".join(t.name for t in memory.tools(write=True)))
print("memory is", type(memory).__module__ + "." + type(memory).__name__)
'''


def python(run: Run) -> None:
    url, read = run.args.base_url, run.args.read_key
    cli = "uvx alexein-cli"
    version = run.versions["alexein-cli"]
    py = run.work / "python"
    py.mkdir()
    run.step("P1", "the command runs", "#what-init-does", f"{cli} --version", py, contains=(f"alexein-cli {version}",))

    bot = py / "py-bot"
    step = run.step(
        "P2",
        "create langgraph py-bot",
        "#create",
        f"{cli} create langgraph py-bot {run.key_flags()}",
        py,
        contains=(
            "wrote    src/py_bot/memory.py, graph.py, chat.py",
            "ran      uv add 'alexein[langgraph]>=0.3' python-dotenv langchain-anthropic",
            "ran      uv add --dev 'langgraph-cli[inmem]'",
            "ALEXEIN_API_URL in .env",
            *run.key_said(),
            "uv run -m py_bot.chat --user dana",
        ),
        files=("py-bot/src/py_bot/memory.py", "py-bot/src/py_bot/graph.py", "py-bot/src/py_bot/chat.py", "py-bot/langgraph.json", "py-bot/.env"),
    )
    lock = _read(bot / "uv.lock")
    run.check(step, 'name = "alexein"' in lock and "localhost:8070" in lock, "installed alexein from the rehearsal's index, by version")
    run.check(step, f'name = "alexein"\nversion = "{run.versions["alexein"]}"' in lock, f"locked alexein {run.versions['alexein']}")
    run.check(step, "from alexein.langgraph import" in _read(bot / "src/py_bot/memory.py"), "memory.py imports alexein.langgraph")

    run.step(
        "P3",
        "doctor in the new project",
        "#doctor",
        f"{cli} doctor",
        bot,
        expect_code=run.by_key(valid=0, rejected=1, none=1),  # type: ignore[arg-type]
        contains=(
            f"✓ memory file src/py_bot/memory.py (written by {version}, for LangGraph)",
            "✓ dependencies: alexein[langgraph]>=0.3",
            f"✓ alexein {run.versions['alexein']}",
            "✓ alexein.langgraph imports",
            *run.by_key(  # type: ignore[misc]
                valid=("✓ ALEXEIN_API_KEY from .env", "reads and writes", "All good."),
                rejected=("✓ ALEXEIN_API_KEY from .env", f"✓ ALEXEIN_API_URL from .env: {url}", f"✗ key at {url}", UNKNOWN_KEY, "Fix what is marked ✗"),
                none=("✗ no ALEXEIN_API_KEY", "Fix what is marked ✗"),
            ),
        ),
    )
    (bot / "imports.py").write_text(IMPORTS_PY)
    run.step(
        "P4",
        "the graph imports and compiles with no key",
        "#create",
        "uv run python imports.py",
        bot,
        contains=("nodes: agent recall remember tools", "tools: memory_search memory_open"),
    )

    (bot / "converse.py").write_text(CONVERSE_PY)
    run.step(
        "P5",
        "two conversations: the second recalls the first",
        "#wire-it-in",
        "uv run python converse.py",
        bot,
        needs_key=True,
        expect_code=run.by_key(valid=0, rejected=1, none=0),  # type: ignore[arg-type]
        contains=run.by_key(  # type: ignore[arg-type]
            valid=("second turn saw the first: True",),
            rejected=(f"AuthenticationError: {REJECTED}",),
            none=(),
        ),
    )

    app = py / "app"
    run.step("P6a", "an existing LangGraph project (uv init, uv add langgraph langchain)", "#what-init-does", "uv init -q --package app && cd app && uv add -q langgraph langchain", py)
    (app / "src" / "app" / "graph.py").write_text(textwrap.dedent(APP_GRAPH_PY))
    (app / "langgraph.json").write_text(json.dumps({"dependencies": ["."], "graphs": {"agent": "./src/app/graph.py:graph"}, "env": ".env"}))
    (app / ".gitignore").write_text(".venv\n.env\n")
    run.step(
        "P6b",
        "init langgraph",
        "#what-init-does",
        f"{cli} init langgraph {run.key_flags()}",
        app,
        contains=(
            "wrote    ./src/app/memory.py",
            "ran      uv add 'alexein[langgraph]>=0.3'",
            *run.key_said(),
            "from app.memory import MemoryContext, MemoryState, memory",
        ),
        lacks=(".env is not in .gitignore",),
        files=("src/app/memory.py",),
    )
    (app / "wired.py").write_text(WIRED_PY)
    run.step(
        "P6c",
        "the written file imports with no key, and the printed wiring compiles",
        "#wire-it-in",
        "uv run python wired.py",
        app,
        contains=("compiled: agent recall remember", "tools: memory_search memory_open memory_add", "memory is alexein.langgraph.AlexeinMemory"),
    )
    before = _read(app / "src/app/memory.py")
    step = run.step("P7", "--dry-run changes nothing", "#what-init-does", f"{cli} init langgraph --force --dry-run", app, contains=("would    write ./src/app/memory.py", "Dry run: nothing was changed."))
    run.check(step, _read(app / "src/app/memory.py") == before, "memory.py is as it was")
    step = run.step(
        "P8",
        "--fast",
        "#what-init-does",
        f"{cli} init langgraph --force --fast --skip-key",
        app,
        contains=("wrote    ./src/app/memory.py", "kept     alexein[langgraph]>=0.3: already a dependency"),
    )
    run.check(step, "FAST = True" in _read(app / "src/app/memory.py"), "the file says FAST = True")
    run.step(
        "P8b",
        "the presets are gone: --tools-only is refused",
        "#what-init-does",
        f"{cli} init langgraph --force --tools-only --skip-key",
        app,
        expect_code=2,
        contains=("unrecognized arguments: --tools-only",),
    )
    if read:
        run.step("P9a", "a key that only reads is called out", "#what-init-does", f"{cli} init langgraph --force --key {read} --base-url {url}", app, contains=("reads only", "this key only reads"))
        run.step("P9b", "doctor with that key", "#doctor", f"{cli} doctor", app, contains=("the key only reads",))
    plain = py / "plain"
    run.step(
        "P10a",
        "a project without LangGraph is refused",
        "#what-init-does",
        f"uv init -q plain && cd plain && {cli} init langgraph --skip-key",
        py,
        expect_code=1,
        contains=("this project does not use LangGraph; run again with --yes", "Nothing changed."),
    )
    run.check(run.steps[-1], not (plain / "memory.py").exists(), "wrote nothing")
    step = run.step(
        "P10b",
        "--yes adds LangGraph",
        "#what-init-does",
        f"{cli} init langgraph --yes",
        plain,
        contains=("wrote    ./", "ran      uv add 'alexein[langgraph]>=0.3'"),
    )
    # Where it went is uv's layout's to decide (`uv init` makes a src/ package since 0.12): the
    # module is the one the printed wiring imports.
    named = re.search(r"from ([\w.]+) import MemoryContext", step.output)
    module = named.group(1) if named else "memory"
    run.step(
        "P10c",
        "the file imports there, with no key",
        "#what-it-writes",
        f"uv run python -c 'import {module} as m; print(\"imported:\", type(m.memory).__module__)'",
        plain,
        contains=("imported: alexein.langgraph",),
    )
    (bot / "outage.py").write_text(OUTAGE_PY)
    run.step(
        "P11",
        "memory down: the turn still answers",
        "#when-memory-is-down",
        "uv run python outage.py",
        bot,
        env={"ALEXEIN_API_KEY": "tm_any", "ALEXEIN_API_URL": "http://127.0.0.1:9"},
        contains=("Alexein unavailable", "reply: 'Happy to help anyway.'"),
    )


# -------------------------------------------------------------- python: openai-agents --

AGENT_PY = '''
from agents import Agent

agent = Agent(name="Assistant", instructions="Be brief.")
'''

AGENT_WIRED_PY = '''
from agents import Agent, RunConfig

from agent_app.memory import MemoryContext, memory

agent = Agent[MemoryContext](name="Assistant", tools=memory.tools())
config = RunConfig(call_model_input_filter=memory.recall)
print("tools:", " ".join(t.name for t in agent.tools))
print("context:", MemoryContext(user_id="dana").user_id)
'''

AGENT_CONVERSE_PY = '''
"""Two runs of an agent wired as `init openai-agents` prints, its model a scripted stand-in."""
import asyncio, time, uuid
from dotenv import load_dotenv

load_dotenv(".env")
from agents import Agent, RunConfig, Runner
from agents.testing.model import ScriptedModel, assistant_message
from alexein import AlexeinError, Memory
from agent_app.memory import MemoryContext, memory

model = ScriptedModel([[assistant_message("Noted, Porto in June.")], [assistant_message("In June.")]])
agent = Agent(name="Assistant", instructions="Be brief.", model=model, tools=memory.tools())
config = RunConfig(call_model_input_filter=memory.recall, tracing_disabled=True)
user = "rehearsal-oa-" + uuid.uuid4().hex[:6]


async def turn(text: str) -> None:
    result = await Runner.run(agent, text, context=MemoryContext(user_id=user, session_id=uuid.uuid4().hex), run_config=config)
    await memory.remember(result)


async def main() -> None:
    await turn("My sister Leila is getting married in Porto in June.")
    dana = Memory().user(user)
    for _ in range(60):
        try:
            if dana.search("Leila married", fast=True).memories:
                break
        except AlexeinError:
            pass
        time.sleep(0.5)
    await turn("When is Leila getting married?")
    told = model.calls[-1].system_instructions or ""
    print("user:", user)
    print("second run's instructions end:", repr(told[-140:]))
    print("second run saw the first:", "Porto" in told)


asyncio.run(main())
'''


def python_openai_agents(run: Run) -> None:
    cli = "uvx alexein-cli"
    docs = "/docs/integrations/openai-agents"
    work = run.work / "python"
    app = work / "agent-app"
    run.step("PA1", "an existing OpenAI Agents SDK project (uv init, uv add openai-agents)", f"{docs}#what-init-does", "uv init -q --package agent-app && cd agent-app && uv add -q openai-agents python-dotenv", work)
    (app / "src" / "agent_app" / "bot.py").write_text(AGENT_PY)
    (app / ".gitignore").write_text(".venv\n.env\n")
    run.step(
        "PA2",
        "init openai-agents",
        f"{docs}#what-init-does",
        f"{cli} init openai-agents {run.key_flags()}",
        app,
        contains=(
            "wrote    ./src/agent_app/memory.py",
            "ran      uv add 'alexein[openai-agents]>=0.3'",
            *run.key_said(),
            "from agent_app.memory import MemoryContext, memory",
        ),
        files=("src/agent_app/memory.py",),
    )
    (app / "wired.py").write_text(AGENT_WIRED_PY)
    run.step(
        "PA3",
        "the written file imports with no key, and the agent builds",
        f"{docs}#wire-it-in",
        "uv run python wired.py",
        app,
        contains=("tools: memory_search memory_open", "context: dana"),
    )
    (app / "converse.py").write_text(AGENT_CONVERSE_PY)
    run.step(
        "PA4",
        "two runs: the second recalls the first",
        f"{docs}#wire-it-in",
        "uv run python converse.py",
        app,
        needs_key=True,
        expect_code=run.by_key(valid=0, rejected=1, none=0),  # type: ignore[arg-type]
        contains=run.by_key(  # type: ignore[arg-type]
            valid=("second run saw the first: True",),
            rejected=(f"AuthenticationError: {REJECTED}",),
            none=(),
        ),
    )


# ------------------------------------------------------------------- typescript: langgraph --

IMPORTS_TS = '''
// The graph `create langgraph` made, imported with no key anywhere.
import { graph } from "./src/graph.js";

console.log("nodes:", Object.keys(graph.nodes).filter((n) => !n.startsWith("__")).sort().join(" "));
'''

CONVERSE_TS = '''
// Two conversations through this project's memory.ts, with a stand-in where the model would be.
import "dotenv/config";
import { randomUUID } from "node:crypto";
import { AIMessage, HumanMessage } from "@langchain/core/messages";
import { END, START, StateGraph } from "@langchain/langgraph";
import { Memory } from "@alexein/sdk";
import { memory, MemoryAnnotation, MemoryContext } from "./src/memory.js";

const seen: string[] = [];
const replies = ["Noted, Porto in June.", "Leila's wedding, in June."];
const graph = new StateGraph(MemoryAnnotation, MemoryContext)
  .addNode("recall", memory.recall)
  .addNode("agent", async (state) => {
    seen.push(memory.prompt(state));
    return { messages: [new AIMessage(replies.shift()!)] };
  })
  .addNode("remember", memory.remember)
  .addEdge(START, "recall").addEdge("recall", "agent").addEdge("agent", "remember").addEdge("remember", END)
  .compile();
const user = `rehearsal-js-${randomUUID().slice(0, 6)}`;
const turn = (thread: string, text: string) =>
  graph.invoke({ messages: [new HumanMessage(text)] }, { context: { user_id: user }, configurable: { thread_id: thread } });
await turn("t-1", "My sister Leila is getting married in Porto in June.");
const dana = new Memory().user(user);
for (let i = 0; i < 60; i++) {
  const found = await dana.search("Leila married", { fast: true }).catch(() => undefined);
  if (found?.memories.length) break;
  await new Promise((r) => setTimeout(r, 500));
}
await turn("t-2", "When is Leila getting married?");
console.log("user:", user);
console.log("second turn's prompt ends:", JSON.stringify(seen[1]!.slice(-140)));
console.log("second turn saw the first:", seen[1]!.includes("Porto"));
'''

OUTAGE_TS = '''
import { AIMessage, HumanMessage } from "@langchain/core/messages";
import { END, START, StateGraph } from "@langchain/langgraph";
import { memory, MemoryAnnotation, MemoryContext } from "./src/memory.js";

const graph = new StateGraph(MemoryAnnotation, MemoryContext)
  .addNode("recall", memory.recall)
  .addNode("agent", async () => ({ messages: [new AIMessage("Happy to help anyway.")] }))
  .addNode("remember", memory.remember)
  .addEdge(START, "recall").addEdge("recall", "agent").addEdge("agent", "remember").addEdge("remember", END)
  .compile();
const t0 = Date.now();
const out = await graph.invoke({ messages: [new HumanMessage("Hi")] }, { context: { user_id: "rehearsal-outage" } });
console.log(`reply: ${JSON.stringify(out.messages.at(-1)!.text)} after ${((Date.now() - t0) / 1000).toFixed(1)}s`);
'''

APP_GRAPH_TS = '''
import { END, MessagesValue, START, StateGraph, StateSchema } from "@langchain/langgraph";

const State = new StateSchema({ messages: MessagesValue });
export const graph = new StateGraph(State)
  .addNode("agent", async () => ({ messages: [] }))
  .addEdge(START, "agent")
  .addEdge("agent", END)
  .compile();
'''

# The wiring `init langgraph` prints, typed in.
WIRED_TS = '''
import { AIMessage } from "@langchain/core/messages";
import { END, START, StateGraph } from "@langchain/langgraph";
import { memory, MemoryAnnotation, MemoryContext } from "./src/memory.js";

const graph = new StateGraph(MemoryAnnotation, MemoryContext)
  .addNode("recall", memory.recall)
  .addNode("agent", async (state) => ({ messages: [new AIMessage("ok" + memory.prompt(state))] }))
  .addNode("remember", memory.remember)
  .addEdge(START, "recall")
  .addEdge("recall", "agent")
  .addEdge("agent", "remember")
  .addEdge("remember", END)
  .compile();
console.log("compiled:", Object.keys(graph.nodes).filter((n) => !n.startsWith("__")).sort().join(" "));
console.log("tools:", memory.tools({ write: true }).map((t) => t.name).join(" "));
'''


def typescript(run: Run) -> None:
    url, read = run.args.base_url, run.args.read_key
    cli = "npx -y @alexein/cli"
    version = run.versions["@alexein/cli"]
    js = run.work / "typescript"
    js.mkdir()
    run.step("J1", "the command runs", "#what-init-does", f"{cli} --version", js, contains=(f"@alexein/cli {version}",))

    bot = js / "js-bot"
    step = run.step(
        "J2",
        "create langgraph js-bot",
        "#create",
        f"{cli} create langgraph js-bot {run.key_flags()}",
        js,
        contains=(
            "wrote    src/memory.ts, graph.ts, chat.ts",
            "ran      npm install '@alexein/sdk@>=0.3'",
            "ran      npm install --save-dev typescript tsx @types/node @langchain/langgraph-cli",
            "ALEXEIN_API_URL in .env",
            *run.key_said(),
            "npm run chat -- --user dana",
        ),
        files=("js-bot/src/memory.ts", "js-bot/src/graph.ts", "js-bot/src/chat.ts", "js-bot/langgraph.json", "js-bot/.env"),
    )
    pkg = json.loads(_read(bot / "package.json") or "{}")
    run.check(step, pkg.get("dependencies", {}).get("@alexein/sdk", "").startswith(("^", ">=")), "depends on @alexein/sdk by version")
    lock = json.loads(_read(bot / "package-lock.json") or "{}")
    sdk = lock.get("packages", {}).get("node_modules/@alexein/sdk", {})
    run.check(step, sdk.get("resolved", "").startswith(NPM), "installed @alexein/sdk from the rehearsal's registry")
    run.check(step, sdk.get("version") == run.versions["@alexein/sdk"], f"installed @alexein/sdk {run.versions['@alexein/sdk']}")
    run.step(
        "J3",
        "doctor in the new project",
        "#doctor",
        f"{cli} doctor",
        bot,
        expect_code=run.by_key(valid=0, rejected=1, none=1),  # type: ignore[arg-type]
        contains=(
            f"✓ memory file src/memory.ts (written by {version})",
            "✓ dependencies: @alexein/sdk, @langchain/langgraph, @langchain/core, zod",
            f"✓ @alexein/sdk {run.versions['@alexein/sdk']}",
            *run.by_key(  # type: ignore[misc]
                valid=("✓ ALEXEIN_API_KEY from .env", "reads and writes", "All good."),
                rejected=("✓ ALEXEIN_API_KEY from .env", f"✓ ALEXEIN_API_URL from .env: {url}", f"✗ key at {url}: {UNKNOWN_KEY}", "Fix what is marked ✗"),
                none=("✗ no ALEXEIN_API_KEY", "Fix what is marked ✗"),
            ),
        ),
    )
    run.step("J3b", "the new project type-checks", "#create", "npm run -s typecheck", bot)
    (bot / "imports.ts").write_text(IMPORTS_TS)
    run.step("J3c", "the graph imports and compiles with no key", "#create", "npx tsx imports.ts", bot, contains=("nodes: agent recall remember tools",))
    (bot / "converse.ts").write_text(CONVERSE_TS)
    run.step(
        "J4",
        "two conversations: the second recalls the first",
        "#wire-it-in",
        "npx tsx converse.ts",
        bot,
        needs_key=True,
        expect_code=run.by_key(valid=0, rejected=1, none=0),  # type: ignore[arg-type]
        contains=run.by_key(  # type: ignore[arg-type]
            valid=("second turn saw the first: true",),
            rejected=(f"AuthenticationError: {REJECTED}",),
            none=(),
        ),
    )

    app = js / "app"
    app.mkdir()
    (app / "src").mkdir()
    (app / "src" / "graph.ts").write_text(APP_GRAPH_TS)
    (app / "langgraph.json").write_text(json.dumps({"graphs": {"agent": "./src/graph.ts:graph"}, "env": ".env"}))
    (app / ".gitignore").write_text("node_modules\n.env\n")
    run.step("J5a", "an existing LangGraph.js project (npm init, npm install @langchain/langgraph)", "#what-init-does", "npm init -y >/dev/null && npm pkg set type=module && npm install -s @langchain/langgraph @langchain/core zod typescript @types/node", app)
    run.step(
        "J5b",
        "init langgraph",
        "#what-init-does",
        f"{cli} init langgraph {run.key_flags()}",
        app,
        contains=(
            "wrote    ./src/memory.ts",
            "ran      npm install '@alexein/sdk@>=0.3'",
            *run.key_said(),
            'import { memory, MemoryAnnotation, MemoryContext } from "./memory.js";',
        ),
        lacks=(".env is not in .gitignore",),
        files=("src/memory.ts",),
    )
    (app / "wired.ts").write_text(WIRED_TS)
    run.step(
        "J5c",
        "the written file imports with no key, and the printed wiring compiles",
        "#wire-it-in",
        "npx -y tsx wired.ts",
        app,
        contains=("compiled: agent recall remember", "tools: memory_search memory_open memory_add"),
    )
    before = _read(app / "src/memory.ts")
    step = run.step("J6", "--dry-run changes nothing", "#what-init-does", f"{cli} init langgraph --force --dry-run", app, contains=("would    write ./src/memory.ts", "Dry run: nothing was changed."))
    run.check(step, _read(app / "src/memory.ts") == before, "memory.ts is as it was")
    step = run.step("J7", "--tools-only", "#what-init-does", f"{cli} init langgraph --force --tools-only --skip-key", app, contains=("wrote    ./src/memory.ts",))
    written = _read(app / "src/memory.ts")
    run.check(step, "MemoryAnnotation" not in written and "export { MemoryContext }" in written, "the file has no state for the nodes")
    step = run.step("J7b", "--nodes-only", "#what-init-does", f"{cli} init langgraph --force --nodes-only --skip-key", app, contains=("wrote    ./src/memory.ts",))
    written = _read(app / "src/memory.ts")
    run.check(step, "memory.tools(" not in written and "MemoryAnnotation" in written, "the file has no tools")
    if read:
        run.step("J8a", "a key that only reads is called out", "#what-init-does", f"{cli} init langgraph --force --key {read} --base-url {url}", app, contains=("reads only",))
        run.step("J8b", "doctor with that key", "#doctor", f"{cli} doctor", app, contains=("reads only",))
    plain = js / "plain"
    plain.mkdir()
    run.step(
        "J9a",
        "a project without LangGraph is refused",
        "#what-init-does",
        f"npm init -y >/dev/null && {cli} init langgraph --skip-key",
        plain,
        expect_code=1,
        contains=("this project does not use LangGraph; run again with --yes", "Nothing changed."),
    )
    run.step("J9b", "--yes adds LangGraph", "#what-init-does", f"{cli} init langgraph --yes", plain, contains=("wrote    ./memory.ts", "'@langchain/langgraph@>=1.0'"))
    (bot / "outage.ts").write_text(OUTAGE_TS)
    run.step(
        "J10",
        "memory down: the turn still answers",
        "#when-memory-is-down",
        "npx tsx outage.ts",
        bot,
        env={"ALEXEIN_API_KEY": "tm_any", "ALEXEIN_API_URL": "http://127.0.0.1:9"},
        contains=("Alexein is unavailable", 'reply: "Happy to help anyway."'),
    )


# ---------------------------------------------------------------- typescript: openai-agents --

AGENT_TS = '''
import { Agent } from "@openai/agents";

export const agent = new Agent({ name: "Assistant", instructions: "Be brief." });
'''

AGENT_WIRED_TS = '''
import { Agent } from "@openai/agents";
import { memory, type MemoryContext } from "./src/memory.js";

const agent = new Agent<MemoryContext>({ name: "Assistant", tools: memory.tools() });
const context: MemoryContext = { userId: "dana" };
console.log("tools:", agent.tools.map((t) => t.name).join(" "));
console.log("context:", context.userId);
'''

AGENT_CONVERSE_TS = '''
// Two runs of an agent wired as `init openai-agents` prints, its model a scripted stand-in.
import "dotenv/config";
import { randomUUID } from "node:crypto";
import { Agent, type Model, type ModelRequest, type ModelResponse, run, Usage } from "@openai/agents";
import { Memory } from "@alexein/sdk";
import { memory, type MemoryContext } from "./src/memory.js";

const told: string[] = [];
const replies = ["Noted, Porto in June.", "In June."];
const model: Model = {
  async getResponse(request: ModelRequest): Promise<ModelResponse> {
    told.push(request.systemInstructions ?? "");
    const text = replies.shift()!;
    return { usage: new Usage(), output: [{ type: "message", role: "assistant", status: "completed", content: [{ type: "output_text", text }] }] };
  },
  async *getStreamedResponse() {
    throw new Error("not streamed");
  },
};
const agent = new Agent<MemoryContext>({ name: "Assistant", instructions: "Be brief.", model, tools: memory.tools() });
const user = `rehearsal-oa-js-${randomUUID().slice(0, 6)}`;
const turn = async (text: string) => {
  const result = await run(agent, text, { context: { userId: user, sessionId: randomUUID() }, callModelInputFilter: memory.recall });
  await memory.remember(result);
};
await turn("My sister Leila is getting married in Porto in June.");
const dana = new Memory().user(user);
for (let i = 0; i < 60; i++) {
  const found = await dana.search("Leila married", { fast: true }).catch(() => undefined);
  if (found?.memories.length) break;
  await new Promise((r) => setTimeout(r, 500));
}
await turn("When is Leila getting married?");
console.log("user:", user);
console.log("second run's instructions end:", JSON.stringify(told.at(-1)!.slice(-140)));
console.log("second run saw the first:", told.at(-1)!.includes("Porto"));
'''


def typescript_openai_agents(run: Run) -> None:
    cli = "npx -y @alexein/cli"
    docs = "/docs/integrations/openai-agents"
    app = run.work / "typescript" / "agent-app"
    app.mkdir(parents=True)
    (app / "src").mkdir()
    (app / "src" / "bot.ts").write_text(AGENT_TS)
    (app / ".gitignore").write_text("node_modules\n.env\n")
    run.step("JA1", "an existing OpenAI Agents SDK project (npm install @openai/agents)", f"{docs}#what-init-does", "npm init -y >/dev/null && npm pkg set type=module && npm install -s @openai/agents zod dotenv typescript @types/node", app)
    run.step(
        "JA2",
        "init openai-agents",
        f"{docs}#what-init-does",
        f"{cli} init openai-agents {run.key_flags()}",
        app,
        contains=(
            "wrote    ./src/memory.ts",
            "ran      npm install '@alexein/sdk@>=0.3'",
            *run.key_said(),
            'import { memory, type MemoryContext } from "./memory.js";',
        ),
        files=("src/memory.ts",),
    )
    (app / "wired.ts").write_text(AGENT_WIRED_TS)
    run.step("JA3", "the written file imports with no key, and the agent builds", f"{docs}#wire-it-in", "npx -y tsx wired.ts", app, contains=("tools: memory_search memory_open", "context: dana"))
    (app / "converse.ts").write_text(AGENT_CONVERSE_TS)
    run.step(
        "JA4",
        "two runs: the second recalls the first",
        f"{docs}#wire-it-in",
        "npx -y tsx converse.ts",
        app,
        needs_key=True,
        expect_code=run.by_key(valid=0, rejected=1, none=0),  # type: ignore[arg-type]
        contains=run.by_key(  # type: ignore[arg-type]
            valid=("second run saw the first: true",),
            rejected=(f"AuthenticationError: {REJECTED}",),
            none=(),
        ),
    )


# ------------------------------------------------------------------------------------- crewai --

STAND_PY = """
import os
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")
from crewai.llms.base_llm import BaseLLM


SHOWN = []  # every prompt the model was shown


class Stand(BaseLLM):
    def call(self, messages, *args, **kwargs):
        text = messages if isinstance(messages, str) else "\\n".join(str(m.get("content")) for m in messages)
        SHOWN.append(text)
        return "Final Answer: Noted."

    def supports_function_calling(self):
        return False
"""

IMPORTS_CREW_PY = """
from trip_crew.crew import TripCrew
from trip_crew.memory import alexein_memory, whose

print("memory is", type(alexein_memory).__module__ + "." + type(alexein_memory).__name__)
print("crew class:", TripCrew.__name__, "whose:", callable(whose))
"""

CONVERSE_CREW_PY = """
import time, uuid
from dotenv import load_dotenv

load_dotenv(".env")
from stand import SHOWN, Stand
from alexein import AlexeinError, Memory
from trip_crew import crew as c, main

c.MODEL = Stand(model="stand-in")
user = "rehearsal-crew-" + uuid.uuid4().hex[:6]
main.ask(user, "I just moved to Lisbon for a job at Acme.")
dana = Memory().user(user)
for _ in range(60):
    try:
        if dana.search("Lisbon Acme", fast=True).memories:
            break
    except AlexeinError:
        pass
    time.sleep(0.5)
main.ask(user, "Where do I live these days, Lisbon or Porto?")
print("user:", user)
print("second run saw the first:", "moved to Lisbon" in SHOWN[-1])
"""

OUTAGE_CREW_PY = """
import logging
from dotenv import load_dotenv

load_dotenv(".env", override=False)
logging.basicConfig(level=logging.WARNING, format="log: %(name)s %(message)s")
from stand import Stand
from trip_crew import crew as c, main

c.MODEL = Stand(model="stand-in")
print("reply:", main.ask("rehearsal-outage", "Hi"))
"""

# Answers to `crewai create crew`'s questions for a JSON crew: one agent, one task, no memory of
# CrewAI's own.
JSON_CREW_ANSWERS = (
    "Personal assistant\\nHelp the user\\nYou work for one person.\\n\\nn\\nn\\nn\\n"
    "The user says: {question}\\nA short reply.\\nn\\nn\\n"
)


def crewai(run: Run) -> None:
    read = run.args.read_key
    cli = "uvx alexein-cli"
    version = run.versions["alexein-cli"]
    crewai_cli = "uvx --from 'crewai>=1.15,<1.16' crewai"
    docs = "/docs/integrations/crewai"
    work = run.work / "crewai"
    work.mkdir()
    bot = work / "trip-crew"
    run.step(
        "C1",
        "create crewai trip-crew",
        f"{docs}#create",
        f"{cli} create crewai trip-crew {run.key_flags()}",
        work,
        contains=("ran      uv add 'alexein[crewai]>=0.3'", *run.key_said(), 'uv run run_crew --user dana "I just moved to Lisbon."'),
        files=("trip-crew/src/trip_crew/memory.py", "trip-crew/src/trip_crew/crew.py", "trip-crew/.env"),
    )
    run.step(
        "C2",
        "doctor in the new crew",
        f"{docs}#doctor",
        f"{cli} doctor",
        bot,
        expect_code=run.by_key(valid=0, rejected=1, none=1),  # type: ignore[arg-type]
        contains=(
            f"✓ memory file src/trip_crew/memory.py (written by {version}, for CrewAI)",
            "✓ dependencies: alexein[crewai]>=0.3",
            "✓ crewai 1.15",
            "✓ alexein.crewai imports",
            *run.by_key(  # type: ignore[misc]
                valid=("reads and writes", "All good."),
                rejected=("✓ ALEXEIN_API_KEY from .env", UNKNOWN_KEY, "Fix what is marked ✗"),
                none=("✗ no ALEXEIN_API_KEY", "Fix what is marked ✗"),
            ),
        ),
    )
    (bot / "imports.py").write_text(IMPORTS_CREW_PY)
    run.step("C2b", "the crew imports with no key", f"{docs}#what-it-writes", "uv run python imports.py", bot, contains=("memory is alexein.crewai.AlexeinMemory", "crew class: TripCrew whose: True"))
    (bot / "stand.py").write_text(STAND_PY)
    (bot / "converse.py").write_text(CONVERSE_CREW_PY)
    run.step(
        "C3",
        "two runs: the second recalls the first",
        f"{docs}#what-it-writes",
        "uv run python converse.py",
        bot,
        needs_key=True,
        expect_code=run.by_key(valid=0, rejected=1, none=0),  # type: ignore[arg-type]
        contains=run.by_key(  # type: ignore[arg-type]
            valid=("second run saw the first: True",),
            rejected=(f"AuthenticationError: {REJECTED}",),
            none=(),
        ),
    )

    run.step("C4a", "a classic crew made by crewai create --classic", f"{docs}#what-init-does", f"{crewai_cli} create crew classic_crew --classic --skip-provider < /dev/null", work, contains=("created successfully",))
    run.step(
        "C4b",
        "init crewai into the classic crew",
        f"{docs}#what-init-does",
        f"{cli} init crewai {run.key_flags()}",
        work / "classic_crew",
        contains=("wrote    ./src/classic_crew/memory.py", "ran      uv add 'alexein[crewai]>=0.3'", "memory = alexein_memory", "@before_kickoff", *run.key_said()),
        files=("src/classic_crew/memory.py",),
    )
    run.step("C5a", "a JSON crew made by crewai create", f"{docs}#what-init-does", f"printf '{JSON_CREW_ANSWERS}' | {crewai_cli} create crew json_crew --skip-provider", work, contains=("created successfully",))
    run.step(
        "C5b",
        "init crewai into the JSON crew",
        f"{docs}#what-init-does",
        f"{cli} init crewai --skip-key",
        work / "json_crew",
        contains=("wrote    ./memory.py", '"memory": {"python": "memory.alexein_memory"}', '"before_kickoff_callbacks": [{"python": "memory.whose"}]'),
        files=("memory.py",),
    )
    flow = work / "flow"
    flow.mkdir()
    (flow / "pyproject.toml").write_text('[project]\nname = "flow"\n\n[tool.crewai]\ntype = "flow"\n')
    run.step("C6", "a Flow is refused", f"{docs}#what-init-does", f"{cli} init crewai --skip-key", flow, expect_code=1, contains=("Flows are not supported",))
    if read:
        run.step("C7", "a key that only reads is called out", f"{docs}#what-init-does", f"{cli} init crewai --force --key {read} --base-url {run.args.base_url}", work / "classic_crew", contains=("reads only", "this key only reads"))
    (bot / "outage.py").write_text(OUTAGE_CREW_PY)
    run.step(
        "C8",
        "memory down: the crew still answers",
        f"{docs}#when-memory-is-down",
        "uv run python outage.py",
        bot,
        env={"ALEXEIN_API_KEY": "tm_any", "ALEXEIN_API_URL": "http://127.0.0.1:9"},
        contains=("Alexein unavailable", "reply: Noted."),
    )


# ---------------------------------------------------------------------------------- setup --


def _get(url: str, bearer: str | None = None) -> tuple[int, str]:
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as answer:
            return answer.status, answer.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")


def published() -> dict[str, str]:
    """What the rehearsal's registries hold of ours: the versions this run rehearses."""
    versions: dict[str, str] = {}
    for name in ("@alexein/sdk", "@alexein/cli"):
        _, body = _get(NPM + name.replace("/", "%2F"))
        versions[name] = json.loads(body).get("dist-tags", {}).get("latest", "")
    for name in ("alexein", "alexein-cli", "alexein-livekit"):
        _, body = _get(f"{PYPI}{name}/")
        found = re.findall(rf"{name.replace('-', '_')}-([0-9][^-]*?)(?:-py3|\.tar\.gz)", body)
        versions[name] = max(found, key=lambda v: [int(n) for n in re.findall(r"\d+", v)], default="")
    return versions


def key_state(args: argparse.Namespace) -> str:
    """What the service says of --key: "valid", "rejected" (401), or "none" without one."""
    if not args.key:
        return "none"
    status, body = _get(f"{args.base_url}/v2/me", args.key)
    if status == 200:
        return "valid"
    if status == 401:
        return "rejected"
    raise SystemExit(f"the memory API at {args.base_url} answered GET /v2/me with {status}: {body[:200]}")


# ------------------------------------------------------------------------------------- report --


def landed(run: Run) -> dict:
    """What the memory API's own request log says this run's key did (the console reads the same)."""
    secret = run.args.control_secret
    if not secret or run.key != "valid":
        return {}
    _, body = _get(f"{run.args.base_url}/v2/me", run.args.key)
    me = json.loads(body)
    query = f"org={me['org']}&project={me.get('project', '')}&limit=500"
    _, body = _get(f"{run.args.base_url}/v1/control/logs?{query}", secret)
    ours = [e for e in json.loads(body).get("entries", []) if e.get("key_id") == me.get("key_id")]
    users = sorted({e.get("user") for e in ours if str(e.get("user", "")).startswith("rehearsal-")})
    routes: dict[str, int] = {}
    for entry in ours:
        routes[entry["route"]] = routes.get(entry["route"], 0) + 1
    return {"key_id": me.get("key_id"), "requests": len(ours), "routes": routes, "end_users": users}


KEY_SAID = {
    "valid": "a key the service knows: the steps that need one must work",
    "rejected": "a key the service does not know (401): the steps that need one must stop with the 401 the CLIs and SDKs say",
    "none": "no key: the steps that need one are skipped",
}


def report(run: Run, out: Path, seen: dict) -> None:
    passed = sum(s.result == "PASS" for s in run.steps)
    skipped = [s for s in run.steps if s.result == "SKIP"]
    ran = len(run.steps) - len(skipped)
    v = run.versions
    lines = [
        "# Alexein release rehearsal",
        "",
        f"{time.strftime('%Y-%m-%d %H:%M %Z')}. The integration docs ({DOCS} and its siblings), followed with the packages",
        f"published to the rehearsal's registries (PyPI: alexein {v['alexein']}, alexein-cli {v['alexein-cli']},",
        f"alexein-livekit {v['alexein-livekit']}; npm: @alexein/sdk {v['@alexein/sdk']}, @alexein/cli {v['@alexein/cli']}),",
        f"against the memory API at {run.args.base_url}. Key: {KEY_SAID[run.key]}.",
        "",
        f"**{passed} of {ran} steps passed**" + (f", {len(skipped)} skipped for want of a key." if skipped else "."),
        "",
        "| Step | What | Docs | Result | Time |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in run.steps:
        page = s.docs if s.docs.startswith("/") else DOCS + s.docs
        result = s.result + (" (401 expected)" if s.note.startswith("the key was refused") and s.passed else "")
        lines.append(f"| {s.id} | {s.title} | [{s.docs}]({page}) | {result} | {s.seconds}s |")
    if skipped:
        lines += ["", "Skipped, needing a key the service knows: " + ", ".join(f"{s.id} ({s.title})" for s in skipped) + "."]
    if seen:
        lines += ["", "## What the memory API recorded for this run's key", "", "```json", json.dumps(seen, indent=2), "```"]
    for s in run.steps:
        lines += ["", f"## {s.id} - {s.title}", "", f"In `{s.cwd}`:", ""]
        if s.result == "SKIP":
            lines += ["```", f"$ {s.command}", "```", f"- skipped: {s.note}"]
            continue
        lines += ["```", f"$ {s.command}", s.output.strip(), f"[exit {s.code}]", "```"]
        lines += [f"- note: {s.note}"] if s.note else []
        lines += [f"- ok: {c}" for c in s.checks] + [f"- **FAILED: {c}**" for c in s.failed]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    results = {"key": run.key, "versions": v, "steps": [asdict(s) for s in run.steps], "recorded": seen}
    (out / "results.json").write_text(json.dumps(results, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--key", default=os.environ.get("REHEARSAL_KEY", ""), help="a key that writes; without one, the steps that need it are skipped")
    parser.add_argument("--read-key", default=os.environ.get("REHEARSAL_READ_KEY", ""), help="a key that only reads")
    parser.add_argument("--base-url", default="http://localhost:8210")
    parser.add_argument("--control-secret", default=os.environ.get("MEMORY_CONTROL_SECRET", ""), help="to read the request log back")
    parser.add_argument("--only", choices=["python", "typescript", "crewai"])
    parser.add_argument("--keep", action="store_true", help="keep the projects it made")
    args = parser.parse_args()
    args.base_url = args.base_url.rstrip("/")
    try:
        _get(NPM + "-/ping")
        _get(PYPI)
    except OSError:
        parser.error(f"the registries are not up: docker compose up -d in {HERE}, then ./publish.sh")
    versions = published()
    if not all(versions.values()):
        missing = ", ".join(name for name, found in versions.items() if not found)
        parser.error(f"not published to the rehearsal's registries: {missing}. Run ./publish.sh")
    try:
        key = key_state(args)
    except OSError as error:
        parser.error(f"no memory API at {args.base_url}: {error}")
    run = Run(args, key, versions)
    print(f"working in {run.work}")
    print(f"key: {KEY_SAID[key]}")
    try:
        if args.only in (None, "python"):
            print("python")
            python(run)
            python_openai_agents(run)
        if args.only in (None, "typescript"):
            print("typescript")
            typescript(run)
            typescript_openai_agents(run)
        if args.only in (None, "crewai"):
            print("crewai")
            crewai(run)
    finally:
        out = HERE / "runs" / time.strftime("%Y%m%d-%H%M%S")
        out.mkdir(parents=True)
        try:
            seen = landed(run)
        except Exception as error:  # the report matters more than this part of it
            seen = {"error": str(error)}
        report(run, out, seen)
        print(f"report: {out / 'report.md'}")
        if args.keep:
            print(f"projects kept in {run.work}")
        else:
            shutil.rmtree(run.work, ignore_errors=True)
    failed = [s.id for s in run.steps if s.result == "FAIL"]
    skipped = [s.id for s in run.steps if s.result == "SKIP"]
    print(("all passed" if not failed else f"failed: {', '.join(failed)}") + (f"; skipped (no key): {', '.join(skipped)}" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
