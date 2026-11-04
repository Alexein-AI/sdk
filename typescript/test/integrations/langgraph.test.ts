/**
 * `@alexein/sdk/langgraph` in real LangGraph.js graphs - nodes and a ToolNode - against a recorded
 * memory API.
 */

import { AIMessage, HumanMessage } from "@langchain/core/messages";
import { END, START, StateGraph } from "@langchain/langgraph";
import { describe, expect, it, vi } from "vitest";

import { AuthenticationError, ServiceUnavailableError } from "../../src/index.js";
import { MemoryContext, MemoryState, UNAVAILABLE } from "../../src/langgraph/index.js";
import { RUN, load, toolResults, toolsGraph, turnGraph } from "./langgraph.js";
import { FACT_REF, REF, bodies, down, routes, users, wrongKey } from "./recorded.js";

describe("in a graph", () => {
  it("recalls before the model and saves the turn after", async () => {
    const { m, sent } = load();
    const prompts: string[] = [];
    const out = await turnGraph(m, async (state) => {
      prompts.push(m.prompt(state));
      return { messages: [new AIMessage({ content: "You live in Lisbon.", id: "ai-1" })] };
    }).invoke({ messages: [new HumanMessage({ content: "Where do I live?", id: "h-1" })] }, RUN);

    const [search, add] = sent;
    expect(routes(sent)).toEqual(["search", "add"]);
    expect(search!.headers["X-Alexein-User"]).toBe("dana");
    expect(search!.headers["User-Agent"]).toMatch(/^alexein-js\/\S+ langgraph$/);
    expect(search!.body).toEqual({ query: "Where do I live?", fast: false });
    expect(out.memory).toContain("- Dana lives in Lisbon.");
    expect(prompts[0]).toMatch(/^What you remember about this user/);
    expect(prompts[0]).toContain("- 2026-10-01: Dana: I moved to Lisbon.");
    expect(add!.body.items).toEqual([
      { session: "t-1", id: "h-1", role: "user", text: "Where do I live?" },
      { session: "t-1", id: "ai-1", role: "assistant", text: "You live in Lisbon." },
    ]);
  });

  it("works with MemoryState as well", async () => {
    const { m } = load();
    const graph = new StateGraph(MemoryState, MemoryContext)
      .addNode("recall", m.recall)
      .addEdge(START, "recall")
      .addEdge("recall", END)
      .compile();
    const out = await graph.invoke({ messages: [new HumanMessage("Where do I live?")] }, RUN);
    expect(out.memory).toContain("Dana lives in Lisbon.");
  });

  it("does not save tool calls or tool results", async () => {
    const { m, sent } = load();
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
      },
      RUN,
    );
    expect(bodies(sent, "add")[0]!.items.map((i: any) => i.id)).toEqual(["h-1", "ai-2"]);
  });

  it("gives a message without an id a stable one, and running a turn again the same", async () => {
    const { m, sent } = load();
    const state = { messages: [new HumanMessage("hi"), new AIMessage("hello")] };
    await m.remember(state, RUN);
    await m.remember(state, RUN);
    const [first, second] = bodies(sent, "add").map((b) => b.items.map((i: any) => i.id));
    expect(first).toEqual(second);
    expect(first![0]).toMatch(/^[0-9a-f]{24}$/);
    expect(first![0]).not.toBe(first![1]);
    await m.remember(state, { ...RUN, configurable: { thread_id: "t-2" } });
    expect(bodies(sent, "add")[2]!.items[0].id).not.toBe(first![0]);
  });

  it("takes the user from configurable too, and must have one", async () => {
    const { m, sent } = load();
    const state = { messages: [new HumanMessage("hi")] };
    await m.recall(state, { configurable: { user_id: "sam" } });
    expect(sent[0]!.headers["X-Alexein-User"]).toBe("sam");
    await expect(m.recall(state, { configurable: {} })).rejects.toThrow(/whose memory/);
    await expect(m.remember(state, {})).rejects.toThrow(/whose memory/);
  });

  it("recalls nothing for a user with no memory yet, and searches no empty message", async () => {
    const { m, sent } = load(() => Response.json({ detail: "none" }, { status: 404 }));
    expect(await m.recall({ messages: [new HumanMessage("hi")] }, RUN)).toEqual({ memory: "" });
    expect(await m.recall({ messages: [new HumanMessage("  ")] }, RUN)).toEqual({ memory: "" });
    expect(sent).toHaveLength(1);
    expect(m.prompt({ memory: "" })).toBe("");
  });

  it("searches a long message by its end", async () => {
    const { m, sent } = load();
    await m.recall({ messages: [new HumanMessage("x".repeat(2500) + " Where do I live?")] }, RUN);
    const query: string = bodies(sent, "search")[0]!.query;
    expect(query.length).toBe(2000);
    expect(query.endsWith("Where do I live?")).toBe(true);
  });
});

describe("the tools", () => {
  it("take the user from the run, never from the model", async () => {
    const { m, sent } = load();
    for (const each of m.tools({ write: true })) {
      expect(Object.keys((each.schema as any).shape)).not.toContain("user_id");
    }
    const out = await toolsGraph(m).invoke(
      { messages: [new HumanMessage("x")] },
      { context: { user_id: "dana" }, configurable: { thread_id: "t-9" } },
    );
    expect(users(sent)).toEqual(new Set(["dana"]));
    const results = toolResults(out);
    expect(results.c1).toContain("- Dana lives in Lisbon.");
    expect(results.c1).toMatch(
      new RegExp(`To read one whole, memory_open:\\n- ${FACT_REF}\\n- ${REF}$`),
    );
    expect(results.c2).toBe("2026-10-01: Dana: I moved to Lisbon.");
    expect(results.c3).toBe("Saved.");
    expect(bodies(sent, "open")).toEqual([{ ref: REF }]);
    expect(bodies(sent, "add")[0]!.items).toEqual([
      { kind: "note", session: "t-9", text: "Prefers trains." },
    ]);
  });

  it("are named as the hosted MCP server names them; memory_add only with write", () => {
    const { m } = load();
    expect(m.tools().map((t) => t.name)).toEqual(["memory_search", "memory_open"]);
    expect(m.tools({ write: true }).map((t) => t.name)).toEqual([
      "memory_search",
      "memory_open",
      "memory_add",
    ]);
  });

  it("open a fact with what it was learned from, and say when nothing is there", async () => {
    const opened = {
      memory: { type: "fact", ref: FACT_REF, text: "Dana moved to Lisbon.", source: REF },
      sources: [{ type: "excerpt", ref: REF, text: "I moved.", date: null, roles: [] }],
    };
    const [search, open] = load(() => Response.json(opened)).m.tools();
    expect(search).toBeDefined();
    expect(await open!.invoke({ ref: FACT_REF }, RUN)).toBe(
      "Dana moved to Lisbon.\n\nLearned from:\n- I moved.",
    );
    const none = (detail: string) => () => Response.json({ detail }, { status: 404 });
    const [, unknownRef] = load(none("memory holds nothing by this ref")).m.tools();
    expect(await unknownRef!.invoke({ ref: "mem_x" }, RUN)).toBe(
      "Memory holds nothing by that ref.",
    );
    const [noUser, noOne] = load(none("no memory for app user 'dana' yet")).m.tools();
    expect(await noOne!.invoke({ ref: "mem_x" }, RUN)).toBe(
      "Nothing has been remembered for this user yet.",
    );
    expect(await noUser!.invoke({ query: "x" }, RUN)).toBe("Nothing remembered about that.");
  });
});

describe("memory being down", () => {
  it("lets a turn go ahead without it", async () => {
    const { m } = load(down);
    const out = await turnGraph(m, async () => ({
      messages: [new AIMessage({ content: "Still here.", id: "ai-1" })],
    })).invoke({ messages: [new HumanMessage({ content: "hi", id: "h-1" })] }, RUN);
    expect(out.memory).toBe("");
    expect(out.messages.at(-1)!.text).toBe("Still here.");
  });

  it("tells the model through the tools", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { m } = load(down);
    const out = await toolsGraph(m).invoke({ messages: [new HumanMessage("x")] }, RUN);
    expect(Object.values(toolResults(out))).toEqual(Array(3).fill(UNAVAILABLE));
    expect(warn).toHaveBeenCalledOnce(); // memory_open's; search and add fail open in the client
  });

  it("throws on a wrong key even so", async () => {
    const { m } = load(wrongKey);
    await expect(m.recall({ messages: [new HumanMessage("hi")] }, RUN)).rejects.toBeInstanceOf(
      AuthenticationError,
    );
  });

  it("throws when strict", async () => {
    const { m } = load(down, { failOpen: false, strict: true });
    await expect(m.recall({ messages: [new HumanMessage("hi")] }, RUN)).rejects.toBeInstanceOf(
      ServiceUnavailableError,
    );
    const [, open] = m.tools();
    await expect(open!.invoke({ ref: REF }, RUN)).rejects.toBeInstanceOf(ServiceUnavailableError);
  });
});
