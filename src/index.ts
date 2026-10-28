/**
 * Alexein for JavaScript and TypeScript: long-term memory for your users, behind one API key.
 *
 * ```ts
 * import { Memory } from "twinmemory";
 *
 * const dana = new Memory().user("dana");
 * await dana.add("I moved to Lisbon for the job at Acme.");
 * console.log((await dana.search("Where does Dana live?")).context());
 * ```
 */

export { DEFAULT_BASE_URL, Memory, User, VERSION } from "./client.js";
export type { AddOptions, MemoryOptions } from "./client.js";
export type { ForgetOptions, ItemDefaults, LatestOptions, SearchOptions } from "./calls.js";
export {
  APIConnectionError,
  APITimeoutError,
  AuthenticationError,
  InvalidRequestError,
  NotFoundError,
  PermissionDeniedError,
  RateLimitError,
  ServiceUnavailableError,
  TwinMemoryError,
} from "./errors.js";
export { SearchResult } from "./types.js";
export type {
  AddResult,
  AddedItem,
  Author,
  Correction,
  Fact,
  File,
  GrepResult,
  History,
  Hit,
  Item,
  Json,
  Lineage,
  Listing,
  Me,
  Overview,
  Passages,
  Receipt,
  TableChange,
  Versions,
} from "./types.js";
