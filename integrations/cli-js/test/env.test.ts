/** The key: what `check` asks the API, what it makes of the answers, and where a key is found. */

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import * as env from "../src/env.js";

const BASE = "https://memory.example.com";

interface Asked {
  route: string;
  headers: Headers;
}

/** An API that answers `GET /v2/me` with `me`, and records what it is asked. */
function service(me: () => Response): Asked[] {
  const asked: Asked[] = [];
  vi.stubGlobal("fetch", async (input: string | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    asked.push({
      route: `${init.method ?? "GET"} ${url.origin}${url.pathname}`,
      headers: new Headers(init.headers),
    });
    return me();
  });
  return asked;
}

const ME = {
  kind: "key",
  org: "scratch",
  project: "demo",
  key_id: "key_1",
  writes: false,
  label: "dev",
  created_by: null,
  org_name: "Scratch",
  project_name: "Demo",
  space: "project",
};

describe("check", () => {
  it("asks GET /v2/me what the key is, once, as the CLI", async () => {
    const asked = service(() => Response.json(ME));
    expect(await env.check("tm_x", BASE)).toEqual({
      ok: true,
      writes: false,
      detail: "scratch/demo, reads only",
    });
    expect(asked.map((a) => a.route)).toEqual([`GET ${BASE}/v2/me`]);
    expect(asked[0]!.headers.get("Authorization")).toBe("Bearer tm_x");
    expect(asked[0]!.headers.get("User-Agent")).toMatch(/^alexein-js\/\S+ cli$/);
    expect(asked[0]!.headers.get("X-Alexein-User")).toBeNull();
  });

  it("goes to the default address when the project sets none", async () => {
    vi.stubEnv(env.BASE_URL, "");
    const asked = service(() => Response.json({ ...ME, writes: true }));
    expect((await env.check("tm_x", undefined)).detail).toBe("scratch/demo, reads and writes");
    expect(asked[0]!.route).toBe("GET https://api.alexein.ai/v2/me");
  });

  it("fails a key the API does not know", async () => {
    service(() => Response.json({ detail: "unknown key" }, { status: 401 }));
    expect(await env.check("tm_bad", BASE)).toEqual({
      ok: false,
      writes: undefined,
      detail: "the service does not know this key",
    });
  });

  it("says why it could not check, without retrying", async () => {
    const asked = service(() => Response.json({ detail: "down" }, { status: 503 }));
    const checked = await env.check("tm_x", BASE);
    expect(checked.ok).toBe(false);
    expect(checked.detail).toMatch(/^could not check it: /);
    expect(asked.length).toBe(1);
  });
});

describe("resolveKey", () => {
  const roots: string[] = [];
  afterEach(() => roots.splice(0).forEach((r) => rmSync(r, { recursive: true, force: true })));
  const root = (dotenv?: string) => {
    const made = mkdtempSync(join(tmpdir(), "env-"));
    roots.push(made);
    if (dotenv !== undefined) writeFileSync(join(made, ".env"), dotenv);
    return made;
  };

  it("takes .env first, then the environment, and says which", () => {
    vi.stubEnv(env.KEY, "tm_env");
    vi.stubEnv(env.BASE_URL, "http://localhost:8210");
    expect(env.resolveKey(root(`${env.KEY}=tm_file\n`))).toEqual({
      key: "tm_file",
      keyFrom: ".env",
      baseUrl: "http://localhost:8210",
      baseUrlFrom: "the environment",
    });
  });

  it("finds nothing when neither has it", () => {
    vi.stubEnv(env.KEY, "");
    vi.stubEnv(env.BASE_URL, "");
    expect(env.resolveKey(root())).toEqual({
      key: "",
      keyFrom: undefined,
      baseUrl: undefined,
      baseUrlFrom: undefined,
    });
  });
});
