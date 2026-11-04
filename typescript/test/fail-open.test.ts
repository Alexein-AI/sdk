/**
 * `failOpen`: memory being down costs a search its answer and an add its save, not the caller its
 * turn. A wrong key or a wrong request still throws. And `integration`, in the User-Agent.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  AuthenticationError,
  InvalidRequestError,
  Memory,
  ServiceUnavailableError,
  TwinMemoryError,
  VERSION,
} from "../src/index.js";
import { type Answer, memory, noWaiting, ok } from "./helpers.js";

afterEach(() => {
  vi.restoreAllMocks();
});

const unreachable: Answer = () => {
  throw new TypeError("fetch failed");
};
const timedOut: Answer = () => {
  throw new DOMException("The operation timed out.", "TimeoutError");
};

const OUTAGES: [string, Answer][] = [
  ["503", () => ok({ detail: "rebuilding" }, 503)],
  ["429", () => ok({ detail: "busy" }, 429)],
  ["500", () => ok({ detail: "boom" }, 500)],
  ["502", () => ok({ detail: "bad gateway" }, 502)],
  ["unreachable", unreachable],
  ["timeout", timedOut],
];

describe("failOpen", () => {
  it.each(OUTAGES)("answers a %s empty, and logs it", async (_, answer) => {
    noWaiting();
    const logged: string[] = [];
    const { client } = memory(answer, { failOpen: true, logger: (m) => logged.push(m) });
    const dana = client.user("dana");

    const found = await dana.search("Where does Dana live?");
    const saved = await dana.add("I moved to Lisbon.");

    expect(found.failed).toBe(true);
    expect(found.found).toBe(0);
    expect(found.context()).toBe("");
    expect(found.query).toBe("Where does Dana live?");
    expect(saved.failed).toBe(true);
    expect(saved.items).toEqual([]);
    expect(logged.filter((m) => m.includes("unavailable"))).toHaveLength(2);
  });

  it.each([
    [401, AuthenticationError],
    [400, InvalidRequestError],
  ] as const)("still throws a %i: a mistake, not an outage", async (status, Kind) => {
    const { client } = memory(() => ok({ detail: "no" }, status), { failOpen: true });
    await expect(client.user("dana").search("q")).rejects.toBeInstanceOf(Kind);
    await expect(client.user("dana").add("x")).rejects.toBeInstanceOf(Kind);
  });

  it("is off by default", async () => {
    noWaiting();
    const { client } = memory(() => ok({ detail: "rebuilding" }, 503));
    await expect(client.user("dana").search("q")).rejects.toBeInstanceOf(ServiceUnavailableError);
  });

  it("retries a 503 before failing open", async () => {
    noWaiting();
    const { client, sent } = memory(() => ok({ detail: "busy" }, 503), {
      failOpen: true,
      logger: () => {},
    });
    expect((await client.user("dana").search("q")).failed).toBe(true);
    expect(sent.requests).toHaveLength(1 + client.maxRetries);
  });

  it("does not mark a success failed", async () => {
    const { client } = memory(() => ok({ query: "q", found: 0 }), { failOpen: true });
    expect((await client.user("dana").search("q")).failed).toBe(false);
  });

  it("says on every error whether it is an outage", async () => {
    noWaiting();
    const down = memory(unreachable).client;
    const outage = await down
      .user("dana")
      .search("q")
      .then(
        () => undefined,
        (e: TwinMemoryError) => e,
      );
    expect(outage?.outage).toBe(true);
    const denied = memory(() => ok({ detail: "no" }, 401)).client;
    const mistake = await denied
      .user("dana")
      .search("q")
      .then(
        () => undefined,
        (e: TwinMemoryError) => e,
      );
    expect(mistake?.outage).toBe(false);
  });
});

describe("integration", () => {
  it("names itself in the User-Agent", async () => {
    const { client, sent } = memory(() => ok({ query: "q" }), { integration: "langgraph" });
    await client.user("dana").search("q");
    expect(sent.last.headers["User-Agent"]).toBe(`twinmemory-js/${VERSION} langgraph`);
  });

  it.each(["Lang Graph", "", "x".repeat(40), "a/b"])("must be one short word, not %j", (bad) => {
    expect(() => new Memory({ apiKey: "tm_test", integration: bad })).toThrow(/integration/);
  });
});
