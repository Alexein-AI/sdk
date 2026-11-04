/**
 * Every method against the API's own contract, `contract/openapi.json` at the repository's root -
 * the document the Python client is held to as well. Refresh it with `scripts/refresh-openapi.sh`;
 * a route or field the API renames or drops then fails here, before a release.
 */

import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { memory, ok, type Sent } from "./helpers.js";

type Schema = {
  $ref?: string;
  type?: string | string[];
  anyOf?: Schema[];
  properties?: Record<string, Schema>;
  required?: string[];
  items?: Schema;
};
type Operation = {
  parameters?: { name: string; in: string; required?: boolean }[];
  requestBody?: { content: { "application/json": { schema: Schema } } };
};

const CONTRACT = JSON.parse(
  readFileSync(new URL("../../contract/openapi.json", import.meta.url), "utf8"),
);
const SCHEMAS: Record<string, Schema> = CONTRACT.components.schemas;
const PATHS: Record<string, Record<string, Operation>> = CONTRACT.paths;

const resolve = (schema: Schema): Schema =>
  schema.$ref ? resolve(SCHEMAS[schema.$ref.split("/").pop()!]!) : schema;

/** Whether `schema` takes `value`, as far as JSON types go. */
function takes(schema: Schema, value: unknown): boolean {
  const s = resolve(schema);
  if (s.anyOf) return s.anyOf.some((each) => takes(each, value));
  if (s.type === undefined) return true;
  const type = Array.isArray(value)
    ? "array"
    : value === null
      ? "null"
      : Number.isInteger(value)
        ? "integer"
        : typeof value;
  const types = Array.isArray(s.type) ? s.type : [s.type];
  return types.some((t) => t === type || (t === "number" && type === "integer"));
}

/** Every method, with every option it has, against a service that answers `{}`. */
async function everyRequest(): Promise<Sent[]> {
  const { client, sent } = memory(() => ok());
  const dana = client.user("dana");
  const filters = { metadata: { priority: { gte: 3 } } };
  const origin = { provider: "github", source: "items", kind: ["issue"] };
  await client.me();
  await client.users({ limit: 10, cursor: "c" });
  await dana.add(
    { text: "t", id: "i", at: "2026-10-01", about: ["project:atlas"], expires: null },
    {
      wait: true,
      redact: true,
      kind: "note",
      session: "s",
      role: "user",
      author: { id: "u1", name: "Dana", email: "d@x", handle: "@d", self: true },
      title: "T",
      metadata: { k: 1 },
    },
  );
  await dana.search("q", {
    before: "2026-12-01",
    after: "2026-01-01",
    filters,
    fast: true,
    ...origin,
  });
  await dana.grep("p", { limit: 5, ...origin });
  await dana.latest({
    k: 3,
    place: "eng",
    after: "2026-01-01",
    before: "2026-12-01",
    filters,
    ...origin,
  });
  await dana.around("mem_1", { width: 3 });
  await dana.open("mem_1");
  await dana.history("s", { attribute: "a" });
  await dana.summary();
  await dana.facts({ limit: 5, cursor: "c" });
  await dana.openItems({
    kind: ["issue"],
    provider: "github",
    place: "p",
    mine: false,
    withinDays: 7,
    limit: 5,
  });
  await dana.sources();
  await dana.items({ limit: 5, cursor: "c", filters });
  await dana.item("i");
  await dana.status(["i"]);
  await dana.forget({ items: ["i"], sessions: ["s"], refs: ["mem_1"] });
  await dana.correct("mem_1", "x");
  await dana.versions("i");
  await dana.export({ limit: 5, cursor: "c" });
  await dana.delete();
  return sent.requests;
}

const SENT = await everyRequest();

function operation(request: Sent): Operation {
  const path = request.url.pathname.replace(/^\/v2/, "");
  const found = PATHS[path]?.[request.method.toLowerCase()];
  expect(found, `${request.method} ${path} is in the contract`).toBeTruthy();
  return found!;
}

// Documented, and left out of the client on purpose. `events/lookup` (2026-11-04) is the console's:
// it takes the ingestion service's own event ids, which a customer never holds, and answers in a
// shape no other route has (`phase`, `queueComplete`, `occurredAt`). The Python client leaves out
// the same routes (`tests/test_contract.py`).
const NOT_OFFERED = new Set(["post /memory/events/lookup"]);

describe("the API's contract", () => {
  it("is the API version the client speaks: the same major and minor", async () => {
    // A patch release (0.3.1) is the client's own; any 0.3.x speaks the API's 0.3.
    const { VERSION } = await import("../src/index.js");
    const minor = (v: string) => v.split(".").slice(0, 2).join(".");
    expect(minor(CONTRACT.info.version)).toBe(minor(VERSION));
    expect(CONTRACT.servers[0].url).toBe("https://api.alexein.ai/v2");
  });

  it("documents every request's path, method and body fields", () => {
    for (const request of SENT) {
      const op = operation(request);
      const where = request.url.pathname;
      if (request.method === "GET") {
        expect(request.body, where).toBeUndefined();
        continue;
      }
      const body = request.body as Record<string, unknown>;
      if (!op.requestBody) {
        expect(body, where).toEqual({});
        continue;
      }
      const schema = resolve(op.requestBody.content["application/json"].schema);
      for (const [field, value] of Object.entries(body)) {
        const property = schema.properties?.[field];
        expect(property, `${where}: ${field}`).toBeTruthy();
        expect(takes(property!, value), `${where}: ${field} = ${JSON.stringify(value)}`).toBe(true);
      }
      for (const field of schema.required ?? []) expect(Object.keys(body), where).toContain(field);
    }
  });

  it("takes every item and author field the client sends", () => {
    const add = SENT.find((r) => r.url.pathname === "/v2/memory/add")!;
    const item = SCHEMAS.Item!;
    for (const sent of add.body.items as Record<string, unknown>[]) {
      for (const [field, value] of Object.entries(sent)) {
        expect(item.properties, field).toHaveProperty(field);
        expect(takes(item.properties![field]!, value), field).toBe(true);
      }
      for (const field of Object.keys(sent.author as object)) {
        expect(SCHEMAS.Author!.properties).toHaveProperty(field);
      }
    }
  });

  it("sends the headers each route documents", () => {
    for (const request of SENT) {
      const params = operation(request).parameters ?? [];
      const headers = params.filter((p) => p.in === "header").map((p) => p.name);
      const where = request.url.pathname;
      const user = params.find((p) => p.name === "X-Alexein-User");
      expect(request.headers["X-Alexein-User"] !== undefined, where).toBe(Boolean(user?.required));
      if (request.headers["Idempotency-Key"]) expect(headers, where).toContain("Idempotency-Key");
      for (const name of Object.keys(request.headers)) {
        if (name.startsWith("X-") || name === "Idempotency-Key")
          expect(headers, where).toContain(name);
      }
    }
  });

  it("has a method for every route it documents", () => {
    const reached = new Set(
      SENT.map((r) => `${r.method.toLowerCase()} ${r.url.pathname.slice(3)}`),
    );
    const documented = Object.entries(PATHS).flatMap(([path, ops]) =>
      Object.keys(ops).map((method) => `${method} ${path}`),
    );
    for (const route of NOT_OFFERED) expect(documented).toContain(route);
    expect([...reached].sort()).toEqual(documented.filter((r) => !NOT_OFFERED.has(r)).sort());
  });
});
