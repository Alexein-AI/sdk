/** What a failed answer becomes: one class per thing a caller would handle differently. */

import { describe, expect, it } from "vitest";
import {
  APIConnectionError,
  APITimeoutError,
  AlexeinError,
  AuthenticationError,
  InvalidRequestError,
  NotFoundError,
  PermissionDeniedError,
  RateLimitError,
  ServiceUnavailableError,
} from "../src/index.js";
import { memory, noWaiting, ok, rejection } from "./helpers.js";

describe("an answer that is an error", () => {
  it.each([
    [400, InvalidRequestError, false],
    [401, AuthenticationError, false],
    [403, PermissionDeniedError, false],
    [404, NotFoundError, false],
    [409, InvalidRequestError, false],
    [413, InvalidRequestError, false],
    [422, InvalidRequestError, false],
    [429, RateLimitError, true],
    [500, ServiceUnavailableError, true],
    [502, ServiceUnavailableError, true],
    [503, ServiceUnavailableError, true],
  ] as const)("%i is a %o", async (status, Kind, outage) => {
    noWaiting();
    const { client } = memory(() => ok({ detail: "said why" }, status, { "X-Request-Id": "r1" }), {
      maxRetries: 0,
    });
    const error = await rejection(client.user("dana").open("mem_1"));
    expect(error).toBeInstanceOf(AlexeinError);
    expect(error.constructor).toBe(Kind);
    expect(error.name).toBe(Kind.name);
    expect(error.status).toBe(status);
    expect(error.detail).toBe("said why");
    expect(error.errors).toEqual([]);
    expect(error.requestId).toBe("r1");
    expect(error.outage).toBe(outage);
    expect(error.message).toBe(`${status}: said why`);
  });

  it("names each field a 422 got wrong", async () => {
    const body = {
      detail:
        "`query` must not be empty. See https://docs.alexein.ai/api/search for what this route takes.",
      errors: [
        { field: "query", message: "`query` must not be empty" },
        { field: "items[0].text", message: "`items[0].text` is required" },
      ],
    };
    const error = await rejection(
      memory(() => ok(body, 422))
        .client.user("dana")
        .search("x"),
    );
    expect(error).toBeInstanceOf(InvalidRequestError);
    expect(error.detail).toBe(body.detail);
    expect(error.errors).toEqual(body.errors);
  });

  it("reads a validator's own list too", async () => {
    const detail = [{ loc: ["body", "query"], msg: "Field required", type: "missing" }];
    const error = await rejection(
      memory(() => ok({ detail }, 422))
        .client.user("dana")
        .grep("x"),
    );
    expect(error.errors).toEqual([{ field: "query", message: "Field required" }]);
    expect(error.detail).toBe("query: Field required");
  });

  it("says what came back when the body is not JSON", async () => {
    const { client } = memory(() => new Response("Bad Gateway", { status: 502 }), {
      maxRetries: 0,
    });
    const error = await rejection(client.user("dana").grep("x"));
    expect(error).toBeInstanceOf(ServiceUnavailableError);
    expect(error.message).toBe("502: Bad Gateway");
    expect(error.requestId).toBeNull();
  });

  it("is an AlexeinError when a success is not JSON", async () => {
    const error = await rejection(
      memory(() => new Response("<html>", { status: 200 })).client.me(),
    );
    expect(error).toBeInstanceOf(AlexeinError);
    expect(error.status).toBe(200);
  });
});

describe("no answer", () => {
  it("is a connection error with no status, an outage", async () => {
    noWaiting();
    const { client } = memory(() => {
      throw new TypeError("fetch failed");
    });
    const error = await rejection(client.user("dana").grep("x"));
    expect(error).toBeInstanceOf(APIConnectionError);
    expect(error).not.toBeInstanceOf(APITimeoutError);
    expect([error.status, error.outage, error.requestId]).toEqual([null, true, null]);
    expect(error.message).toMatch(/could not be reached: fetch failed/);
    expect(error.cause).toBeInstanceOf(TypeError);
  });

  it("is a timeout, a kind of connection error", async () => {
    noWaiting();
    const { client } = memory(() => {
      throw new DOMException("The operation timed out.", "TimeoutError");
    });
    const error = await rejection(client.user("dana").grep("x"));
    expect(error).toBeInstanceOf(APITimeoutError);
    expect(error).toBeInstanceOf(APIConnectionError);
    expect(error.outage).toBe(true);
  });
});
