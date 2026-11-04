/**
 * The `memory.ts` that `twinmemory-cli init langgraph` writes, run inside real LangGraph.js graphs
 * against a recorded memory API - and checked as a developer's project would check it: strict
 * TypeScript, and prettier at its defaults.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { AIMessage, HumanMessage, type BaseMessage } from "@langchain/core/messages";
import { END, MessagesValue, START, StateGraph, StateSchema } from "@langchain/langgraph";
import { ToolNode } from "@langchain/langgraph/prebuilt";
import { AuthenticationError, ServiceUnavailableError } from "twinmemory";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { render } from "../src/render.js";
import { GENERATED as ALL_GENERATED } from "./helpers.js";
import { answer, down, loadMemoryFile, type Respond } from "./recorded.js";

/** This file's own corner, so files running in parallel never remove each other's. */
const GENERATED = ALL_GENERATED + "template/";

/** The file as `init` writes it, imported fresh, with its client answered by `respond`. */
const load = (parts: string[], respond: Respond = answer, { failOpen = true } = {}) =>
  loadMemoryFile(GENERATED, "langgraph/memory.ts.tmpl", parts, respond, {
    integration: "langgraph",
    failOpen,
  });

type Module = Record<string, any>;

const RUN = { context: { user_id: "dana" }, configurable: { thread_id: "t-1" } };
const CALLS = [
  { name: "memory_search", args: { query: "home" }, id: "c1" },
  { name: "memory_read", args: { path: "passages/p1.md" }, id: "c2" },
  { name: "memory_add", args: { text: "Prefers trains." }, id: "c3" },
];

function turnGraph(m: Module, agent: (state: any) => Promise<{ messages: BaseMessage[] }>) {
  return new StateGraph(m.MemoryState, m.MemoryContext)
    .addNode("recall", m.recall)
    .addNode("agent", agent)
    .addNode("remember", m.remember)
    .addEdge(START, "recall")
    .addEdge("recall", "agent")
    .addEdge("agent", "remember")
    .addEdge("remember", END)
    .compile();
}

function toolsGraph(m: Module) {
  const State = new StateSchema({ messages: MessagesValue });
  return new StateGraph(State, m.MemoryContext)
    .addNode("agent", async () => ({
      messages: [new AIMessage({ content: "", tool_calls: CALLS })],
    }))
    .addNode("tools", new ToolNode(m.MEMORY_WRITE_TOOLS))
    .addEdge(START, "agent")
    .addEdge("agent", "tools")
    .addEdge("tools", END)
    .compile();
}

beforeAll(() => mkdirSync(GENERATED, { recursive: true }));
afterAll(() => rmSync(GENERATED, { recursive: true, force: true }));

describe("the written file in a graph", () => {
  it("recalls before the model and saves the turn after", async () => {
    const { module: m, sent } = await load(["nodes", "tools"]);
    const prompts: string[] = [];
    const out = await turnGraph(m, async (state) => {
      prompts.push(m.memoryPrompt(state));
      return { messages: [new AIMessage({ content: "You live in Lisbon.", id: "ai-1" })] };
    }).invoke({ messages: [new HumanMessage({ content: "Where do I live?", id: "h-1" })] }, RUN);

    const [search, add] = sent;
    expect(search!.path).toBe("/v1/memory/search");
    expect(search!.headers["X-Twin-Account"]).toBe("dana");
    expect(search!.headers["User-Agent"]).toMatch(/ langgraph$/);
    expect(search!.body.query).toBe("Where do I live?");
    expect(out.memory).toContain("Dana lives in Lisbon.");
    expect(prompts[0]).toContain("Dana lives in Lisbon.");
    expect(add!.body.items).toEqual([
      { session: "t-1", id: "h-1", role: "user", text: "Where do I live?" },
      { session: "t-1", id: "ai-1", role: "assistant", text: "You live in Lisbon." },
    ]);
  });

  it("does not save tool calls or tool results", async () => {
    const { module: m, sent } = await load(["nodes"]);
    await m.remember(
      {
        messages: [
          new HumanMessage({ content: "Book it", id: "h-1" }),
          new AIMessage({
            content: "",
            id: "ai-1",
            tool_calls: [{ name: "book", args: {}, id: "x" }],
          }),
          new AIMessage({ content: "Booked.", id: "ai-2" }),
        ],
        memory: "",
      },
      RUN,
    );
    expect((sent[0]!.body.items as { id: string }[]).map((i) => i.id)).toEqual(["h-1", "ai-2"]);
  });

  it("takes the user from configurable too, and must have one", async () => {
    const { module: m, sent } = await load(["nodes"]);
    const state = { messages: [new HumanMessage("hi")], memory: "" };
    await m.recall(state, { configurable: { user_id: "sam" } });
    expect(sent[0]!.headers["X-Twin-Account"]).toBe("sam");
    await expect(m.recall(state, { configurable: {} })).rejects.toThrow(/whose memory/);
  });

  it("recalls nothing for a user with no memory yet", async () => {
    const { module: m } = await load(["nodes"], () =>
      Response.json({ detail: "none" }, { status: 404 }),
    );
    expect(await m.recall({ messages: [new HumanMessage("hi")], memory: "" }, RUN)).toEqual({
      memory: "",
    });
    expect(m.memoryPrompt({ memory: "" })).toBe("");
  });

  it("gives tools the user from the run, never from the model", async () => {
    const { module: m, sent } = await load(["nodes", "tools"]);
    for (const each of m.MEMORY_WRITE_TOOLS) {
      expect(Object.keys((each.schema as any).shape)).not.toContain("user_id");
    }
    const out = await toolsGraph(m).invoke(
      { messages: [new HumanMessage("x")] },
      {
        context: { user_id: "dana" },
        configurable: { thread_id: "t-9" },
      },
    );
    expect(new Set(sent.map((s) => s.headers["X-Twin-Account"]))).toEqual(new Set(["dana"]));
    const results = Object.fromEntries(
      out.messages.slice(-3).map((msg: any) => [msg.tool_call_id, msg.content]),
    );
    expect(results.c1).toContain("Dana lives in Lisbon.");
    expect(results.c1).toMatch(/To read one whole, memory_read:\n- passages\/p1\.md$/);
    expect(results.c2).toBe("Dana: I moved to Lisbon.");
    expect(results.c3).toBe("Saved.");
    expect(sent.find((s) => s.path.endsWith("/add"))!.body.items).toEqual([
      { kind: "note", session: "t-9", text: "Prefers trains." },
    ]);
  });
});

describe("a long message", () => {
  it("is searched by its end", async () => {
    // The service takes a question of at most 2,000 characters; a pasted email is longer.
    const { module, sent } = await load(["nodes"]);
    const asked = "x".repeat(2500) + " Where do I live?";
    await module.recall({ messages: [new HumanMessage(asked)], memory: "" }, RUN);
    const query: string = sent[0]!.body.query as string;
    expect(query.length).toBe(2000);
    expect(query.endsWith("Where do I live?")).toBe(true);
  });
});

describe("memory being down", () => {
  it("lets a turn go ahead without it", async () => {
    const { module: m } = await load(["nodes", "tools"], down);
    const out = await turnGraph(m, async () => ({
      messages: [new AIMessage({ content: "Still here.", id: "ai-1" })],
    })).invoke({ messages: [new HumanMessage({ content: "hi", id: "h-1" })] }, RUN);
    expect(out.memory).toBe("");
    expect(out.messages.at(-1).text).toBe("Still here.");
  });

  it("tells the model through the tools", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { module: m } = await load(["tools"], down);
    const out = await toolsGraph(m).invoke({ messages: [new HumanMessage("x")] }, RUN);
    expect(out.messages.slice(-3).map((msg: any) => msg.content)).toEqual(
      Array(3).fill(m.UNAVAILABLE),
    );
    warn.mockRestore();
  });

  it("throws on a wrong key even so", async () => {
    const { module: m } = await load(["nodes", "tools"], () =>
      Response.json({ detail: "bad key" }, { status: 401 }),
    );
    await expect(
      m.recall({ messages: [new HumanMessage("hi")], memory: "" }, RUN),
    ).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("throws when the client does not fail open (STRICT)", async () => {
    const { module: m } = await load(["nodes"], down, { failOpen: false });
    await expect(
      m.recall({ messages: [new HumanMessage("hi")], memory: "" }, RUN),
    ).rejects.toBeInstanceOf(ServiceUnavailableError);
  });
});

describe("presets", () => {
  it("leaves tools out of nodes-only, and nodes out of tools-only", async () => {
    const nodes = (await load(["nodes"])).module;
    expect(nodes.recall).toBeTypeOf("function");
    expect(nodes.MEMORY_TOOLS).toBeUndefined();
    const tools = (await load(["tools"])).module;
    expect(tools.MEMORY_TOOLS).toHaveLength(2);
    expect(tools.recall).toBeUndefined();
    expect(tools.MemoryState).toBeUndefined();
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
      render("langgraph/memory.ts.tmpl", parts, { version: "0.1.0", fast: "false" }),
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
    // --ignore-path: this package's own .prettierignore skips test/.generated, which would pass
    // the check without making it.
    execFileSync(
      "npx",
      ["prettier", "--no-config", "--ignore-path", "/dev/null", "--check", join(dir, "memory.ts")],
      { stdio: "pipe" },
    );
  });
});
