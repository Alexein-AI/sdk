"""Follow the LangGraph docs page, word for word, against packages published to the rehearsal's
registries and a running memory API - in Python and in TypeScript - and record what each step did.

    python3 scripts/release-rehearsal/rehearse.py --key tm_... [--read-key tm_...] [--base-url URL]

Every command a step runs is one the docs print (`uvx twinmemory-cli ...`, `npx twinmemory-cli ...`),
with only the key and the address filled in. Where a step needs a model it uses a stand-in, so nothing
is spent; memory is the real service. Each run writes runs/<time>/report.md and results.json beside
this file, and works in a temporary folder that is removed afterwards (--keep keeps it).

Standard library only, so it runs on any python3.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = "/docs/integrations/langgraph"


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
    passed: bool = False
    checks: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


class Run:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.steps: list[Step] = []
        self.work = Path(tempfile.mkdtemp(prefix="tm-rehearsal-"))
        self.env = dict(os.environ)
        for name in list(self.env):
            if name.startswith(("TWIN_MEMORY_", "UV_", "npm_config_", "VIRTUAL_ENV")):
                del self.env[name]
        self.env.update(
            npm_config_registry="http://localhost:4873/",
            npm_config_cache=str(HERE / ".cache" / "npm"),
            npm_config_update_notifier="false",
            npm_config_fund="false",
            npm_config_audit="false",
            UV_INDEX="rehearsal=http://localhost:8070/simple/",
            UV_CACHE_DIR=str(HERE / ".cache" / "uv"),
            UV_TOOL_DIR=str(HERE / ".cache" / "uv-tools"),
        )

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
        timeout: int = 900,
    ) -> Step:
        shown = command.replace(self.args.key, "$KEY")
        if self.args.read_key:
            shown = shown.replace(self.args.read_key, "$READ_KEY")
        step = Step(id, title, docs, shown, str(cwd.relative_to(self.work)) or ".")
        started = time.monotonic()
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
        step.seconds = round(time.monotonic() - started, 1)
        step.code = done.returncode
        out = (done.stdout + done.stderr).replace(self.args.key, "$KEY")
        if self.args.read_key:
            out = out.replace(self.args.read_key, "$READ_KEY")
        step.output = "\n".join(line for line in out.splitlines() if not _noise(line))
        self._check(step, done.returncode == expect_code, f"exit code {expect_code}")
        for text in contains:
            self._check(step, text in step.output, f"says {text!r}")
        for text in lacks:
            self._check(step, text not in step.output, f"does not say {text!r}")
        for path in files:
            self._check(step, (cwd / path).exists(), f"wrote {path}")
        step.passed = not step.failed
        self.steps.append(step)
        mark = "PASS" if step.passed else "FAIL"
        print(f"  {mark}  {id:<4} {title} ({step.seconds}s)", flush=True)
        return step

    def check(self, step: Step, ok: bool, what: str) -> None:
        self._check(step, ok, what)
        step.passed = not step.failed

    @staticmethod
    def _check(step: Step, ok: bool, what: str) -> None:
        (step.checks if ok else step.failed).append(what)


def _noise(line: str) -> bool:
    """Package managers' chatter that says nothing about our packages."""
    return line.startswith(("npm warn", "npm notice", "Resolved ", "Prepared ", "Audited ", "Downloading ", " Downloaded ")) or (
        line.startswith((" + ", " - ", " ~ ")) and "==" in line
    )


# ------------------------------------------------------------------------------------- python --

CONVERSE_PY = '''
"""Two conversations through the created graph, its model replaced by a stand-in."""
import sys, time, uuid
from dotenv import load_dotenv

load_dotenv(".env")
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from py_bot import graph as g, memory as m

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
for _ in range(60):
    if m._memory().user(user).search("Leila married", fast=True).found:
        break
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


def python(run: Run) -> None:
    key, url, read = run.args.key, run.args.base_url, run.args.read_key
    cli = "uvx twinmemory-cli"
    py = run.work / "python"
    py.mkdir()
    run.step("P1", "the command runs", "#what-init-does", f"{cli} --version", py, contains=("twinmemory-cli 0.1.0",))

    bot = py / "py-bot"
    run.step(
        "P2",
        "create langgraph py-bot",
        "#create",
        f"{cli} create langgraph py-bot --key {key} --base-url {url}",
        py,
        contains=("ran      uv add", "checked  key: ", "reads and writes", "uv run python -m py_bot.chat --user dana"),
        files=("py-bot/src/py_bot/memory.py", "py-bot/src/py_bot/graph.py", "py-bot/src/py_bot/chat.py", "py-bot/langgraph.json", "py-bot/.env"),
    )
    lock = (bot / "uv.lock").read_text() if (bot / "uv.lock").exists() else ""
    step = run.steps[-1]
    run.check(step, 'name = "twinmemory"' in lock and "localhost:8070" in lock, "installed twinmemory from the package index, by version")

    run.step("P3", "doctor in the new project", "#doctor", f"{cli} doctor", bot, contains=("✓ memory file", "✓ twinmemory 0.2.0", "reads and writes", "All good."))

    (bot / "converse.py").write_text(CONVERSE_PY)
    run.step(
        "P4",
        "two conversations: the second recalls the first",
        "#wire-it-in",
        "uv run python converse.py",
        bot,
        contains=("second turn saw the first: True",),
    )

    app = py / "app"
    run.step("P5a", "an existing LangGraph project (uv init, uv add langgraph langchain)", "#what-init-does", "uv init -q --package app && cd app && uv add -q langgraph langchain", py)
    (app / "src" / "app" / "graph.py").write_text(textwrap.dedent(APP_GRAPH_PY))
    (app / "langgraph.json").write_text(json.dumps({"dependencies": ["."], "graphs": {"agent": "./src/app/graph.py:graph"}, "env": ".env"}))
    (app / ".gitignore").write_text(".venv\n.env\n")
    run.step(
        "P5b",
        "init langgraph",
        "#what-init-does",
        f"{cli} init langgraph --key {key} --base-url {url}",
        app,
        contains=("wrote    ./src/app/memory.py", "uv add 'twinmemory>=0.2'", "checked  key: ", "from app.memory import"),
        files=("src/app/memory.py",),
    )
    run.step("P5c", "the written file imports", "#what-it-writes", "uv run python -c 'import app.memory as m; print(sorted(n for n in dir(m) if n.isupper() or n[0].isupper()))'", app, contains=("MEMORY_TOOLS", "MemoryContext", "MemoryState"))
    run.step("P6", "--dry-run changes nothing", "#what-init-does", f"{cli} init langgraph --force --dry-run", app, contains=("would    write ./src/app/memory.py", "Dry run: nothing was changed."))
    run.step("P7a", "--tools-only", "#what-init-does", f"{cli} init langgraph --force --tools-only --skip-key", app, contains=("wrote",))
    run.check(run.steps[-1], "def recall" not in (app / "src/app/memory.py").read_text(), "the file has no nodes")
    run.step("P7b", "--async", "#what-init-does", f"{cli} init langgraph --force --async --skip-key", app, contains=("wrote",))
    run.check(run.steps[-1], "async def recall" in (app / "src/app/memory.py").read_text(), "the nodes are async")
    if read:
        run.step("P8a", "a key that only reads is called out", "#what-init-does", f"{cli} init langgraph --force --key {read} --base-url {url}", app, contains=("reads only", "this key only reads"))
        run.step("P8b", "doctor with that key", "#doctor", f"{cli} doctor", app, expect_code=1, contains=("only reads, and the memory file saves",))
    plain = py / "plain"
    run.step("P9a", "a project without LangGraph is refused", "#what-init-does", f"uv init -q plain && cd plain && {cli} init langgraph --skip-key", py, expect_code=1, contains=("not a LangGraph project",))
    run.step("P9b", "--yes adds LangGraph", "#what-init-does", f"{cli} init langgraph --yes --skip-key", plain, contains=("wrote", "langgraph>=1.0"))
    (bot / "outage.py").write_text(OUTAGE_PY)
    run.step(
        "P10",
        "memory down: the turn still answers",
        "#when-memory-is-down",
        "uv run python outage.py",
        bot,
        env={"TWIN_MEMORY_BASE_URL": "http://127.0.0.1:9"},
        contains=("twin memory unavailable", "reply: 'Happy to help anyway.'"),
    )


# ----------------------------------------------------------------------------------- typescript --

CONVERSE_TS = '''
// Two conversations through this project's memory.ts, with a stand-in where the model would be.
import "dotenv/config";
import { randomUUID } from "node:crypto";
import { AIMessage, HumanMessage } from "@langchain/core/messages";
import { END, START, StateGraph } from "@langchain/langgraph";
import { Memory } from "twinmemory";
import { MemoryContext, MemoryState, memoryPrompt, recall, remember } from "./src/memory.js";

const seen: string[] = [];
const replies = ["Noted, Porto in June.", "Leila's wedding, in June."];
const graph = new StateGraph(MemoryState, MemoryContext)
  .addNode("recall", recall)
  .addNode("agent", async (state) => {
    seen.push(memoryPrompt(state));
    return { messages: [new AIMessage(replies.shift()!)] };
  })
  .addNode("remember", remember)
  .addEdge(START, "recall").addEdge("recall", "agent").addEdge("agent", "remember").addEdge("remember", END)
  .compile();
const user = `rehearsal-js-${randomUUID().slice(0, 6)}`;
const turn = (thread: string, text: string) =>
  graph.invoke({ messages: [new HumanMessage(text)] }, { context: { user_id: user }, configurable: { thread_id: thread } });
await turn("t-1", "My sister Leila is getting married in Porto in June.");
const dana = new Memory().user(user);
for (let i = 0; i < 60; i++) {
  const found = await dana.search("Leila married", { fast: true }).catch(() => undefined);
  if (found?.found) break;
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
import { MemoryContext, MemoryState, recall, remember } from "./src/memory.js";

const graph = new StateGraph(MemoryState, MemoryContext)
  .addNode("recall", recall)
  .addNode("agent", async () => ({ messages: [new AIMessage("Happy to help anyway.")] }))
  .addNode("remember", remember)
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


def typescript(run: Run) -> None:
    key, url, read = run.args.key, run.args.base_url, run.args.read_key
    cli = "npx -y twinmemory-cli"
    js = run.work / "typescript"
    js.mkdir()
    run.step("J1", "the command runs", "#what-init-does", f"{cli} --version", js, contains=("twinmemory-cli 0.1.0",))

    bot = js / "js-bot"
    run.step(
        "J2",
        "create langgraph js-bot",
        "#create",
        f"{cli} create langgraph js-bot --key {key} --base-url {url}",
        js,
        contains=("ran      npm install", "checked  key: ", "reads and writes", "npm run chat -- --user dana"),
        files=("js-bot/src/memory.ts", "js-bot/src/graph.ts", "js-bot/src/chat.ts", "js-bot/langgraph.json", "js-bot/.env"),
    )
    pkg = json.loads((bot / "package.json").read_text()) if (bot / "package.json").exists() else {}
    run.check(run.steps[-1], pkg.get("dependencies", {}).get("twinmemory", "").startswith(("^", ">=")), "installed twinmemory from the registry, by version")
    run.step("J3", "doctor in the new project", "#doctor", f"{cli} doctor", bot, contains=("✓ memory file", "✓ twinmemory 0.1.0", "reads and writes", "All good."))
    run.step("J3b", "the new project type-checks", "#create", "npm run -s typecheck", bot)
    (bot / "converse.ts").write_text(CONVERSE_TS)
    run.step("J4", "two conversations: the second recalls the first", "#wire-it-in", "npx tsx converse.ts", bot, contains=("second turn saw the first: true",))

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
        f"{cli} init langgraph --key {key} --base-url {url}",
        app,
        contains=("wrote    ./src/memory.ts", "npm install", "twinmemory@>=0.1", "checked  key: ", 'from "./memory.js"'),
        files=("src/memory.ts",),
    )
    run.step("J6", "--dry-run changes nothing", "#what-init-does", f"{cli} init langgraph --force --dry-run", app, contains=("would    write ./src/memory.ts", "Dry run: nothing was changed."))
    run.step("J7", "--tools-only", "#what-init-does", f"{cli} init langgraph --force --tools-only --skip-key", app, contains=("wrote",))
    run.check(run.steps[-1], "export async function recall" not in (app / "src/memory.ts").read_text(), "the file has no nodes")
    run.step("J7b", "--nodes-only", "#what-init-does", f"{cli} init langgraph --force --nodes-only --skip-key", app, contains=("wrote",))
    run.check(run.steps[-1], "memorySearch" not in (app / "src/memory.ts").read_text(), "the file has no tools")
    if read:
        run.step("J8a", "a key that only reads is called out", "#what-init-does", f"{cli} init langgraph --force --key {read} --base-url {url}", app, contains=("reads only", "this key only reads"))
        run.step("J8b", "doctor with that key", "#doctor", f"{cli} doctor", app, expect_code=1, contains=("only reads, and the memory file saves",))
    plain = js / "plain"
    plain.mkdir()
    run.step("J9a", "a project without LangGraph is refused", "#what-init-does", f"npm init -y >/dev/null && {cli} init langgraph --skip-key", plain, expect_code=1, contains=("not a LangGraph project",))
    run.step("J9b", "--yes adds LangGraph", "#what-init-does", f"{cli} init langgraph --yes --skip-key", plain, contains=("wrote", "@langchain/langgraph@>=1.0"))
    (bot / "outage.ts").write_text(OUTAGE_TS)
    run.step(
        "J10",
        "memory down: the turn still answers",
        "#when-memory-is-down",
        "npx tsx outage.ts",
        bot,
        env={"TWIN_MEMORY_API_KEY": "tm_any", "TWIN_MEMORY_BASE_URL": "http://127.0.0.1:9"},
        contains=("twin memory unavailable", 'reply: "Happy to help anyway."'),
    )


# ------------------------------------------------------------------------------------- report --


def landed(run: Run) -> dict:
    """What the memory API's own request log says this run's key did (the console reads the same)."""
    secret = run.args.control_secret
    if not secret:
        return {}
    me = json.loads(_get(f"{run.args.base_url}/v1/me", run.args.key))
    query = f"org={me['org']}&project={me.get('project', '')}&limit=500"
    logs = json.loads(_get(f"{run.args.base_url}/v1/control/logs?{query}", secret))
    ours = [e for e in logs.get("entries", []) if e.get("key_id") == me.get("key_id")]
    users = sorted({e.get("user") for e in ours if str(e.get("user", "")).startswith("rehearsal-")})
    routes: dict[str, int] = {}
    for entry in ours:
        routes[entry["route"]] = routes.get(entry["route"], 0) + 1
    return {"key_id": me.get("key_id"), "requests": len(ours), "routes": routes, "end_users": users}


def _get(url: str, bearer: str) -> str:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"})
    with urllib.request.urlopen(request, timeout=20) as answer:
        return answer.read().decode()


def report(run: Run, out: Path, seen: dict) -> None:
    passed = sum(s.passed for s in run.steps)
    lines = [
        "# twinmemory-cli release rehearsal",
        "",
        f"{time.strftime('%Y-%m-%d %H:%M %Z')}. The docs page {DOCS}, followed with the packages published to the",
        "rehearsal's registries (twinmemory 0.2.0 and twinmemory-cli 0.1.0 on PyPI; twinmemory 0.1.0 and",
        f"twinmemory-cli 0.1.0 on npm), against the memory API at {run.args.base_url}.",
        "",
        f"**{passed} of {len(run.steps)} steps passed.**",
        "",
        "| Step | What | Docs | Result | Time |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in run.steps:
        lines.append(f"| {s.id} | {s.title} | [{s.docs}]({DOCS}{s.docs}) | {'PASS' if s.passed else 'FAIL'} | {s.seconds}s |")
    if seen:
        lines += ["", "## What the memory API recorded for this run's key", "", "```json", json.dumps(seen, indent=2), "```"]
    for s in run.steps:
        lines += ["", f"## {s.id} - {s.title}", "", f"In `{s.cwd}`:", "", "```", f"$ {s.command}", s.output.strip(), f"[exit {s.code}]", "```"]
        lines += [f"- ok: {c}" for c in s.checks] + [f"- **FAILED: {c}**" for c in s.failed]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    (out / "results.json").write_text(json.dumps({"steps": [asdict(s) for s in run.steps], "recorded": seen}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--key", default=os.environ.get("REHEARSAL_KEY", ""), help="a key that writes")
    parser.add_argument("--read-key", default=os.environ.get("REHEARSAL_READ_KEY", ""), help="a key that only reads")
    parser.add_argument("--base-url", default="http://localhost:8210")
    parser.add_argument("--control-secret", default=os.environ.get("MEMORY_CONTROL_SECRET", ""), help="to read the request log back")
    parser.add_argument("--only", choices=["python", "typescript"])
    parser.add_argument("--keep", action="store_true", help="keep the projects it made")
    args = parser.parse_args()
    if not args.key:
        parser.error("--key: a key that writes, from the console under API keys")
    run = Run(args)
    print(f"working in {run.work}")
    try:
        if args.only in (None, "python"):
            print("python")
            python(run)
        if args.only in (None, "typescript"):
            print("typescript")
            typescript(run)
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
    failed = [s.id for s in run.steps if not s.passed]
    print("all passed" if not failed else f"failed: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
