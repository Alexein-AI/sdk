/** What the writes answer, and the reads that say what became of them: add, status, versions. */

import { type Json, bool, count, maybe, maybeCount, object, objects, text } from "./json.js";

/** One item of an add: `stored` (searchable) or `queued` (searchable in a moment). */
export interface AddedItem {
  readonly id: string;
  readonly status: string;
  /** With `redact`: how many of each kind were replaced (`{PHONE: 1}`); null when none. */
  readonly redacted: Record<string, number> | null;
  readonly raw: Json;
}

/**
 * An add's answer. `waiting` is how many items are not searchable yet; zero once they are.
 * `failed` is true when a `failOpen` client could not reach memory, and nothing more was saved.
 */
export interface AddResult {
  readonly items: AddedItem[];
  readonly waiting: number;
  readonly failed: boolean;
  /** Each item's id, in order. */
  readonly ids: string[];
  readonly raw: Json;
}

function addResult(items: AddedItem[], waiting: number, failed: boolean, raw: Json): AddResult {
  return { items, waiting, failed, ids: items.map((i) => i.id), raw };
}

export function parseAddResult(value: unknown): AddResult {
  const raw = object(value);
  const items = objects(raw.items).map((i) => ({
    id: text(i.id),
    status: text(i.status),
    redacted: i.redacted ? (object(i.redacted) as Record<string, number>) : null,
    raw: i,
  }));
  return addResult(items, count(raw.waiting), false, raw);
}

/**
 * Batches' answers as one, in the API's own shape. `failed` when a `failOpen` client could not
 * reach memory: then `items` holds what the batches before it saved, if any.
 */
export function mergedAdd(results: AddResult[], failed = false): AddResult {
  if (results.length === 1 && !failed) return results[0]!;
  const items = results.flatMap((r) => r.items);
  const waiting = results.reduce((n, r) => n + r.waiting, 0);
  const raw = results.length ? { items: items.map((i) => i.raw), waiting } : {};
  return addResult(items, waiting, failed, raw);
}

/** How far one item has got: `queued`, `stored`, `processed` or `unknown`. */
export interface ItemStatus {
  readonly id: string;
  readonly status: string;
  /** Null unless something holds it back; then what does, in words. */
  readonly reason: string | null;
  readonly raw: Json;
}

export interface Statuses {
  readonly items: ItemStatus[];
  /** Each id's status. */
  readonly byId: Record<string, string>;
  readonly raw: Json;
}

export function parseStatuses(value: unknown): Statuses {
  const raw = object(value);
  const items = objects(raw.items).map((i) => ({
    id: text(i.id),
    status: text(i.status),
    reason: maybe(i.reason),
    raw: i,
  }));
  return { items, byId: Object.fromEntries(items.map((i) => [i.id, i.status])), raw };
}

/**
 * What a forget erased: the items, the facts learned from them, the versions an edit kept, the
 * copies still on their way in; and `relearning`, the facts of other items that stay, taken to be
 * learned again from what is left.
 */
export interface Erased {
  readonly items: number;
  readonly facts: number;
  readonly versions: number;
  readonly waiting: number;
  readonly relearning: number;
}

/** `complete` is false when some copies on their way in could not be checked: ask again. */
export interface Forgotten {
  readonly erased: Erased;
  readonly complete: boolean;
  readonly raw: Json;
}

export function parseForgotten(value: unknown): Forgotten {
  const raw = object(value);
  const e = object(raw.erased);
  return {
    erased: {
      items: count(e.items),
      facts: count(e.facts),
      versions: count(e.versions),
      waiting: count(e.waiting),
      relearning: count(e.relearning),
    },
    complete: bool(raw.complete),
    raw,
  };
}

/** The fact retracted (its ref), its text, and the id of the note holding what is true instead. */
export interface Correction {
  readonly retracted: string;
  readonly text: string | null;
  readonly replacement: string | null;
  readonly raw: Json;
}

export function parseCorrection(value: unknown): Correction {
  const raw = object(value);
  return {
    retracted: text(raw.retracted),
    text: maybe(raw.text),
    replacement: maybe(raw.replacement),
    raw,
  };
}

/**
 * One line of an item's history: a `version` (`at`, its number and the item as it was held) or,
 * once it went, `gone` (`at` and `why`: `forgotten` or `expired`).
 */
export interface VersionEntry {
  readonly event: string;
  readonly at: string | null;
  readonly version: number | null;
  readonly item: Json | null;
  readonly why: string | null;
  readonly raw: Json;
}

/** Every version of one added item, oldest first. `state`: live, expired, forgotten or unknown. */
export interface Versions {
  readonly id: string;
  readonly state: string;
  readonly history: VersionEntry[];
  readonly raw: Json;
}

export function parseVersions(value: unknown): Versions {
  const raw = object(value);
  return {
    id: text(raw.id),
    state: text(raw.state),
    history: objects(raw.history).map((h) => ({
      event: text(h.event),
      at: maybe(h.at),
      version: maybeCount(h.version),
      item: h.item ? object(h.item) : null,
      why: maybe(h.why),
      raw: h,
    })),
    raw,
  };
}

/** An app user erased whole. */
export interface Deleted {
  readonly user: string;
  readonly deleted: boolean;
  readonly raw: Json;
}

export function parseDeleted(value: unknown): Deleted {
  const raw = object(value);
  return { user: text(raw.user), deleted: bool(raw.deleted), raw };
}
