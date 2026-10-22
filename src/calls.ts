/**
 * Each operation as the request it is: path, body and how to read the answer. Written once here,
 * and sent by the client, the same requests the Python client sends.
 */

import {
  type AddResult,
  type Correction,
  type File,
  type GrepResult,
  type History,
  type Item,
  type Json,
  type Lineage,
  type Listing,
  type Me,
  type Overview,
  type Passages,
  type Receipt,
  type Versions,
  SearchResult,
  parseAddResult,
  parseCorrection,
  parseFile,
  parseGrep,
  parseHistory,
  parseLineage,
  parseListing,
  parseMe,
  parseOverview,
  parsePassages,
  parseReceipt,
  parseVersions,
} from "./types.js";

/** The API takes at most this many items in one add; a longer list is sent in batches. */
export const BATCH = 500;

// What the API accepts as an end user id, checked here so a typo fails before a round trip. The
// API also bounds its length, which depends on the key's organisation and project.
const USER_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export interface Call<T> {
  method: "GET" | "POST";
  path: string;
  parse: (raw: Json) => T;
  body?: Json;
  headers?: Record<string, string>;
}

export function checkedUser(userId: string): string {
  if (!USER_ID.test(userId)) {
    throw new TypeError(
      `not a usable end user id: ${JSON.stringify(userId)} (letters, digits, '.', '_' and '-', ` +
        "starting with a letter or digit)",
    );
  }
  return userId;
}

function post<T>(path: string, parse: (raw: Json) => T, body: Json): Call<T> {
  const sent = Object.fromEntries(Object.entries(body).filter(([, v]) => v !== undefined));
  return { method: "POST", path: `/v1/memory/${path}`, parse, body: sent };
}

export const me = (): Call<Me> => ({ method: "GET", path: "/v1/me", parse: parseMe });

/** The fields `add` takes besides the items, applied to every item that does not set its own. */
export interface ItemDefaults {
  kind?: Item["kind"];
  session?: string;
  role?: string;
  author?: Item["author"];
  title?: string;
  about?: string[];
  expires?: string;
  at?: string;
  metadata?: Json;
}

/**
 * One call per batch of `BATCH` items. Each carries an `Idempotency-Key`, so a retried batch is
 * the same events again, never a second copy of an item sent without an id.
 */
export function add(
  items: string | Item | (string | Item)[],
  wait: boolean,
  defaults: ItemDefaults,
): Call<AddResult>[] {
  const given = Array.isArray(items) ? items : [items];
  const shaped = given.map((item) => shape(item, defaults));
  if (!shaped.length) throw new TypeError("add needs at least one item");
  const key = crypto.randomUUID().replaceAll("-", "");
  const calls: Call<AddResult>[] = [];
  for (let at = 0; at < shaped.length; at += BATCH) {
    calls.push({
      method: "POST",
      path: "/v1/memory/add",
      parse: parseAddResult,
      body: { items: shaped.slice(at, at + BATCH), wait },
      headers: { "Idempotency-Key": `${key}-${at / BATCH}` },
    });
  }
  return calls;
}

function shape(given: string | Item, defaults: ItemDefaults): Json {
  const item: Json = typeof given === "string" ? { text: given } : { ...given };
  if (!item.text) throw new TypeError(`an item needs text: ${JSON.stringify(given)}`);
  const set = Object.entries(defaults).filter(([, v]) => v !== undefined && v !== null);
  return { ...Object.fromEntries(set), ...item };
}

/** Batches' answers as one. */
export function merged(results: AddResult[]): AddResult {
  if (results.length === 1) return results[0]!;
  return {
    items: results.flatMap((r) => r.items),
    queued: results.reduce((n, r) => n + r.queued, 0),
    pending: results.reduce((n, r) => n + r.pending, 0),
    failed: false,
    raw: { batches: results.map((r) => r.raw) },
  };
}

export interface SearchOptions {
  /** ISO date: only what happened before it. */
  before?: string;
  /** ISO date: only what happened after it. */
  after?: string;
  /** A path prefix the search stays inside. */
  scope?: string;
  /** Skip the model filter: free and quicker, a little less precise. */
  fast?: boolean;
}

export const search = (query: string, o: SearchOptions): Call<SearchResult> =>
  post("search", SearchResult.parse, {
    query,
    before: o.before,
    after: o.after,
    scope: o.scope,
    fast: o.fast ?? false,
  });

export const grep = (pattern: string, scope: string | undefined, limit: number): Call<GrepResult> =>
  post("grep", parseGrep, { pattern, scope, limit });

export const read = (path: string): Call<File> => post("read", parseFile, { path });

export const ls = (path: string): Call<Listing> => post("ls", parseListing, { path });

export const around = (passageId: string, width: number): Call<Passages> =>
  post("around", parsePassages, { passage_id: passageId, width });

export const history = (subject: string, attribute: string | undefined): Call<History> =>
  post("history", parseHistory, { subject, attribute });

export interface LatestOptions {
  k?: number;
  place?: string;
  after?: string;
  before?: string;
}

export const latest = (o: LatestOptions): Call<Passages> =>
  post("latest", parsePassages, {
    k: o.k ?? 10,
    place: o.place ?? "",
    after: o.after,
    before: o.before,
  });

export const overview = (): Call<Overview> => post("overview", parseOverview, {});

export interface ForgetOptions {
  items?: string[];
  sessions?: string[];
  threads?: string[];
  events?: string[];
}

export function forget(named: ForgetOptions): Call<Receipt> {
  const body = Object.fromEntries(
    Object.entries(named).filter(([, v]) => Array.isArray(v) && v.length),
  );
  if (!Object.keys(body).length) {
    throw new TypeError("forget needs at least one of items, sessions, threads or events");
  }
  return post("forget", parseReceipt, body);
}

export const correct = (recordId: string, replacement: string | undefined): Call<Correction> =>
  post("correct", parseCorrection, { record_id: recordId, replacement });

export const versions = (itemId: string): Call<Versions> =>
  post("versions", parseVersions, { id: itemId });

export const status = (ids: string[]): Call<Record<string, string>> =>
  post("status", (raw) => Object.fromEntries(Object.entries(raw.phases ?? {})), { ids });

export const lineage = (id: string): Call<Lineage> => post("lineage", parseLineage, { id });
