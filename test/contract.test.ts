/**
 * Every method against the API's own document, `openapi-memory.json`, pinned in this folder - the
 * same document the Python client is held to. Refresh it from a running service with
 * `scripts/refresh-openapi.sh`; a field the API renames or drops then fails here, before a release.
 */

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { memory, ok, type Sent } from "./helpers.js";

type Schema = { properties?: Record<string, unknown>; required?: string[] };
const DOCUMENT = JSON.parse(
  readFileSync(new URL("./openapi-memory.json", import.meta.url), "utf8"),
);
const SCHEMAS: Record<string, Schema> = DOCUMENT.components.schemas;

async function everyCall(): Promise<Sent[]> {
  const { client, sent } = memory(() => ok());
  const dana = client.user("dana");
  await client.me();
  await dana.add(
    { text: "t", id: "i", at: "2026-10-01", about: ["project:atlas"] },
    {
      wait: true,
      kind: "note",
      session: "s",
      role: "user",
      author: { name: "Dana", self: true },
      title: "T",
      expires: "2027-01-01",
      metadata: { k: 1 },
    },
  );
  await dana.search("q", {
    before: "2026-12-01",
    after: "2026-01-01",
    scope: "passages/",
    fast: true,
  });
  await dana.grep("p", { scope: "passages/", limit: 5 });
  await dana.read("a");
  await dana.ls("a");
  await dana.around("p", { width: 3 });
  await dana.history("s", { attribute: "a" });
  await dana.latest({ k: 3, place: "slack", after: "2026-01-01", before: "2026-12-01" });
  await dana.overview();
  await dana.forget({ items: ["i"], sessions: ["s"], threads: ["t"], events: ["e"] });
  await dana.correct("r", "x");
  await dana.versions("i");
  await dana.status(["i"]);
  await dana.lineage("i");
  return sent.requests;
}

function fields(ref: string): [Set<string>, Set<string>] {
  const schema = SCHEMAS[ref.split("/").pop()!]!;
  return [new Set(Object.keys(schema.properties ?? {})), new Set(schema.required ?? [])];
}

describe("the API's document", () => {
  it("documents every request's path, method and body", async () => {
    for (const request of await everyCall()) {
      const method = request.method.toLowerCase();
      const operation = DOCUMENT.paths[request.url.pathname]?.[method];
      expect(operation, `${request.method} ${request.url.pathname}`).toBeTruthy();
      if (method === "get") continue;
      const body = request.body as Record<string, unknown>;
      if (!operation.requestBody) {
        expect(body, request.url.pathname).toEqual({});
        continue;
      }
      const [known, required] = fields(
        operation.requestBody.content["application/json"].schema.$ref,
      );
      for (const field of Object.keys(body)) expect(known, request.url.pathname).toContain(field);
      for (const field of required)
        expect(Object.keys(body), request.url.pathname).toContain(field);
    }
  });

  it("takes every item field the client sends", async () => {
    const add = (await everyCall()).find((r) => r.url.pathname === "/v1/memory/add")!;
    const [known] = fields("Item");
    for (const item of (add.body as { items: Record<string, unknown>[] }).items) {
      for (const field of Object.keys(item)) expect(known).toContain(field);
    }
  });

  it("has a method for every route it documents", async () => {
    const reached = new Set(
      (await everyCall()).map((r) => `${r.method.toLowerCase()} ${r.url.pathname}`),
    );
    const documented = new Set(
      Object.entries(DOCUMENT.paths as Record<string, Record<string, unknown>>).flatMap(
        ([path, spec]) => Object.keys(spec).map((method) => `${method} ${path}`),
      ),
    );
    expect([...reached].sort()).toEqual([...documented].sort());
  });
});
