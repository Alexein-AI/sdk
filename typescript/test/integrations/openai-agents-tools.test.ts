/**
 * `@alexein/sdk/openai-agents`: its tools in a run, memory being down, and the module-level
 * defaults.
 */

import { Agent, run, setTracingDisabled } from "@openai/agents";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { AuthenticationError, ServiceUnavailableError } from "../../src/index.js";
import { UNAVAILABLE } from "../../src/openai-agents/index.js";
import { Scripted, calls, says } from "./agents.js";
import { CONTEXT, load, toolOutputs, turn } from "./openai.js";
import { REF, SEARCHED, answer, bodies, down, routes, users, wrongKey } from "./recorded.js";

beforeAll(() => setTracingDisabled(true));

describe("the tools", () => {
  it("take the user from the run, never from the model", async () => {
    const { m, sent } = load();
    const outputs = await toolOutputs(m);
    expect(outputs.c1).toContain("- Dana lives in Lisbon.");
    expect(outputs.c1).toContain(`memory_open:\n- mem_5pQ1zX8gHd2\n- ${REF}`);
    expect(outputs.c2).toBe("2026-10-01: Dana: I moved to Lisbon.");
    expect(outputs.c3).toBe("Saved.");
    expect(users(sent)).toEqual(new Set(["dana"]));
    expect(bodies(sent, "add")[0]!.items).toEqual([
      { text: "Prefers trains.", kind: "note", session: "conv-7" },
    ]);
    for (const t of m.tools({ write: true })) {
      expect(JSON.stringify(t.parameters)).not.toMatch(/user/i);
    }
    expect(m.tools().map((t) => t.name)).toEqual(["memory_search", "memory_open"]);
  });

  it("hand the model its own mistakes, and the run goes on", async () => {
    const strict = (route: string) =>
      route === "open"
        ? Response.json({ detail: "`ref` must not be empty" }, { status: 422 })
        : answer(route);
    const { m } = load(strict);
    const model = new Scripted([[calls("memory_open", { ref: "" }, "c1")], [says("Sorry.")]]);
    const result = await run(new Agent({ name: "A", model, tools: m.tools() }), "x", {
      context: CONTEXT,
    });
    const output = (model.calls[1]!.input as any[]).find((i) => i.type === "function_call_result");
    expect(result.finalOutput).toBe("Sorry.");
    expect(output.output.text ?? output.output).toMatch(/^That did not work: .*must not be empty/);
  });

  it("do not let a run with no user go on", async () => {
    const { m, sent } = load();
    await expect(toolOutputs(m, { plan: "pro" })).rejects.toThrow(/whose memory/);
    expect(sent).toEqual([]);
  });
});

describe("memory being down", () => {
  it("lets a turn go ahead without it", async () => {
    const { m, sent } = load(down);
    const model = new Scripted([[says("Still here.")]]);
    const result = await turn(m, model);
    expect(result.finalOutput).toBe("Still here.");
    expect(model.calls[0]!.systemInstructions).toBe("Be brief.");
    expect(routes(sent).at(-1)).toBe("add"); // tried, failed open
  });

  it("tells the model through the tools", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { m } = load(down);
    expect(new Set(Object.values(await toolOutputs(m)))).toEqual(new Set([UNAVAILABLE]));
    expect(warn).toHaveBeenCalled();
  });

  it("throws when strict", async () => {
    const { m } = load(down, { failOpen: false, strict: true });
    await expect(turn(m, new Scripted([[says("Hi.")]]))).rejects.toBeInstanceOf(
      ServiceUnavailableError,
    );
  });

  it("throws on a wrong key even so", async () => {
    const { m } = load(wrongKey);
    await expect(turn(m, new Scripted([[says("Hi.")]]))).rejects.toBeInstanceOf(
      AuthenticationError,
    );
    await expect(toolOutputs(m)).rejects.toThrow(/bad key/);
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
    const oa = await import("../../src/openai-agents/index.js");
    const agents = await import("@openai/agents");
    const model = new Scripted([[says("Lisbon.")]]);
    const agent = new agents.Agent({ name: "A", model, tools: oa.memoryTools() });
    const result = await agents.run(agent, "Where?", {
      context: CONTEXT,
      callModelInputFilter: oa.recall,
    });
    await oa.remember(result);
    expect(model.calls[0]!.systemInstructions).toContain("Dana lives in Lisbon.");
    expect(oa.memoryTools({ write: true })).toHaveLength(3);
    expect(oa.defaultMemory().client.integration).toBe("openai-agents");
    const sentTo = fetch.mock.calls.map(([input]) => new URL(String(input)).pathname);
    expect(sentTo).toEqual(["/v2/memory/search", "/v2/memory/add"]);
  });
});
