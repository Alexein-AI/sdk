/** The request each method sends: method, path, headers and body, with unset fields left out. */

import { describe, expect, it } from "vitest";
import { VERSION } from "../src/index.js";
import { memory } from "./helpers.js";

describe("headers", () => {
  it("sends the key, the app user, the client and JSON", async () => {
    const { client, sent } = memory();
    await client.user("dana").search("Where does Dana live?");
    const request = sent.last;
    expect(request.method).toBe("POST");
    expect(String(request.url)).toBe("https://api.alexein.ai/v2/memory/search");
    expect(request.headers).toEqual({
      Authorization: "Bearer ak_test",
      "User-Agent": `alexein-js/${VERSION}`,
      "X-Alexein-User": "dana",
      "X-Request-Id": expect.stringMatching(/^req_[0-9a-f]{32}$/),
      "Content-Type": "application/json",
    });
  });

  it("names no app user for me() and users()", async () => {
    const { client, sent } = memory();
    await client.me();
    expect(sent.last.method).toBe("GET");
    expect(sent.last.url.pathname).toBe("/v2/me");
    expect(sent.last.body).toBeUndefined();
    expect(sent.last.headers["X-Alexein-User"]).toBeUndefined();
    expect(sent.last.headers["Content-Type"]).toBeUndefined();
    await client.users();
    expect(sent.last.url.pathname).toBe("/v2/memory/users");
    expect(sent.last.headers["X-Alexein-User"]).toBeUndefined();
    expect(sent.last.body).toEqual({});
  });

  it("names the integration in the User-Agent", async () => {
    const { client, sent } = memory(undefined, { integration: "langgraph" });
    await client.me();
    expect(sent.last.headers["User-Agent"]).toBe(`alexein-js/${VERSION} langgraph`);
  });
});

describe("bodies", () => {
  it("send only what was set", async () => {
    const { client, sent } = memory();
    const dana = client.user("dana");
    const calls: [() => Promise<unknown>, string, unknown][] = [
      [() => dana.search("q"), "search", { query: "q" }],
      [() => dana.grep("p"), "grep", { pattern: "p" }],
      [() => dana.latest(), "latest", {}],
      [() => dana.around("mem_1"), "around", { ref: "mem_1" }],
      [() => dana.open("mem_1"), "open", { ref: "mem_1" }],
      [() => dana.history("Dana"), "history", { subject: "Dana" }],
      [() => dana.summary(), "summary", {}],
      [() => dana.facts(), "facts", {}],
      [() => dana.openItems(), "open_items", {}],
      [() => dana.sources(), "sources", {}],
      [() => dana.items(), "items", {}],
      [() => dana.item("diet"), "item", { id: "diet" }],
      [() => dana.status(["diet"]), "status", { items: ["diet"] }],
      [() => dana.forget({ items: ["diet"] }), "forget", { items: ["diet"] }],
      [() => dana.correct("mem_1"), "correct", { ref: "mem_1" }],
      [() => dana.versions("diet"), "versions", { id: "diet" }],
      [() => dana.export(), "export", {}],
      [() => dana.delete(), "users/delete", {}],
    ];
    for (const [call, route, body] of calls) {
      await call();
      expect(sent.last.url.pathname, route).toBe(`/v2/memory/${route}`);
      expect(sent.last.method, route).toBe("POST");
      expect(sent.last.headers["X-Alexein-User"], route).toBe("dana");
      expect(sent.last.body, route).toEqual(body);
    }
  });

  it("send every option, in the API's names", async () => {
    const { client, sent } = memory();
    const dana = client.user("dana");
    const filters = { metadata: { priority: { gte: 3 } } };
    const calls: [() => Promise<unknown>, unknown][] = [
      [
        () =>
          dana.search("q", {
            before: "2026-12-01",
            after: "2026-01-01",
            filters,
            provider: "github",
            source: "items",
            kind: "issue",
            fast: true,
          }),
        {
          query: "q",
          before: "2026-12-01",
          after: "2026-01-01",
          filters,
          provider: "github",
          source: "items",
          kind: ["issue"],
          fast: true,
        },
      ],
      [
        () => dana.grep("p", { limit: 5, provider: "slack", source: "s", kind: ["message"] }),
        { pattern: "p", limit: 5, provider: "slack", source: "s", kind: ["message"] },
      ],
      [
        () =>
          dana.latest({ k: 3, place: "eng", after: "2026-01-01", before: "2026-02-01", filters }),
        { k: 3, place: "eng", after: "2026-01-01", before: "2026-02-01", filters },
      ],
      [() => dana.around("mem_1", { width: 4 }), { ref: "mem_1", width: 4 }],
      [
        () => dana.history("Dana", { attribute: "home_city" }),
        { subject: "Dana", attribute: "home_city" },
      ],
      [() => dana.facts({ limit: 5, cursor: "c1" }), { limit: 5, cursor: "c1" }],
      [
        () =>
          dana.openItems({
            kind: ["issue", "pull_request"],
            provider: "github",
            place: "acme/api",
            mine: false,
            withinDays: 30,
            limit: 10,
          }),
        {
          kind: ["issue", "pull_request"],
          provider: "github",
          place: "acme/api",
          mine: false,
          within_days: 30,
          limit: 10,
        },
      ],
      [
        () => dana.items({ limit: 10, cursor: "c2", filters }),
        { limit: 10, cursor: "c2", filters },
      ],
      [
        () => dana.forget({ items: ["a"], sessions: ["s"], refs: ["mem_1"] }),
        { items: ["a"], sessions: ["s"], refs: ["mem_1"] },
      ],
      [() => dana.correct("mem_1", "Porto"), { ref: "mem_1", replacement: "Porto" }],
      [() => dana.export({ limit: 100, cursor: "c3" }), { limit: 100, cursor: "c3" }],
      [() => client.users({ limit: 10, cursor: "u" }), { limit: 10, cursor: "u" }],
    ];
    for (const [call, body] of calls) {
      await call();
      expect(sent.last.body, sent.last.url.pathname).toEqual(body);
    }
  });

  it("leave out a forget's empty lists, and refuse one naming nothing before sending", async () => {
    const { client, sent } = memory();
    const dana = client.user("dana");
    await dana.forget({ items: [], sessions: ["s"] });
    expect(sent.last.body).toEqual({ sessions: ["s"] });
    const before = sent.requests.length;
    await expect(dana.forget({})).rejects.toBeInstanceOf(RangeError);
    await expect(dana.forget({ items: [], refs: [] })).rejects.toThrow(/at least one/);
    expect(sent.requests).toHaveLength(before);
  });
});
