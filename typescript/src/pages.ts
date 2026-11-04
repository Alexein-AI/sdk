/**
 * The paged answers - facts, items, export, users - and the items, app users and key they hold.
 * `next` is the cursor of the page after, null on the last; the `iter*` methods follow it.
 */

import type { Author } from "./items.js";
import {
  type Json,
  bool,
  count,
  maybe,
  maybeStrings,
  object,
  objects,
  strings,
  text,
} from "./json.js";
import { type Fact, parseFact } from "./memories.js";

export interface FactsPage {
  readonly facts: Fact[];
  readonly next: string | null;
  readonly raw: Json;
}

export function parseFactsPage(value: unknown): FactsPage {
  const raw = object(value);
  return { facts: objects(raw.facts).map(parseFact), next: maybe(raw.next), raw };
}

/** An item as `add` was given it, and whether it is searchable yet. */
export interface StoredItem {
  readonly id: string;
  readonly kind: string | null;
  readonly text: string;
  readonly title: string | null;
  readonly at: string | null;
  readonly author: string | Author | null;
  readonly role: string | null;
  readonly session: string | null;
  readonly about: string[] | null;
  readonly metadata: Json | null;
  readonly expires: string | null;
  /** `queued` while it waits to be stored, then `stored`. */
  readonly status: string;
  readonly raw: Json;
}

export function parseStoredItem(value: unknown): StoredItem {
  const raw = object(value);
  const author = raw.author;
  return {
    id: text(raw.id),
    kind: maybe(raw.kind),
    text: text(raw.text),
    title: maybe(raw.title),
    at: maybe(raw.at),
    author: typeof author === "string" ? author : author ? (object(author) as Author) : null,
    role: maybe(raw.role),
    session: maybe(raw.session),
    about: maybeStrings(raw.about),
    metadata: raw.metadata ? object(raw.metadata) : null,
    expires: maybe(raw.expires),
    status: text(raw.status),
    raw,
  };
}

/** `item(id)`'s answer: the item, or null when memory holds none by that id. */
export function parseFound(value: unknown): StoredItem | null {
  const raw = object(value);
  return raw.found === false || !raw.item ? null : parseStoredItem(raw.item);
}

export interface ItemsPage {
  readonly items: StoredItem[];
  readonly next: string | null;
  readonly raw: Json;
}

export function parseItemsPage(value: unknown): ItemsPage {
  const raw = object(value);
  return { items: objects(raw.items).map(parseStoredItem), next: maybe(raw.next), raw };
}

/** An app user of the key's project with memory. */
export interface AppUser {
  readonly user: string;
  readonly items: number;
  readonly facts: number;
  /** When memory last took something for them; null when unknown. */
  readonly lastWrite: string | null;
  readonly raw: Json;
}

export interface UsersPage {
  readonly users: AppUser[];
  readonly next: string | null;
  readonly raw: Json;
}

export function parseUsersPage(value: unknown): UsersPage {
  const raw = object(value);
  const users = objects(raw.users).map((u) => ({
    user: text(u.user),
    items: count(u.items),
    facts: count(u.facts),
    lastWrite: maybe(u.last_write),
    raw: u,
  }));
  return { users, next: maybe(raw.next), raw };
}

/**
 * One record of an export, as the API sent it: `type` is `item`, `version`, `event` or `fact`,
 * and the rest of its fields are that record's own.
 */
export type ExportRecord = Json & { type: string };

/**
 * A page of everything memory holds for an app user. `withheld` names what a read key went
 * without (`version`).
 */
export interface ExportPage {
  readonly user: string;
  readonly exportedAt: string | null;
  readonly records: ExportRecord[];
  readonly next: string | null;
  readonly withheld: string[];
  readonly raw: Json;
}

export function parseExportPage(value: unknown): ExportPage {
  const raw = object(value);
  return {
    user: text(raw.user),
    exportedAt: maybe(raw.exported_at),
    records: objects(raw.records).map((r) => ({ ...r, type: text(r.type) })),
    next: maybe(raw.next),
    withheld: strings(raw.withheld),
    raw,
  };
}

/** What the API key is. `kind` is `key` for an API key. */
export interface Me {
  readonly kind: string;
  readonly org: string | null;
  readonly project: string | null;
  readonly keyId: string | null;
  /** Whether the key may add, forget and correct, or only read. */
  readonly writes: boolean;
  readonly label: string | null;
  /** Who made the key: an email, or null when unknown. */
  readonly createdBy: string | null;
  readonly orgName: string | null;
  readonly projectName: string | null;
  /** `project` for a project's key, `personal` for a member's personal space. */
  readonly space: string | null;
  readonly raw: Json;
}

export function parseMe(value: unknown): Me {
  const raw = object(value);
  return {
    kind: text(raw.kind),
    org: maybe(raw.org),
    project: maybe(raw.project),
    keyId: maybe(raw.key_id),
    writes: bool(raw.writes),
    label: maybe(raw.label),
    createdBy: maybe(raw.created_by),
    orgName: maybe(raw.org_name),
    projectName: maybe(raw.project_name),
    space: maybe(raw.space),
    raw,
  };
}

/** Every entry of every page, following `next` until it is null. */
export async function* paged<P extends { next: string | null }, E>(
  page: (cursor: string | undefined) => Promise<P>,
  entries: (page: P) => E[],
): AsyncGenerator<E, void, undefined> {
  let cursor: string | undefined;
  do {
    const got = await page(cursor);
    yield* entries(got);
    cursor = got.next ?? undefined;
  } while (cursor);
}
