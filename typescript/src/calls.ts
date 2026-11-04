/**
 * Each route as the request it is: path, body and how to read the answer. Written once here and
 * sent by the client; the same requests the Python client sends. Fields left unset are not sent.
 */

import { type Json, compact } from "./json.js";
import { type Memories, parseMemoriesResult } from "./reads.js";
import * as reads from "./reads.js";
import * as pages from "./pages.js";
import { SearchResult } from "./search.js";
import type { Call } from "./transport.js";
import * as writes from "./writes.js";

/**
 * Only items that match: `author`, `mentions` (`kind:name`, or `session:<id>`) and `metadata`
 * keys, as `{field: value}` or `{field: {op: value}}`, in `AND`, `OR` and `NOT`.
 */
export type Filters = Json;

/** Narrowing to what a connected app delivered. `kind` takes one kind or several. */
export interface Origin {
  provider?: string;
  source?: string;
  kind?: string | string[];
}

export interface SearchOptions extends Origin {
  /** ISO date: the question is answered as of that day. */
  before?: string;
  /** ISO date: only memory from this day on; the answer is then the facts and excerpts that match. */
  after?: string;
  filters?: Filters;
  /** Answer sooner, a little less precisely. Free. */
  fast?: boolean;
}

export interface GrepOptions extends Origin {
  limit?: number;
}

export interface LatestOptions extends Origin {
  k?: number;
  /** A connected app, a channel or a repository. */
  place?: string;
  after?: string;
  before?: string;
  filters?: Filters;
}

export interface OpenItemsOptions {
  kind?: string | string[];
  provider?: string;
  place?: string;
  /** The person's own (the default), or everyone's. */
  mine?: boolean;
  /** Only those from the last this many days; 0 is any age. */
  withinDays?: number;
  limit?: number;
}

export interface PageOptions {
  limit?: number;
  cursor?: string | null;
}

export interface ItemsOptions extends PageOptions {
  filters?: Filters;
}

export interface ForgetOptions {
  items?: string[];
  sessions?: string[];
  /** Refs of facts or excerpts. */
  refs?: string[];
}

const kinds = (kind: string | string[] | undefined) =>
  kind === undefined ? undefined : Array.isArray(kind) ? kind : [kind];

function post<T>(route: string, parse: (body: unknown) => T, body: Json = {}): Call<T> {
  return { method: "POST", path: `/memory/${route}`, body: compact(body), parse };
}

export const me = (): Call<pages.Me> => ({ method: "GET", path: "/me", parse: pages.parseMe });

export const users = (o: PageOptions): Call<pages.UsersPage> =>
  post("users", pages.parseUsersPage, { limit: o.limit, cursor: o.cursor });

export const deleteUser = (): Call<writes.Deleted> => post("users/delete", writes.parseDeleted);

export const add = (body: Json, key: string): Call<writes.AddResult> => ({
  method: "POST",
  path: "/memory/add",
  body,
  headers: { "Idempotency-Key": key },
  parse: writes.parseAddResult,
});

export const search = (query: string, o: SearchOptions): Call<SearchResult> =>
  post("search", SearchResult.parse, {
    query,
    before: o.before,
    after: o.after,
    filters: o.filters,
    provider: o.provider,
    source: o.source,
    kind: kinds(o.kind),
    fast: o.fast,
  });

export const grep = (pattern: string, o: GrepOptions): Call<Memories> =>
  post("grep", parseMemoriesResult, {
    pattern,
    limit: o.limit,
    provider: o.provider,
    source: o.source,
    kind: kinds(o.kind),
  });

export const latest = (o: LatestOptions): Call<Memories> =>
  post("latest", parseMemoriesResult, {
    k: o.k,
    place: o.place,
    after: o.after,
    before: o.before,
    filters: o.filters,
    provider: o.provider,
    source: o.source,
    kind: kinds(o.kind),
  });

export const around = (ref: string, width: number | undefined): Call<Memories> =>
  post("around", parseMemoriesResult, { ref, width });

export const open = (ref: string): Call<reads.Opened> => post("open", reads.parseOpened, { ref });

export const history = (subject: string, attribute: string | undefined): Call<reads.History> =>
  post("history", reads.parseHistory, { subject, attribute });

export const summary = (): Call<reads.Summary> => post("summary", reads.parseSummary);

export const facts = (o: PageOptions): Call<pages.FactsPage> =>
  post("facts", pages.parseFactsPage, { limit: o.limit, cursor: o.cursor });

export const openItems = (o: OpenItemsOptions): Call<reads.OpenItems> =>
  post("open_items", reads.parseOpenItems, {
    kind: kinds(o.kind),
    provider: o.provider,
    place: o.place,
    mine: o.mine,
    within_days: o.withinDays,
    limit: o.limit,
  });

export const sources = (): Call<reads.Sources> => post("sources", reads.parseSources);

export const items = (o: ItemsOptions): Call<pages.ItemsPage> =>
  post("items", pages.parseItemsPage, { limit: o.limit, cursor: o.cursor, filters: o.filters });

export const item = (id: string): Call<pages.StoredItem | null> =>
  post("item", pages.parseFound, { id });

export const status = (ids: string[]): Call<writes.Statuses> =>
  post("status", writes.parseStatuses, { items: ids });

/** A forget naming nothing is a RangeError before sending: it would erase nothing. */
export function forget(named: ForgetOptions): Call<writes.Forgotten> {
  const body = compact({
    items: named.items?.length ? named.items : undefined,
    sessions: named.sessions?.length ? named.sessions : undefined,
    refs: named.refs?.length ? named.refs : undefined,
  });
  if (!Object.keys(body).length) {
    throw new RangeError("forget needs at least one of items, sessions or refs");
  }
  return post("forget", writes.parseForgotten, body);
}

export const correct = (ref: string, replacement: string | undefined): Call<writes.Correction> =>
  post("correct", writes.parseCorrection, { ref, replacement });

export const versions = (id: string): Call<writes.Versions> =>
  post("versions", writes.parseVersions, { id });

export const exportPage = (o: PageOptions): Call<pages.ExportPage> =>
  post("export", pages.parseExportPage, { limit: o.limit, cursor: o.cursor });
