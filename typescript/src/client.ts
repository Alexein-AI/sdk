/**
 * The client, `Memory`: one API key and the settings it sends with. `memory.user("dana")` is the
 * memory of one of your app users.
 */

import * as calls from "./calls.js";
import { type AppUser, type Me, type UsersPage, paged } from "./pages.js";
import { type MemoryOptions, type Settings, checkedUserId, settings } from "./settings.js";
import { Transport } from "./transport.js";
import { User } from "./user.js";

/**
 * An Alexein client, for one API key.
 *
 * ```ts
 * const memory = new Memory();          // ALEXEIN_API_KEY from the environment
 * const dana = memory.user("dana");     // your own id for one of your app users
 * await dana.add("I moved to Lisbon for the job at Acme.");
 * console.log((await dana.search("Where does Dana live?")).context());
 * ```
 */
export class Memory {
  /** The API's host, without `/v2`. */
  readonly baseUrl: string;
  /** Milliseconds one attempt may take. */
  readonly timeout: number;
  readonly maxRetries: number;
  readonly failOpen: boolean;
  /** The word in the User-Agent, or null. */
  readonly integration: string | null;
  readonly #settings: Settings;
  readonly #transport: Transport;

  constructor(options: MemoryOptions = {}) {
    this.#settings = settings(options);
    this.#transport = new Transport(this.#settings);
    this.baseUrl = this.#settings.baseUrl;
    this.timeout = this.#settings.timeout;
    this.maxRetries = this.#settings.maxRetries;
    this.failOpen = this.#settings.failOpen;
    this.integration = this.#settings.integration;
  }

  /** What this key is: its organisation, project, and whether it writes. Names no app user. */
  me(): Promise<Me> {
    return this.#transport.send(calls.me());
  }

  /**
   * The memory of one of your app users, by your own id for them: 1 to 35 letters, digits, `.`,
   * `_` and `-`, beginning with a letter or digit. A RangeError otherwise, before any request.
   */
  user(id: string): User {
    return new User(this.#transport, checkedUserId(id), this.failOpen, this.#settings.log);
  }

  /** The app users of this key's project with memory, a page at a time in id order. */
  users(options: calls.PageOptions = {}): Promise<UsersPage> {
    return this.#transport.send(calls.users(options));
  }

  /** Every app user with memory, across pages. */
  iterUsers(options: { limit?: number } = {}): AsyncIterable<AppUser> {
    return paged(
      (cursor) => this.users({ ...options, cursor }),
      (page) => page.users,
    );
  }

  /** Nothing to release: each request is its own. Here so code written for Python reads the same. */
  close(): void {}
}
