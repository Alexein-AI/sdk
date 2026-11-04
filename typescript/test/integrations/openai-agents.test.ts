/**
 * `@alexein/sdk/openai-agents` inside the OpenAI Agents SDK's own runner - a scripted model
 * standing in for OpenAI - against a recorded memory API: `recall` and `remember`.
 */

import { Agent, MemorySession, run, setTracingDisabled } from "@openai/agents";
import { beforeAll, describe, expect, it } from "vitest";
import { z } from "zod";

import { Scripted, calls, says } from "./agents.js";
import { CONTEXT, load, turn } from "./openai.js";
import { REF, SEARCHED, answer, bodies, routes, users } from "./recorded.js";

beforeAll(() => setTracingDisabled(true));

describe("in a run", () => {
  it("recalls before the model and saves the turn after", async () => {
    const { m, sent } = load();
    const model = new Scripted([[says("You live in Lisbon.")]]);
    const result = await turn(m, model);

    expect(result.finalOutput).toBe("You live in Lisbon.");
    expect(routes(sent)).toEqual(["search", "add"]);
    expect(users(sent)).toEqual(new Set(["dana"]));
    expect(sent[0]!.headers["User-Agent"]).toMatch(/ openai-agents$/);
    expect(bodies(sent, "search")[0]!.query).toBe("Where do I live?");
    expect(model.calls[0]!.systemInstructions).toMatch(/^Be brief\.\n\nWhat you remember/);
    expect(model.calls[0]!.systemInstructions).toContain("- Dana lives in Lisbon.");
    const items = bodies(sent, "add")[0]!.items;
    expect(items.map((i: any) => [i.role, i.text, i.author, i.session])).toEqual([
      ["user", "Where do I live?", undefined, "conv-7"],
      ["assistant", "You live in Lisbon.", "Assistant", "conv-7"],
    ]);
    expect(items[0].id).toMatch(/^[0-9a-f]{24}$/);
  });

  it("searches once in a tool loop, and every call has the memory", async () => {
    const { m, sent } = load();
    const model = new Scripted([[calls("memory_open", { ref: REF }, "c1")], [says("Lisbon.")]]);
    await turn(m, model, "Where do I live?", { tools: m.tools() });
    expect(routes(sent)).toEqual(["search", "open", "add"]);
    for (const call of model.calls) expect(call.systemInstructions).toContain("Lisbon");
  });

  it("gives the agent after a handoff the memory too", async () => {
    const { m, sent } = load();
    const expertModel = new Scripted([[says("Lisbon, as you said.")]]);
    const expert = new Agent({ name: "Expert", instructions: "Know things.", model: expertModel });
    const triage = Agent.create({
      name: "Triage",
      model: new Scripted([[calls("transfer_to_Expert", {}, "h1")]]),
      handoffs: [expert],
    });
    const result = await run(triage, "Where do I live?", {
      context: CONTEXT,
      callModelInputFilter: m.recall,
    });
    await m.remember(result);
    expect(routes(sent)).toEqual(["search", "add"]);
    expect(expertModel.calls[0]!.systemInstructions).toContain("Dana lives in Lisbon.");
    expect(bodies(sent, "add")[0]!.items[1].author).toBe("Expert");
  });

  it("remembers a stream once it has completed", async () => {
    const { m, sent } = load();
    const agent = new Agent({ name: "Assistant", model: new Scripted([[says("Lisbon.")]]) });
    const stream = await run(agent, "Where do I live?", {
      context: CONTEXT,
      callModelInputFilter: m.recall,
      stream: true,
    });
    for await (const _ of stream.toTextStream());
    await stream.completed;
    await m.remember(stream);
    expect(routes(sent)).toEqual(["search", "add"]);
    expect(bodies(sent, "add")[0]!.items[1].text).toBe("Lisbon.");
  });

  it("never lets the memory land in a session", async () => {
    const { m, sent } = load();
    const session = new MemorySession();
    const agent = new Agent({
      name: "A",
      model: new Scripted([[says("Hello.")], [says("Lisbon.")]]),
    });
    for (const input of ["Hi", "Where do I live?"]) {
      const result = await run(agent, input, {
        context: CONTEXT,
        callModelInputFilter: m.recall,
        session,
      });
      await m.remember(result);
    }
    expect(JSON.stringify(await session.getItems())).not.toContain("Dana lives in Lisbon.");
    expect(bodies(sent, "search").map((b) => b.query)).toEqual(["Hi", "Where do I live?"]);
    expect(bodies(sent, "add")[1]!.items[0].text).toBe("Where do I live?");
  });

  it("saves the same result twice under the same ids", async () => {
    const { m, sent } = load();
    const result = await turn(m, new Scripted([[says("Lisbon.")]]));
    await m.remember(result);
    const [first, second] = bodies(sent, "add");
    expect(first!.items.map((i: any) => i.id)).toEqual(second!.items.map((i: any) => i.id));
  });

  it("saves each turn apart from a model without response ids", async () => {
    const { m, sent } = load();
    const agent = new Agent({
      name: "A",
      model: new Scripted([[says("Hi.")], [says("Hi.")]], false),
    });
    const options = { context: { userId: "dana" }, callModelInputFilter: m.recall };
    const first = await run(agent, "Thanks", options);
    await m.remember(first);
    await m.remember(await run(agent, "Thanks", options));
    await m.remember(first);
    const ids = bodies(sent, "add").map((b) => b.items.map((i: any) => i.id));
    expect(ids[0]).not.toEqual(ids[1]); // two turns, said the same way
    expect(ids[0]).toEqual(ids[2]); // one turn, saved twice
  });

  it("saves structured output as JSON", async () => {
    const { m, sent } = load();
    const model = new Scripted([[says('{"city":"Lisbon"}')]]);
    await turn(m, model, "Where do I live?", { outputType: z.object({ city: z.string() }) });
    expect(JSON.parse(bodies(sent, "add")[0]!.items[1].text)).toEqual({ city: "Lisbon" });
  });

  it("takes any context with a userId, and must have one", async () => {
    const { m, sent } = load();
    const agent = new Agent({ name: "A", model: new Scripted([[says("Hi.")], [says("Hi.")]]) });
    const result = await run(agent, "Hi", {
      context: { userId: "dana", plan: "pro" },
      callModelInputFilter: m.recall,
    });
    await m.remember(result);
    expect(users(sent)).toEqual(new Set(["dana"]));
    expect(bodies(sent, "add")[0]!.items[0].session).toBeUndefined();
    const before = sent.length;
    await expect(run(agent, "Hi", { context: {}, callModelInputFilter: m.recall })).rejects.toThrow(
      /whose memory/,
    );
    expect(sent.length).toBe(before);
  });
});

/** What the runner hands the filter before a model call. */
const call = (context: unknown, ...input: unknown[]) =>
  ({
    modelData: { input, instructions: "Be brief." },
    agent: new Agent({ name: "A" }),
    context,
  }) as any;
const ASKED = { role: "user", content: "Where do I live?" };
const TOOL_OUTPUT = { type: "function_call_result", callId: "c1", name: "t", status: "completed" };

describe("what a real model and server send", () => {
  it("searches a long message by its end", async () => {
    const { m, sent } = load();
    await turn(m, new Scripted([[says("Lisbon.")]]), "x".repeat(2500) + " Where do I live?");
    const query: string = bodies(sent, "search")[0]!.query;
    expect(query.length).toBe(2000);
    expect(query.endsWith("Where do I live?")).toBe(true);
  });

  it("keeps two turns in flight for one user apart", async () => {
    const echo = (route: string, body: any) =>
      route === "search"
        ? Response.json({ ...SEARCHED, memories: [{ type: "known", text: `FOR: ${body.query}` }] })
        : answer(route);
    const { m } = load(echo);
    const [first, second] = [{ userId: "dana" }, { userId: "dana" }];
    await m.recall(call(first, ASKED));
    await m.recall(call(second, { role: "user", content: "My dog's name?" }));
    const afterATool = await m.recall(call(first, ASKED, TOOL_OUTPUT));
    expect(afterATool.instructions).toContain("FOR: Where do I live?");
    expect(afterATool.instructions).not.toContain("dog");
  });

  it("searches its user's message in a resumed run with nothing kept", async () => {
    const { m, sent } = load();
    const resumed = await m.recall(call({ userId: "dana" }, ASKED, TOOL_OUTPUT));
    expect(bodies(sent, "search").map((b) => b.query)).toEqual(["Where do I live?"]);
    expect(resumed.instructions).toContain("Dana lives in Lisbon.");
  });

  it("still recalls when a system message follows the user's", async () => {
    const { m, sent } = load();
    await m.recall(call({ userId: "dana" }, ASKED, { role: "system", content: "Friday." }));
    expect(bodies(sent, "search").map((b) => b.query)).toEqual(["Where do I live?"]);
  });

  it("saves nothing from a run paused for an approval", async () => {
    const { m, sent } = load();
    await m.remember({ interruptions: [{ type: "tool_approval_item" }] });
    expect(sent).toEqual([]);
  });
});
