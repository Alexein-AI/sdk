/** `@alexein/sdk/ai-sdk` inside the real AI SDK, with its mock model standing in for a real one. */

import { generateText, simulateReadableStream, streamText, tool, wrapLanguageModel } from "ai";
import { MockLanguageModelV4 } from "ai/test";
import { describe, expect, it, vi } from "vitest";
import { z } from "zod";

import { alexeinMiddleware } from "../src/ai-sdk/index.js";
import { HEADER } from "../src/wrap/index.js";
import { ADDED, SEARCH } from "./fixtures.js";
import { type Answer, type Recorded, memory, ok } from "./helpers.js";

const USER = "Where do I live now?";
const REPLY = "You live in Lisbon.";
const USAGE = {
  inputTokens: { total: 10, noCache: 10, cacheRead: undefined, cacheWrite: undefined },
  outputTokens: { total: 5, text: 5, reasoning: undefined },
};
const STOP = { unified: "stop", raw: "stop" } as const;

function searched(changes: Record<string, unknown> = {}): Answer {
  return (sent) =>
    sent.url.pathname.endsWith("/search") ? ok({ ...SEARCH, ...changes }) : ok(ADDED, 202);
}

function adds(sent: Recorded): any[] {
  return sent.requests.filter((r) => r.url.pathname.endsWith("/add")).flatMap((r) => r.body.items);
}

function generating(text = REPLY) {
  return new MockLanguageModelV4({
    doGenerate: async () => ({
      content: [{ type: "text", text }],
      finishReason: STOP,
      usage: USAGE,
      warnings: [],
    }),
  });
}

describe("alexeinMiddleware", () => {
  it("puts memory in the system prompt and saves the exchange", async () => {
    const { client, sent } = memory(searched());
    const middleware = alexeinMiddleware(client, { userId: "dana", session: "conv-7" });
    const mock = generating();
    const model = wrapLanguageModel({ model: mock, middleware });

    const { text } = await generateText({ model, system: "Be brief.", prompt: USER });
    await middleware.alexein.flush();

    expect(text).toBe(REPLY);
    const prompt = mock.doGenerateCalls[0]!.prompt;
    expect(prompt[0]!.role).toBe("system");
    expect(prompt[0]!.content).toMatch(new RegExp(`^Be brief\\.\\n\\n${HEADER.slice(0, 40)}`));
    expect(prompt[0]!.content).toContain("</memory>");
    expect(prompt[1]).toMatchObject({ role: "user", content: [{ type: "text", text: USER }] });
    expect(sent.requests[0]!.body).toEqual({ query: USER, fast: true });
    expect(sent.requests[0]!.headers["X-Alexein-User"]).toBe("dana");
    expect(adds(sent).map((i) => [i.role, i.text, i.session])).toEqual([
      ["user", USER, "conv-7"],
      ["assistant", REPLY, "conv-7"],
    ]);
  });

  it("adds a system message when the call has none", async () => {
    const { client } = memory(searched());
    const mock = generating();
    const model = wrapLanguageModel({
      model: mock,
      middleware: alexeinMiddleware(client, { userId: "dana" }),
    });

    await generateText({ model, messages: [{ role: "user", content: USER }] });

    const prompt = mock.doGenerateCalls[0]!.prompt;
    expect(prompt[0]!.role).toBe("system");
    expect(String(prompt[0]!.content).startsWith(HEADER)).toBe(true);
  });

  it("leaves memory out when it does not hold the answer, or is late", async () => {
    const { client } = memory(searched({ answerable: false }));
    const mock = generating();
    const model = wrapLanguageModel({
      model: mock,
      middleware: alexeinMiddleware(client, { userId: "dana" }),
    });
    await generateText({ model, prompt: USER });
    expect(mock.doGenerateCalls[0]!.prompt[0]!.role).toBe("user");

    const slow = memory(() => new Promise<Response>(() => {}));
    const late = alexeinMiddleware(slow.client, { userId: "dana", budget: 20, save: false });
    const other = generating();
    await generateText({
      model: wrapLanguageModel({ model: other, middleware: late }),
      prompt: USER,
    });
    expect(other.doGenerateCalls[0]!.prompt[0]!.role).toBe("user");
    expect(late.alexein.last?.timedOut).toBe(true);
  });

  it("never stops the call when memory fails", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { client } = memory(() => ok({ detail: "bad key" }, 401));
    const mock = generating();
    const middleware = alexeinMiddleware(client, { userId: "dana" });

    const { text } = await generateText({
      model: wrapLanguageModel({ model: mock, middleware }),
      prompt: USER,
    });
    await middleware.alexein.flush();

    expect(text).toBe(REPLY);
    expect(middleware.alexein.last?.failed).toBe(true);
  });

  it("saves a stream once it ends", async () => {
    const { client, sent } = memory(searched());
    const mock = new MockLanguageModelV4({
      doStream: async () => ({
        stream: simulateReadableStream({
          chunks: [
            { type: "text-start", id: "t" },
            { type: "text-delta", id: "t", delta: "You live " },
            { type: "text-delta", id: "t", delta: "in Lisbon." },
            { type: "text-end", id: "t" },
            { type: "finish", finishReason: STOP, usage: USAGE },
          ],
        }),
      }),
    });
    const middleware = alexeinMiddleware(client, { userId: "dana" });

    const result = streamText({
      model: wrapLanguageModel({ model: mock, middleware }),
      prompt: USER,
    });
    expect(await result.text).toBe(REPLY);
    await middleware.alexein.flush();

    expect(String(mock.doStreamCalls[0]!.prompt[0]!.content).startsWith(HEADER)).toBe(true);
    expect(adds(sent).map((i) => i.text)).toEqual([USER, REPLY]);
  });

  it("searches once across a tool loop and saves its last answer", async () => {
    const { client, sent } = memory(searched());
    const steps = [
      {
        content: [{ type: "tool-call", toolCallId: "c1", toolName: "weather", input: "{}" }],
        finishReason: { unified: "tool-calls", raw: "tool_use" },
        usage: USAGE,
        warnings: [],
      },
      {
        content: [{ type: "text", text: "Sunny in Lisbon." }],
        finishReason: STOP,
        usage: USAGE,
        warnings: [],
      },
    ];
    const mock = new MockLanguageModelV4({ doGenerate: steps as any });
    const middleware = alexeinMiddleware(client, { userId: "dana" });

    const { text } = await generateText({
      model: wrapLanguageModel({ model: mock, middleware }),
      prompt: "What's the weather where I live?",
      tools: { weather: tool({ inputSchema: z.object({}), execute: async () => "18C" }) },
      stopWhen: () => false,
      maxRetries: 0,
    } as any);
    await middleware.alexein.flush();

    expect(text).toBe("Sunny in Lisbon.");
    expect(sent.routes.filter((r) => r === "search")).toHaveLength(1);
    expect(middleware.alexein.last?.reused).toBe(true);
    expect(adds(sent).map((i) => i.text)).toEqual([
      "What's the weather where I live?",
      "Sunny in Lisbon.",
    ]);
  });
});
