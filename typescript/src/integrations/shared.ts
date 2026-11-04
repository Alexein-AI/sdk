/**
 * What the framework integrations share: a client made on first use, the tools' answers in words
 * a model reads, and the ids that make saving a turn twice an edit rather than a copy. Built on
 * the client alone; never HTTP.
 */

import { Memory } from "../client.js";
import { AlexeinError, NotFoundError } from "../errors.js";
import type { Excerpt, Fact } from "../memories.js";
import type { Opened } from "../reads.js";
import type { SearchResult } from "../search.js";
import type { User } from "../user.js";

/** What the model is told when memory is down, unless the integration is strict. */
export const UNAVAILABLE = "Memory is unavailable right now; carry on without it.";
export const NOTHING_FOUND = "Nothing remembered about that.";
export const NOTHING_YET = "Nothing has been remembered for this user yet.";
export const SAVED = "Saved.";

/** What goes before what memory found, in a system prompt. */
export const HEADING =
  "What you remember about this user from earlier conversations. Use it where it helps; the " +
  "conversation itself takes precedence where they differ.";

/** The longest question the API takes; a longer one (a pasted email) is searched by its end. */
export const MAX_QUERY = 2000;
/** Milliseconds each attempt may take when an integration makes its own client. */
export const TIMEOUT = 10_000;

/** What an integration's entry point takes besides its client. */
export interface IntegrationOptions {
  /** Skip search's relevance check: free and quicker, a little less precise. */
  fast?: boolean;
  /** How much of what memory holds goes into a prompt or a tool's answer, in characters. */
  maxChars?: number;
  /** Throw on an outage instead of carrying on without memory. */
  strict?: boolean;
}

/** The client given, or one made on first use - so importing needs no key. */
export class LazyClient {
  #client: Memory | undefined;

  constructor(
    given: Memory | undefined,
    private readonly integration: string,
    private readonly strict: boolean,
  ) {
    this.#client = given;
  }

  get client(): Memory {
    this.#client ??= new Memory({
      failOpen: !this.strict,
      integration: this.integration,
      timeout: TIMEOUT,
    });
    return this.#client;
  }
}

/** A client, or options: the first argument an integration's entry point takes. */
export function isClient(given: unknown): given is Memory {
  return typeof (given as { user?: unknown } | undefined)?.user === "function";
}

/** What memory holds for `query`; undefined for an app user with nothing saved yet. */
export async function searchFor(
  user: User,
  query: string,
  fast: boolean,
): Promise<SearchResult | undefined> {
  try {
    return await user.search(query.slice(-MAX_QUERY), { fast });
  } catch (error) {
    if (error instanceof NotFoundError) return undefined;
    throw error;
  }
}

/** `memory_search`'s answer: the context, then the refs to open. */
export function searchAnswer(found: SearchResult | undefined, maxChars: number): string {
  if (found?.failed) return UNAVAILABLE;
  const said = found?.context(maxChars) ?? "";
  if (!found || !said) return NOTHING_FOUND;
  const refs = [...new Set(found.refs)];
  if (!refs.length) return said;
  return `${said}\n\nTo read one whole, memory_open:\n${refs.map((r) => `- ${r}`).join("\n")}`;
}

function described(memory: Fact | Excerpt): string {
  return memory.type === "excerpt" && memory.date
    ? `${memory.date.slice(0, 10)}: ${memory.text}`
    : memory.text;
}

/** `memory_open`'s answer: the memory whole, and for a fact the excerpts it came from. */
export function openAnswer(opened: Opened): string {
  if (!opened.sources.length) return described(opened.memory);
  const from = opened.sources.map((s) => `- ${described(s)}`).join("\n");
  return `${described(opened.memory)}\n\nLearned from:\n${from}`;
}

/** `memory_open`'s answer to a 404: no memory for this app user, or none by this ref. */
export function notFoundAnswer(error: NotFoundError): string {
  return /\bref\b/.test(error.detail) ? "Memory holds nothing by that ref." : NOTHING_YET;
}

/**
 * A tool's answer to `error`: an outage is told to the model (and logged) unless `strict`;
 * anything else is thrown, for the framework to handle as it handles a tool's errors.
 */
export function outageAnswer(error: unknown, strict: boolean): string {
  if (strict || !(error instanceof AlexeinError) || !error.outage) throw error;
  console.warn(`Alexein is unavailable: ${error.message}`);
  return UNAVAILABLE;
}

/** What `recall` found as a block for a system prompt; empty when it found nothing. */
export function promptBlock(found: string): string {
  return found ? `${HEADING}\n\n${found}` : "";
}

/** A stable id for a saved message: the first 24 hex digits of the SHA-256 of `parts`. */
export async function stableId(...parts: (string | undefined)[]): Promise<string> {
  const bytes = new TextEncoder().encode(parts.map((p) => p ?? "").join("|"));
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, (b) => b.toString(16).padStart(2, "0"))
    .join("")
    .slice(0, 24);
}
