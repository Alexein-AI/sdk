/** Settings from options, the environment and defaults; base URLs; app user ids; the User-Agent. */

import { describe, expect, it, vi } from "vitest";
import {
  AlexeinError,
  DEFAULT_BASE_URL,
  DEFAULT_RETRIES,
  DEFAULT_TIMEOUT_MS,
  Memory,
} from "../src/index.js";
import { memory, ok } from "./helpers.js";

describe("the key", () => {
  it("comes from the option, else ALEXEIN_API_KEY", async () => {
    vi.stubEnv("ALEXEIN_API_KEY", "ak_env");
    const { client, sent } = memory(() => ok(), { apiKey: undefined });
    await client.me();
    expect(sent.last.headers.Authorization).toBe("Bearer ak_env");
  });

  it("is required, and the error says where to get one", () => {
    vi.stubEnv("ALEXEIN_API_KEY", "");
    const make = () => new Memory();
    expect(make).toThrow(AlexeinError);
    expect(make).toThrow(/ALEXEIN_API_KEY/);
    expect(make).toThrow(/API keys/);
  });

  it("is looked for only where there is a process.env", () => {
    vi.stubGlobal("process", undefined);
    expect(() => new Memory()).toThrow(/ALEXEIN_API_KEY/);
    expect(new Memory({ apiKey: "ak" }).baseUrl).toBe(DEFAULT_BASE_URL);
  });
});

describe("the base URL", () => {
  it("defaults to the hosted API, else ALEXEIN_API_URL", () => {
    vi.stubEnv("ALEXEIN_API_URL", "");
    expect(new Memory({ apiKey: "ak" }).baseUrl).toBe("https://api.alexein.ai");
    vi.stubEnv("ALEXEIN_API_URL", "http://localhost:8210");
    expect(new Memory({ apiKey: "ak" }).baseUrl).toBe("http://localhost:8210");
    expect(new Memory({ apiKey: "ak", baseUrl: "https://eu.example" }).baseUrl).toBe(
      "https://eu.example",
    );
  });

  it.each([
    "http://localhost:8210",
    "http://localhost:8210/",
    "http://localhost:8210/v2",
    "http://localhost:8210/v2/",
    " http://localhost:8210// ",
  ])("means the same host given as %j", async (given) => {
    const { client, sent } = memory(() => ok(), { baseUrl: given });
    expect(client.baseUrl).toBe("http://localhost:8210");
    await client.user("dana").summary();
    expect(String(sent.last.url)).toBe("http://localhost:8210/v2/memory/summary");
  });

  it("keeps a path before /v2", () => {
    expect(new Memory({ apiKey: "ak", baseUrl: "https://gw.example/alexein/v2" }).baseUrl).toBe(
      "https://gw.example/alexein",
    );
  });
});

describe("defaults", () => {
  it("are a 60 s timeout, 2 retries, failing closed, no integration", () => {
    const client = new Memory({ apiKey: "ak" });
    expect([client.timeout, client.maxRetries, client.failOpen, client.integration]).toEqual([
      60_000,
      2,
      false,
      null,
    ]);
    expect([DEFAULT_TIMEOUT_MS, DEFAULT_RETRIES]).toEqual([60_000, 2]);
  });

  it("send with the fetch given, else the global one", async () => {
    const global = vi.fn(async () => ok({ kind: "key" }));
    vi.stubGlobal("fetch", global);
    await new Memory({ apiKey: "ak" }).me();
    expect(global).toHaveBeenCalledOnce();
  });
});

describe("an app user id", () => {
  it.each(["dana", "user_42", "a", "A.b-c_d", "9lives", "x".repeat(35)])("takes %j", (id) => {
    expect(memory().client.user(id).id).toBe(id);
  });

  it.each(["", "-dana", ".dana", "_dana", "dana smith", "dana/1", "dané", "x".repeat(36)])(
    "refuses %j with a RangeError, before a round trip",
    (bad) => {
      const { client, sent } = memory();
      expect(() => client.user(bad)).toThrow(RangeError);
      expect(() => client.user(bad)).toThrow(/app user id/);
      expect(sent.requests).toHaveLength(0);
    },
  );
});

describe("integration", () => {
  it.each(["langgraph", "openai-agents", "my.app_2"])("takes %j", (word) => {
    expect(new Memory({ apiKey: "ak", integration: word }).integration).toBe(word);
  });

  it.each(["Lang Graph", "", "x".repeat(33), "a/b", "-x"])(
    "must be one short word, not %j",
    (bad) => {
      expect(() => new Memory({ apiKey: "ak", integration: bad })).toThrow(/integration/);
    },
  );

  it("is left out of a browser's request, which may not set a User-Agent", async () => {
    vi.stubGlobal("document", {});
    vi.resetModules();
    const { Memory: InPage } = await import("../src/index.js");
    const requests: RequestInit[] = [];
    const fetch: typeof globalThis.fetch = async (_, init) => {
      requests.push(init!);
      return ok({});
    };
    await new InPage({ apiKey: "ak", fetch }).me();
    expect(Object.keys(requests[0]!.headers as object)).not.toContain("User-Agent");
  });
});

it("close() is there, and does nothing", () => {
  expect(() => new Memory({ apiKey: "ak" }).close()).not.toThrow();
});
