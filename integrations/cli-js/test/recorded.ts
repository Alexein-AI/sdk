/**
 * A memory API that answers as the real one does, reached through a stubbed global `fetch`, and a
 * memory file as `init` writes it, imported fresh.
 *
 * The written file's `memory` makes its client on first use, from `ALEXEIN_API_KEY` and the global
 * `fetch`; a test stubs both before importing it, and the file runs exactly as written, through the
 * real `@alexein/sdk`, with every request it sends recorded.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { vi } from "vitest";

import { render } from "../src/render.js";
import { preset } from "../src/scaffold.js";

export const KEY = "tm_test";
export const BASE = "https://memory.test";

export interface Sent {
  /** The route after `/v2/memory/`, or `me`. */
  route: string;
  headers: Record<string, string>;
  body: Record<string, any>;
}

export type Respond = (route: string, body: any) => Response;

export const REF = "mem_9fK2xQ7aLp3";

export const SEARCHED = {
  query: "q",
  answerable: true,
  notes: [],
  memories: [
    { type: "known", text: "Dana lives in Lisbon." },
    {
      type: "excerpt",
      ref: REF,
      text: "Dana: I moved to Lisbon.",
      date: "2026-10-01T09:30:00+00:00",
      added_at: "2026-10-01T09:30:02+00:00",
      session: "t-1",
      roles: ["user"],
    },
  ],
};

export function answer(route: string): Response {
  if (route === "search") return Response.json(SEARCHED);
  if (route === "open") return Response.json({ memory: SEARCHED.memories[1] });
  if (route === "add") return Response.json({ items: [], waiting: 1 }, { status: 202 });
  return Response.json({});
}

/** An outage that asks to be tried again at once, so the client's retries cost no time. */
export const down = () =>
  Response.json(
    { detail: "briefly unavailable" },
    { status: 503, headers: { "Retry-After": "0" } },
  );
export const wrongKey = () => Response.json({ detail: "bad key" }, { status: 401 });
export const nobody = () => Response.json({ detail: "no memory for this user" }, { status: 404 });

/** Stub the key, the address and `fetch`; what is sent is recorded, and answered by `respond`. */
export function serve(respond: Respond = answer): Sent[] {
  const sent: Sent[] = [];
  vi.stubEnv("ALEXEIN_API_KEY", KEY);
  vi.stubEnv("ALEXEIN_API_URL", BASE);
  vi.stubGlobal("fetch", async (input: string | URL, init: RequestInit = {}) => {
    const route = new URL(String(input)).pathname.replace(/^\/v2\/(memory\/)?/, "");
    const body = init.body ? JSON.parse(String(init.body)) : {};
    sent.push({ route, headers: init.headers as Record<string, string>, body });
    return respond(route, body);
  });
  return sent;
}

export const routes = (sent: Sent[]) => sent.map((s) => s.route);
export const bodies = (sent: Sent[], route: string) =>
  sent.filter((s) => s.route === route).map((s) => s.body);
export const users = (sent: Sent[]) => new Set(sent.map((s) => s.headers["X-Alexein-User"]));

let counter = 0;

export interface Written {
  /** What the preset keeps: `nodes`, `tools` or both. */
  parts?: string[];
  fast?: boolean;
  /** Changes to the file as written, as its developer would make them: `[from, to]`. */
  edits?: [string, string][];
}

/** The file at `templates/<template>` as `init` writes it, in a directory of its own in `dir`. */
export function writeMemoryFile(
  dir: string,
  template: string,
  { parts = ["nodes", "tools"], fast = false, edits = [] }: Written = {},
): string {
  const own = join(dir, `memory-${process.pid}-${counter++}`);
  mkdirSync(own, { recursive: true });
  let text = render(template, preset({ parts }), { version: "0.3.0", fast: String(fast) });
  for (const [from, to] of edits) {
    if (!text.includes(from)) throw new Error(`the written file has no ${JSON.stringify(from)}`);
    text = text.replace(from, to);
  }
  const path = join(own, "memory.ts");
  writeFileSync(path, text);
  return path;
}

/** The written file, imported fresh against `respond`: its exports, and what it sends. */
export async function loadMemoryFile(
  dir: string,
  template: string,
  respond: Respond = answer,
  written: Written = {},
) {
  const sent = serve(respond);
  const path = writeMemoryFile(dir, template, written);
  const module: Record<string, any> = await import(pathToFileURL(path).href);
  return { module, sent, path };
}
