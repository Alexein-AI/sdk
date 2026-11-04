/**
 * `@alexein/sdk/langgraph` under `createAgent` with a scripted model, over a stand-in client, and
 * through its module-level defaults.
 */

import { BaseChatModel } from "@langchain/core/language_models/chat_models";
import { AIMessage, HumanMessage } from "@langchain/core/messages";
import type { ChatResult } from "@langchain/core/outputs";
import { createAgent } from "langchain";
import { describe, expect, it, vi } from "vitest";

import type { Memory } from "../../src/index.js";
import { AlexeinMemory, MemoryContext } from "../../src/langgraph/index.js";
import { CALLS, RUN, load } from "./langgraph.js";
import { SEARCHED, routes, users } from "./recorded.js";

/** A chat model that answers each call with the next message of a script, tools bound or not. */
class Scripted extends BaseChatModel {
  constructor(private readonly script: AIMessage[]) {
    super({});
  }

  _llmType(): string {
    return "scripted";
  }

  override bindTools(): this {
    return this;
  }

  async _generate(): Promise<ChatResult> {
    const message = this.script.shift();
    if (!message) throw new Error("the script has no step left");
    return { generations: [{ message, text: message.text }] };
  }
}

describe("createAgent", () => {
  it("runs the tools with the user from the run's context", async () => {
    const { m, sent } = load();
    const model = new Scripted([
      new AIMessage({ content: "", tool_calls: [CALLS[0]!] }),
      new AIMessage("You live in Lisbon."),
    ]);
    const agent = createAgent({ model, tools: m.tools(), contextSchema: MemoryContext });
    const out = await agent.invoke(
      { messages: [new HumanMessage("Where do I live?")] },
      { context: { user_id: "dana" } },
    );
    expect(out.messages.at(-1)!.text).toBe("You live in Lisbon.");
    expect(routes(sent)).toEqual(["search"]);
    expect(users(sent)).toEqual(new Set(["dana"]));
  });
});

describe("a stand-in client", () => {
  it("is used as given, with no key", async () => {
    vi.stubEnv("ALEXEIN_API_KEY", "");
    const asked: [string, string][] = [];
    const fake = {
      user: (id: string) => ({
        search: async (query: string) => {
          asked.push([id, query]);
          return { context: () => "- Dana lives in Lisbon.", failed: false, refs: [] };
        },
        add: async () => ({ failed: false }),
      }),
    } as unknown as Memory;
    const m = new AlexeinMemory(fake, { maxChars: 100 });
    expect(m.client).toBe(fake);
    const found = await m.recall({ messages: [new HumanMessage("Where?")] }, RUN);
    expect(found.memory).toBe("- Dana lives in Lisbon.");
    expect(asked).toEqual([["dana", "Where?"]]);
  });

  it("makes its own client only when first used, fail-open with a 10 s timeout", () => {
    vi.stubEnv("ALEXEIN_API_KEY", "");
    const m = new AlexeinMemory({ fast: true });
    expect(m.fast).toBe(true);
    expect(() => m.client).toThrow(/ALEXEIN_API_KEY/);
    vi.stubEnv("ALEXEIN_API_KEY", "ak_env");
    expect([m.client.failOpen, m.client.timeout, m.client.integration]).toEqual([
      true,
      10_000,
      "langgraph",
    ]);
    expect(new AlexeinMemory({ strict: true }).client.failOpen).toBe(false);
  });
});

describe("module-level defaults", () => {
  it("share one AlexeinMemory, made from the environment on first use", async () => {
    vi.stubEnv("ALEXEIN_API_KEY", "ak_env");
    const fetch = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) =>
      String(input).endsWith("/search") ? Response.json(SEARCHED) : Response.json({}),
    );
    vi.stubGlobal("fetch", fetch);
    vi.resetModules();
    const lg = await import("../../src/langgraph/index.js");
    expect(fetch).not.toHaveBeenCalled();
    const found = await lg.recall({ messages: [new HumanMessage("Where?")] }, RUN);
    expect(lg.memoryPrompt(found)).toContain("Dana lives in Lisbon.");
    await lg.remember({ messages: [new HumanMessage("Where?")] }, RUN);
    expect(lg.memoryTools().map((t) => t.name)).toEqual(["memory_search", "memory_open"]);
    expect(lg.memoryTools({ write: true })).toHaveLength(3);
    expect(lg.defaultMemory()).toBe(lg.defaultMemory());
    const headers = fetch.mock.calls.map(([, init]) => init!.headers as Record<string, string>);
    expect(headers.map((h) => h.Authorization)).toEqual(["Bearer ak_env", "Bearer ak_env"]);
    expect(headers[0]!["User-Agent"]).toMatch(/ langgraph$/);
  });
});
