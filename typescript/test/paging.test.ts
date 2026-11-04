/** The `iter*` methods: every entry of every page, following `next` until it is null. */

import { describe, expect, it } from "vitest";
import { type Sent, memory, ok } from "./helpers.js";

/** Three pages: `a`, `b` then `c`, the key holding each page's entries. */
function threePages(key: string, entry: (name: string) => unknown) {
  return (sent: Sent) => {
    const at: string | undefined = sent.body.cursor;
    const [names, next] =
      at === undefined ? [["a1", "a2"], "p2"] : at === "p2" ? [["b1"], "p3"] : [["c1"], null];
    return ok({ [key]: names.map(entry), next });
  };
}

async function all<T>(iterable: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const value of iterable) out.push(value);
  return out;
}

describe("iteration", () => {
  it("iterFacts follows every page", async () => {
    const { client, sent } = memory(
      threePages("facts", (ref) => ({ type: "fact", ref, text: ref, source: null })),
    );
    const facts = await all(client.user("dana").iterFacts({ limit: 2 }));
    expect(facts.map((f) => f.ref)).toEqual(["a1", "a2", "b1", "c1"]);
    expect(sent.requests.map((r) => r.body)).toEqual([
      { limit: 2 },
      { limit: 2, cursor: "p2" },
      { limit: 2, cursor: "p3" },
    ]);
  });

  it("iterItems keeps its filters on every page", async () => {
    const filters = { author: "u_42" };
    const { client, sent } = memory(
      threePages("items", (id) => ({ id, text: id, status: "stored" })),
    );
    const items = await all(client.user("dana").iterItems({ filters }));
    expect(items.map((i) => i.id)).toEqual(["a1", "a2", "b1", "c1"]);
    expect(sent.requests.every((r) => r.body.filters.author === "u_42")).toBe(true);
  });

  it("iterExport yields the records", async () => {
    const { client } = memory(threePages("records", (id) => ({ type: "item", id })));
    const records = await all(client.user("dana").iterExport());
    expect(records.map((r) => r.id)).toEqual(["a1", "a2", "b1", "c1"]);
  });

  it("iterUsers names no app user", async () => {
    const { client, sent } = memory(threePages("users", (user) => ({ user, items: 1, facts: 0 })));
    const users = await all(client.iterUsers({ limit: 2 }));
    expect(users.map((u) => u.user)).toEqual(["a1", "a2", "b1", "c1"]);
    expect(sent.requests.every((r) => r.headers["X-Alexein-User"] === undefined)).toBe(true);
    expect(sent.routes).toEqual(["users", "users", "users"]);
  });

  it("asks for no page until it is iterated, and stops when the caller does", async () => {
    const { client, sent } = memory(threePages("facts", (ref) => ({ type: "fact", ref })));
    const facts = client.user("dana").iterFacts();
    expect(sent.requests).toHaveLength(0);
    for await (const fact of facts) {
      expect(fact.ref).toBe("a1");
      break;
    }
    expect(sent.requests).toHaveLength(1);
  });

  it("ends on a page with no next", async () => {
    const { client, sent } = memory(() => ok({ facts: [], next: null }));
    expect(await all(client.user("dana").iterFacts())).toEqual([]);
    expect(sent.requests).toHaveLength(1);
  });
});
