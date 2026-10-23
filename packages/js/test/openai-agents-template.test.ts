/**
 * The `memory.ts` that `twinmemory-cli init openai-agents` writes, run inside the OpenAI Agents
 * SDK's own runner - with a scripted model standing in for OpenAI - against a recorded memory API,
 * and checked as a developer's project would check it: strict TypeScript, and prettier at its
 * defaults.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { Agent, MemorySession, run, setTracingDisabled } from "@openai/agents";
import { AuthenticationError, Memory, ServiceUnavailableError } from "twinmemory";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { render } from "../src/render.js";
import { calls, says, Scripted } from "./agents.js";
import { GENERATED as ALL_GENERATED } from "./helpers.js";

/** This file's own corner, so files running in parallel never remove each other's. */
const GENERATED = ALL_GENERATED + "openai-agents-template/";

beforeAll(() => setTracingDisabled(true));

interface Sent {
  path: string;
  headers: Record<string, string>;
  body: Record<string, any>;
}

const SEARCHED = {
  query: "q",
  found: 1,
  known: ["Dana lives in Lisbon."],
  facts: [],
  hits: [{ path: "passages/p1.md", id: "p1", text: "Dana: I moved to Lisbon." }],
};

function answer(path: string): Response {
  const route = path.split("/").pop();
  if (route === "search") return Response.json(SEARCHED);
  if (route === "read")
    return Response.json({ path: "passages/p1.md", text: "Dana: I moved to Lisbon." });
  if (route === "add") return Response.json({ items: [], queued: 1, pending: 1 }, { status: 202 });
  return Response.json({});
}

const down = () => Response.json({ detail: "rebuilding" }, { status: 503 });
const wrongKey = () => Response.json({ detail: "bad key" }, { status: 401 });

function client(respond: (path: string, body: any) => Response, failOpen = true) {
  const sent: Sent[] = [];
  const memory = new Memory({
    apiKey: "tm_test",
    failOpen,
    integration: "openai-agents",
    maxRetries: 0,
    logger: () => {},
    fetch: async (input, init) => {
      const path = new URL(String(input)).pathname;
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      sent.push({ path, headers: init?.headers as Record<string, string>, body });
      return respond(path, body);
    },
  });
  return { memory, sent };
}

type Module = Record<string, any>;
let counter = 0;

/** The file as `init` writes it, imported fresh, with its client answered by `respond`. */
async function load(
  parts = ["nodes", "tools"],
  respond: (path: string, body: any) => Response = answer,
  failOpen = true,
) {
  const dir = join(GENERATED, `memory-${process.pid}-${counter++}`);
  mkdirSync(dir, { recursive: true });
  const path = join(dir, "memory.ts");
  writeFileSync(
    path,
    render("openai_agents/memory.ts.tmpl", parts, { version: "test", fast: "false" }),
  );
  const module: Module = await import(pathToFileURL(path).href);
  const { memory, sent } = client(respond, failOpen);
  module.useMemory(memory);
  return { module, sent };
}

const routes = (sent: Sent[]) => sent.map((s) => s.path.split("/").pop());
const bodies = (sent: Sent[], route: string) =>
  sent.filter((s) => s.path.endsWith(route)).map((s) => s.body);
const CONTEXT = { userId: "dana", sessionId: "conv-7" };

/** One turn of a plain agent: run with `recall`, then `remember`. */
async function turn(m: Module, model: Scripted, input = "Where do I live?", extra = {}) {
  const agent = new Agent({ name: "Assistant", instructions: "Be brief.", model, ...extra });
  const result = await run(agent, input, { context: CONTEXT, callModelInputFilter: m.recall });
  await m.remember(result);
  return result;
}

// --------------------------------------------------------------- recall and remember --

describe("the written file in a run", () => {
  it("recalls before the model and saves the turn after", async () => {
    const { module, sent } = await load();
    const model = new Scripted([[says("You live in Lisbon.")]]);

    const result = await turn(module, model);

    expect(result.finalOutput).toBe("You live in Lisbon.");
    expect(routes(sent)).toEqual(["search", "add"]);
    expect(new Set(sent.map((s) => s.headers["X-Twin-Account"]))).toEqual(new Set(["dana"]));
    expect(bodies(sent, "search")[0]!.query).toBe("Where do I live?");
    expect(model.calls[0]!.systemInstructions).toMatch(/^Be brief\.\n\nWhat you remember/);
    expect(model.calls[0]!.systemInstructions).toContain("Dana lives in Lisbon.");
    const items = bodies(sent, "add")[0]!.items;
    expect(items.map((i: any) => [i.role, i.text, i.author])).toEqual([
      ["user", "Where do I live?", undefined],
      ["assistant", "You live in Lisbon.", "Assistant"],
    ]);
    expect(items.map((i: any) => i.session)).toEqual(["conv-7", "conv-7"]);
  });

  it("searches once in a tool loop, and every call has the memory", async () => {
    const { module, sent } = await load();
    const model = new Scripted([
      [calls("memory_read", { path: "passages/p1.md" }, "c1")],
      [says("Lisbon.")],
    ]);

    await turn(module, model, "Where do I live?", { tools: module.MEMORY_TOOLS });

    expect(routes(sent)).toEqual(["search", "read", "add"]); // recall, the tool, remember
    for (const call of model.calls) expect(call.systemInstructions).toContain("Lisbon");
    const items = bodies(sent, "add")[0]!.items;
    expect(items.map((i: any) => i.role)).toEqual(["user", "assistant"]);
  });

  it("gives the agent after a handoff the memory too", async () => {
    const { module, sent } = await load();
    const expertModel = new Scripted([[says("Lisbon, as you said.")]]);
    const expert = new Agent({ name: "Expert", instructions: "Know things.", model: expertModel });
    const triage = Agent.create({
      name: "Triage",
      model: new Scripted([[calls("transfer_to_Expert", {}, "h1")]]),
      handoffs: [expert],
    });

    const result = await run(triage, "Where do I live?", {
      context: CONTEXT,
      callModelInputFilter: module.recall,
    });
    await module.remember(result);

    expect(routes(sent)).toEqual(["search", "add"]);
    expect(expertModel.calls[0]!.systemInstructions).toContain("Dana lives in Lisbon.");
    expect(bodies(sent, "add")[0]!.items[1].author).toBe("Expert");
  });

  it("remembers a stream once it has completed", async () => {
    const { module, sent } = await load();
    const agent = new Agent({ name: "Assistant", model: new Scripted([[says("Lisbon.")]]) });

    const stream = await run(agent, "Where do I live?", {
      context: CONTEXT,
      callModelInputFilter: module.recall,
      stream: true,
    });
    for await (const _ of stream.toTextStream());
    await stream.completed;
    await module.remember(stream);

    expect(routes(sent)).toEqual(["search", "add"]);
    expect(bodies(sent, "add")[0]!.items[1].text).toBe("Lisbon.");
  });

  it("never lets the memory land in a session", async () => {
    const { module, sent } = await load();
    const session = new MemorySession();
    const model = new Scripted([[says("Hello.")], [says("Lisbon.")]]);
    const agent = new Agent({ name: "Assistant", model });
    for (const input of ["Hi", "Where do I live?"]) {
      const result = await run(agent, input, {
        context: CONTEXT,
        callModelInputFilter: module.recall,
        session,
      });
      await module.remember(result);
    }

    expect(JSON.stringify(await session.getItems())).not.toContain("Dana lives in Lisbon.");
    expect(bodies(sent, "search").map((b) => b.query)).toEqual(["Hi", "Where do I live?"]);
    expect(bodies(sent, "add")[1]!.items[0].text).toBe("Where do I live?");
  });

  it("saves the same result twice under the same ids", async () => {
    const { module, sent } = await load();
    const result = await turn(module, new Scripted([[says("Lisbon.")]]));
    await module.remember(result);
    const [first, second] = bodies(sent, "add");
    expect(first!.items.map((i: any) => i.id)).toEqual(second!.items.map((i: any) => i.id));
  });

  it("saves structured output as JSON", async () => {
    const { module, sent } = await load();
    const model = new Scripted([[says('{"city":"Lisbon"}')]]);
    await turn(module, model, "Where do I live?", {
      outputType: z.object({ city: z.string() }),
    });
    expect(JSON.parse(bodies(sent, "add")[0]!.items[1].text)).toEqual({ city: "Lisbon" });
  });

  it("recalls nothing for a user with no memory yet", async () => {
    const { module } = await load(undefined, (path) =>
      path.endsWith("search")
        ? Response.json({ detail: "no such account" }, { status: 404 })
        : answer(path),
    );
    const model = new Scripted([[says("Hello.")]]);
    await turn(module, model);
    expect(model.calls[0]!.systemInstructions).toBe("Be brief.");
  });

  it("takes any context with a userId, and must have one", async () => {
    const { module, sent } = await load();
    const agent = new Agent({ name: "A", model: new Scripted([[says("Hi.")], [says("Hi.")]]) });
    const result = await run(agent, "Hi", {
      context: { userId: "dana", plan: "pro" },
      callModelInputFilter: module.recall,
    });
    await module.remember(result);
    expect(new Set(sent.map((s) => s.headers["X-Twin-Account"]))).toEqual(new Set(["dana"]));
    expect(bodies(sent, "add")[0]!.items[0].session).toBeUndefined();

    const before = sent.length;
    await expect(
      run(agent, "Hi", { context: {}, callModelInputFilter: module.recall }),
    ).rejects.toThrow(/whose memory/);
    expect(sent.length).toBe(before);
  });

  it("says where its requests came from", async () => {
    const { module, sent } = await load();
    await turn(module, new Scripted([[says("Hi.")]]));
    expect(sent.at(-1)!.headers["User-Agent"]).toMatch(/ openai-agents$/);
  });
});

// ----------------------------------------------- what a real model and server send --

/** What the runner hands the filter before a model call. */
const call = (context: unknown, ...input: unknown[]) => ({
  modelData: { input, instructions: "Be brief." },
  agent: new Agent({ name: "A" }),
  context,
});
const ASKED = { role: "user", content: "Where do I live?" };
const TOOL_OUTPUT = { type: "function_call_result", callId: "c1", name: "t", status: "completed" };

describe("what a real model and server send", () => {
  it("searches a long message by its end", async () => {
    // The service takes a question of at most 2,000 characters; a pasted email is longer.
    const { module, sent } = await load();
    await turn(module, new Scripted([[says("Lisbon.")]]), "x".repeat(2500) + " Where do I live?");
    const query: string = bodies(sent, "search")[0]!.query;
    expect(query.length).toBe(2000);
    expect(query.endsWith("Where do I live?")).toBe(true);
  });

  it("saves each turn apart from a model without response ids", async () => {
    // Chat Completions models give no response id.
    const { module, sent } = await load();
    const agent = new Agent({
      name: "A",
      model: new Scripted([[says("Hi.")], [says("Hi.")]], false),
    });
    const options = { context: { userId: "dana" }, callModelInputFilter: module.recall };
    const first = await run(agent, "Thanks", options);
    await module.remember(first);
    await module.remember(await run(agent, "Thanks", options));
    await module.remember(first);
    const ids = bodies(sent, "add").map((b) => b.items.map((i: any) => i.id));
    expect(ids[0]).not.toEqual(ids[1]); // two turns, said the same way
    expect(ids[0]).toEqual(ids[2]); // one turn, saved twice
  });

  it("keeps two turns in flight for one user apart", async () => {
    const echo = (path: string, body: any) =>
      path.endsWith("search")
        ? Response.json({ query: "q", known: [`ANSWER FOR: ${body.query}`] })
        : answer(path);
    const { module } = await load(undefined, echo);
    const [first, second] = [{ userId: "dana" }, { userId: "dana" }];
    await module.recall(call(first, ASKED));
    await module.recall(call(second, { role: "user", content: "My dog's name?" }));

    const afterATool = await module.recall(call(first, ASKED, TOOL_OUTPUT));

    expect(afterATool.instructions).toContain("ANSWER FOR: Where do I live?");
    expect(afterATool.instructions).not.toContain("dog");
  });

  it("searches its user's message in a resumed run with nothing kept", async () => {
    // A run resumed after an approval, or in another process, starts on a tool output.
    const { module, sent } = await load();
    const resumed = await module.recall(call({ userId: "dana" }, ASKED, TOOL_OUTPUT));
    expect(bodies(sent, "search").map((b) => b.query)).toEqual(["Where do I live?"]);
    expect(resumed.instructions).toContain("Dana lives in Lisbon.");
  });

  it("still recalls when a system message follows the user's", async () => {
    const { module, sent } = await load();
    await module.recall(call({ userId: "dana" }, ASKED, { role: "system", content: "Friday." }));
    expect(bodies(sent, "search").map((b) => b.query)).toEqual(["Where do I live?"]);
  });

  it("saves nothing from a run paused for an approval", async () => {
    const { module, sent } = await load();
    await module.remember({ interruptions: [{ type: "tool_approval_item" }] });
    expect(sent).toEqual([]);
  });
});

// ------------------------------------------------------------------------------ tools --

/** A model that calls every tool once, then stops: what each call returned. */
async function toolOutputs(m: Module, context: unknown = CONTEXT) {
  const model = new Scripted([
    [
      calls("memory_search", { query: "home" }, "c1"),
      calls("memory_read", { path: "passages/p1.md" }, "c2"),
      calls("memory_add", { text: "Prefers trains." }, "c3"),
    ],
    [says("Done.")],
  ]);
  const agent = new Agent({ name: "A", model, tools: m.MEMORY_WRITE_TOOLS });
  await run(agent, "x", { context });
  const outputs = (model.calls[1]!.input as any[]).filter((i) => i.type === "function_call_result");
  return Object.fromEntries(outputs.map((i) => [i.callId, i.output.text ?? i.output]));
}

describe("the tools", () => {
  it("take the user from the run, never from the model", async () => {
    const { module, sent } = await load();
    const outputs = await toolOutputs(module);

    expect(outputs.c1).toContain("Dana lives in Lisbon.");
    expect(outputs.c1).toContain("memory_read:\n- passages/p1.md");
    expect(outputs.c2).toBe("Dana: I moved to Lisbon.");
    expect(outputs.c3).toBe("Saved.");
    expect(new Set(sent.map((s) => s.headers["X-Twin-Account"]))).toEqual(new Set(["dana"]));
    expect(bodies(sent, "add")[0]!.items).toEqual([
      { text: "Prefers trains.", kind: "note", session: "conv-7" },
    ]);
    for (const t of module.MEMORY_WRITE_TOOLS) {
      expect(JSON.stringify(t.parameters)).not.toMatch(/user/i);
    }
  });
});

// ----------------------------------------------------------------- when memory fails --

describe("the model's own mistakes", () => {
  it("go back to it, and the run goes on", async () => {
    const strict = (path: string) =>
      path.endsWith("read")
        ? Response.json({ detail: "read needs a path" }, { status: 422 })
        : answer(path);
    const { module } = await load(undefined, strict);
    const model = new Scripted([[calls("memory_read", { path: "" }, "c1")], [says("Sorry.")]]);
    const agent = new Agent({ name: "A", model, tools: module.MEMORY_TOOLS });
    const result = await run(agent, "x", { context: CONTEXT });
    const output = (model.calls[1]!.input as any[]).find((i) => i.type === "function_call_result");
    expect(result.finalOutput).toBe("Sorry.");
    expect(output.output.text ?? output.output).toMatch(/^That did not work: .*read needs a path/);
  });

  it("are not the reason a run with no user goes on", async () => {
    const { module, sent } = await load();
    await expect(toolOutputs(module, { plan: "pro" })).rejects.toThrow(/whose memory/);
    expect(sent).toEqual([]);
  });
});

describe("memory being down", () => {
  it("lets a turn go ahead without it", async () => {
    const { module, sent } = await load(undefined, down);
    const model = new Scripted([[says("Still here.")]]);
    const result = await turn(module, model);
    expect(result.finalOutput).toBe("Still here.");
    expect(model.calls[0]!.systemInstructions).toBe("Be brief.");
    expect(routes(sent).at(-1)).toBe("add"); // tried, failed open
  });

  it("tells the model through the tools", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { module } = await load(undefined, down);
    expect(new Set(Object.values(await toolOutputs(module)))).toEqual(
      new Set([module.UNAVAILABLE]),
    );
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("throws when the client does not fail open (STRICT)", async () => {
    const { module } = await load(undefined, down, false);
    await expect(turn(module, new Scripted([[says("Hi.")]]))).rejects.toBeInstanceOf(
      ServiceUnavailableError,
    );
  });

  it("throws on a wrong key even so", async () => {
    const { module } = await load(undefined, wrongKey);
    await expect(turn(module, new Scripted([[says("Hi.")]]))).rejects.toBeInstanceOf(
      AuthenticationError,
    );
    await expect(toolOutputs(module)).rejects.toThrow(/bad key/);
  });
});

// --------------------------------------------------------------------------- presets --

describe("presets", () => {
  it("leaves tools out of nodes-only, and recall out of tools-only", async () => {
    const nodes = (await load(["nodes"])).module;
    expect(nodes.recall).toBeDefined();
    expect(nodes.MEMORY_TOOLS).toBeUndefined();

    const { module: tools, sent } = await load(["tools"]);
    expect(tools.recall).toBeUndefined();
    expect((await toolOutputs(tools)).c3).toBe("Saved.");
    expect(routes(sent)).toEqual(["search", "read", "add"]);
  });
});

/** Every preset, in a project of its own, through `tsc --strict` and `prettier --check`. */
describe("clean as written", () => {
  const PRESETS = [["nodes", "tools"], ["nodes"], ["tools"]];

  it.each(PRESETS)("passes strict TypeScript and prettier: %s", (...parts) => {
    const dir = join(GENERATED, `lint-${parts.join("-")}`);
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "memory.ts"),
      render("openai_agents/memory.ts.tmpl", parts, { version: "0.1.0", fast: "false" }),
    );
    writeFileSync(
      join(dir, "tsconfig.json"),
      JSON.stringify({
        compilerOptions: {
          target: "ES2023",
          module: "NodeNext",
          moduleResolution: "NodeNext",
          strict: true,
          noUncheckedIndexedAccess: true,
          noEmit: true,
          skipLibCheck: true,
          types: ["node"],
        },
        include: ["memory.ts"],
      }),
    );
    execFileSync("npx", ["tsc", "-p", join(dir, "tsconfig.json")], { stdio: "pipe" });
    execFileSync(
      "npx",
      ["prettier", "--no-config", "--ignore-path", "/dev/null", "--check", join(dir, "memory.ts")],
      { stdio: "pipe" },
    );
  });
});
