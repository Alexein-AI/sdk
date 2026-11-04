/** A client whose every request is answered by a function, and the requests it was sent. */

import { vi } from "vitest";
import { Memory, type MemoryOptions } from "../src/index.js";

export interface Sent {
  url: URL;
  method: string;
  headers: Record<string, string>;
  body: any;
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

  /** The route of each request: `search`, `users/delete`, `me`. */
  get routes(): string[] {
    return this.requests.map((r) => r.url.pathname.replace(/^\/v2\/(memory\/)?/, ""));
  }
}

export function ok(body: unknown = {}, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers });
}

export function memory(answer: Answer = () => ok(), options: MemoryOptions = {}) {
  const sent = new Recorded(answer);
  const client = new Memory({ apiKey: "ak_test", fetch: sent.fetch, ...options });
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

/** What a promise rejects with. */
export async function rejection(promise: Promise<unknown>): Promise<any> {
  try {
    await promise;
  } catch (error) {
    return error;
  }
  throw new Error("expected a rejection");
}
