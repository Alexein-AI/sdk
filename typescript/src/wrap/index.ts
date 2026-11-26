/**
 * Memory for the official Anthropic and OpenAI clients, with no tool for the model to call.
 *
 * ```ts
 * import Anthropic from "@anthropic-ai/sdk";
 * import { Memory } from "@alexein/sdk";
 * import { wrapAnthropic } from "@alexein/sdk/wrap";
 *
 * const memory = new Memory(); // one for the process
 * const claude = wrapAnthropic(new Anthropic(), memory, { userId: "dana", session: "conv-7" });
 * await claude.messages.create({ model, max_tokens: 1024, messages });
 * ```
 *
 * Before each call, what memory holds about the user's latest message is added to the system
 * prompt, as quoted data with who said it and when; after it, the user's message and the reply
 * are saved. `wrapOpenAI` does the same for `chat.completions` and `responses`. Neither ever
 * throws for memory's sake, nor holds a call up longer than `budget`: when memory is slow or
 * down, the model is called without it.
 *
 * Whose memory is read is decided by your code, never by a model: the `userId` you pass. Wrap a
 * client per request or per conversation; wrapping is cheap, and the clients are shared.
 */

import type { Memory } from "../client.js";
import {
  type Asked,
  AutoMemory,
  type AutoMemoryOptions,
  Reply,
  latestAsked,
  textOf,
} from "./memory.js";

export { AutoMemory, HEADER, memoryBlock } from "./memory.js";
export type { AutoMemoryOptions, RecallInfo } from "./memory.js";

type Params = Record<string, unknown>;

/** How one API's calls are read and changed. */
interface Provider {
  asked(params: Params): Asked | null;
  inject(params: Params, text: string): Params;
  reply(result: unknown): Reply;
  feed(reply: Reply, event: unknown): void;
}

/** What the libraries send and answer, read field by field: their types are theirs to change. */
type Loose = any;

const PAUSED = ["tool_use", "pause_turn"];

/** `messages`: the system prompt is `system`, a string or a list of blocks. */
const anthropicMessages: Provider = {
  asked: (params) => latestAsked(params.messages),
  inject(params, text) {
    const system = params.system;
    if (Array.isArray(system)) return { ...params, system: [...system, { type: "text", text }] };
    if (typeof system === "string" && system.trim())
      return { ...params, system: `${system}\n\n${text}` };
    return { ...params, system: text };
  },
  reply(result: Loose) {
    const reply = new Reply();
    for (const part of Array.isArray(result?.content) ? result.content : []) {
      if (part?.type === "text") reply.parts.push(part.text ?? "");
      else if (part?.type === "tool_use") reply.callsTool = true;
    }
    reply.callsTool ||= PAUSED.includes(result?.stop_reason);
    reply.done = true;
    return reply;
  },
  feed(reply, event: Loose) {
    if (event?.type === "content_block_start" && event.content_block?.type === "tool_use") {
      reply.callsTool = true;
    } else if (event?.type === "content_block_delta" && event.delta?.type === "text_delta") {
      reply.parts.push(event.delta.text ?? "");
    } else if (event?.type === "message_delta") {
      reply.callsTool ||= PAUSED.includes(event.delta?.stop_reason);
    } else if (event?.type === "message_stop") {
      reply.done = true;
    }
  },
};

const INSTRUCTIONS = ["system", "developer"];
const TOOL_FINISH = ["tool_calls", "function_call"];

/** `chat.completions`: the system prompt is a `system` (or `developer`) message. */
const chatCompletions: Provider = {
  asked: (params) => latestAsked(params.messages),
  inject(params, text) {
    const messages = Array.isArray(params.messages) ? [...(params.messages as Loose[])] : [];
    let lead = 0;
    while (lead < messages.length && INSTRUCTIONS.includes(messages[lead]?.role)) lead++;
    const role = lead ? messages[0].role : "system";
    messages.splice(lead, 0, { role, content: text });
    return { ...params, messages };
  },
  reply(result: Loose) {
    const reply = new Reply();
    const choice = result?.choices?.[0];
    if (choice) {
      const content = choice.message?.content;
      reply.parts.push(typeof content === "string" ? content : textOf(content));
      reply.callsTool =
        Boolean(choice.message?.tool_calls?.length || choice.message?.function_call) ||
        TOOL_FINISH.includes(choice.finish_reason);
    }
    reply.done = true;
    return reply;
  },
  feed(reply, event: Loose) {
    const choice = event?.choices?.[0];
    if (!choice) return;
    if (typeof choice.delta?.content === "string") reply.parts.push(choice.delta.content);
    if (choice.delta?.tool_calls?.length || choice.delta?.function_call) reply.callsTool = true;
    if (choice.finish_reason) {
      reply.done = true;
      reply.callsTool ||= TOOL_FINISH.includes(choice.finish_reason);
    }
  },
};

/** What the model asks your code to run: the turn is not over until it answers. */
const CALLS = new Set([
  "function_call",
  "custom_tool_call",
  "computer_call",
  "local_shell_call",
  "shell_call",
  "apply_patch_call",
  "mcp_approval_request",
]);

/** `responses`: the system prompt is `instructions`; `input` is a string or a list. */
const responsesApi: Provider = {
  asked(params) {
    const input = params.input;
    if (typeof input === "string")
      return input.trim() ? { text: input.trim(), before: "", at: 0 } : null;
    return latestAsked(input);
  },
  inject(params, text) {
    const given = typeof params.instructions === "string" ? params.instructions.trim() : "";
    return { ...params, instructions: given ? `${params.instructions}\n\n${text}` : text };
  },
  reply(result: Loose) {
    const reply = new Reply();
    for (const item of Array.isArray(result?.output) ? result.output : []) {
      if (CALLS.has(item?.type)) reply.callsTool = true;
      else if (item?.type === "message") reply.parts.push(textOf(item.content, ["output_text"]));
    }
    reply.done =
      result?.status === undefined || result?.status === null || result?.status === "completed";
    return reply;
  },
  feed(reply, event: Loose) {
    if (event?.type === "response.output_text.delta") reply.parts.push(event.delta ?? "");
    else if (
      event?.type === "response.output_item.added" ||
      event?.type === "response.output_item.done"
    ) {
      reply.callsTool ||= CALLS.has(event.item?.type);
    } else if (event?.type === "response.completed") reply.done = true;
  },
};

/** Calls `done` once, with what was seen, when the stream's iteration ends. */
function observed<S extends object>(
  stream: S,
  provider: Provider,
  done: (reply: Reply) => void,
): S {
  const reply = new Reply();
  let ended = false;
  const end = () => {
    if (!ended) {
      ended = true;
      done(reply);
    }
  };
  return new Proxy(stream, {
    get(target, prop) {
      if (prop === Symbol.asyncIterator) {
        return () => {
          const inner = (target as Loose)[Symbol.asyncIterator]();
          const iterator: AsyncIterator<unknown> & AsyncIterable<unknown> = {
            async next() {
              const step = await inner.next();
              if (step.done) end();
              else {
                try {
                  provider.feed(reply, step.value);
                } catch {
                  // an event this version cannot read: it is handed on all the same
                }
              }
              return step;
            },
            return: (value?: unknown) =>
              inner.return?.(value) ?? Promise.resolve({ done: true, value }),
            throw: (error?: unknown) => inner.throw?.(error) ?? Promise.reject(error),
            [Symbol.asyncIterator]() {
              return iterator;
            },
          };
          return iterator;
        };
      }
      const value = Reflect.get(target, prop, target);
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}

/**
 * A call that looks memory up first and then makes the real one: awaited, it answers what the
 * library's call answers; `withResponse()` and `asResponse()` reach the same request.
 */
class Deferred implements PromiseLike<unknown> {
  #request: Promise<{ call: Loose }> | undefined;
  #result: Promise<unknown> | undefined;

  constructor(
    private readonly start: () => Promise<{ call: Loose }>,
    private readonly seen: (data: unknown) => unknown,
  ) {
    // Sent at once, as the library's own call is, awaited or not; a failure is the awaiter's.
    this.#answer().catch(() => {});
  }

  #call(): Promise<{ call: Loose }> {
    this.#request ??= this.start();
    return this.#request;
  }

  #answer(): Promise<unknown> {
    this.#result ??= this.#call().then(({ call }) =>
      Promise.resolve(call).then((data) => this.seen(data)),
    );
    return this.#result;
  }

  then<A = unknown, B = never>(
    onfulfilled?: ((value: unknown) => A | PromiseLike<A>) | null,
    onrejected?: ((reason: unknown) => B | PromiseLike<B>) | null,
  ): Promise<A | B> {
    return this.#answer().then(onfulfilled, onrejected);
  }

  catch<B = never>(
    onrejected?: ((reason: unknown) => B | PromiseLike<B>) | null,
  ): Promise<unknown> {
    return this.#answer().catch(onrejected);
  }

  finally(onfinally?: (() => void) | null): Promise<unknown> {
    return this.#answer().finally(onfinally);
  }

  async withResponse(): Promise<unknown> {
    const { call } = await this.#call();
    const answered = await call.withResponse();
    return { ...answered, data: this.seen(answered.data) };
  }

  async asResponse(): Promise<unknown> {
    const { call } = await this.#call();
    return call.asResponse();
  }

  get [Symbol.toStringTag](): string {
    return "Promise";
  }
}

/** `messages`, `chat.completions` or `responses`, with memory on `create` and `parse`. */
function resource(
  target: Loose,
  provider: Provider,
  auto: AutoMemory,
  client: () => unknown,
): unknown {
  function call(method: "create" | "parse") {
    return (params: Params, ...rest: unknown[]) => {
      const asked = provider.asked(params ?? {});
      let saved = false;
      const remember = (reply: Reply) => {
        if (!saved) {
          saved = true;
          auto.remember(asked, reply);
        }
      };
      const seen = (data: unknown) => {
        if (params?.stream && data && typeof data === "object") {
          return observed(data as object, provider, remember);
        }
        try {
          remember(provider.reply(data));
        } catch {
          // a reply this version cannot read is not saved
        }
        return data;
      };
      return new Deferred(async () => {
        const text = await auto.lookup(asked);
        return { call: target[method](text ? provider.inject(params, text) : params, ...rest) };
      }, seen);
    };
  }
  const wrapped: Record<string | symbol, unknown> = {
    create: call("create"),
    parse: call("parse"),
  };
  const proxy: unknown = new Proxy(target, {
    get(t, prop) {
      if (prop in wrapped) return wrapped[prop];
      // The libraries' stream helpers call `create` on this resource, or on its `_client`: both
      // answer the wrapped ones, so a helper's stream has memory too.
      if (prop === "_client") return client();
      const value = Reflect.get(t, prop, t);
      return typeof value === "function" ? (...args: unknown[]) => value.apply(proxy, args) : value;
    },
  });
  return proxy;
}

/** A client with some of its resources wrapped, and `alexein`, its memory. */
function wrapped<C extends object>(
  target: C,
  resources: Record<string, (value: Loose, self: () => unknown) => unknown>,
  auto: AutoMemory,
  rewrap: (target: Loose) => unknown,
): C {
  const made = new Map<string | symbol, unknown>();
  const self: C = new Proxy(target, {
    get(t, prop) {
      if (prop === "alexein") return auto;
      if (prop === "withOptions") {
        return (...args: unknown[]) => rewrap((t as Loose).withOptions(...args));
      }
      const make = typeof prop === "string" ? resources[prop] : undefined;
      if (make) {
        if (!made.has(prop))
          made.set(
            prop,
            make(Reflect.get(t, prop, t), () => self),
          );
        return made.get(prop);
      }
      const value = Reflect.get(t, prop, t);
      return typeof value === "function" ? value.bind(t) : value;
    },
  });
  return self;
}

/** Options for `wrapAnthropic` and `wrapOpenAI`. */
export type WrapOptions = AutoMemoryOptions;

/**
 * `client` (an `Anthropic`), with memory on `messages.create`, `messages.parse` and
 * `messages.stream`.
 *
 * Before a call, one search with the user's latest message, waited for at most `budget`
 * milliseconds; what it finds that bears on the message, up to about `maxTokens` tokens, is added
 * to `system` as quoted data. After a call, the user's message and the final reply are saved in
 * the background (a reply that asks to run a tool is not; the turn's last one is). A stream is
 * saved when it ends. Memory that is down, slow or refusing never throws and never stops the
 * call.
 *
 * `memory` is your `Memory`; without one, a client for the process is made from
 * ALEXEIN_API_KEY. The returned client is `client` in every other way.
 */
export function wrapAnthropic<C extends object>(
  client: C,
  memory: Memory | undefined,
  options: WrapOptions,
): C;
export function wrapAnthropic<C extends object>(client: C, options: WrapOptions): C;
export function wrapAnthropic<C extends object>(
  client: C,
  memory: Memory | WrapOptions | undefined,
  options?: WrapOptions,
): C {
  const auto = autoMemory(memory, options);
  const rewrap = (target: Loose): Loose =>
    wrapped(
      target,
      { messages: (value, self) => resource(value, anthropicMessages, auto, self) },
      auto,
      rewrap,
    );
  return rewrap(client);
}

/**
 * `client` (an `OpenAI` or `AzureOpenAI`), with memory on `chat.completions` (`create`, `parse`,
 * `stream`) and `responses` (`create`, `parse`, `stream`). Memory goes in a system message after
 * yours, or after `instructions`. Every option is `wrapAnthropic`'s.
 */
export function wrapOpenAI<C extends object>(
  client: C,
  memory: Memory | undefined,
  options: WrapOptions,
): C;
export function wrapOpenAI<C extends object>(client: C, options: WrapOptions): C;
export function wrapOpenAI<C extends object>(
  client: C,
  memory: Memory | WrapOptions | undefined,
  options?: WrapOptions,
): C {
  const auto = autoMemory(memory, options);
  const rewrap = (target: Loose): Loose =>
    wrapped(
      target,
      {
        chat: (value, self) => {
          let completions: unknown;
          return new Proxy(value, {
            get(t, prop) {
              if (prop === "completions") {
                completions ??= resource(Reflect.get(t, prop, t), chatCompletions, auto, self);
                return completions;
              }
              const inner = Reflect.get(t, prop, t);
              return typeof inner === "function" ? inner.bind(t) : inner;
            },
          });
        },
        responses: (value, self) => resource(value, responsesApi, auto, self),
      },
      auto,
      rewrap,
    );
  return rewrap(client);
}

function autoMemory(memory: Memory | WrapOptions | undefined, options?: WrapOptions): AutoMemory {
  if (options) return new AutoMemory(memory as Memory | undefined, options);
  if (memory && "userId" in memory) return new AutoMemory(undefined, memory as WrapOptions);
  throw new TypeError("Alexein needs to know whose memory this is: pass { userId }");
}

/**
 * The memory of a client `wrapAnthropic` or `wrapOpenAI` answered: `last` says how its last
 * lookup went; `await flush()` waits for its saves.
 */
export function memoryOf(client: unknown): AutoMemory {
  const auto = (client as { alexein?: unknown } | null)?.alexein;
  if (!(auto instanceof AutoMemory))
    throw new TypeError("not a client wrapAnthropic or wrapOpenAI answered");
  return auto;
}
