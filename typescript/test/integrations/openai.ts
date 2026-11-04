/** An `AlexeinMemory` over a recorded client, and agents run with it, for the tests. */

import { Agent, run } from "@openai/agents";

import { AlexeinMemory } from "../../src/openai-agents/index.js";
import { Scripted, calls, says } from "./agents.js";
import { REF, type Respond, answer, recorded } from "./recorded.js";

export function load(respond: Respond = answer, { failOpen = true, strict = false } = {}) {
  const { memory, sent } = recorded(respond, "openai-agents", failOpen);
  return { m: new AlexeinMemory(memory, { strict }), sent };
}

export const CONTEXT = { userId: "dana", sessionId: "conv-7" };

/** One turn of a plain agent: run with `recall`, then `remember`. */
export async function turn(
  m: AlexeinMemory,
  model: Scripted,
  input = "Where do I live?",
  extra = {},
) {
  const agent = new Agent({ name: "Assistant", instructions: "Be brief.", model, ...extra });
  const result = await run(agent, input, { context: CONTEXT, callModelInputFilter: m.recall });
  await m.remember(result);
  return result;
}

/** A model that calls every tool once, then stops: what each call returned. */
export async function toolOutputs(m: AlexeinMemory, context: unknown = CONTEXT) {
  const model = new Scripted([
    [
      calls("memory_search", { query: "home" }, "c1"),
      calls("memory_open", { ref: REF }, "c2"),
      calls("memory_add", { text: "Prefers trains." }, "c3"),
    ],
    [says("Done.")],
  ]);
  await run(new Agent({ name: "A", model, tools: m.tools({ write: true }) }), "x", { context });
  const outputs = (model.calls[1]!.input as any[]).filter((i) => i.type === "function_call_result");
  return Object.fromEntries(outputs.map((i) => [i.callId, i.output.text ?? i.output]));
}
