/**
 * The `memory.ts` that `npx @alexein/cli init openai-agents` writes, imported as written - its
 * client made from its own settings - and run inside the OpenAI Agents SDK's own runner, with a
 * scripted model standing in for OpenAI, through the real `@alexein/sdk`, against a recorded memory
 * API. And checked as a developer's project would check it: strict TypeScript, and prettier at its
 * defaults.
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { AuthenticationError, ServiceUnavailableError } from "@alexein/sdk";
import { Agent, MemorySession, run, setTracingDisabled } from "@openai/agents";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { GENERATED as GENERATED_BY } from "../src/project.js";
import { calls, says, Scripted } from "./agents.js";
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
const GENERATED = ALL_GENERATED + "openai-agents-template/";

beforeAll(() => {
  setTracingDisabled(true);
  mkdirSync(GENERATED, { recursive: true });
});
afterAll(() => rmSync(GENERATED, { recursive: true, force: true }));

/** The file as `init` writes it, imported fresh, its requests answered by `respond`. */
const load = (respond: Respond = answer, written: Written = {}) =>
  loadMemoryFile(GENERATED, "openai_agents/memory.ts.tmpl", respond, written);
type Module = Record<string, any>;

const CONTEXT = { userId: "dana", sessionId: "conv-7" };
const UNAVAILABLE = "Memory is unavailable right now; carry on without it.";

/** One turn of a plain agent: run with `memory.recall`, then `memory.remember`. */
async function turn(m: Module, model: Scripted, input = "Where do I live?", extra = {}) {
  const agent = new Agent({ name: "Assistant", instructions: "Be brief.", model, ...extra });
  const result = await run(agent, input, {
    context: CONTEXT,
    callModelInputFilter: m.memory.recall,
  });
  await m.memory.remember(result);
  return result;
}

describe("the written file", () => {
  it("is short, and imports everything else from @alexein/sdk", async () => {
    const { path, module: m } = await load();
    const text = readFileSync(path, "utf8");
    expect(text.split("\n").length).toBeLessThanOrEqual(60);
    expect(GENERATED_BY.exec(text)?.slice(1)).toEqual(["openai-agents", "0.3.0"]);
    const imports = [...text.matchAll(/^(?:import|export) .*? from "([^"]+)";$/gms)].map(
      (i) => i[1],
    );
    expect(new Set(imports)).toEqual(new Set(["@alexein/sdk/openai-agents"]));
    expect(Object.keys(m).sort()).toEqual(["FAST", "MAX_CHARS", "STRICT", "TIMEOUT", "memory"]);
  });

  it("makes its client from its settings, with the key and address from the environment", async () => {
    const { module: m } = await load(answer, {
      fast: true,
      edits: [["TIMEOUT = 10_000", "TIMEOUT = 3_000"]],
    });
    expect(m.memory.client).toMatchObject({
      baseUrl: "https://memory.test",
      timeout: 3_000,
      failOpen: true,
      integration: "openai-agents",
    });
    expect(m.memory).toMatchObject({ fast: true, maxChars: 4000, strict: false });
  });
  it("imports with no key, and asks for one on first use", async () => {
    vi.stubEnv("ALEXEIN_API_KEY", "");
    const path = writeMemoryFile(GENERATED, "openai_agents/memory.ts.tmpl", {
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
      integration: "openai-agents",
    });
  });
});

describe("the written file in a run", () => {
  it("recalls before the model and saves the turn after", async () => {
    const { module: m, sent } = await load();
    const model = new Scripted([[says("You live in Lisbon.")]]);

    const result = await turn(m, model);

    expect(result.finalOutput).toBe("You live in Lisbon.");
    expect(routes(sent)).toEqual(["search", "add"]);
    expect(users(sent)).toEqual(new Set(["dana"]));
    expect(sent[0]!.headers["User-Agent"]).toMatch(/^alexein-js\/\S+ openai-agents$/);
    expect(bodies(sent, "search")[0]).toMatchObject({ query: "Where do I live?", fast: false });
    expect(model.calls[0]!.systemInstructions).toMatch(/^Be brief\.\n\nWhat you remember/);
    expect(model.calls[0]!.systemInstructions).toContain("Dana lives in Lisbon.");
    const items = bodies(sent, "add")[0]!.items;
    expect(items.map((i: any) => [i.role, i.text, i.author, i.session])).toEqual([
      ["user", "Where do I live?", undefined, "conv-7"],
      ["assistant", "You live in Lisbon.", "Assistant", "conv-7"],
    ]);
  });

  it("searches once in a tool loop, and every call has the memory", async () => {
    const { module: m, sent } = await load();
    const model = new Scripted([[calls("memory_open", { ref: REF }, "c1")], [says("Lisbon.")]]);

    await turn(m, model, "Where do I live?", { tools: m.memory.tools() });

    expect(routes(sent)).toEqual(["search", "open", "add"]); // recall, the tool, remember
    for (const call of model.calls) expect(call.systemInstructions).toContain("Lisbon");
  });

  it("gives the agent after a handoff the memory too", async () => {
    const { module: m, sent } = await load();
    const expertModel = new Scripted([[says("Lisbon, as you said.")]]);
    const expert = new Agent({ name: "Expert", instructions: "Know things.", model: expertModel });
    const triage = Agent.create({
      name: "Triage",
      model: new Scripted([[calls("transfer_to_Expert", {}, "h1")]]),
      handoffs: [expert],
    });

    const result = await run(triage, "Where do I live?", {
      context: CONTEXT,
      callModelInputFilter: m.memory.recall,
    });
    await m.memory.remember(result);

    expect(routes(sent)).toEqual(["search", "add"]);
    expect(expertModel.calls[0]!.systemInstructions).toContain("Dana lives in Lisbon.");
    expect(bodies(sent, "add")[0]!.items[1].author).toBe("Expert");
  });

  it("remembers a stream once it has completed", async () => {
    const { module: m, sent } = await load();
    const agent = new Agent({ name: "Assistant", model: new Scripted([[says("Lisbon.")]]) });

    const stream = await run(agent, "Where do I live?", {
      context: CONTEXT,
      callModelInputFilter: m.memory.recall,
      stream: true,
    });
    for await (const _ of stream.toTextStream());
    await stream.completed;
    await m.memory.remember(stream);

    expect(routes(sent)).toEqual(["search", "add"]);
    expect(bodies(sent, "add")[0]!.items[1].text).toBe("Lisbon.");
  });

  it("never lets the memory land in a session", async () => {
    const { module: m, sent } = await load();
    const session = new MemorySession();
    const agent = new Agent({
      name: "A",
      model: new Scripted([[says("Hello.")], [says("Lisbon.")]]),
    });
    for (const input of ["Hi", "Where do I live?"]) {
      const result = await run(agent, input, {
        context: CONTEXT,
        callModelInputFilter: m.memory.recall,
        session,
      });
      await m.memory.remember(result);
    }
    expect(JSON.stringify(await session.getItems())).not.toContain("Dana lives in Lisbon.");
    expect(bodies(sent, "search").map((b) => b.query)).toEqual(["Hi", "Where do I live?"]);
  });

  it("saves the same result twice under the same ids", async () => {
    const { module: m, sent } = await load();
    const result = await turn(m, new Scripted([[says("Lisbon.")]]));
    await m.memory.remember(result);
    const [first, second] = bodies(sent, "add");
    expect(first!.items.map((i: any) => i.id)).toEqual(second!.items.map((i: any) => i.id));
  });

  it("saves structured output as JSON", async () => {
    const { module: m, sent } = await load();
    await turn(m, new Scripted([[says('{"city":"Lisbon"}')]]), "Where do I live?", {
      outputType: z.object({ city: z.string() }),
    });
    expect(JSON.parse(bodies(sent, "add")[0]!.items[1].text)).toEqual({ city: "Lisbon" });
  });

  it("recalls nothing for a user with no memory yet", async () => {
    const { module: m } = await load((route) => (route === "search" ? nobody() : answer(route)));
    const model = new Scripted([[says("Hello.")]]);
    await turn(m, model);
    expect(model.calls[0]!.systemInstructions).toBe("Be brief.");
  });

  it("takes any context with a userId, and must have one", async () => {
    const { module: m, sent } = await load();
    const agent = new Agent({ name: "A", model: new Scripted([[says("Hi.")], [says("Hi.")]]) });
    const result = await run(agent, "Hi", {
      context: { userId: "dana", plan: "pro" },
      callModelInputFilter: m.memory.recall,
    });
    await m.memory.remember(result);
    expect(users(sent)).toEqual(new Set(["dana"]));
    expect(bodies(sent, "add")[0]!.items[0].session).toBeUndefined();

    const before = sent.length;
    await expect(
      run(agent, "Hi", { context: {}, callModelInputFilter: m.memory.recall }),
    ).rejects.toThrow('context: { userId: "..." }');
    expect(sent.length).toBe(before);
  });

  it("searches a long message by its end", async () => {
    const { module: m, sent } = await load();
    await turn(m, new Scripted([[says("Lisbon.")]]), "x".repeat(2500) + " Where do I live?");
    const query: string = bodies(sent, "search")[0]!.query;
    expect(query.length).toBe(2000);
    expect(query.endsWith("Where do I live?")).toBe(true);
  });
});

/** A model that calls every tool once, then stops: what each call returned. */
async function toolOutputs(m: Module, context: unknown = CONTEXT) {
  const model = new Scripted([
    [
      calls("memory_search", { query: "home" }, "c1"),
      calls("memory_open", { ref: REF }, "c2"),
      calls("memory_add", { text: "Prefers trains." }, "c3"),
    ],
    [says("Done.")],
  ]);
  const agent = new Agent({ name: "A", model, tools: m.memory.tools({ write: true }) });
  await run(agent, "x", { context });
  const outputs = (model.calls[1]!.input as any[]).filter((i) => i.type === "function_call_result");
  return Object.fromEntries(outputs.map((i) => [i.callId, i.output.text ?? i.output]));
}

describe("the tools", () => {
  it("take the user from the run, never from the model", async () => {
    const { module: m, sent } = await load();
    const outputs = await toolOutputs(m);

    expect(outputs.c1).toContain("Dana lives in Lisbon.");
    expect(outputs.c1).toContain(`memory_open:\n- ${REF}`);
    expect(outputs.c2).toBe("2026-10-01: Dana: I moved to Lisbon.");
    expect(outputs.c3).toBe("Saved.");
    expect(users(sent)).toEqual(new Set(["dana"]));
    expect(bodies(sent, "add")[0]!.items).toEqual([
      { text: "Prefers trains.", kind: "note", session: "conv-7" },
    ]);
    for (const t of m.memory.tools({ write: true })) {
      expect(JSON.stringify(t.parameters)).not.toMatch(/user/i);
    }
  });

  it("hand the model its own mistakes, and the run goes on", async () => {
    const refused = (route: string) =>
      route === "open"
        ? Response.json({ detail: "open needs a ref" }, { status: 422 })
        : answer(route);
    const { module: m } = await load(refused);
    const model = new Scripted([[calls("memory_open", { ref: "" }, "c1")], [says("Sorry.")]]);
    const agent = new Agent({ name: "A", model, tools: m.memory.tools() });
    const result = await run(agent, "x", { context: CONTEXT });
    const output = (model.calls[1]!.input as any[]).find((i) => i.type === "function_call_result");
    expect(result.finalOutput).toBe("Sorry.");
    expect(output.output.text ?? output.output).toMatch(/^That did not work: .*open needs a ref/);
  });
});

describe("memory being down", () => {
  it("lets a turn go ahead without it", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { module: m, sent } = await load(down);
    const model = new Scripted([[says("Still here.")]]);
    const result = await turn(m, model);
    expect(result.finalOutput).toBe("Still here.");
    expect(model.calls[0]!.systemInstructions).toBe("Be brief.");
    expect(routes(sent)).toEqual(["search", "search", "search", "add", "add", "add"]);
  });

  it("tells the model through the tools", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { module: m } = await load(down);
    expect(new Set(Object.values(await toolOutputs(m)))).toEqual(new Set([UNAVAILABLE]));
    expect(warn).toHaveBeenCalled();
  });

  it("throws with STRICT = true", async () => {
    const { module: m } = await load(down, { edits: [["STRICT = false", "STRICT = true"]] });
    await expect(turn(m, new Scripted([[says("Hi.")]]))).rejects.toBeInstanceOf(
      ServiceUnavailableError,
    );
  });

  it("throws on a wrong key even so", async () => {
    const { module: m } = await load(wrongKey);
    await expect(turn(m, new Scripted([[says("Hi.")]]))).rejects.toBeInstanceOf(
      AuthenticationError,
    );
    await expect(toolOutputs(m)).rejects.toThrow(/bad key/);
  });
});

describe("presets", () => {
  it("shows the wiring each one uses", async () => {
    const text = (parts: string[]) =>
      readFileSync(writeMemoryFile(GENERATED, "openai_agents/memory.ts.tmpl", { parts }), "utf8");
    expect(text(["nodes"])).toContain("callModelInputFilter: memory.recall");
    expect(text(["nodes"])).not.toContain("memory.tools");
    expect(text(["tools"])).toContain("memory.tools({ write: true })");
    expect(text(["tools"])).not.toContain("memory.recall");
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
    const path = writeMemoryFile(GENERATED, "openai_agents/memory.ts.tmpl", { parts });
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
    execFileSync(
      "npx",
      ["prettier", "--no-config", "--ignore-path", "/dev/null", "--check", path],
      { stdio: "pipe" },
    );
  });
});
