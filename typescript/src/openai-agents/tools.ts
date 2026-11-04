/**
 * The tools an agent is given: `memory_search`, `memory_open` and `memory_add`. The run context
 * is filled in by the runner and never shown to the model, so a model cannot ask for anybody
 * else's memory.
 */

import { type FunctionTool, type RunContext, tool } from "@openai/agents";
import { z } from "zod";

import {
  AlexeinError,
  AuthenticationError,
  NotFoundError,
  PermissionDeniedError,
} from "../errors.js";
import {
  SAVED,
  UNAVAILABLE,
  notFoundAnswer,
  openAnswer,
  searchAnswer,
  searchFor,
} from "../integrations/shared.js";
import type { AlexeinMemory } from "./index.js";
import { type MemoryContext, sessionIdOf } from "./run.js";

type Run = RunContext<unknown> | undefined;

/**
 * What the model is told when a tool fails: that memory is down, or what was wrong with what it
 * asked, so it can carry on or try again. A wrong key, a run with no user in its context, or an
 * outage when strict throws: those are the developer's to fix.
 */
function failed(strict: boolean) {
  return (run: RunContext<unknown>, error: unknown): string => {
    const yours = error instanceof AuthenticationError || error instanceof PermissionDeniedError;
    const outage = error instanceof AlexeinError && error.outage;
    const noUser = !(run.context as Partial<MemoryContext> | undefined)?.userId;
    if (yours || noUser || (strict && outage)) throw error;
    if (outage) {
      console.warn(`Alexein is unavailable: ${(error as Error).message}`);
      return UNAVAILABLE;
    }
    return `That did not work: ${error instanceof Error ? error.message : String(error)}`;
  };
}

export function buildTools(
  memory: AlexeinMemory,
  write: boolean,
): FunctionTool<unknown, any, string>[] {
  const errorFunction = failed(memory.strict);

  const search = tool({
    name: "memory_search",
    description:
      "Search what you remember about this user: what they said, did and decided in earlier " +
      "conversations. Ask in plain language. Ends with the refs of what it found, to read whole " +
      "with memory_open.",
    parameters: z.object({ query: z.string().describe("What to look for") }),
    errorFunction,
    async execute({ query }, run?: Run) {
      const found = await searchFor(memory.userOf(run?.context), query, memory.fast);
      return searchAnswer(found, memory.maxChars);
    },
  });

  const open = tool({
    name: "memory_open",
    description: "Read one remembered memory whole, by a ref memory_search gave.",
    parameters: z.object({ ref: z.string().describe("A ref memory_search gave") }),
    errorFunction,
    async execute({ ref }, run?: Run) {
      try {
        return openAnswer(await memory.userOf(run?.context).open(ref));
      } catch (error) {
        if (!(error instanceof NotFoundError)) throw error;
        return notFoundAnswer(error);
      }
    },
  });

  const add = tool({
    name: "memory_add",
    description:
      "Remember something about this user for later conversations: a preference, a fact about " +
      "them, a decision. Write it as one plain sentence. Never save passwords, keys or secrets.",
    parameters: z.object({ text: z.string().describe("One plain sentence") }),
    errorFunction,
    async execute({ text }, run?: Run) {
      const saved = await memory.userOf(run?.context).add(text, {
        kind: "note",
        session: sessionIdOf(run?.context),
      });
      return saved.failed ? UNAVAILABLE : SAVED;
    },
  });

  return write ? [search, open, add] : [search, open];
}
