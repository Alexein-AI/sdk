/**
 * The `memory.ts` that `npx @alexein/cli init langgraph` writes, imported as written - its client
 * made from its own settings - and run inside real LangGraph.js graphs, through the real
 * `@alexein/sdk`, against a recorded memory API. And checked as a developer's project would check
 * it: strict TypeScript, and prettier at its defaults.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { AuthenticationError, ServiceUnavailableError } from "@alexein/sdk";
import { AIMessage, HumanMessage, type BaseMessage } from "@langchain/core/messages";
import { END, MessagesAnnotation, START, StateGraph } from "@langchain/langgraph";
import { ToolNode } from "@langchain/langgraph/prebuilt";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { GENERATED as GENERATED_BY } from "../src/project.js";
import { GENERATED as ALL_GENERATED } from "./helpers.js";
import {
  answer,
  bodies,
  down,
  loadMemoryFile,
  nobody,
  REF,
  type Respond,
  routes,
  users,
  wrongKey,
  type Written,
  writeMemoryFile,
} from "./recorded.js";

/** This file's own corner, so files running in parallel never remove each other's. */
const GENERATED = ALL_GENERATED + "template/";

/** The file as `init` writes it, imported fresh, its requests answered by `respond`. */
const load = (respond: Respond = answer, written: Written = {}) =>
  loadMemoryFile(GENERATED, "langgraph/memory.ts.tmpl", respond, written);

type Module = Record<string, any>;

const RUN = { context: { user_id: "dana" }, configurable: { thread_id: "t-1" } };
const CALLS = [
  { name: "memory_search", args: { query: "home" }, id: "c1" },
  { name: "memory_open", args: { ref: REF }, id: "c2" },
  { name: "memory_add", args: { text: "Prefers trains." }, id: "c3" },
];

/** recall, the model, remember: the graph the file's comment shows. */
function turnGraph(m: Module, agent: (state: any) => Promise<{ messages: BaseMessage[] }>) {
  return new StateGraph(m.MemoryAnnotation, m.MemoryContext)
    .addNode("recall", m.memory.recall)
    .addNode("agent", agent)
    .addNode("remember", m.memory.remember)
    .addEdge(START, "recall")
    .addEdge("recall", "agent")
    .addEdge("agent", "remember")
    .addEdge("remember", END)
    .compile();
}

/** A model that calls every tool once, through LangGraph's own ToolNode. */
function toolsGraph(m: Module) {
  return new StateGraph(MessagesAnnotation, m.MemoryContext)
    .addNode("agent", async () => ({
      messages: [new AIMessage({ content: "", tool_calls: CALLS })],
    }))
    .addNode("tools", new ToolNode(m.memory.tools({ write: true })))
    .addEdge(START, "agent")
    .addEdge("agent", "tools")
    .addEdge("tools", END)
    .compile();
}

const said = (text: string) => ({ messages: [new HumanMessage(text)], memory: "" });

beforeAll(() => mkdirSync(GENERATED, { recursive: true }));
afterAll(() => rmSync(GENERATED, { recursive: true, force: true }));

describe("the written file", () => {
  it("is short, and imports everything else from @alexein/sdk", async () => {
    const { path, module: m } = await load();
    const text = readFileSync(path, "utf8");
    expect(text.split("\n").length).toBeLessThanOrEqual(60);
    expect(GENERATED_BY.exec(text)?.slice(1)).toEqual(["langgraph", "0.3.0"]);
    const imports = [...text.matchAll(/^(?:import|export) .*? from "([^"]+)";$/gms)].map(
      (i) => i[1],
    );
    expect(new Set(imports)).toEqual(new Set(["@alexein/sdk/langgraph"]));
    expect(Object.keys(m).sort()).toEqual([
      "FAST",
      "MAX_CHARS",
      "MemoryAnnotation",
      "MemoryContext",
      "MemoryState",
      "STRICT",
      "TIMEOUT",
      "memory",
    ]);
  });

  it("makes its client from its settings, with the key and address from the environment", async () => {
    const { module: m } = await load();
    expect(m.memory.client).toMatchObject({
      baseUrl: "https://memory.test",
      timeout: 10_000,
      failOpen: true,
      integration: "langgraph",
    });
    expect(m.memory).toMatchObject({ fast: false, maxChars: 4000, strict: false });
  });

  it("takes the settings its developer changes", async () => {
    const { module: m, sent } = await load(answer, {
      fast: true,
      edits: [
        ["STRICT = false", "STRICT = true"],
        ["MAX_CHARS = 4000", "MAX_CHARS = 30"],
        ["TIMEOUT = 10_000", "TIMEOUT = 2_500"],
      ],
    });
    expect(m.memory.client).toMatchObject({ timeout: 2_500, failOpen: false });
    expect(m.memory).toMatchObject({ fast: true, maxChars: 30, strict: true });
    const out = await m.memory.recall(said("Where do I live?"), RUN);
    expect(bodies(sent, "search")[0]).toMatchObject({ fast: true });
    expect(out.memory).toBe("- Dana lives in Lisbon.");
  });

  it("imports with no key, and asks for one on first use", async () => {
    vi.stubEnv("ALEXEIN_API_KEY", "");
    const path = writeMemoryFile(GENERATED, "langgraph/memory.ts.tmpl", {
      edits: [
        ["STRICT = false", "STRICT = true"],
        ["TIMEOUT = 10_000", "TIMEOUT = 1_234"],
      ],
    });
    const m = await import(pathToFileURL(path).href);
    expect(() => m.memory.client).toThrow(/ALEXEIN_API_KEY.*API keys/s);
    vi.stubEnv("ALEXEIN_API_KEY", "tm_later");
    expect(m.memory.client).toMatchObject({
      timeout: 1_234,
      failOpen: false,
      integration: "langgraph",
    });
  });
});

describe("the written file in a graph", () => {
  it("recalls before the model and saves the turn after", async () => {
    const { module: m, sent } = await load();
    const prompts: string[] = [];
    const out = await turnGraph(m, async (state) => {
      prompts.push(m.memory.prompt(state));
      return { messages: [new AIMessage({ content: "You live in Lisbon.", id: "ai-1" })] };
    }).invoke({ messages: [new HumanMessage({ content: "Where do I live?", id: "h-1" })] }, RUN);

    expect(routes(sent)).toEqual(["search", "add"]);
    const [search] = sent;
    expect(search!.headers["X-Alexein-User"]).toBe("dana");
    expect(search!.headers.Authorization).toBe("Bearer tm_test");
    expect(search!.headers["User-Agent"]).toMatch(/^alexein-js\/\S+ langgraph$/);
    expect(search!.body).toMatchObject({ query: "Where do I live?", fast: false });
    expect(out.memory).toContain("Dana lives in Lisbon.");
    expect(prompts[0]).toMatch(/^What you remember about this user/);
    expect(prompts[0]).toContain("Dana lives in Lisbon.");
    expect(bodies(sent, "add")[0]!.items).toEqual([
      { id: "h-1", role: "user", text: "Where do I live?", session: "t-1" },
      { id: "ai-1", role: "assistant", text: "You live in Lisbon.", session: "t-1" },
    ]);
  });

  it("does not save tool calls or tool results", async () => {
    const { module: m, sent } = await load();
    await m.memory.remember(
      {
        messages: [
          new HumanMessage({ content: "Book it", id: "h-1" }),
          new AIMessage({
            content: "",
            id: "ai-1",
            tool_calls: [{ name: "b", args: {}, id: "x" }],
          }),
          new AIMessage({ content: "Booked.", id: "ai-2" }),
        ],
        memory: "",
      },
      RUN,
    );
    expect(bodies(sent, "add")[0]!.items.map((i: { id: string }) => i.id)).toEqual(["h-1", "ai-2"]);
  });

  it("takes the user from configurable too, and must have one", async () => {
    const { module: m, sent } = await load();
    await m.memory.recall(said("hi"), { configurable: { user_id: "sam" } });
    expect(sent[0]!.headers["X-Alexein-User"]).toBe("sam");
    await expect(m.memory.recall(said("hi"), { configurable: {} })).rejects.toThrow(
      'context: { user_id: "..." }',
    );
  });

  it("recalls nothing for a user with no memory yet", async () => {
    const { module: m } = await load(nobody);
    expect(await m.memory.recall(said("hi"), RUN)).toEqual({ memory: "" });
    expect(m.memory.prompt({ memory: "" })).toBe("");
  });

  it("searches a long message by its end", async () => {
    // The API takes a question of at most 2,000 characters; a pasted email is longer.
    const { module: m, sent } = await load();
    await m.memory.recall(said("x".repeat(2500) + " Where do I live?"), RUN);
    const query: string = bodies(sent, "search")[0]!.query;
    expect(query.length).toBe(2000);
    expect(query.endsWith("Where do I live?")).toBe(true);
  });
});

describe("the tools", () => {
  it("take the user from the run, never from the model", async () => {
    const { module: m, sent } = await load();
    const tools = m.memory.tools({ write: true });
    expect(tools.map((t: { name: string }) => t.name)).toEqual([
      "memory_search",
      "memory_open",
      "memory_add",
    ]);
    expect(m.memory.tools().map((t: { name: string }) => t.name)).toEqual([
      "memory_search",
      "memory_open",
    ]);
    for (const each of tools) expect(JSON.stringify(each.schema)).not.toMatch(/user/i);

    const out = await toolsGraph(m).invoke(
      { messages: [new HumanMessage("x")] },
      { context: { user_id: "dana" }, configurable: { thread_id: "t-9" } },
    );

    expect(users(sent)).toEqual(new Set(["dana"]));
    const results = Object.fromEntries(
      out.messages.slice(-3).map((msg: any) => [msg.tool_call_id, msg.content]),
    );
    expect(results.c1).toContain("Dana lives in Lisbon.");
    expect(results.c1).toMatch(new RegExp(`To read one whole, memory_open:\\n- ${REF}$`));
    expect(results.c2).toBe("2026-10-01: Dana: I moved to Lisbon.");
    expect(results.c3).toBe("Saved.");
    expect(bodies(sent, "add")[0]!.items).toEqual([
      { text: "Prefers trains.", kind: "note", session: "t-9" },
    ]);
  });
});

describe("memory being down", () => {
  it("lets a turn go ahead without it, after trying three times", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { module: m, sent } = await load(down);
    const out = await turnGraph(m, async () => ({
      messages: [new AIMessage({ content: "Still here.", id: "ai-1" })],
    })).invoke({ messages: [new HumanMessage({ content: "hi", id: "h-1" })] }, RUN);
    expect(out.memory).toBe("");
    expect(out.messages.at(-1).text).toBe("Still here.");
    expect(routes(sent)).toEqual(["search", "search", "search", "add", "add", "add"]);
    expect(warn).toHaveBeenCalled();
  });

  it("tells the model through the tools", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { module: m } = await load(down);
    const out = await toolsGraph(m).invoke({ messages: [new HumanMessage("x")] }, RUN);
    expect(out.messages.slice(-3).map((msg: any) => msg.content)).toEqual(
      Array(3).fill("Memory is unavailable right now; carry on without it."),
    );
  });

  it("throws on a wrong key even so", async () => {
    const { module: m } = await load(wrongKey);
    await expect(m.memory.recall(said("hi"), RUN)).rejects.toBeInstanceOf(AuthenticationError);
  });

  it("throws with STRICT = true", async () => {
    const { module: m } = await load(down, { edits: [["STRICT = false", "STRICT = true"]] });
    await expect(m.memory.recall(said("hi"), RUN)).rejects.toBeInstanceOf(ServiceUnavailableError);
  });
});

describe("presets", () => {
  it("tools-only exports the context and not the state", async () => {
    const { module: m, path } = await load(answer, { parts: ["tools"] });
    expect(Object.keys(m)).toContain("MemoryContext");
    expect(m.MemoryState).toBeUndefined();
    expect(m.MemoryAnnotation).toBeUndefined();
    const text = readFileSync(path, "utf8");
    expect(text).toContain("memory.tools({ write: true })");
    expect(text).not.toContain("memory.recall");
  });

  it("nodes-only shows no tools", async () => {
    const { path } = await load(answer, { parts: ["nodes"] });
    const text = readFileSync(path, "utf8");
    expect(text).toContain("memory.recall");
    expect(text).not.toContain("memory.tools");
  });
});

/** Every preset, in a project of its own, through `tsc --strict` and `prettier --check`. */
describe("clean as written", () => {
  const PRESETS: [string, string[]][] = [
    ["both", ["nodes", "tools"]],
    ["nodes-only", ["nodes"]],
    ["tools-only", ["tools"]],
  ];

  it.each(PRESETS)("passes strict TypeScript and prettier: %s", (_, parts) => {
    const path = writeMemoryFile(GENERATED, "langgraph/memory.ts.tmpl", { parts });
    const dir = join(path, "..");
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
      ["prettier", "--no-config", "--ignore-path", "/dev/null", "--check", path],
      { stdio: "pipe" },
    );
  });
});
