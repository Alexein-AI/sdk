/**
 * What `add` takes - a string, an item, or a list of either - shaped into the requests it sends:
 * at most 500 items each, every one with an `Idempotency-Key` its retries send again.
 */

import { type Json, compact } from "./json.js";

/** The most items the API takes in one add; a longer list goes in batches of this many. */
export const BATCH = 500;

/** Who said it. `id` is your stable id for the person; `email` and `handle` join them up. */
export interface Author {
  id?: string | null;
  name?: string | null;
  email?: string | null;
  handle?: string | null;
  /** True when it is the app user themself. */
  self?: boolean | null;
}

/**
 * One thing to remember. Only `text` is required. The same `id` again is an edit of it; set
 * `expires` (an ISO date) for what stops being true, or `null` to lift an expiry.
 */
export interface Item {
  text: string;
  kind?: "message" | "document" | "note";
  id?: string | null;
  session?: string | null;
  role?: string | null;
  author?: string | Author | null;
  title?: string | null;
  /** What it is about, as `kind:name`: `project:atlas`. */
  about?: string[] | null;
  /** When it happened: an ISO date or timestamp. */
  at?: string | null;
  expires?: string | null;
  metadata?: Json | null;
}

/** The item fields `add` fills in for every item that does not set its own. */
export interface ItemDefaults {
  kind?: Item["kind"];
  session?: string;
  role?: string;
  author?: string | Author;
  title?: string;
  about?: string[];
  expires?: string;
  at?: string;
  metadata?: Json;
}

/** Options `add` takes besides the items. */
export interface AddOptions extends ItemDefaults {
  /** Answer once the items are searchable (briefly waited for). */
  wait?: boolean;
  /** Replace phone numbers, cards, keys and the like with their kind before memory keeps them. */
  redact?: boolean;
}

export type Adding = string | Item | readonly (string | Item)[];

/** One request of an add: its body and its idempotency key. */
export interface Batch {
  body: Json;
  key: string;
}

function shape(given: string | Item, defaults: Json): Json {
  const item: Json = typeof given === "string" ? { text: given } : { ...given };
  if (typeof item.text !== "string" || !item.text) {
    throw new TypeError(`an item needs text: ${JSON.stringify(given)}`);
  }
  // An item's own fields win, an explicit null among them (`expires: null` lifts an expiry);
  // a field it leaves unset is filled from the defaults, or not sent at all.
  const own = Object.fromEntries(Object.entries(item).filter(([, v]) => v !== undefined));
  return { ...defaults, ...own };
}

/**
 * The requests an add is: one per `BATCH` items, each keyed `<one uuid for the call>-<index>`, so
 * a retried batch is the same items again, never a second copy. None for an empty list.
 */
export function batches(items: Adding, options: AddOptions): Batch[] {
  const { wait, redact, ...fields } = options;
  const defaults = compact(fields as Json);
  const given: readonly (string | Item)[] =
    typeof items === "string" || !Array.isArray(items) ? [items as string | Item] : items;
  const shaped = given.map((item) => shape(item, defaults));
  if (!shaped.length) return [];
  const call = crypto.randomUUID();
  const out: Batch[] = [];
  for (let at = 0; at < shaped.length; at += BATCH) {
    out.push({
      body: compact({ items: shaped.slice(at, at + BATCH), wait, redact }),
      key: `${call}-${at / BATCH}`,
    });
  }
  return out;
}
