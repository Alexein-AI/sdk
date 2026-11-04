/**
 * Long-term memory for OpenAI Agents SDK agents, from Alexein.
 *
 * ```ts
 * import { AlexeinMemory } from "@alexein/sdk/openai-agents";
 *
 * const memory = new AlexeinMemory(); // or new AlexeinMemory(client, { fast, maxChars, strict })
 * const agent = new Agent({ name: "Assistant", tools: memory.tools() });
 * const result = await run(agent, message, {
 *   context: { userId: "dana", sessionId: "conv-7" },
 *   callModelInputFilter: memory.recall,
 * });
 * await memory.remember(result);
 * ```
 *
 * `recall` searches once a turn, with the user's latest message, and adds what it finds to the
 * instructions of every model call in that turn, so it is never written into your session or
 * history. Whose memory is read is decided by your code, never by a model: the run's
 * `context.userId`.
 */

import type {
  AgentInputItem,
  CallModelInputFilterArgs,
  FunctionTool,
  ModelInputData,
} from "@openai/agents";

import type { Memory } from "../client.js";
import {
  type IntegrationOptions,
  LazyClient,
  isClient,
  promptBlock,
  searchFor,
} from "../integrations/shared.js";
import type { User } from "../user.js";
import { type SavedResult, saidByUser, sessionIdOf, textOf, turnItems, userIdOf } from "./run.js";
import { buildTools } from "./tools.js";

export { NOTHING_FOUND, NOTHING_YET, UNAVAILABLE } from "../integrations/shared.js";
export type { IntegrationOptions as AlexeinMemoryOptions } from "../integrations/shared.js";
export type { MemoryContext, SavedResult } from "./run.js";
export { sessionIdOf, userIdOf } from "./run.js";

/**
 * The user's message when this model call is the first of a turn - the input ends with it, or
 * with developer or system messages after it - else undefined.
 */
function asked(items: AgentInputItem[]): string | undefined {
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i]!;
    const role: string = "role" in item ? item.role : "";
    if (role === "developer" || role === "system") continue;
    return role === "user" ? textOf(item).trim() : undefined;
  }
  return undefined;
}

/** Memory for OpenAI Agents SDK runs: `recall`, `remember` and tools, over one client. */
export class AlexeinMemory {
  readonly fast: boolean;
  readonly maxChars: number;
  readonly strict: boolean;
  readonly #client: LazyClient;
  /**
   * What `recall` found for each run - its context object - for the model calls after the first
   * in a turn (a tool loop, a handoff), whose input no longer ends with the user's message. Per
   * run, so two turns in flight for one user keep their own.
   */
  readonly #recalled = new WeakMap<object, string>();

  /** `client` defaults to one made on first use: fail-open unless strict, a 10 s timeout. */
  constructor(client?: Memory | IntegrationOptions, options: IntegrationOptions = {}) {
    const given = isClient(client) ? client : undefined;
    const settings = isClient(client) ? options : { ...client, ...options };
    this.fast = settings.fast ?? false;
    this.maxChars = settings.maxChars ?? 4000;
    this.strict = settings.strict ?? false;
    this.#client = new LazyClient(given, "openai-agents", this.strict);
  }

  get client(): Memory {
    return this.#client.client;
  }

  /** The memory of the app user a run's context names. */
  userOf(context: unknown): User {
    return this.client.user(userIdOf(context));
  }

  /**
   * `callModelInputFilter: memory.recall`: before the model, what memory holds for the user's
   * latest message, added to the instructions. Already using a filter? Run both:
   * `async (args) => yours({ ...args, modelData: await memory.recall(args) })`.
   */
  readonly recall = async ({
    modelData,
    context,
  }: CallModelInputFilterArgs<unknown>): Promise<ModelInputData> => {
    const user = this.userOf(context);
    const run = context as object;
    let question = asked(modelData.input);
    if (question === undefined && !this.#recalled.has(run)) {
      // A run resumed after an approval, or in another process: nothing kept for it.
      const said = modelData.input.findLast(saidByUser);
      question = said && textOf(said).trim();
    }
    if (question !== undefined) {
      const found = question ? await searchFor(user, question, this.fast) : undefined;
      this.#recalled.set(run, promptBlock(found?.context(this.maxChars) ?? ""));
    }
    const block = this.#recalled.get(run);
    if (!block) return modelData;
    const given = modelData.instructions;
    return { ...modelData, instructions: given ? `${given}\n\n${block}` : block };
  };

  /**
   * Save the turn a run answered - the user's latest message and the final output, under the
   * agent's name - in the context's `sessionId`. Call it once the run is done (for a stream, once
   * `completed` resolves). Saving the same result again edits rather than copies. Tool calls and
   * their results are not saved, and a run paused for an approval saves nothing. Needs a key that
   * writes.
   */
  readonly remember = async (result: SavedResult): Promise<void> => {
    if (result.interruptions?.length) return;
    const context: unknown = result.runContext?.context;
    const session = sessionIdOf(context);
    const items = await turnItems(result, session);
    if (items.length) await this.userOf(context).add(items, { session });
  };

  /**
   * Tools the model calls when it decides to: `memory_search` and `memory_open`, and with
   * `write`, `memory_add`. The user comes from the run's context, which a model never sees.
   */
  tools({ write = false }: { write?: boolean } = {}): FunctionTool<unknown, any, string>[] {
    return buildTools(this, write);
  }
}

// ------------------------------------------------------------ module-level defaults --

let fallback: AlexeinMemory | undefined;

/** The `AlexeinMemory` the module-level functions use: made on first use, from the environment. */
export function defaultMemory(): AlexeinMemory {
  fallback ??= new AlexeinMemory();
  return fallback;
}

/** `recall` of the default `AlexeinMemory`. */
export const recall = (args: CallModelInputFilterArgs<unknown>): Promise<ModelInputData> =>
  defaultMemory().recall(args);

/** `remember` of the default `AlexeinMemory`. */
export const remember = (result: SavedResult): Promise<void> => defaultMemory().remember(result);

/** `tools` of the default `AlexeinMemory`. */
export const memoryTools = (
  options: { write?: boolean } = {},
): FunctionTool<unknown, any, string>[] => defaultMemory().tools(options);
