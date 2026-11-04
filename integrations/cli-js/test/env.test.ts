/** Trying a key: what `check` asks the service, and what it makes of the answers. */

import { afterEach, describe, expect, it, vi } from "vitest";

import * as env from "../src/env.js";

const BASE = "https://memory.example.com";

interface Asked {
  route: string;
  user: string | null;
  body: Record<string, unknown> | undefined;
}

/** A service that answers by path, 404 for any path not named, and records what it is asked. */
function service(answers: Record<string, () => Response>): Asked[] {
  const asked: Asked[] = [];
  vi.stubGlobal("fetch", async (input: string | URL, init: RequestInit = {}) => {
    const path = new URL(String(input)).pathname;
    asked.push({
      route: `${init.method ?? "GET"} ${path}`,
      user: new Headers(init.headers).get("X-Twin-Account"),
      body: init.body ? JSON.parse(String(init.body)) : undefined,
    });
    return answers[path]?.() ?? Response.json({ detail: "Not Found" }, { status: 404 });
  });
  return asked;
}

const unknownKey = () => Response.json({ detail: "unknown key" }, { status: 401 });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("check", () => {
  it("asks GET /v1/me what the key is", async () => {
    const asked = service({
      "/v1/me": () =>
        Response.json({
          kind: "key",
          org: "scratch",
          project: "demo",
          key_id: "k1",
          writes: false,
        }),
    });
    expect(await env.check("tm_x", BASE)).toEqual({
      ok: true,
      writes: false,
      detail: "scratch/demo, reads only",
    });
    expect(asked.map((a) => a.route)).toEqual(["GET /v1/me"]);
  });

  it("where GET /v1/me answers 404, tries a free search instead", async () => {
    const asked = service({});
    expect(await env.check("tm_x", BASE)).toEqual({
      ok: true,
      writes: undefined,
      detail: "works; this service does not say whether it writes",
    });
    expect(asked.map((a) => a.route)).toEqual(["GET /v1/me", "POST /v1/memory/search"]);
    expect(asked[1]).toMatchObject({ user: "twinmemory-key-check", body: { fast: true } });
  });

  it("fails a key the service does not know", async () => {
    service({ "/v1/me": unknownKey });
    expect(await env.check("tm_bad", BASE)).toEqual({
      ok: false,
      writes: undefined,
      detail: "the service does not know this key",
    });
  });

  it("fails a key the search does not know, where GET /v1/me answers 404", async () => {
    service({ "/v1/memory/search": unknownKey });
    expect(await env.check("tm_bad", BASE)).toEqual({
      ok: false,
      writes: undefined,
      detail: "the service does not know this key",
    });
  });
});
