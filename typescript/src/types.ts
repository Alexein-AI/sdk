/**
 * What the API answers, as typed values. Typed fields are camelCase; JSON passed through as it
 * came (`assertions`, `history`, `records`, `manifest`) keeps the API's names. Every result except
 * `status()`, which is a plain map of phases, keeps the whole answer in `raw`, so a field this
 * version does not know yet is still reachable.
 */

export type Json = Record<string, unknown>;

export interface Author {
  id?: string;
  name?: string;
  email?: string;
  handle?: string;
  self?: boolean;
}

/**
 * One thing to remember. Only `text` is required. The same `id` again is an edit of it; set
 * `expires` (an ISO date) for what stops being true.
 */
export interface Item {
  text: string;
  kind?: "message" | "document" | "note";
  id?: string;
  at?: string;
  author?: string | Author;
  role?: string;
  session?: string;
  title?: string;
  about?: string[];
  expires?: string;
  metadata?: Json;
}

const text = (value: unknown): string => (typeof value === "string" ? value : "");
const maybe = (value: unknown): string | undefined =>
  typeof value === "string" ? value : undefined;
const list = <T = unknown>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);
const strings = (value: unknown): string[] => list(value).map(String);
const count = (value: unknown): number => (typeof value === "number" ? value : Number(value) || 0);
const object = (value: unknown): Json =>
  typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Json) : {};

/** What a key is: `kind` is "key" for an API key. */
export interface Me {
  kind: string;
  writes: boolean;
  org?: string;
  project?: string;
  keyId?: string;
  raw: Json;
}

export function parseMe(raw: Json): Me {
  return {
    kind: text(raw.kind),
    writes: Boolean(raw.writes),
    org: maybe(raw.org),
    project: maybe(raw.project),
    keyId: maybe(raw.key_id),
    raw,
  };
}

export interface AddedItem {
  id: string;
  eventId: string;
  /** Whether it has landed, stored and searchable; undefined when the answer does not say. */
  landed?: boolean;
  threadId?: string;
  path?: string;
}

/**
 * `pending` is how many items are accepted and not yet searchable; zero once they are. `failed`
 * is true when a `failOpen` client could not reach memory and saved nothing.
 */
export interface AddResult {
  items: AddedItem[];
  queued: number;
  pending: number;
  failed: boolean;
  raw: Json;
}

export function parseAddResult(raw: Json): AddResult {
  return {
    items: list<Json>(raw.items).map((item) => ({
      id: text(item.id),
      eventId: text(item.event_id),
      landed: typeof item.landed === "boolean" ? item.landed : undefined,
      threadId: maybe(item.thread_id),
      path: maybe(item.path),
    })),
    queued: count(raw.queued),
    pending: count(raw.pending),
    failed: false,
    raw,
  };
}

/** A passage: what was said or written, with its address. */
export interface Hit {
  path: string;
  id: string;
  text: string;
  thread?: string;
}

function parseHit(raw: unknown): Hit {
  const hit = object(raw);
  return {
    path: text(hit.path),
    id: text(hit.id),
    text: text(hit.text),
    thread: maybe(hit.thread),
  };
}

/** One dated fact; `source` is the passage it came from. */
export interface Fact {
  text: string;
  id: string;
  path: string;
  thread?: string;
  source?: string;
}

/**
 * What memory holds for a question: `known` lines first, then dated `facts`, then whole passages
 * (`hits`). `held` is false when memory's own check finds it does not hold the answer; `filtered`
 * is whether search's relevance check ran. `failed` is true when a `failOpen` client could not
 * reach memory, and the result is empty for that reason.
 */
export class SearchResult {
  constructor(
    readonly query: string,
    readonly found: number,
    readonly hits: Hit[],
    readonly facts: Fact[],
    readonly known: string[],
    readonly workedOut: string[],
    readonly notes: string[],
    readonly held: boolean | undefined,
    readonly filtered: boolean,
    readonly raw: Json = {},
    readonly failed = false,
  ) {}

  static parse(raw: Json): SearchResult {
    const facts = list(raw.facts).map((value) => {
      const fact = object(value);
      return {
        text: text(fact.text),
        id: text(fact.id),
        path: text(fact.path),
        thread: maybe(fact.thread),
        source: maybe(fact.source),
      };
    });
    return new SearchResult(
      text(raw.query),
      count(raw.found),
      list(raw.hits).map(parseHit),
      facts,
      strings(raw.known),
      strings(raw.worked_out),
      strings(raw.notes),
      typeof raw.held === "boolean" ? raw.held : undefined,
      Boolean(raw.filtered),
      raw,
    );
  }

  /** What a `failOpen` client answers when memory could not be reached. */
  static unavailable(query: string): SearchResult {
    return new SearchResult(query, 0, [], [], [], [], [], undefined, false, {}, true);
  }

  /**
   * A block to paste into a prompt: known lines, worked-out lines, dated facts, then passages,
   * whole entries only, at most `maxChars` long. Empty when memory found nothing.
   */
  context(maxChars = 4000): string {
    const sections: [string, string[]][] = [
      ["What is known", this.known],
      ["Worked out", this.workedOut],
      ["Facts", this.facts.map((f) => f.text)],
      ["Passages", this.hits.map((h) => h.text)],
    ];
    let out: string[] = [];
    for (const [title, lines] of sections) {
      let heading = out.length ? ["", `${title}:`] : [`${title}:`];
      for (const line of lines) {
        const grown = [...out, ...heading, "- " + line.split(/\s+/).filter(Boolean).join(" ")];
        if (grown.join("\n").length > maxChars) return out.join("\n");
        out = grown;
        heading = [];
      }
    }
    return out.join("\n");
  }
}

export interface GrepResult {
  pattern: string;
  total: number;
  matches: Hit[];
  raw: Json;
}

export const parseGrep = (raw: Json): GrepResult => ({
  pattern: text(raw.pattern),
  total: count(raw.total),
  matches: list(raw.matches).map(parseHit),
  raw,
});

/** `latest` and `around`: passages in order, newest first for `latest`. */
export interface Passages {
  passages: Hit[];
  raw: Json;
}

export const parsePassages = (raw: Json): Passages => ({
  passages: list(raw.passages).map(parseHit),
  raw,
});

/**
 * One passage, by path. When there is none, `error` says so and `siblings` lists what is next
 * to it.
 */
export interface File {
  path: string;
  text?: string;
  error?: string;
  siblings: string[];
  raw: Json;
}

export const parseFile = (raw: Json): File => ({
  path: text(raw.path),
  text: maybe(raw.text),
  error: maybe(raw.error),
  siblings: strings(raw.siblings),
  raw,
});

export interface Listing {
  path: string;
  entries: string[];
  raw: Json;
}

export const parseListing = (raw: Json): Listing => ({
  path: text(raw.path),
  entries: strings(raw.entries),
  raw,
});

/**
 * Every dated value recorded for one subject. When nothing is, `error` says so and `subjects`
 * offers the nearest names.
 */
export interface History {
  subject: string;
  assertions: Json[];
  error?: string;
  subjects: string[];
  raw: Json;
}

export const parseHistory = (raw: Json): History => ({
  subject: text(raw.subject),
  assertions: list<Json>(raw.assertions),
  error: maybe(raw.error),
  subjects: strings(raw.subjects),
  raw,
});

/**
 * An added item's versions, as they were sent. `state` is "live", "forgotten", "expired", or
 * "unknown" for an id memory never took; once an item goes, its history is one line saying when
 * and why.
 */
export interface Versions {
  id: string;
  state: string;
  history: Json[];
  raw: Json;
}

export const parseVersions = (raw: Json): Versions => ({
  id: text(raw.id),
  state: text(raw.state),
  history: list<Json>(raw.history),
  raw,
});

export interface TableChange {
  before: number;
  after: number;
}

/**
 * What a forget erased: `events` is how many stored items went, `0` when nothing matched. `raw` is
 * the whole receipt: `threads_emptied`, `records`, `assertions`, `versions`, `inbox`, `queue` and
 * further counts for your records. Keep it whole with your record of the request. `tables` holds
 * further before-and-after counts when the API sends them; don't depend on its keys.
 */
export interface Receipt {
  events: number;
  tables: Record<string, TableChange>;
  raw: Json;
}

export function parseReceipt(raw: Json): Receipt {
  const tables: Record<string, TableChange> = {};
  for (const [name, change] of Object.entries(object(raw.tables))) {
    const t = object(change);
    tables[name] = { before: count(t.before), after: count(t.after) };
  }
  return { events: count(raw.events), tables, raw };
}

/** The fact retracted, its text, and the id of the note holding what is true instead. */
export interface Correction {
  retracted: string;
  text?: string;
  replacement?: string;
  raw: Json;
}

export const parseCorrection = (raw: Json): Correction => ({
  retracted: text(raw.retracted),
  text: maybe(raw.text),
  replacement: maybe(raw.replacement),
  raw,
});

/**
 * What an item or event became: the event ids it names (`events`), its `passages`, and the facts
 * taken from it (`records`). For a fact id, use `passages`, the passages it came from; the fact
 * is in `raw.record`, and the events it came from, each with its `id`, in `raw.events`. An id
 * memory does not know comes back with empty `events`, `passages` and `records` and the reason in
 * `raw.error`, not as a `NotFoundError`.
 */
export interface Lineage {
  of: string;
  events: string[];
  passages: Json[];
  records: Json[];
  raw: Json;
}

export const parseLineage = (raw: Json): Lineage => ({
  of: text(raw.of),
  events: strings(raw.events),
  passages: list<Json>(raw.passages),
  records: list<Json>(raw.records),
  raw,
});

/**
 * What this end user's memory holds: its top directories, its counts (`manifest`), and `index`,
 * a short written guide for a model to read first.
 */
export interface Overview {
  directories: string[];
  manifest: Json;
  index: string;
  raw: Json;
}

export const parseOverview = (raw: Json): Overview => ({
  directories: strings(raw.directories),
  manifest: object(raw.manifest),
  index: text(raw.index),
  raw,
});
