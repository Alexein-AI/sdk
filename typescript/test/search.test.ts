/** `search`: the result's parts, and `context()`, the text of it for a prompt. */

import { describe, expect, it } from "vitest";
import { SearchResult } from "../src/index.js";
import { EXCERPT, FACT, SEARCH } from "./fixtures.js";
import { memory, ok } from "./helpers.js";

const NOTE = SEARCH.notes[0]!;
const KNOWN = "- Alice Chen · home city: Lisbon (said 2026-10-01); Berlin (said 2024-06-01)";
const FACT_LINE = "- (said 2026-10-01) Alice lives in Lisbon";
const EXCERPT_LINE = "- 2026-10-01: I just moved to Lisbon from Berlin\nfor the new job at Acme.";

describe("SearchResult", () => {
  it("reads the answer into typed memories", async () => {
    const found = await memory(() => ok(SEARCH))
      .client.user("alice")
      .search("Where does Alice live?");
    expect(found.query).toBe("Where does Alice live?");
    expect(found.answerable).toBe(true);
    expect(found.notes).toEqual(SEARCH.notes);
    expect(found.memories.map((m) => m.type)).toEqual(["known", "fact", "excerpt"]);
    expect(found.known.map((k) => k.text)).toEqual([SEARCH.memories[0]!.text]);
    expect(found.facts).toEqual([
      {
        type: "fact",
        ref: "mem_5pQ1zX8gHd2",
        text: FACT.text,
        source: "mem_9fK2xQ7aLp3",
        date: null,
        raw: FACT,
      },
    ]);
    expect(found.excerpts[0]).toMatchObject({
      addedAt: "2026-10-01T09:30:02+00:00",
      session: "onboarding",
      roles: ["user"],
    });
    expect(found.refs).toEqual(["mem_5pQ1zX8gHd2", "mem_9fK2xQ7aLp3"]);
    expect(found.sources).toBeNull();
    expect(found.failed).toBe(false);
    expect(found.raw).toEqual(SEARCH);
  });

  it("keeps answerable null when it was not checked, and sources when sent", () => {
    const found = SearchResult.parse({ query: "q", answerable: null, sources: [{ a: 1 }] });
    expect(found.answerable).toBeNull();
    expect(found.sources).toEqual([{ a: 1 }]);
    expect(found.memories).toEqual([]);
  });

  it("is empty and failed when unavailable", () => {
    const found = SearchResult.unavailable("q");
    expect([found.query, found.failed, found.answerable, found.memories]).toEqual([
      "q",
      true,
      null,
      [],
    ]);
    expect(found.context()).toBe("");
  });
});

describe("context()", () => {
  const found = SearchResult.parse(SEARCH);

  it("is the notes, a blank line, then each memory, exactly as the other clients write it", () => {
    expect(found.context()).toBe(
      "Values are listed as stated, newest first.\n" +
        "\n" +
        "- Alice Chen · home city: Lisbon (said 2026-10-01); Berlin (said 2024-06-01)\n" +
        "- (said 2026-10-01) Alice lives in Lisbon\n" +
        "- 2026-10-01: I just moved to Lisbon from Berlin\nfor the new job at Acme.",
    );
  });

  it("has no blank line without notes", () => {
    const bare = SearchResult.parse({ ...SEARCH, notes: [] });
    expect(bare.context()).toBe([KNOWN, FACT_LINE, EXCERPT_LINE].join("\n"));
  });

  it("puts each note on its own line", () => {
    const two = SearchResult.parse({ ...SEARCH, notes: ["one", "two"], memories: [FACT] });
    expect(two.context()).toBe(`one\ntwo\n\n${FACT_LINE}`);
  });

  it("cuts at a whole memory, never past maxChars", () => {
    const head = `${NOTE}\n\n`;
    expect(found.context(head.length + KNOWN.length)).toBe(head + KNOWN);
    expect(found.context(head.length + KNOWN.length + 1 + FACT_LINE.length)).toBe(
      `${head}${KNOWN}\n${FACT_LINE}`,
    );
    expect(found.context(head.length + KNOWN.length - 1)).toBe("");
    const whole = found.context();
    for (let max = 0; max <= whole.length + 1; max++) {
      const cut = found.context(max);
      expect(cut.length).toBeLessThanOrEqual(max);
      expect(whole.startsWith(cut)).toBe(true);
    }
  });

  it("is empty when there are no memories, notes or not", () => {
    expect(SearchResult.parse({ query: "q", notes: ["n"], memories: [] }).context()).toBe("");
  });

  it("dates an excerpt only when its date is known", () => {
    const undated = SearchResult.parse({ memories: [{ ...EXCERPT, date: null }] });
    expect(undated.context()).toBe(`- ${EXCERPT.text}`);
  });
});
