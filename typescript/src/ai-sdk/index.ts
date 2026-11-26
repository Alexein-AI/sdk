/**
 * Memory for any model of the Vercel AI SDK, with no tool for the model to call: a language model
 * middleware.
 *
 * ```ts
 * import { generateText, wrapLanguageModel } from "ai";
 * import { Memory } from "@alexein/sdk";
 * import { alexeinMiddleware } from "@alexein/sdk/ai-sdk";
 *
 * const memory = new Memory(); // one for the process
 * const model = wrapLanguageModel({
 *   model: yourModel,
 *   middleware: alexeinMiddleware(memory, { userId: "dana", session: "conv-7" }),
 * });
 * await generateText({ model, messages });
 * ```
 *
 * Before each call, what memory holds about the user's latest message is added to the system
 * prompt, as quoted data; after it, the user's message and the final reply are saved, a stream's
 * once it ends. Memory never throws, and never holds a call up longer than `budget`.
 */

import type {
  LanguageModelV4CallOptions,
  LanguageModelV4Middleware,
  LanguageModelV4StreamPart,
} from "@ai-sdk/provider";
import type { Memory } from "../client.js";
import {
  type Asked,
  AutoMemory,
  type AutoMemoryOptions,
  Reply,
  latestAsked,
} from "../wrap/memory.js";

export { AutoMemory, HEADER } from "../wrap/memory.js";
export type { AutoMemoryOptions, RecallInfo } from "../wrap/memory.js";

type Prompt = LanguageModelV4CallOptions["prompt"];

/** The finish reason as each specification version gives it: a string, or `{ unified }`. */
function finishedWith(reason: unknown): string | undefined {
  if (typeof reason === "string") return reason;
  const unified = (reason as { unified?: unknown } | null)?.unified;
  return typeof unified === "string" ? unified : undefined;
}

/** Memory after the system prompt's last leading message, or as the first message. */
function withMemory(prompt: Prompt, text: string): Prompt {
  let lead = 0;
  while (lead < prompt.length && prompt[lead]?.role === "system") lead++;
  if (!lead) return [{ role: "system", content: text }, ...prompt];
  const last = prompt[lead - 1] as { role: "system"; content: string };
  return [
    ...prompt.slice(0, lead - 1),
    { ...last, content: `${last.content}\n\n${text}` },
    ...prompt.slice(lead),
  ];
}

/** The call's middleware and its memory: `last` and `flush()`. */
export type AlexeinMiddleware = LanguageModelV4Middleware & { readonly alexein: AutoMemory };

/**
 * A middleware for `wrapLanguageModel` that gives the model what memory holds about the user's
 * latest message and saves each exchange. Options are `wrapAnthropic`'s (`@alexein/sdk/wrap`):
 * `userId` (required), `session`, `author`, `recall`, `save`, `budget`, `maxTokens`, `fast`,
 * `redact`, `beforeSave`. `memory` is your `Memory`; without one, a client for the process is made
 * from ALEXEIN_API_KEY.
 */
export function alexeinMiddleware(
  memory: Memory | undefined,
  options: AutoMemoryOptions,
): AlexeinMiddleware;
export function alexeinMiddleware(options: AutoMemoryOptions): AlexeinMiddleware;
export function alexeinMiddleware(
  memory: Memory | AutoMemoryOptions | undefined,
  options?: AutoMemoryOptions,
): AlexeinMiddleware {
  const auto = options
    ? new AutoMemory(memory as Memory | undefined, options)
    : new AutoMemory(undefined, memory as AutoMemoryOptions);
  const asked = (prompt: Prompt): Asked | null => latestAsked(prompt);

  return {
    specificationVersion: "v4",
    alexein: auto,

    async transformParams({ params }) {
      const text = await auto.lookup(asked(params.prompt));
      return text ? { ...params, prompt: withMemory(params.prompt, text) } : params;
    },

    async wrapGenerate({ doGenerate, params }) {
      const result = await doGenerate();
      const reply = new Reply();
      for (const part of result.content) {
        if (part.type === "text") reply.parts.push(part.text);
        else if (part.type === "tool-call" && !part.providerExecuted) reply.callsTool = true;
      }
      reply.callsTool ||= finishedWith(result.finishReason) === "tool-calls";
      reply.done = true;
      auto.remember(asked(params.prompt), reply);
      return result;
    },

    async wrapStream({ doStream, params }) {
      const { stream, ...rest } = await doStream();
      const reply = new Reply();
      const said = asked(params.prompt);
      let failed = false;
      const seen = new TransformStream<LanguageModelV4StreamPart, LanguageModelV4StreamPart>({
        transform(part, controller) {
          if (part.type === "text-delta") reply.parts.push(part.delta);
          else if (part.type === "tool-call" && !part.providerExecuted) reply.callsTool = true;
          else if (part.type === "finish") {
            reply.done = true;
            reply.callsTool ||= finishedWith(part.finishReason) === "tool-calls";
          } else if (part.type === "error") failed = true;
          controller.enqueue(part);
        },
        flush() {
          if (!failed) auto.remember(said, reply);
        },
      });
      return { stream: stream.pipeThrough(seen), ...rest };
    },
  };
}
