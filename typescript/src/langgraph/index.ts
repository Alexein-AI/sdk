/**
 * Long-term memory for a LangGraph.js graph, from Alexein.
 *
 * ```ts
 * import { AlexeinMemory, MemoryAnnotation } from "@alexein/sdk/langgraph";
 *
 * const memory = new AlexeinMemory(); // or new AlexeinMemory(client, { fast, maxChars, strict })
 * const graph = new StateGraph(MemoryAnnotation)
 *   .addNode("recall", memory.recall) // what memory holds for the latest human message
 *   .addNode("agent", agent) // yours: put memory.prompt(state) in its system prompt
 *   .addNode("remember", memory.remember) // save the turn
 *   .addEdge(START, "recall").addEdge("recall", "agent").addEdge("agent", "remember")
 *   .compile();
 * await graph.invoke(inputs, { context: { user_id: "dana" }, configurable: { thread_id: "t-1" } });
 * ```
 *
 * Whose memory is read is decided by your code, never by a model: the user id comes from the
 * run's `context.user_id`, else `configurable.user_id`.
 */

import { AIMessage, type BaseMessage, HumanMessage } from "@langchain/core/messages";
import { type StructuredToolInterface, tool } from "@langchain/core/tools";
import { Annotation, MessagesAnnotation, MessagesValue, StateSchema } from "@langchain/langgraph";
import { z } from "zod";

import type { Memory } from "../client.js";
import { NotFoundError } from "../errors.js";
import type { Item } from "../items.js";
import {
  type IntegrationOptions,
  LazyClient,
  SAVED,
  UNAVAILABLE,
  isClient,
  notFoundAnswer,
  openAnswer,
  outageAnswer,
  promptBlock,
  searchAnswer,
  searchFor,
  stableId,
} from "../integrations/shared.js";
import type { User } from "../user.js";

export { NOTHING_FOUND, NOTHING_YET, UNAVAILABLE } from "../integrations/shared.js";
export type { IntegrationOptions as AlexeinMemoryOptions } from "../integrations/shared.js";

/** A graph's state with room for what `recall` found: `messages` and `memory`. */
export const MemoryAnnotation = Annotation.Root({
  ...MessagesAnnotation.spec,
  memory: Annotation<string>({ reducer: (_, found) => found, default: () => "" }),
});

/** The same state as a `StateSchema`, for graphs written that way. */
export const MemoryState = new StateSchema({
  messages: MessagesValue,
  memory: z.string().default(""),
});

/**
 * Whose memory a run reads, as a context schema. Optional, so that a run without it reaches the
 * check that says how to give one instead of failing the schema's.
 */
export const MemoryContext = z.object({ user_id: z.string().optional() });

/** What a node or tool is handed about its run: its context and its thread. */
export interface RunConfig {
  context?: unknown;
  configurable?: Record<string, unknown>;
}

/** A state with messages, and `memory` once `recall` has run. */
export interface MemoryStateValue {
  messages: BaseMessage[];
  memory?: string;
}

/** The app user this run is for: `context.user_id`, else `configurable.user_id`. */
export function userIdOf(config: RunConfig | undefined): string {
  const context = config?.context as { user_id?: unknown } | undefined;
  const found = context?.user_id ?? config?.configurable?.user_id;
  if (found === undefined || found === null || found === "") {
    throw new Error(
      "Alexein needs to know whose memory this is: run the graph with " +
        '{ context: { user_id: "..." } }, or { configurable: { user_id: "..." } }',
    );
  }
  return String(found);
}

function threadOf(config: RunConfig | undefined): string | undefined {
  const thread = config?.configurable?.thread_id;
  return thread === undefined || thread === null ? undefined : String(thread);
}

function lastHuman(messages: BaseMessage[]): BaseMessage | undefined {
  return messages.findLast((m) => HumanMessage.isInstance(m));
}

/** The last reply that is an answer, not a tool call. */
function lastReply(messages: BaseMessage[]): BaseMessage | undefined {
  return messages.findLast((m) => AIMessage.isInstance(m) && !m.tool_calls?.length);
}

/** Memory for a LangGraph.js graph: nodes, a prompt block and tools, over one client. */
export class AlexeinMemory {
  readonly fast: boolean;
  readonly maxChars: number;
  readonly strict: boolean;
  readonly #client: LazyClient;

  /** `client` defaults to one made on first use: fail-open unless strict, a 10 s timeout. */
  constructor(client?: Memory | IntegrationOptions, options: IntegrationOptions = {}) {
    const given = isClient(client) ? client : undefined;
    const settings = isClient(client) ? options : { ...client, ...options };
    this.fast = settings.fast ?? false;
    this.maxChars = settings.maxChars ?? 4000;
    this.strict = settings.strict ?? false;
    this.#client = new LazyClient(given, "langgraph", this.strict, settings.timeout);
  }

  get client(): Memory {
    return this.#client.client;
  }

  private user(config: RunConfig | undefined): User {
    return this.client.user(userIdOf(config));
  }

  /** A node: what memory holds for the latest human message, into `state.memory`. */
  readonly recall = async (
    state: MemoryStateValue,
    config?: RunConfig,
  ): Promise<{ memory: string }> => {
    const asked = lastHuman(state.messages)?.text.trim();
    const user = this.user(config); // first: a run with no user says so, whatever else is missing
    if (!asked) return { memory: "" };
    const found = await searchFor(user, asked, this.fast);
    return { memory: found?.context(this.maxChars) ?? "" };
  };

  /**
   * A node: save the turn - the latest human message and the last reply that is not a tool call -
   * in the thread's session. Each message keeps its LangGraph id as its item id (else a stable
   * hash), so running a turn again edits what was saved rather than adding a copy. Tool calls and
   * tool results are not saved. Needs a key that writes.
   */
  readonly remember = async (
    state: MemoryStateValue,
    config?: RunConfig,
  ): Promise<Record<string, never>> => {
    const user = this.user(config);
    const thread = threadOf(config);
    const said = [
      await item(lastHuman(state.messages), "user", thread),
      await item(lastReply(state.messages), "assistant", thread),
    ].filter((i): i is Item => i !== undefined);
    if (said.length) await user.add(said, { session: thread });
    return {};
  };

  /** What `recall` found, as a block for your system prompt; empty when it found nothing. */
  readonly prompt = (state: { memory?: string }): string => promptBlock(state.memory ?? "");

  /**
   * Tools the model calls when it decides to: `memory_search` and `memory_open`, and with
   * `write`, `memory_add`. The user comes from the run, which a model never sees.
   */
  tools({ write = false }: { write?: boolean } = {}): StructuredToolInterface[] {
    const read = [this.searchTool(), this.openTool()];
    return write ? [...read, this.addTool()] : read;
  }

  private searchTool() {
    return tool(
      async ({ query }, config) => {
        const found = await searchFor(this.user(config), query, this.fast);
        return searchAnswer(found, this.maxChars);
      },
      {
        name: "memory_search",
        description:
          "Search what you remember about this user: what they said, did and decided in " +
          "earlier conversations. Ask in plain language. Ends with the refs of what it found, " +
          "to read whole with memory_open.",
        schema: z.object({ query: z.string().describe("What to look for") }),
      },
    );
  }

  private openTool() {
    return tool(
      async ({ ref }, config) => {
        const user = this.user(config);
        try {
          return openAnswer(await user.open(ref));
        } catch (error) {
          if (error instanceof NotFoundError) return notFoundAnswer(error);
          return outageAnswer(error, this.strict);
        }
      },
      {
        name: "memory_open",
        description: "Read one remembered memory whole, by a ref memory_search gave.",
        schema: z.object({ ref: z.string().describe("A ref memory_search gave") }),
      },
    );
  }

  private addTool() {
    return tool(
      async ({ text }, config) => {
        const saved = await this.user(config).add(text, {
          kind: "note",
          session: threadOf(config),
        });
        return saved.failed ? UNAVAILABLE : SAVED;
      },
      {
        name: "memory_add",
        description:
          "Remember something about this user for later conversations: a preference, a fact " +
          "about them, a decision. Write it as one plain sentence. Never save passwords, keys " +
          "or secrets.",
        schema: z.object({ text: z.string().describe("One plain sentence") }),
      },
    );
  }
}

async function item(
  message: BaseMessage | undefined,
  role: string,
  thread: string | undefined,
): Promise<Item | undefined> {
  const text = message?.text;
  if (!text?.trim()) return undefined;
  const id = message?.id ?? (await stableId(thread, role, text));
  return { id, role, text };
}

// ------------------------------------------------------------ module-level defaults --

let fallback: AlexeinMemory | undefined;

/** The `AlexeinMemory` the module-level functions use: made on first use, from the environment. */
export function defaultMemory(): AlexeinMemory {
  fallback ??= new AlexeinMemory();
  return fallback;
}

/** `recall` of the default `AlexeinMemory`. */
export const recall = (state: MemoryStateValue, config?: RunConfig) =>
  defaultMemory().recall(state, config);

/** `remember` of the default `AlexeinMemory`. */
export const remember = (state: MemoryStateValue, config?: RunConfig) =>
  defaultMemory().remember(state, config);

/** `prompt` of the default `AlexeinMemory`. */
export const memoryPrompt = (state: { memory?: string }): string => defaultMemory().prompt(state);

/** `tools` of the default `AlexeinMemory`. */
export const memoryTools = (options: { write?: boolean } = {}): StructuredToolInterface[] =>
  defaultMemory().tools(options);
