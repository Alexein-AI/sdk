/** What each method sends, and what it makes of the answer. */

import { afterEach, describe, expect, it, vi } from "vitest";
import { Memory, SearchResult, TwinMemoryError, VERSION } from "../src/index.js";
import { memory, ok, type Sent } from "./helpers.js";

const SEARCHED = {
  query: "Where does Dana live?",
  found: 1,
  known: ["Dana lives in Lisbon (since 2026-10-01)."],
  facts: [
    {
      path: "records/x.md",
      id: "th_1#r1",
      thread: "th_1",
      source: "passages/memory/messages/th_1/p_0001.md",
      text: "2026-10-01: Dana moved to Lisbon for a job at Acme.",
    },
  ],
  hits: [
    {
      path: "passages/memory/messages/th_1/p_0001.md",
      id: "th_1/p_0001",
      thread: "th_1",
      text: "**Dana** 00:00 · I moved to Lisbon\nfor the job at Acme.",
    },
  ],
  held: true,
  filtered: true,
};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("Memory", () => {
  it("sends the key, the end user, and who is calling", async () => {
    const { client, sent } = memory(() => ok(SEARCHED));
    await client.user("dana").search("Where does Dana live?");
    const request = sent.last;
    expect(request.method).toBe("POST");
    expect(String(request.url)).toBe("https://api.alexein.ai/v1/memory/search");
    expect(request.headers.Authorization).toBe("Bearer tm_test");
    expect(request.headers["X-Twin-Account"]).toBe("dana");
    expect(request.headers["User-Agent"]).toBe(`twinmemory-js/${VERSION}`);
    expect(sent.body()).toEqual({ query: "Where does Dana live?", fast: false });
  });

  it("names no end user for me()", async () => {
    const answer = { kind: "key", org: "o1", project: "prod", key_id: "key_1", writes: true };
    const { client, sent } = memory(() => ok(answer));
    const me = await client.me();
    expect([me.kind, me.org, me.project, me.keyId, me.writes]).toEqual([
      "key",
      "o1",
      "prod",
      "key_1",
      true,
    ]);
    expect(sent.last.method).toBe("GET");
    expect(sent.last.url.pathname).toBe("/v1/me");
    expect(sent.last.headers["X-Twin-Account"]).toBeUndefined();
  });

  it("takes the key and base URL from the environment", () => {
    vi.stubEnv("TWIN_MEMORY_API_KEY", "");
    vi.stubEnv("TWIN_MEMORY_BASE_URL", "");
    expect(() => new Memory()).toThrow(/TWIN_MEMORY_API_KEY/);
    vi.stubEnv("TWIN_MEMORY_API_KEY", "tm_env");
    vi.stubEnv("TWIN_MEMORY_BASE_URL", "http://localhost:8210/");
    expect(new Memory().baseUrl).toBe("http://localhost:8210");
  });

  it.each(["", "-dana", "dana smith", "dana/1", "x".repeat(65)])(
    "refuses the end user id %j before a round trip",
    (bad) => {
      const { client, sent } = memory(() => ok());
      expect(() => client.user(bad)).toThrow(/end user id/);
      expect(sent.requests).toHaveLength(0);
    },
  );
});

describe("add", () => {
  it("makes a string an item, and fills what an item leaves out", async () => {
    const { client, sent } = memory(() => ok({ items: [], queued: 0, pending: 0 }));
    await client
      .user("dana")
      .add(["I moved to Lisbon.", { text: "Booked the hotel.", role: "assistant" }], {
        role: "user",
        session: "trip",
        wait: true,
      });
    expect(sent.body()).toEqual({
      items: [
        { role: "user", session: "trip", text: "I moved to Lisbon." },
        { role: "assistant", session: "trip", text: "Booked the hotel." },
      ],
      wait: true,
    });
    expect(sent.last.headers["Idempotency-Key"]!.length).toBeGreaterThan(16);
  });

  it("reads each item's id, event id and whether it has landed", async () => {
    const answer = {
      items: [{ id: "diet", event_id: "ev_1", landed: true }],
      queued: 1,
      pending: 0,
    };
    const { client } = memory(() => ok(answer));
    const added = await client
      .user("dana")
      .add({ id: "diet", text: "Vegetarian." }, { wait: true });
    expect(added.items).toEqual([{ id: "diet", eventId: "ev_1", landed: true }]);
    expect(added.raw).toEqual(answer);
  });

  it("refuses an item without text, and an empty add, before sending", async () => {
    const { client, sent } = memory(() => ok());
    await expect(client.user("dana").add([{ id: "x" } as never])).rejects.toThrow(/text/);
    await expect(client.user("dana").add([])).rejects.toThrow(/at least one/);
    expect(sent.requests).toHaveLength(0);
  });

  it("sends a long add in batches of 500, and answers as one", async () => {
    const answer = (request: Sent) => {
      const n = (request.body as { items: unknown[] }).items.length;
      const items = Array.from({ length: n }, (_, k) => ({ id: `i${k}`, event_id: `ev_${k}` }));
      return ok({ items, queued: n, pending: n }, 202);
    };
    const { client, sent } = memory(answer);
    const result = await client
      .user("dana")
      .add(Array.from({ length: 1201 }, (_, k) => `fact ${k}`));
    expect(sent.requests.map((r) => (r.body as { items: unknown[] }).items.length)).toEqual([
      500, 500, 201,
    ]);
    const keys = sent.requests.map((r) => r.headers["Idempotency-Key"]!);
    expect(new Set(keys).size).toBe(3);
    expect(new Set(keys.map((k) => k.slice(0, k.lastIndexOf("-")))).size).toBe(1);
    expect([result.items.length, result.queued, result.pending]).toEqual([1201, 1201, 1201]);
  });
});

describe("search", () => {
  it("reads the answer into typed parts", async () => {
    const { client } = memory(() => ok(SEARCHED));
    const result = await client
      .user("dana")
      .search("Where does Dana live?", { fast: true, after: "2026-01-01" });
    expect(result.known).toEqual(["Dana lives in Lisbon (since 2026-10-01)."]);
    expect(result.facts[0]!.source).toBe("passages/memory/messages/th_1/p_0001.md");
    expect(result.hits[0]!.thread).toBe("th_1");
    expect(result.held).toBe(true);
    expect(result.filtered).toBe(true);
    expect(result.failed).toBe(false);
    expect(result.raw).toEqual(SEARCHED);
  });

  it("puts known lines, then facts, then passages in context(), whole entries only", () => {
    const result = SearchResult.parse(SEARCHED);
    expect(result.context()).toBe(
      "What is known:\n- Dana lives in Lisbon (since 2026-10-01).\n\n" +
        "Facts:\n- 2026-10-01: Dana moved to Lisbon for a job at Acme.\n\n" +
        "Passages:\n- **Dana** 00:00 · I moved to Lisbon for the job at Acme.",
    );
    expect(result.context(60)).toBe("What is known:\n- Dana lives in Lisbon (since 2026-10-01).");
    expect(SearchResult.parse({ hits: [] }).context()).toBe("");
  });
});

describe("every other method", () => {
  it("reaches its route with its fields", async () => {
    const { client, sent } = memory(() => ok());
    const dana = client.user("dana");
    const calls: [() => Promise<unknown>, string, unknown][] = [
      [() => dana.grep("Lisbon", { limit: 5 }), "grep", { pattern: "Lisbon", limit: 5 }],
      [() => dana.read("a/b.md"), "read", { path: "a/b.md" }],
      [() => dana.ls(), "ls", { path: "" }],
      [() => dana.around("th_1/p_0001"), "around", { passage_id: "th_1/p_0001", width: 2 }],
      [
        () => dana.history("Dana", { attribute: "city" }),
        "history",
        { subject: "Dana", attribute: "city" },
      ],
      [() => dana.latest({ k: 3 }), "latest", { k: 3, place: "" }],
      [() => dana.overview(), "overview", {}],
      [() => dana.forget({ items: ["diet"] }), "forget", { items: ["diet"] }],
      [
        () => dana.correct("th_1#r1", "Porto"),
        "correct",
        { record_id: "th_1#r1", replacement: "Porto" },
      ],
      [() => dana.versions("diet"), "versions", { id: "diet" }],
      [() => dana.status(["diet"]), "status", { ids: ["diet"] }],
      [() => dana.lineage("diet"), "lineage", { id: "diet" }],
    ];
    for (const [call, route, body] of calls) {
      await call();
      expect(sent.last.url.pathname, route).toBe(`/v1/memory/${route}`);
      expect(sent.body(), route).toEqual(body);
    }
  });

  it("refuses a forget that names nothing", () => {
    const { client } = memory(() => ok());
    expect(() => client.user("dana").forget({})).toThrow(/at least one/);
  });

  it("reads each table's before and after from a receipt", async () => {
    const receipt = { events: 1, tables: { events: { before: 3, after: 2 } } };
    const { client } = memory(() => ok(receipt));
    const got = await client.user("dana").forget({ items: ["diet"] });
    expect(got.events).toBe(1);
    expect(got.tables.events!.after).toBe(2);
    expect(got.raw).toEqual(receipt);
  });

  it("reads status phases", async () => {
    const { client } = memory(() => ok({ phases: { diet: "landed" } }));
    expect(await client.user("dana").status(["diet"])).toEqual({ diet: "landed" });
  });
});

it("exports one error class every error is", () => {
  expect(new TwinMemoryError("x")).toBeInstanceOf(Error);
});
