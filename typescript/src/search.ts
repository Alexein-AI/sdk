/** What `search` answers, and the text of it to paste into a prompt. */

import { type Json, list, maybe, object, strings, text } from "./json.js";
import {
  type Excerpt,
  type Fact,
  type Known,
  type MemoryEntry,
  parseMemories,
  refsOf,
} from "./memories.js";

/**
 * A line break and the spaces around it: an excerpt's text is its header, a blank line, then what
 * was said, often over several lines, and in a prompt each memory is one line.
 */
const BREAK = /\s*[\r\n]\s*/g;

/**
 * One memory as one line of a prompt: `- <text>`, an excerpt with a date `- <YYYY-MM-DD>: <text>`,
 * its line breaks made spaces.
 */
function line(memory: MemoryEntry): string {
  const dated = memory.type === "excerpt" && memory.date ? `${memory.date.slice(0, 10)}: ` : "";
  return `- ${dated}${memory.text.trim().replace(BREAK, " ")}`;
}

/**
 * What memory holds for a question. `memories` come in order: known lines, then facts, then
 * excerpts. `answerable` is false when memory does not seem to hold the answer, and null when it
 * was not checked. `failed` is true when a `failOpen` client could not reach memory, and the
 * result is empty for that reason. `searchId` is what `feedback()` takes to say how the search
 * went (null when failed).
 */
export class SearchResult {
  constructor(
    readonly query: string,
    readonly answerable: boolean | null,
    readonly notes: string[],
    readonly memories: MemoryEntry[],
    readonly sources: Json[] | null,
    readonly failed: boolean,
    readonly raw: Json,
    readonly searchId: string | null = null,
  ) {}

  static parse(value: unknown): SearchResult {
    const raw = object(value);
    return new SearchResult(
      text(raw.query),
      typeof raw.answerable === "boolean" ? raw.answerable : null,
      strings(raw.notes),
      parseMemories(raw.memories),
      Array.isArray(raw.sources) ? list(raw.sources).map(object) : null,
      false,
      raw,
      maybe(raw.search_id),
    );
  }

  /** What a `failOpen` client answers when memory could not be reached. */
  static unavailable(query: string): SearchResult {
    return new SearchResult(query, null, [], [], null, true, {});
  }

  get known(): Known[] {
    return this.memories.filter((m): m is Known => m.type === "known");
  }

  get facts(): Fact[] {
    return this.memories.filter((m): m is Fact => m.type === "fact");
  }

  get excerpts(): Excerpt[] {
    return this.memories.filter((m): m is Excerpt => m.type === "excerpt");
  }

  /** Every ref, in order: each opens with `user.open(ref)`. */
  get refs(): string[] {
    return refsOf(this.memories);
  }

  /**
   * The text to paste into a prompt: each note on its own line, a blank line, then each memory on
   * its own line as `- <text>` (an excerpt with a date as `- <YYYY-MM-DD>: <text>`; a memory's
   * own line breaks made spaces), cut at a whole
   * memory so it is never longer than `maxChars`. Empty when there are no memories, or when not
   * even the first fits. The Python client and the n8n node write the same text.
   */
  context(maxChars = 4000): string {
    const head = this.notes.length ? `${this.notes.join("\n")}\n\n` : "";
    let out = "";
    for (const memory of this.memories) {
      const grown = `${out || head}${out ? "\n" : ""}${line(memory)}`;
      if (grown.length > maxChars) break;
      out = grown;
    }
    return out;
  }
}
