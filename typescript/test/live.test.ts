/**
 * The quickstart against a running service, end to end. Skipped unless ALEXEIN_API_KEY is set;
 * ALEXEIN_API_URL defaults to a local stack, http://localhost:8210.
 *
 * Free: searches are `fast`, so no model is asked, and the app user made here is erased at the
 * end. The questions share words with what they look for, so a service with no embedding model
 * finds it too.
 */

import { describe, expect, it } from "vitest";
import { Memory } from "../src/index.js";

const key = process.env.ALEXEIN_API_KEY;

describe.skipIf(!key)("a running service", () => {
  it("adds, searches, opens, versions and forgets", { timeout: 120_000 }, async () => {
    const memory = new Memory({ baseUrl: process.env.ALEXEIN_API_URL || "http://localhost:8210" });
    const me = await memory.me();
    expect(me.writes, "the live test needs a key that writes").toBe(true);
    const user = memory.user(`sdk-js-${crypto.randomUUID().slice(0, 8)}`);
    try {
      const empty = await user.search("anything", { fast: true });
      expect(empty.memories).toEqual([]);

      const added = await user.add(
        [
          { id: "diet", kind: "note", text: "Dana is vegetarian, allergic to peanuts." },
          { text: "I moved to Lisbon for the job at Acme.", role: "user" },
        ],
        { session: "onboarding", wait: true },
      );
      expect(added.items).toHaveLength(2);
      expect(added.waiting).toBe(0);

      const found = await user.search("Which city did I take the job at Acme in?", { fast: true });
      expect(found.context(), JSON.stringify(found.raw)).toContain("Lisbon");
      const ref = found.excerpts[0]?.ref;
      if (ref) expect((await user.open(ref)).memory.text).toContain("Lisbon");

      expect((await user.grep("peanuts")).memories.length).toBeGreaterThan(0);
      expect(["stored", "processed"]).toContain((await user.status(["diet"])).byId.diet);
      expect((await user.item("diet"))?.text).toContain("vegetarian");
      expect((await user.versions("diet")).state).toBe("live");

      const forgotten = await user.forget({ items: ["diet"] });
      expect(forgotten.erased.items).toBeGreaterThanOrEqual(1);
      expect((await user.versions("diet")).state).toBe("forgotten");
    } finally {
      await user.delete();
    }
  });
});
