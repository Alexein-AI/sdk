/**
 * Against a running service, end to end. Skipped unless TWIN_MEMORY_LIVE=1, with
 * TWIN_MEMORY_API_KEY and TWIN_MEMORY_BASE_URL set (a local stack: http://localhost:8210).
 *
 * Free: searches are `fast`, so no model is asked, and what was added is erased at the end. The
 * questions share words with what they look for, so a service with no embedding model finds it too.
 */

import { describe, expect, it } from "vitest";
import { Memory, NotFoundError } from "../src/index.js";

const live = process.env.TWIN_MEMORY_LIVE === "1";

describe.skipIf(!live)("a running service", () => {
  it("adds, searches, versions and forgets", async () => {
    const memory = new Memory();
    const me = await memory.me();
    expect(me.writes, "the live test needs a key that writes").toBe(true);
    const user = memory.user(`sdk-live-${crypto.randomUUID().slice(0, 8)}`);
    await expect(user.search("anything", { fast: true })).rejects.toBeInstanceOf(NotFoundError);

    const added = await user.add(
      [
        { id: "diet", kind: "note", text: "Dana is vegetarian, allergic to peanuts." },
        { text: "I moved to Lisbon for the job at Acme.", role: "user" },
      ],
      { session: "onboarding", wait: true },
    );
    expect(added.pending).toBe(0);
    expect(added.items).toHaveLength(2);

    const found = await user.search("Which city did I take the job at Acme in?", { fast: true });
    expect(found.filtered).toBe(false);
    expect(
      found.hits.some((h) => h.text.includes("Lisbon")),
      found.context(),
    ).toBe(true);
    expect(["landed", "read", "folded"]).toContain((await user.status(["diet"])).diet);
    expect((await user.versions("diet")).state).toBe("live");

    const receipt = await user.forget({ items: ["diet"], sessions: ["onboarding"] });
    expect(receipt.events).toBeGreaterThanOrEqual(1);
    expect((await user.versions("diet")).state).toBe("forgotten");
    expect((await user.grep("peanuts")).matches.some((m) => m.text.includes("peanuts"))).toBe(
      false,
    );
  });
});
