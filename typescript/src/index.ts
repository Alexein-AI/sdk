/**
 * Alexein for JavaScript and TypeScript: long-term memory for your app users, behind one API key.
 *
 * ```ts
 * import { Memory } from "@alexein/sdk";
 *
 * const dana = new Memory().user("dana");
 * await dana.add("I moved to Lisbon for the job at Acme.");
 * console.log((await dana.search("Where does Dana live?")).context());
 * ```
 *
 * The integrations are their own entry points: `@alexein/sdk/langgraph` and
 * `@alexein/sdk/openai-agents`. This one imports no framework.
 */

export { Memory } from "./client.js";
export { User } from "./user.js";
export { DEFAULT_BASE_URL, DEFAULT_RETRIES, DEFAULT_TIMEOUT_MS } from "./settings.js";
export type { MemoryOptions } from "./settings.js";
export { VERSION } from "./version.js";
export type {
  Filters,
  ForgetOptions,
  GrepOptions,
  ItemsOptions,
  LatestOptions,
  OpenItemsOptions,
  Origin,
  PageOptions,
  SearchOptions,
} from "./calls.js";
export type { AddOptions, Adding, Author, Item, ItemDefaults } from "./items.js";
export {
  APIConnectionError,
  APITimeoutError,
  AlexeinError,
  AuthenticationError,
  InvalidRequestError,
  NotFoundError,
  PermissionDeniedError,
  RateLimitError,
  ServiceUnavailableError,
} from "./errors.js";
export type { FieldError } from "./errors.js";
export type { Json } from "./json.js";
export type { Excerpt, Fact, Known, MemoryEntry } from "./memories.js";
export { SearchResult } from "./search.js";
export type {
  FollowUp,
  History,
  Memories,
  OpenItem,
  OpenItems,
  Opened,
  Source,
  Sources,
  Summary,
  Value,
} from "./reads.js";
export type {
  AppUser,
  ExportPage,
  ExportRecord,
  FactsPage,
  ItemsPage,
  Me,
  StoredItem,
  UsersPage,
} from "./pages.js";
export type {
  AddResult,
  AddedItem,
  Correction,
  Deleted,
  Erased,
  Forgotten,
  ItemStatus,
  Statuses,
  VersionEntry,
  Versions,
} from "./writes.js";
