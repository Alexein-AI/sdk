/** What a failed response becomes, and which ones are tried again. */

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  APIConnectionError,
  APITimeoutError,
  AuthenticationError,
  InvalidRequestError,
  Memory,
  NotFoundError,
  PermissionDeniedError,
  RateLimitError,
  ServiceUnavailableError,
  TwinMemoryError,
} from "../src/index.js";
import { memory, noWaiting, ok } from "./helpers.js";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("errors", () => {
  it.each([
    [400, InvalidRequestError],
    [401, AuthenticationError],
    [403, PermissionDeniedError],
    [404, NotFoundError],
    [413, InvalidRequestError],
    [500, TwinMemoryError],
  ] as const)("makes %i its own error with the API's detail", async (status, Kind) => {
    const { client, sent } = memory(() =>
      ok({ detail: "said why" }, status, { "X-Request-Id": "r1" }),
    );
    const error = await client
      .user("dana")
      .search("x")
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(Kind);
    expect((error as TwinMemoryError).constructor).toBe(Kind);
    expect((error as TwinMemoryError).status).toBe(status);
    expect((error as TwinMemoryError).detail).toBe("said why");
    expect((error as TwinMemoryError).requestId).toBe("r1");
    expect((error as Error).message).toContain("said why");
    expect(sent.requests).toHaveLength(1);
  });

  it("says which field a validation error is about", async () => {
    const detail = [{ loc: ["body", "query"], msg: "Field required", type: "missing" }];
    const { client } = memory(() => ok({ detail }, 422));
    await expect(client.user("dana").search("x")).rejects.toThrow(/body\.query: Field required/);
  });

  it("says what came back when the body is not JSON", async () => {
    const { client } = memory(() => new Response("Bad Gateway", { status: 502 }));
    await expect(client.user("dana").search("x")).rejects.toThrow("502: Bad Gateway");
  });
});

describe("retries", () => {
  it("waits as Retry-After says on a 429, then succeeds", async () => {
    const waited = noWaiting();
    const answers = [ok({ detail: "slow" }, 429, { "Retry-After": "1" }), ok({ hits: [] })];
    const { client, sent } = memory(() => answers.shift()!);
    await client.user("dana").search("x");
    expect(sent.requests).toHaveLength(2);
    expect(waited).toEqual([1000]);
  });

  it("tries a 503 three times in all, then throws", async () => {
    const waited = noWaiting();
    const { client, sent } = memory(() => ok({ detail: "rebuilding" }, 503));
    await expect(client.user("dana").search("x")).rejects.toBeInstanceOf(ServiceUnavailableError);
    expect(sent.requests).toHaveLength(3);
    expect(waited[0]).toBeGreaterThanOrEqual(375);
    expect(waited[0]).toBeLessThanOrEqual(625);
    expect(waited[1]).toBeGreaterThanOrEqual(750);
    expect(waited[1]).toBeLessThanOrEqual(1250);
  });

  it("throws at once when Retry-After is too long to wait", async () => {
    const waited = noWaiting();
    const { client, sent } = memory(() => ok({ detail: "later" }, 429, { "Retry-After": "600" }));
    await expect(client.user("dana").search("x")).rejects.toBeInstanceOf(RateLimitError);
    expect(sent.requests).toHaveLength(1);
    expect(waited).toEqual([]);
  });

  it("never retries with maxRetries 0", async () => {
    const { client, sent } = memory(() => ok({ detail: "busy" }, 503), { maxRetries: 0 });
    await expect(client.user("dana").search("x")).rejects.toBeInstanceOf(ServiceUnavailableError);
    expect(sent.requests).toHaveLength(1);
  });

  it("retries an unreachable service, then throws a connection error", async () => {
    noWaiting();
    const { client, sent } = memory(() => {
      throw new TypeError("fetch failed");
    });
    await expect(client.user("dana").search("x")).rejects.toThrow(/could not be reached/);
    expect(sent.requests).toHaveLength(3);
  });

  it("makes a timeout its own error", async () => {
    noWaiting();
    const { client } = memory(() => {
      throw new DOMException("The operation timed out.", "TimeoutError");
    });
    const error = await client
      .user("dana")
      .search("x")
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(APITimeoutError);
    expect(error).toBeInstanceOf(APIConnectionError);
  });

  it("resends the same Idempotency-Key when an add is retried", async () => {
    noWaiting();
    const answers = [ok({ detail: "busy" }, 503), ok({ items: [], queued: 0, pending: 0 })];
    const { client, sent } = memory(() => answers.shift()!);
    await client.user("dana").add("Prefers green tea.");
    const [first, second] = sent.requests.map((r) => r.headers["Idempotency-Key"]);
    expect(first).toBe(second);
  });

  it("gives up on an attempt after the timeout", async () => {
    noWaiting();
    const hangs: typeof fetch = (_, init) =>
      new Promise((_resolve, reject) =>
        init?.signal?.addEventListener("abort", () => reject(init.signal!.reason)),
      );
    const client = new Memory({ apiKey: "tm_test", fetch: hangs, timeout: 20, maxRetries: 0 });
    await expect(client.user("dana").search("x")).rejects.toBeInstanceOf(APITimeoutError);
  });
});
