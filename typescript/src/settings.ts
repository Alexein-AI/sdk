/** The client's settings: from its options, else the environment, else the defaults. */

import { AlexeinError } from "./errors.js";
import { VERSION } from "./version.js";

export const DEFAULT_BASE_URL = "https://api.alexein.ai";
/** Long enough for the slowest search and an add that waits; a caller that cannot wait sets less. */
export const DEFAULT_TIMEOUT_MS = 60_000;
export const DEFAULT_RETRIES = 2;
const KEYS_PAGE = "https://app.alexein.ai/console/keys";

/** One short lowercase word, added to the User-Agent: `langgraph`. */
const INTEGRATION = /^[a-z0-9][a-z0-9._-]{0,31}$/;
/** An app user id: as the API takes it, checked before a round trip. */
const USER_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,34}$/;

export interface MemoryOptions {
  /** Defaults to `ALEXEIN_API_KEY` from the environment. */
  apiKey?: string;
  /** The API's host. Defaults to `ALEXEIN_API_URL`, else `https://api.alexein.ai`. */
  baseUrl?: string;
  /** Milliseconds one attempt may take: 60000 by default. */
  timeout?: number;
  /** How many more times a 429, a 503, a timeout or an unreached service is tried: 2. */
  maxRetries?: number;
  /**
   * Ride out an outage - memory unreachable, timing out, or answering 429 or 5xx after its
   * retries: `search` answers empty and `add` saves nothing, each with `failed: true` and a
   * warning logged, instead of throwing. A wrong key or request still throws.
   */
  failOpen?: boolean;
  /** A word added to the User-Agent, so the console's request logs show where calls came from. */
  integration?: string;
  /** Where warnings go: `console.warn` by default. */
  logger?: (message: string) => void;
  /** The `fetch` to send with: the global one by default. */
  fetch?: typeof fetch;
}

export interface Settings {
  key: string;
  baseUrl: string;
  timeout: number;
  maxRetries: number;
  failOpen: boolean;
  integration: string | null;
  userAgent: string;
  log: (message: string) => void;
  fetch: typeof fetch;
}

/** A variable from `process.env`, where there is one: edge runtimes and browsers have none. */
export function environment(name: string): string | undefined {
  const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process
    ?.env;
  return env?.[name] || undefined;
}

/** The host a base URL names: `http://localhost:8210/v2/` is `http://localhost:8210`. */
export function normalizeBaseUrl(url: string): string {
  return url.trim().replace(/\/+$/, "").replace(/\/v2$/, "").replace(/\/+$/, "");
}

/** `id` if it is a usable app user id; a RangeError saying what one is otherwise. */
export function checkedUserId(id: string): string {
  if (typeof id !== "string" || !USER_ID.test(id)) {
    throw new RangeError(
      `not a usable app user id: ${JSON.stringify(id)} (1 to 35 letters, digits, '.', '_' and ` +
        "'-', beginning with a letter or digit)",
    );
  }
  return id;
}

function count(name: string, value: number, least: number): number {
  if (!Number.isFinite(value) || value < least) {
    throw new RangeError(`${name} must be a number of at least ${least}: ${value}`);
  }
  return value;
}

export function settings(options: MemoryOptions): Settings {
  const key = options.apiKey ?? environment("ALEXEIN_API_KEY") ?? "";
  if (!key) {
    throw new AlexeinError(
      "No API key: pass apiKey, or set ALEXEIN_API_KEY. Make one in the console, under API " +
        `keys: ${KEYS_PAGE}`,
    );
  }
  const integration = options.integration ?? null;
  if (integration !== null && !INTEGRATION.test(integration)) {
    throw new RangeError(
      `integration must be one short lowercase word: ${JSON.stringify(integration)}`,
    );
  }
  const given = globalThis.fetch as typeof fetch | undefined;
  const send = options.fetch ?? (given ? given.bind(globalThis) : undefined);
  if (!send) throw new AlexeinError("No fetch in this runtime: pass one as the fetch option.");
  return {
    key,
    baseUrl: normalizeBaseUrl(
      options.baseUrl ?? environment("ALEXEIN_API_URL") ?? DEFAULT_BASE_URL,
    ),
    timeout: count("timeout", options.timeout ?? DEFAULT_TIMEOUT_MS, 1),
    maxRetries: Math.floor(count("maxRetries", options.maxRetries ?? DEFAULT_RETRIES, 0)),
    failOpen: options.failOpen ?? false,
    integration,
    userAgent: `alexein-js/${VERSION}${integration ? ` ${integration}` : ""}`,
    log: options.logger ?? ((message) => console.warn(message)),
    fetch: send,
  };
}
