/** Which failures are tried again, how long each wait is, and the timeout of each attempt. */

import { describe, expect, it } from "vitest";
import {
  APIConnectionError,
  APITimeoutError,
  AuthenticationError,
  InvalidRequestError,
  Memory,
  RateLimitError,
  ServiceUnavailableError,
} from "../src/index.js";
import { SEARCH } from "./fixtures.js";
import { memory, noWaiting, ok } from "./helpers.js";

describe("retries", () => {
  it("wait as Retry-After says on a 429, then succeed", async () => {
    const waited = noWaiting();
    const answers = [ok({ detail: "slow" }, 429, { "Retry-After": "2" }), ok(SEARCH)];
    const { client, sent } = memory(() => answers.shift()!);
    const found = await client.user("dana").search("x");
    expect(found.memories).toHaveLength(3);
    expect(sent.requests).toHaveLength(2);
    expect(waited).toEqual([2000]);
  });

  it("take a fractional Retry-After, and one of exactly 60 s", async () => {
    const waited = noWaiting();
    const answers = [
      ok({}, 503, { "Retry-After": "0.5" }),
      ok({}, 503, { "Retry-After": "60" }),
      ok({}),
    ];
    await memory(() => answers.shift()!).client.me();
    expect(waited).toEqual([500, 60_000]);
  });

  it("try a 503 three times in all with backoff, then throw", async () => {
    const waited = noWaiting();
    const { client, sent } = memory(() => ok({ detail: "rebuilding" }, 503));
    await expect(client.user("dana").grep("x")).rejects.toBeInstanceOf(ServiceUnavailableError);
    expect(sent.requests).toHaveLength(3);
    expect(waited[0]).toBeGreaterThanOrEqual(375);
    expect(waited[0]).toBeLessThanOrEqual(625);
    expect(waited[1]).toBeGreaterThanOrEqual(750);
    expect(waited[1]).toBeLessThanOrEqual(1250);
  });

  it("throw at once when Retry-After is longer than 60 s", async () => {
    const waited = noWaiting();
    const { client, sent } = memory(() => ok({ detail: "later" }, 429, { "Retry-After": "61" }));
    await expect(client.user("dana").grep("x")).rejects.toBeInstanceOf(RateLimitError);
    expect(sent.requests).toHaveLength(1);
    expect(waited).toEqual([]);
  });

  it.each([400, 401, 404, 422, 500, 502, 504])("never retry a %i", async (status) => {
    noWaiting();
    const { client, sent } = memory(() => ok({ detail: "no" }, status));
    await expect(client.user("dana").grep("x")).rejects.toThrow(String(status));
    expect(sent.requests).toHaveLength(1);
  });

  it("follow maxRetries", async () => {
    noWaiting();
    const none = memory(() => ok({ detail: "busy" }, 503), { maxRetries: 0 });
    await expect(none.client.me()).rejects.toBeInstanceOf(ServiceUnavailableError);
    expect(none.sent.requests).toHaveLength(1);
    const five = memory(() => ok({ detail: "busy" }, 503), { maxRetries: 5 });
    await expect(five.client.me()).rejects.toBeInstanceOf(ServiceUnavailableError);
    expect(five.sent.requests).toHaveLength(6);
  });

  it("retry an unreachable service, then throw a connection error", async () => {
    noWaiting();
    const { client, sent } = memory(() => {
      throw new TypeError("fetch failed");
    });
    await expect(client.user("dana").grep("x")).rejects.toThrow(/could not be reached/);
    expect(sent.requests).toHaveLength(3);
  });

  it("recover from a failed connection", async () => {
    noWaiting();
    let first = true;
    const { client, sent } = memory(() => {
      if (first) {
        first = false;
        throw new TypeError("fetch failed");
      }
      return ok({ kind: "key", writes: true });
    });
    expect((await client.me()).writes).toBe(true);
    expect(sent.requests).toHaveLength(2);
  });
});

describe("the timeout", () => {
  it("gives up on an attempt that takes longer", async () => {
    const hangs: typeof fetch = (_, init) =>
      new Promise((_resolve, reject) =>
        init?.signal?.addEventListener("abort", () => reject(init.signal!.reason)),
      );
    const client = new Memory({ apiKey: "ak", fetch: hangs, timeout: 20, maxRetries: 0 });
    await expect(client.user("dana").grep("x")).rejects.toBeInstanceOf(APITimeoutError);
  });

  it("is per attempt: each gets a signal of its own", async () => {
    noWaiting();
    const signals: AbortSignal[] = [];
    const fetch: typeof globalThis.fetch = async (_, init) => {
      signals.push(init!.signal!);
      return signals.length < 3 ? ok({}, 503) : ok({});
    };
    await new Memory({ apiKey: "ak", fetch }).me();
    expect(new Set(signals).size).toBe(3);
  });

  it("is a RangeError when not a positive number", () => {
    expect(() => new Memory({ apiKey: "ak", timeout: 0 })).toThrow(RangeError);
    expect(() => new Memory({ apiKey: "ak", maxRetries: -1 })).toThrow(RangeError);
  });
});

it("a mistake is never an outage", async () => {
  const error = await memory(() => ok({ detail: "bad" }, 400))
    .client.me()
    .catch((e: unknown) => e);
  expect(error).toBeInstanceOf(InvalidRequestError);
  expect((error as InvalidRequestError).outage).toBe(false);
});

describe("request ids", () => {
  it("send one per call, kept across its retries", async () => {
    noWaiting();
    const answers = [ok({ detail: "busy" }, 503), ok(SEARCH), ok(SEARCH)];
    const { client, sent } = memory(() => answers.shift()!);
    await client.user("dana").search("x");
    await client.user("dana").search("x");
    const ids = sent.requests.map((r) => r.headers["X-Request-Id"]);
    expect(ids[0]).toMatch(/^req_[0-9a-f]{32}$/);
    expect(ids[1]).toBe(ids[0]);
    expect(ids[2]).not.toBe(ids[0]);
  });

  it("are on every error, even one whose answer carries none", async () => {
    noWaiting();
    const proxied = memory(() => new Response("Internal Server Error", { status: 500 }));
    const failed = await proxied.client
      .user("dana")
      .summary()
      .catch((e: unknown) => e);
    expect(failed).toBeInstanceOf(ServiceUnavailableError);
    expect((failed as ServiceUnavailableError).requestId).toBe(
      proxied.sent.last.headers["X-Request-Id"],
    );
    const down = memory(() => Promise.reject(new TypeError("fetch failed")), { maxRetries: 0 });
    const unreached = await down.client
      .user("dana")
      .summary()
      .catch((e: unknown) => e);
    expect(unreached).toBeInstanceOf(APIConnectionError);
    expect((unreached as APIConnectionError).requestId).toBe(
      down.sent.last.headers["X-Request-Id"],
    );
    const theirs = memory(() => ok({ detail: "no" }, 401, { "X-Request-Id": "theirs" }));
    const refused = await theirs.client.me().catch((e: unknown) => e);
    expect(refused).toBeInstanceOf(AuthenticationError);
    expect((refused as AuthenticationError).requestId).toBe("theirs");
  });
});
