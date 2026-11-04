/**
 * `failOpen`: memory being down costs a search its answer and an add its save, not the caller its
 * turn. A wrong key or a wrong request still throws, and so does every other method.
 */

import { describe, expect, it } from "vitest";
import {
  AuthenticationError,
  InvalidRequestError,
  PermissionDeniedError,
  ServiceUnavailableError,
} from "../src/index.js";
import { type Answer, memory, noWaiting, ok, type Sent } from "./helpers.js";

const OUTAGES: [string, Answer][] = [
  ["503", () => ok({ detail: "rebuilding" }, 503)],
  ["429", () => ok({ detail: "busy" }, 429)],
  ["500", () => ok({ detail: "boom" }, 500)],
  ["502", () => new Response("Bad Gateway", { status: 502 })],
  [
    "unreachable",
    () => {
      throw new TypeError("fetch failed");
    },
  ],
  [
    "timeout",
    () => {
      throw new DOMException("The operation timed out.", "TimeoutError");
    },
  ],
];

describe("failOpen", () => {
  it.each(OUTAGES)("answers a %s empty, and logs one warning each", async (_, answer) => {
    noWaiting();
    const logged: string[] = [];
    const { client } = memory(answer, { failOpen: true, logger: (m) => logged.push(m) });
    const dana = client.user("dana");

    const found = await dana.search("Where does Dana live?");
    const saved = await dana.add("I moved to Lisbon.");

    expect(found.failed).toBe(true);
    expect(found.memories).toEqual([]);
    expect(found.context()).toBe("");
    expect(found.query).toBe("Where does Dana live?");
    expect([saved.failed, saved.items, saved.waiting]).toEqual([true, [], 0]);
    expect(logged).toHaveLength(2);
    expect(logged.every((m) => m.includes("unavailable") && m.includes("dana"))).toBe(true);
  });

  it("logs with console.warn when given no logger", async () => {
    noWaiting();
    const warned: unknown[] = [];
    const { vi } = await import("vitest");
    vi.spyOn(console, "warn").mockImplementation((m) => warned.push(m));
    await memory(() => ok({}, 503), { failOpen: true })
      .client.user("dana")
      .search("q");
    expect(warned).toHaveLength(1);
  });

  it("keeps what earlier batches saved when a later one fails", async () => {
    noWaiting();
    const answer = (sent: Sent) =>
      sent.headers["Idempotency-Key"]!.endsWith("-0")
        ? ok({ items: [{ id: "a", status: "queued" }], waiting: 1 })
        : ok({ detail: "down" }, 503);
    const { client } = memory(answer, { failOpen: true, logger: () => {} });
    const saved = await client.user("dana").add(Array.from({ length: 501 }, (_, k) => `${k}`));
    expect([saved.failed, saved.ids, saved.waiting]).toEqual([true, ["a"], 1]);
  });

  it.each([
    [401, AuthenticationError],
    [403, PermissionDeniedError],
    [400, InvalidRequestError],
    [422, InvalidRequestError],
  ] as const)("still throws a %i: a mistake, not an outage", async (status, Kind) => {
    const { client } = memory(() => ok({ detail: "no" }, status), { failOpen: true });
    await expect(client.user("dana").search("q")).rejects.toBeInstanceOf(Kind);
    await expect(client.user("dana").add("x")).rejects.toBeInstanceOf(Kind);
  });

  it("covers search and add, and nothing else", async () => {
    noWaiting();
    const { client } = memory(() => ok({ detail: "down" }, 503), { failOpen: true });
    const dana = client.user("dana");
    await expect(dana.grep("x")).rejects.toBeInstanceOf(ServiceUnavailableError);
    await expect(dana.open("mem_1")).rejects.toBeInstanceOf(ServiceUnavailableError);
    await expect(client.me()).rejects.toBeInstanceOf(ServiceUnavailableError);
  });

  it("is off by default", async () => {
    noWaiting();
    const { client } = memory(() => ok({ detail: "rebuilding" }, 503));
    expect(client.failOpen).toBe(false);
    await expect(client.user("dana").search("q")).rejects.toBeInstanceOf(ServiceUnavailableError);
  });

  it("retries before failing open", async () => {
    noWaiting();
    const { client, sent } = memory(() => ok({ detail: "busy" }, 503), {
      failOpen: true,
      logger: () => {},
    });
    expect((await client.user("dana").search("q")).failed).toBe(true);
    expect(sent.requests).toHaveLength(1 + client.maxRetries);
  });

  it("does not mark a success failed", async () => {
    const { client } = memory(() => ok({ query: "q", memories: [] }), { failOpen: true });
    expect((await client.user("dana").search("q")).failed).toBe(false);
  });
});
