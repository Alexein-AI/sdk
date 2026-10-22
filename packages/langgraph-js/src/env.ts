/**
 * The project's `.env`: the key and the address memory is reached at, read and set one line at a
 * time so every other line in the file stays exactly as it was. And the check that a key works.
 *
 * Not a dotenv parser: `KEY=value` lines, optionally quoted, are all it reads, which is all it
 * ever writes.
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { AuthenticationError, Memory, NotFoundError, TwinMemoryError } from "twinmemory";

export const KEY = "TWIN_MEMORY_API_KEY";
export const BASE_URL = "TWIN_MEMORY_BASE_URL";

function nameOf(line: string): string {
  return line
    .split("=")[0]!
    .trim()
    .replace(/^export\s+/, "")
    .trim();
}

/** The `KEY=value` lines of a `.env`, unquoted; empty when there is none. */
export function read(env: string): Record<string, string> {
  if (!existsSync(env)) return {};
  const values: Record<string, string> = {};
  for (const line of readFileSync(env, "utf8").split("\n")) {
    const at = line.indexOf("=");
    const name = nameOf(line);
    if (at >= 0 && name && !name.startsWith("#")) {
      values[name] = line
        .slice(at + 1)
        .trim()
        .replace(/^['"]|['"]$/g, "");
    }
  }
  return values;
}

/**
 * Set `name` in `.env`: added when absent, replaced when `replace` or empty, else kept. Returns
 * what happened: "added", "replaced" or "kept".
 */
export function put(env: string, name: string, value: string, replace: boolean): string {
  const text = existsSync(env) ? readFileSync(env, "utf8") : "";
  const lines = text.split("\n");
  if (lines.at(-1) === "") lines.pop();
  const at = lines.findIndex((line) => line.includes("=") && nameOf(line) === name);
  if (at >= 0) {
    if (!replace && read(env)[name]) return "kept";
    lines[at] = `${name}=${value}`;
    writeFileSync(env, lines.join("\n") + "\n");
    return "replaced";
  }
  const separator = !text || text.endsWith("\n") ? "" : "\n";
  writeFileSync(env, `${text}${separator}${name}=${value}\n`);
  return "added";
}

/** Whether `.gitignore` keeps `.env` out of the repository. */
export function ignored(root: string): boolean {
  const path = join(root, ".gitignore");
  if (!existsSync(path)) return false;
  return readFileSync(path, "utf8")
    .split("\n")
    .some((line) => [".env", "/.env", ".env*", "*.env", ".env.*"].includes(line.trim()));
}

/**
 * What trying a key found. `ok` is whether it works; `writes` is undefined when the service does
 * not say; `detail` is the line to print.
 */
export interface Check {
  ok: boolean;
  writes: boolean | undefined;
  detail: string;
}

export type Checker = (key: string, baseUrl: string | undefined) => Promise<Check>;

/**
 * Try a key against memory: `GET /v1/me` where the service has it, else a free search for an end
 * user nobody has written for, which a working key answers 404.
 */
export const check: Checker = async (key, baseUrl) => {
  try {
    const memory = new Memory({ apiKey: key, baseUrl, timeout: 10_000, maxRetries: 0 });
    let me;
    try {
      me = await memory.me();
    } catch (error) {
      if (!(error instanceof NotFoundError)) throw error;
      try {
        await memory.user("twinmemory-key-check").search("key check", { fast: true });
      } catch (missing) {
        if (!(missing instanceof NotFoundError)) throw missing;
      }
      return {
        ok: true,
        writes: undefined,
        detail: "works; this service does not say whether it writes",
      };
    }
    const where = me.org && me.project ? `${me.org}/${me.project}` : (me.org ?? "this key");
    return {
      ok: true,
      writes: me.writes,
      detail: `${where}, ${me.writes ? "reads and writes" : "reads only"}`,
    };
  } catch (error) {
    if (error instanceof AuthenticationError) {
      return { ok: false, writes: undefined, detail: "the service does not know this key" };
    }
    const said = error instanceof TwinMemoryError ? error.message : String(error);
    return { ok: false, writes: undefined, detail: `could not check it: ${said}` };
  }
};

/** The key and address the project will run with: its `.env`, else the environment. */
export function resolveKey(root: string): { key: string; baseUrl: string | undefined } {
  const values = read(join(root, ".env"));
  return {
    key: values[KEY] || process.env[KEY] || "",
    baseUrl: values[BASE_URL] || process.env[BASE_URL] || undefined,
  };
}
