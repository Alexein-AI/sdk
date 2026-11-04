/** `add`: what it makes of strings and items, its batches of 500, and their idempotency keys. */

import { describe, expect, it } from "vitest";
import { ADDED } from "./fixtures.js";
import { memory, noWaiting, ok, type Sent } from "./helpers.js";

const UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";

describe("add", () => {
  it("makes a string an item, and fills what an item leaves out", async () => {
    const { client, sent } = memory(() => ok(ADDED, 202));
    await client
      .user("dana")
      .add(["I moved to Lisbon.", { text: "Booked the hotel.", role: "assistant" }], {
        role: "user",
        session: "trip",
        wait: true,
      });
    expect(sent.last.url.pathname).toBe("/v2/memory/add");
    expect(sent.last.body).toEqual({
      items: [
        { role: "user", session: "trip", text: "I moved to Lisbon." },
        { role: "assistant", session: "trip", text: "Booked the hotel." },
      ],
      wait: true,
    });
    expect(sent.last.headers["Idempotency-Key"]).toMatch(new RegExp(`^${UUID}-0$`));
  });

  it("sends every item field, and an item's explicit null", async () => {
    const { client, sent } = memory(() => ok(ADDED));
    await client.user("dana").add(
      { text: "t", id: "i", at: "2026-10-01", about: ["project:atlas"], expires: null },
      {
        kind: "note",
        session: "s",
        role: "user",
        author: { name: "Dana", self: true },
        title: "T",
        expires: "2027-01-01",
        metadata: { k: 1 },
        redact: true,
      },
    );
    expect(sent.last.body).toEqual({
      items: [
        {
          text: "t",
          id: "i",
          at: "2026-10-01",
          about: ["project:atlas"],
          expires: null,
          kind: "note",
          session: "s",
          role: "user",
          author: { name: "Dana", self: true },
          title: "T",
          metadata: { k: 1 },
        },
      ],
      redact: true,
    });
  });

  it("reads each item's status, what was redacted, and how many wait", async () => {
    const { client } = memory(() => ok(ADDED, 202));
    const added = await client.user("dana").add(["a", "b"]);
    expect(added.items.map((i) => [i.id, i.status, i.redacted])).toEqual([
      ["msg-001", "queued", null],
      ["pref-diet", "stored", { PHONE: 1 }],
    ]);
    expect(added.ids).toEqual(["msg-001", "pref-diet"]);
    expect(added.waiting).toBe(1);
    expect(added.failed).toBe(false);
    expect(added.raw).toEqual(ADDED);
  });

  it("sends nothing for an empty list, and answers empty", async () => {
    const { client, sent } = memory();
    const added = await client.user("dana").add([]);
    expect(sent.requests).toHaveLength(0);
    expect([added.items, added.waiting, added.failed]).toEqual([[], 0, false]);
  });

  it("refuses an item without text before sending", async () => {
    const { client, sent } = memory();
    await expect(client.user("dana").add(["ok", { id: "x" } as never])).rejects.toThrow(/text/);
    expect(sent.requests).toHaveLength(0);
  });

  it("sends more than 500 items in batches, and answers as one", async () => {
    const answer = (request: Sent) => {
      const n = request.body.items.length;
      const items = Array.from({ length: n }, (_, k) => ({ id: `i${k}`, status: "queued" }));
      return ok({ items, waiting: n }, 202);
    };
    const { client, sent } = memory(answer);
    const result = await client
      .user("dana")
      .add(Array.from({ length: 1201 }, (_, k) => `fact ${k}`));
    expect(sent.requests.map((r) => r.body.items.length)).toEqual([500, 500, 201]);
    const keys = sent.requests.map((r) => r.headers["Idempotency-Key"]!);
    const call = keys[0]!.slice(0, 36);
    expect(keys).toEqual([`${call}-0`, `${call}-1`, `${call}-2`]);
    expect([result.items.length, result.waiting]).toEqual([1201, 1201]);
    expect((result.raw.items as unknown[]).length).toBe(1201);
  });

  it("uses a new key for each call", async () => {
    const { client, sent } = memory(() => ok(ADDED));
    await client.user("dana").add("one");
    await client.user("dana").add("one");
    const [first, second] = sent.requests.map((r) => r.headers["Idempotency-Key"]);
    expect(first).not.toBe(second);
  });

  it("resends the same key when a batch is retried", async () => {
    noWaiting();
    const answers = [ok({ detail: "busy" }, 503), ok(ADDED)];
    const { client, sent } = memory(() => answers.shift()!);
    await client.user("dana").add("Prefers green tea.");
    const [first, second] = sent.requests.map((r) => r.headers["Idempotency-Key"]);
    expect(sent.requests).toHaveLength(2);
    expect(first).toBe(second);
  });
});
