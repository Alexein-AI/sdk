/**
 * A memory API that answers as the real one does, a client whose requests are recorded, and a
 * memory file as `init` writes it, imported fresh with such a client.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { Memory } from "twinmemory";

import { render } from "../src/render.js";

export interface Sent {
  path: string;
  headers: Record<string, string>;
  body: Record<string, any>;
}

export type Respond = (path: string, body: any) => Response;

export const SEARCHED = {
  query: "q",
  found: 1,
  known: ["Dana lives in Lisbon."],
  facts: [],
  hits: [{ path: "passages/p1.md", id: "p1", text: "Dana: I moved to Lisbon." }],
};

export function answer(path: string): Response {
  const route = path.split("/").pop();
  if (route === "search") return Response.json(SEARCHED);
  if (route === "read")
    return Response.json({ path: "passages/p1.md", text: "Dana: I moved to Lisbon." });
  if (route === "add") return Response.json({ items: [], queued: 1, pending: 1 }, { status: 202 });
  return Response.json({});
}

export const down = () => Response.json({ detail: "rebuilding" }, { status: 503 });

export function client(respond: Respond, integration: string, failOpen = true) {
  const sent: Sent[] = [];
  const memory = new Memory({
    apiKey: "tm_test",
    failOpen,
    integration,
    maxRetries: 0,
    logger: () => {},
    fetch: async (input, init) => {
      const path = new URL(String(input)).pathname;
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      sent.push({ path, headers: init?.headers as Record<string, string>, body });
      return respond(path, body);
    },
  });
  return { memory, sent };
}

let counter = 0;

/** The file at `templates/<template>` as `init` writes it, in `dir`, imported fresh. */
export async function loadMemoryFile(
  dir: string,
  template: string,
  parts: string[],
  respond: Respond,
  { integration, failOpen = true }: { integration: string; failOpen?: boolean },
) {
  const own = join(dir, `memory-${process.pid}-${counter++}`);
  mkdirSync(own, { recursive: true });
  const path = join(own, "memory.ts");
  writeFileSync(path, render(template, parts, { version: "test", fast: "false" }));
  const module: Record<string, any> = await import(pathToFileURL(path).href);
  const { memory, sent } = client(respond, integration, failOpen);
  module.useMemory(memory);
  return { module, sent };
}
