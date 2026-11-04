/**
 * The memories search, grep, latest, around and open answer: known lines, facts and excerpts,
 * told apart by `type`. Each keeps the JSON it was read from as `raw`.
 */

import { type Json, maybe, object, strings, text } from "./json.js";

/** A line memory takes to be true now. */
export interface Known {
  readonly type: "known";
  readonly text: string;
  readonly raw: Json;
}

/** Something learned from what was said, with its ref. */
export interface Fact {
  readonly type: "fact";
  /** Opens it with `user.open(ref)`; names it to `forget` and `correct`. */
  readonly ref: string;
  readonly text: string;
  /** The ref of the excerpt it came from, or null. */
  readonly source: string | null;
  /** When it was said: on `facts()` only, null elsewhere. */
  readonly date: string | null;
  readonly raw: Json;
}

/** Part of what was said or delivered, with its ref. */
export interface Excerpt {
  readonly type: "excerpt";
  readonly ref: string;
  readonly text: string;
  /** When it happened, or null when unknown. */
  readonly date: string | null;
  /** When memory took it. */
  readonly addedAt: string | null;
  readonly session: string | null;
  /** The roles of who spoke in it: `user`, `assistant`. */
  readonly roles: string[];
  readonly raw: Json;
}

/** One memory, of whichever type. */
export type MemoryEntry = Known | Fact | Excerpt;

export function parseFact(value: unknown): Fact {
  const raw = object(value);
  return {
    type: "fact",
    ref: text(raw.ref),
    text: text(raw.text),
    source: maybe(raw.source),
    date: maybe(raw.date),
    raw,
  };
}

export function parseExcerpt(value: unknown): Excerpt {
  const raw = object(value);
  return {
    type: "excerpt",
    ref: text(raw.ref),
    text: text(raw.text),
    date: maybe(raw.date),
    addedAt: maybe(raw.added_at),
    session: maybe(raw.session),
    roles: strings(raw.roles),
    raw,
  };
}

/** One memory by its `type`; undefined for a type this version does not know (see `raw`). */
export function parseMemory(value: unknown): MemoryEntry | undefined {
  const raw = object(value);
  if (raw.type === "known") return { type: "known", text: text(raw.text), raw };
  if (raw.type === "fact") return parseFact(raw);
  if (raw.type === "excerpt") return parseExcerpt(raw);
  return undefined;
}

export function parseMemories(value: unknown): MemoryEntry[] {
  const out: MemoryEntry[] = [];
  for (const entry of Array.isArray(value) ? value : []) {
    const memory = parseMemory(entry);
    if (memory) out.push(memory);
  }
  return out;
}

/** The refs of these memories, in order; known lines have none. */
export function refsOf(memories: readonly MemoryEntry[]): string[] {
  return memories.flatMap((m) => (m.type === "known" || !m.ref ? [] : [m.ref]));
}
