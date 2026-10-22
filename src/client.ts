/**
 * The client, `Memory`, and the end user views it hands out.
 *
 * A client holds a key and the settings it sends with; `memory.user("dana")` is a view that sends
 * `X-Twin-Account: dana` on every call. What each call sends is in `calls.ts`, once; here is only
 * how it is sent: the key, the retries, the timeout, and the error a failed response becomes.
 */

import * as calls from "./calls.js";
import { APIConnectionError, APITimeoutError, TwinMemoryError, forStatus } from "./errors.js";
import {
  type AddResult,
  type Correction,
  type File,
  type GrepResult,
  type History,
  type Item,
  type Lineage,
  type Listing,
  type Me,
  type Overview,
  type Passages,
  type Receipt,
  type Versions,
  SearchResult,
} from "./types.js";
import { VERSION } from "./version.js";

export const DEFAULT_BASE_URL = "https://api.twinmemory.dev";
/**
 * Long enough for a search that waits on the model filter at its slowest and an add that waits for
 * its items to land; a person-facing caller that cannot wait sets its own.
 */
export const DEFAULT_TIMEOUT_MS = 60_000;
export const DEFAULT_RETRIES = 2;
/** What the API asks to be retried: too many requests in hand, or memory being rebuilt. */
const RETRIED = new Set([429, 503]);
/** A Retry-After past this is not waited out; the error is thrown instead. */
const LONGEST_WAIT_MS = 60_000;
/**
 * What `integration` may add to the User-Agent: one short token, so the request log can count
 * requests by where they came from (`twinmemory-js/0.1.0 langgraph`).
 */
const INTEGRATION = /^[a-z0-9][a-z0-9._-]{0,31}$/;

export interface MemoryOptions {
  /** Defaults to `TWIN_MEMORY_API_KEY` from the environment. */
  apiKey?: string;
  /** Defaults to `TWIN_MEMORY_BASE_URL`, else the hosted service. */
  baseUrl?: string;
  /** Milliseconds one attempt may take. */
  timeout?: number;
  /** How many times a 429, a 503 or an unreached service is tried again. */
  maxRetries?: number;
  /**
   * Ride out an outage - memory unreachable, timing out, or answering 429 or 5xx after its
   * retries: `search` answers empty and `add` saves nothing, each with `failed: true` and a
   * warning logged, instead of throwing. A wrong key or request still throws.
   */
  failOpen?: boolean;
  /** A word added to the User-Agent, counted in the request log: `"langgraph"`. */
  integration?: string;
  /** Where warnings go when failing open; `console.warn` by default. */
  logger?: (message: string) => void;
  /** The `fetch` to send with; the global one by default. */
  fetch?: typeof fetch;
}

type Send = <T>(call: calls.Call<T>, user: string | undefined) => Promise<T>;

function environment(name: string): string | undefined {
  const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process
    ?.env;
  return env?.[name] || undefined;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * A twin memory client.
 *
 * ```ts
 * const memory = new Memory();          // TWIN_MEMORY_API_KEY from the environment
 * const dana = memory.user("dana");     // your own id for one of your end users
 * await dana.add("I moved to Lisbon for the job at Acme.");
 * console.log((await dana.search("Where does Dana live?")).context());
 * ```
 */
export class Memory {
  readonly baseUrl: string;
  readonly maxRetries: number;
  readonly failOpen: boolean;
  readonly #headers: Record<string, string>;
  readonly #timeout: number;
  readonly #fetch: typeof fetch;
  readonly #log: (message: string) => void;

  constructor(options: MemoryOptions = {}) {
    const key = options.apiKey ?? environment("TWIN_MEMORY_API_KEY") ?? "";
    if (!key) {
      throw new TwinMemoryError(
        "no API key: pass apiKey, or set TWIN_MEMORY_API_KEY. Keys are made in the console, " +
          "under API keys.",
      );
    }
    let agent = `twinmemory-js/${VERSION}`;
    if (options.integration !== undefined) {
      if (!INTEGRATION.test(options.integration)) {
        throw new TypeError(
          `integration must be one short lowercase word: ${JSON.stringify(options.integration)}`,
        );
      }
      agent += ` ${options.integration}`;
    }
    const url = options.baseUrl ?? environment("TWIN_MEMORY_BASE_URL") ?? DEFAULT_BASE_URL;
    this.baseUrl = url.replace(/\/+$/, "");
    this.maxRetries = options.maxRetries ?? DEFAULT_RETRIES;
    this.failOpen = options.failOpen ?? false;
    this.#headers = { Authorization: `Bearer ${key}`, "User-Agent": agent };
    this.#timeout = options.timeout ?? DEFAULT_TIMEOUT_MS;
    this.#fetch = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.#log = options.logger ?? ((message) => console.warn(message));
  }

  /** What this key is: its organisation, project, and whether it writes. */
  me(): Promise<Me> {
    return this.#send(calls.me(), undefined);
  }

  /** The memory of one of your end users, by your own id for them. */
  user(userId: string): User {
    const send: Send = (call, user) => this.#send(call, user);
    return new User(send, calls.checkedUser(userId), this.failOpen, this.#log);
  }

  readonly #send: Send = async (call, user) => {
    for (let attempt = 0; ; attempt++) {
      let response: Response | undefined;
      let failure: TwinMemoryError | undefined;
      try {
        response = await this.#attempt(call, user);
      } catch (error) {
        failure = unreached(error);
      }
      const pause = attempt < this.maxRetries ? pauseFor(attempt, response) : undefined;
      if (pause === undefined) {
        if (failure) throw failure;
        return answer(response!, call);
      }
      await sleep(pause);
    }
  };

  async #attempt<T>(call: calls.Call<T>, user: string | undefined): Promise<Response> {
    const headers: Record<string, string> = { ...this.#headers, ...call.headers };
    if (user !== undefined) headers["X-Twin-Account"] = user;
    if (call.body !== undefined) headers["Content-Type"] = "application/json";
    return this.#fetch(this.baseUrl + call.path, {
      method: call.method,
      headers,
      body: call.body === undefined ? undefined : JSON.stringify(call.body),
      signal: AbortSignal.timeout(this.#timeout),
    });
  }
}

/** The answer a response is, or the error it is. */
async function answer<T>(response: Response, call: calls.Call<T>): Promise<T> {
  const raw = await response.text();
  let body: unknown;
  try {
    body = raw ? JSON.parse(raw) : {};
  } catch {
    body = { detail: raw || undefined };
  }
  if (response.ok) return call.parse((body ?? {}) as Record<string, unknown>);
  const detail =
    typeof body === "object" && body !== null && !Array.isArray(body)
      ? (body as Record<string, unknown>).detail
      : body;
  throw forStatus(response.status, detail, response.headers.get("X-Request-Id") ?? undefined);
}

/** Milliseconds to wait before trying again, or undefined if this should not be retried. */
function pauseFor(attempt: number, response: Response | undefined): number | undefined {
  if (response !== undefined) {
    if (!RETRIED.has(response.status)) return undefined;
    const after = response.headers.get("Retry-After") ?? "";
    if (/^\d+(\.\d+)?$/.test(after)) {
      const ms = Number(after) * 1000;
      return ms <= LONGEST_WAIT_MS ? ms : undefined;
    }
  }
  // 0.5 s, then 1 s, each with up to a quarter either way, so clients that failed together do
  // not come back together.
  return 500 * 2 ** attempt * (0.75 + Math.random() * 0.5);
}

function unreached(error: unknown): TwinMemoryError {
  const name = error instanceof Error ? error.name : "";
  if (name === "TimeoutError" || name === "AbortError") {
    return new APITimeoutError(`the service did not answer in time: ${String(error)}`, {
      cause: error,
    });
  }
  return new APIConnectionError(`the service could not be reached: ${String(error)}`, {
    cause: error,
  });
}

/** Options `add` takes besides the items. */
export interface AddOptions extends calls.ItemDefaults {
  /** Return once the items are searchable. */
  wait?: boolean;
}

/** One end user's memory. Every call sends their id as `X-Twin-Account`. */
export class User {
  constructor(
    private readonly send: Send,
    readonly id: string,
    private readonly failOpen: boolean,
    private readonly log: (message: string) => void,
  ) {}

  /**
   * Remember text: a string, an item, or a list of either. The option fields apply to every item
   * that does not set its own. With `wait`, returns once they are searchable.
   */
  async add(
    items: string | Item | (string | Item)[],
    options: AddOptions = {},
  ): Promise<AddResult> {
    const { wait = false, ...defaults } = options;
    const sent = calls.add(items, wait, defaults);
    try {
      const results: AddResult[] = [];
      for (const call of sent) results.push(await this.send(call, this.id));
      return calls.merged(results);
    } catch (error) {
      this.#rideOut(error, "add");
      return { items: [], queued: 0, pending: 0, failed: true, raw: {} };
    }
  }

  /** What memory holds for a question. */
  async search(query: string, options: calls.SearchOptions = {}): Promise<SearchResult> {
    try {
      return await this.send(calls.search(query, options), this.id);
    } catch (error) {
      this.#rideOut(error, "search");
      return SearchResult.unavailable(query);
    }
  }

  /** Every passage holding an exact phrase, ignoring case. */
  grep(pattern: string, options: { scope?: string; limit?: number } = {}): Promise<GrepResult> {
    return this.send(calls.grep(pattern, options.scope, options.limit ?? 50), this.id);
  }

  /** One file whole, by a path a result gave you. */
  read(path: string): Promise<File> {
    return this.send(calls.read(path), this.id);
  }

  /** A directory's entries. */
  ls(path = ""): Promise<Listing> {
    return this.send(calls.ls(path), this.id);
  }

  /** The passages either side of one you hold, in the same thread. */
  around(passageId: string, options: { width?: number } = {}): Promise<Passages> {
    return this.send(calls.around(passageId, options.width ?? 2), this.id);
  }

  /** Every dated value recorded for one subject. */
  history(subject: string, options: { attribute?: string } = {}): Promise<History> {
    return this.send(calls.history(subject, options.attribute), this.id);
  }

  /** The most recent passages, newest first; with `after` and `before`, all between. */
  latest(options: calls.LatestOptions = {}): Promise<Passages> {
    return this.send(calls.latest(options), this.id);
  }

  /** The shape of this memory: directories, counts and its written index. */
  overview(): Promise<Overview> {
    return this.send(calls.overview(), this.id);
  }

  /** Erase every copy of what is named, for good; a receipt of what went. */
  forget(named: calls.ForgetOptions): Promise<Receipt> {
    return this.send(calls.forget(named), this.id);
  }

  /** Retract one fact, optionally saying what is true instead. */
  correct(recordId: string, replacement?: string): Promise<Correction> {
    return this.send(calls.correct(recordId, replacement), this.id);
  }

  /** An item's versions, as they were sent. */
  versions(itemId: string): Promise<Versions> {
    return this.send(calls.versions(itemId), this.id);
  }

  /** How far each item has got: accepted, landed, read, ... */
  status(ids: string[]): Promise<Record<string, string>> {
    return this.send(calls.status(ids), this.id);
  }

  /** What an item became, or what a fact was read from. */
  lineage(id: string): Promise<Lineage> {
    return this.send(calls.lineage(id), this.id);
  }

  /**
   * Throw `error` unless this fails open and it is an outage; then log it, and the caller answers
   * empty. Memory being down costs a reply its memory, not the reply.
   */
  #rideOut(error: unknown, what: string): void {
    if (!(this.failOpen && error instanceof TwinMemoryError && error.outage)) throw error;
    this.log(`twin memory unavailable, ${what} for ${this.id} skipped: ${error.message}`);
  }
}

export { VERSION };
