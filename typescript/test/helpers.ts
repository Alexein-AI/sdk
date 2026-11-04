/** A client whose every request is answered by a function, and the requests it was sent. */

import { vi } from "vitest";
import { Memory, type MemoryOptions } from "../src/index.js";

export interface Sent {
  url: URL;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

export type Answer = (sent: Sent) => Response | Promise<Response>;

export class Recorded {
  readonly requests: Sent[] = [];
  constructor(readonly answer: Answer) {}

  fetch: typeof fetch = async (input, init) => {
    const sent: Sent = {
      url: new URL(String(input)),
      method: init?.method ?? "GET",
      headers: { ...(init?.headers as Record<string, string>) },
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    this.requests.push(sent);
    return this.answer(sent);
  };

  get last(): Sent {
    return this.requests[this.requests.length - 1]!;
  }

  body(at = -1): unknown {
    return this.requests.at(at)!.body;
  }
}

export function ok(body: unknown = {}, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers });
}

export function memory(answer: Answer, options: MemoryOptions = {}) {
  const sent = new Recorded(answer);
  const client = new Memory({ apiKey: "tm_test", fetch: sent.fetch, ...options });
  return { client, sent };
}

/**
 * Retries record their pauses instead of sleeping them: every timer fires at once, and the delay
 * each was set for is kept.
 */
export function noWaiting(): number[] {
  const waited: number[] = [];
  vi.spyOn(globalThis, "setTimeout").mockImplementation(((done: () => void, ms?: number) => {
    waited.push(ms ?? 0);
    queueMicrotask(done);
    return 0 as unknown as ReturnType<typeof setTimeout>;
  }) as typeof setTimeout);
  return waited;
}
