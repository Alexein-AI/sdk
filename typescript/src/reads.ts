/** What the reads other than search answer: grep, latest, around, open, history, summary and more. */

import {
  type Json,
  count,
  maybe,
  maybeCount,
  maybeStrings,
  object,
  objects,
  strings,
  text,
} from "./json.js";
import {
  type Excerpt,
  type Fact,
  type MemoryEntry,
  parseExcerpt,
  parseFact,
  parseMemories,
} from "./memories.js";

/**
 * Memories in order, from grep (with `pattern` and `total`), latest (with `places` when a place
 * matched nothing: the places there are) or around. Iterable.
 */
export interface Memories extends Iterable<MemoryEntry> {
  readonly memories: MemoryEntry[];
  readonly pattern: string | null;
  readonly total: number | null;
  readonly places: string[] | null;
  readonly raw: Json;
}

export function parseMemoriesResult(value: unknown): Memories {
  const raw = object(value);
  const memories = parseMemories(raw.memories);
  return {
    memories,
    pattern: maybe(raw.pattern),
    total: maybeCount(raw.total),
    places: maybeStrings(raw.places),
    raw,
    [Symbol.iterator]: () => memories[Symbol.iterator](),
  };
}

/** One memory whole: an excerpt, or a fact with the excerpts it was learned from. */
export interface Opened {
  readonly memory: Fact | Excerpt;
  readonly sources: Excerpt[];
  readonly raw: Json;
}

export function parseOpened(value: unknown): Opened {
  const raw = object(value);
  const memory = object(raw.memory);
  return {
    memory: memory.type === "fact" ? parseFact(memory) : parseExcerpt(memory),
    sources: objects(raw.sources).map(parseExcerpt),
    raw,
  };
}

/** One value a subject was stated to have, and since when. */
export interface Value {
  readonly attribute: string;
  readonly value: string;
  readonly since: string | null;
  /** True when it was stated not to hold. */
  readonly negated: boolean;
  readonly raw: Json;
}

/**
 * Every value a subject was stated to have, by attribute, oldest first. `suggestions` names
 * subjects close to one memory does not know, and is null otherwise.
 */
export interface History {
  readonly subject: string;
  readonly values: Value[];
  readonly suggestions: string[] | null;
  readonly raw: Json;
}

export function parseHistory(value: unknown): History {
  const raw = object(value);
  return {
    subject: text(raw.subject),
    values: objects(raw.values).map((v) => ({
      attribute: text(v.attribute),
      value: text(v.value),
      since: maybe(v.since),
      negated: v.negated === true,
      raw: v,
    })),
    suggestions: maybeStrings(raw.suggestions),
    raw,
  };
}

/** What one connected app delivered through one connection. */
export interface Source {
  readonly provider: string;
  readonly source: string;
  readonly connection: string;
  /** How many items it delivered. */
  readonly items: number;
  /** How many of them ended. */
  readonly ended: number;
  /** When the newest happened. */
  readonly newest: string | null;
  readonly raw: Json;
}

function parseSource(raw: Json): Source {
  return {
    provider: text(raw.provider),
    source: text(raw.source),
    connection: text(raw.connection),
    items: count(raw.items),
    ended: count(raw.ended),
    newest: maybe(raw.newest),
    raw,
  };
}

/** What each connected app delivered to this memory. */
export interface Sources {
  readonly sources: Source[];
  readonly raw: Json;
}

export function parseSources(value: unknown): Sources {
  const raw = object(value);
  return { sources: objects(raw.sources).map(parseSource), raw };
}

/**
 * This memory in brief: how many items, the span they cover, the connected sources, and the known
 * lines - what memory takes to be true now.
 */
export interface Summary {
  readonly items: number;
  readonly first: string | null;
  readonly last: string | null;
  readonly sources: Source[];
  readonly known: string[];
  readonly raw: Json;
}

export function parseSummary(value: unknown): Summary {
  const raw = object(value);
  return {
    items: count(raw.items),
    first: maybe(raw.first),
    last: maybe(raw.last),
    sources: objects(raw.sources).map(parseSource),
    known: strings(raw.known),
    raw,
  };
}

/** An issue or pull request still open. */
export interface OpenItem {
  readonly ref: string;
  readonly text: string;
  readonly date: string | null;
  readonly addedAt: string | null;
  readonly ageDays: number | null;
  readonly raw: Json;
}

/** An open ask nobody answered. */
export interface FollowUp {
  readonly title: string | null;
  readonly who: string | null;
  readonly date: string | null;
  readonly ageDays: number | null;
  readonly raw: Json;
}

export interface OpenItems {
  readonly items: OpenItem[];
  readonly followUps: FollowUp[];
  readonly raw: Json;
}

export function parseOpenItems(value: unknown): OpenItems {
  const raw = object(value);
  return {
    items: objects(raw.items).map((i) => ({
      ref: text(i.ref),
      text: text(i.text),
      date: maybe(i.date),
      addedAt: maybe(i.added_at),
      ageDays: maybeCount(i.age_days),
      raw: i,
    })),
    followUps: objects(raw.follow_ups).map((f) => ({
      title: maybe(f.title),
      who: maybe(f.who),
      date: maybe(f.date),
      ageDays: maybeCount(f.age_days),
      raw: f,
    })),
    raw,
  };
}
