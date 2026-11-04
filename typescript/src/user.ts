/** One app user's memory: every call sends their id as `X-Alexein-User`. */

import * as calls from "./calls.js";
import { AlexeinError } from "./errors.js";
import { type AddOptions, type Adding, batches } from "./items.js";
import {
  type ExportPage,
  type ExportRecord,
  type FactsPage,
  type ItemsPage,
  type StoredItem,
  paged,
} from "./pages.js";
import type { Fact } from "./memories.js";
import type { History, Memories, OpenItems, Opened, Sources, Summary } from "./reads.js";
import { SearchResult } from "./search.js";
import type { Call, Transport } from "./transport.js";
import {
  type AddResult,
  type Correction,
  type Deleted,
  type Forgotten,
  type Statuses,
  type Versions,
  mergedAdd,
} from "./writes.js";

export class User {
  /** @internal Made by `memory.user(id)`. */
  constructor(
    private readonly transport: Transport,
    /** Your id for this app user. */
    readonly id: string,
    private readonly failOpen: boolean,
    private readonly log: (message: string) => void,
  ) {}

  private send<T>(call: Call<T>): Promise<T> {
    return this.transport.send(call, this.id);
  }

  /**
   * Remember text: a string, an item, or a list of either. The options fill in each item's unset
   * fields. More than 500 items go as several requests; a retry never saves an item twice.
   */
  async add(items: Adding, options: AddOptions = {}): Promise<AddResult> {
    const results: AddResult[] = [];
    for (const batch of batches(items, options)) {
      try {
        results.push(await this.send(calls.add(batch.body, batch.key)));
      } catch (error) {
        this.rideOut(error, "add");
        return mergedAdd(results, true);
      }
    }
    return mergedAdd(results);
  }

  /** What memory holds for a question: known lines, facts and excerpts, in order. */
  async search(query: string, options: calls.SearchOptions = {}): Promise<SearchResult> {
    try {
      return await this.send(calls.search(query, options));
    } catch (error) {
      this.rideOut(error, "search");
      return SearchResult.unavailable(query);
    }
  }

  /** Excerpts holding an exact phrase, ignoring case. */
  grep(pattern: string, options: calls.GrepOptions = {}): Promise<Memories> {
    return this.send(calls.grep(pattern, options));
  }

  /** The most recent excerpts, newest first; with `after` and `before`, everything between. */
  latest(options: calls.LatestOptions = {}): Promise<Memories> {
    return this.send(calls.latest(options));
  }

  /** The excerpts just before and after one, from the same conversation, in order. */
  around(ref: string, options: { width?: number } = {}): Promise<Memories> {
    return this.send(calls.around(ref, options.width));
  }

  /** One memory by its ref, whole: an excerpt, or a fact with the excerpts it came from. */
  open(ref: string): Promise<Opened> {
    return this.send(calls.open(ref));
  }

  /** Every value a subject was stated to have, by attribute, oldest first. */
  history(subject: string, options: { attribute?: string } = {}): Promise<History> {
    return this.send(calls.history(subject, options.attribute));
  }

  /** This memory in brief: its items, their span, the connected sources and the known lines. */
  summary(): Promise<Summary> {
    return this.send(calls.summary());
  }

  /** The facts memory learned, newest first, a page at a time. */
  facts(options: calls.PageOptions = {}): Promise<FactsPage> {
    return this.send(calls.facts(options));
  }

  /** Every fact, across pages. */
  iterFacts(options: { limit?: number } = {}): AsyncIterable<Fact> {
    return paged(
      (cursor) => this.facts({ ...options, cursor }),
      (page) => page.facts,
    );
  }

  /** The issues and pull requests still open, and the asks nobody answered. */
  openItems(options: calls.OpenItemsOptions = {}): Promise<OpenItems> {
    return this.send(calls.openItems(options));
  }

  /** What each connected app delivered to this memory. */
  sources(): Promise<Sources> {
    return this.send(calls.sources());
  }

  /** The items added, newest first, as they were given, a page at a time. */
  items(options: calls.ItemsOptions = {}): Promise<ItemsPage> {
    return this.send(calls.items(options));
  }

  /** Every item, across pages. */
  iterItems(options: { limit?: number; filters?: calls.Filters } = {}): AsyncIterable<StoredItem> {
    return paged(
      (cursor) => this.items({ ...options, cursor }),
      (page) => page.items,
    );
  }

  /** One added item by its id, whole; null when memory holds none by that id. */
  item(itemId: string): Promise<StoredItem | null> {
    return this.send(calls.item(itemId));
  }

  /** How far each item has got: `queued`, `stored`, `processed` or `unknown`. */
  status(ids: string[]): Promise<Statuses> {
    return this.send(calls.status(ids));
  }

  /** Erase these items, sessions and memories (by ref), with every copy and all learned from them. */
  async forget(named: calls.ForgetOptions): Promise<Forgotten> {
    return this.send(calls.forget(named));
  }

  /** Retract one fact for good, by its ref; a `replacement` is kept as a note. */
  correct(ref: string, replacement?: string): Promise<Correction> {
    return this.send(calls.correct(ref, replacement));
  }

  /** Every version of one added item, oldest first. Takes a key that writes. */
  versions(itemId: string): Promise<Versions> {
    return this.send(calls.versions(itemId));
  }

  /** Everything memory holds for this app user, a page at a time. */
  export(options: calls.PageOptions = {}): Promise<ExportPage> {
    return this.send(calls.exportPage(options));
  }

  /** Every export record, across pages. */
  iterExport(options: { limit?: number } = {}): AsyncIterable<ExportRecord> {
    return paged(
      (cursor) => this.export({ ...options, cursor }),
      (page) => page.records,
    );
  }

  /** Erase this app user whole: every item, fact and version. Not undone. */
  delete(): Promise<Deleted> {
    return this.send(calls.deleteUser());
  }

  /**
   * Throw `error` unless this client fails open and it is an outage; then log it, and the caller
   * answers empty. Memory being down costs a reply its memory, not the reply.
   */
  private rideOut(error: unknown, what: string): void {
    if (!(this.failOpen && error instanceof AlexeinError && error.outage)) throw error;
    this.log(`Alexein is unavailable, so ${what} for ${this.id} was skipped: ${error.message}`);
  }
}
