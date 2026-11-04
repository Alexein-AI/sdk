/**
 * Sending one request: its headers, a timeout per attempt, and retries - 429 and 503, a timeout
 * or an unreached service - waiting as `Retry-After` says (at most 60 s) or with backoff.
 */

import { AlexeinError, errorFor, unreached } from "./errors.js";
import { type Json, object } from "./json.js";
import type { Settings } from "./settings.js";

/** One request, described once: what it sends and how to read the answer. */
export interface Call<T> {
  method: "GET" | "POST";
  /** After `/v2`: `/memory/search`, `/me`. */
  path: string;
  body?: Json;
  headers?: Record<string, string>;
  parse: (body: unknown) => T;
}

/** What the API asks to be retried: too busy (429) and briefly unavailable (503). */
const RETRIED = new Set([429, 503]);
/** A Retry-After past this is not waited out; the error is thrown instead. */
const LONGEST_WAIT_MS = 60_000;

/** Browsers refuse a User-Agent set by a page; everywhere else it is the caller's to set. */
const SETS_USER_AGENT = typeof (globalThis as { document?: unknown }).document === "undefined";

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** Milliseconds to wait before trying again, or undefined when this is not retried. */
function pauseFor(attempt: number, response: Response | undefined): number | undefined {
  if (response !== undefined) {
    if (!RETRIED.has(response.status)) return undefined;
    const after = (response.headers.get("Retry-After") ?? "").trim();
    if (/^\d+(\.\d+)?$/.test(after)) {
      const ms = Number(after) * 1000;
      return ms <= LONGEST_WAIT_MS ? ms : undefined;
    }
  }
  // 0.5 s, then 1 s, ..., each a quarter either way, so clients that failed together do not all
  // come back together.
  return 500 * 2 ** attempt * (0.75 + Math.random() * 0.5);
}

async function bodyOf(response: Response): Promise<{ body: unknown; said: string }> {
  const said = await response.text();
  if (!said) return { body: {}, said };
  try {
    return { body: JSON.parse(said), said };
  } catch {
    return { body: undefined, said };
  }
}

export class Transport {
  constructor(private readonly settings: Settings) {}

  /** Send `call` for app user `user` (none for `me` and `users`), retrying as the API asks. */
  async send<T>(call: Call<T>, user?: string): Promise<T> {
    for (let attempt = 0; ; attempt++) {
      let response: Response | undefined;
      let failure: AlexeinError | undefined;
      try {
        response = await this.attempt(call, user);
      } catch (error) {
        failure = unreached(error);
      }
      if (response?.ok) return this.answer(response, call);
      const pause = attempt < this.settings.maxRetries ? pauseFor(attempt, response) : undefined;
      if (pause === undefined) throw failure ?? (await this.refusal(response!));
      await response?.body?.cancel().catch(() => {});
      await sleep(pause);
    }
  }

  private attempt<T>(call: Call<T>, user: string | undefined): Promise<Response> {
    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.settings.key}`,
      ...call.headers,
    };
    if (SETS_USER_AGENT) headers["User-Agent"] = this.settings.userAgent;
    if (user !== undefined) headers["X-Alexein-User"] = user;
    if (call.method === "POST") headers["Content-Type"] = "application/json";
    return this.settings.fetch(`${this.settings.baseUrl}/v2${call.path}`, {
      method: call.method,
      headers,
      body: call.method === "POST" ? JSON.stringify(call.body ?? {}) : undefined,
      signal: AbortSignal.timeout(this.settings.timeout),
    });
  }

  private async answer<T>(response: Response, call: Call<T>): Promise<T> {
    const { body, said } = await bodyOf(response);
    if (body === undefined) {
      throw new AlexeinError(`${response.status}: the answer is not JSON: ${said.slice(0, 200)}`, {
        status: response.status,
        requestId: response.headers.get("X-Request-Id"),
      });
    }
    return call.parse(body);
  }

  private async refusal(response: Response): Promise<AlexeinError> {
    const { body, said } = await bodyOf(response);
    const json = body === undefined ? { detail: said.trim() } : object(body);
    return errorFor(response.status, json, response.headers.get("X-Request-Id"));
  }
}
