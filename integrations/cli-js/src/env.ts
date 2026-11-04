/**
 * The project's `.env`: the key and the address memory is reached at, read and set one line at a
 * time so every other line in the file stays exactly as it was. And the check that a key works.
 *
 * Not a dotenv parser: `KEY=value` lines, optionally quoted, are all it reads, which is all it
 * ever writes.
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { AlexeinError, AuthenticationError, Memory } from "@alexein/sdk";

export const KEY = "ALEXEIN_API_KEY";
export const BASE_URL = "ALEXEIN_API_URL";

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
 * What trying a key found. `ok` is whether it works; `writes` is whether it writes, undefined when
 * it does not work or the service does not say; `detail` is the line to print.
 */
export interface Check {
  ok: boolean;
  writes: boolean | undefined;
  detail: string;
}

export type Checker = (key: string, baseUrl: string | undefined) => Promise<Check>;

/**
 * Try a key with `memory.me()`: one free request, `GET /v2/me`, which says what the key is and
 * whether it writes. No retries, and ten seconds at most: a check should answer, not wait.
 */
export const check: Checker = async (key, baseUrl) => {
  try {
    const memory = new Memory({
      apiKey: key,
      baseUrl,
      timeout: 10_000,
      maxRetries: 0,
      integration: "cli",
    });
    const me = await memory.me();
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
    const said = error instanceof AlexeinError ? error.message : String(error);
    return { ok: false, writes: undefined, detail: `could not check it: ${said}` };
  }
};

/** Where a setting was found: the project's `.env`, the environment, or nowhere. */
export type Source = ".env" | "the environment" | undefined;

/**
 * The key and address the project will run with: its `.env`, else the environment - with where
 * each came from.
 */
export function resolveKey(root: string): {
  key: string;
  baseUrl: string | undefined;
  keyFrom: Source;
  baseUrlFrom: Source;
} {
  const values = read(join(root, ".env"));
  const from = (name: string): [string | undefined, Source] =>
    values[name]
      ? [values[name], ".env"]
      : process.env[name]
        ? [process.env[name], "the environment"]
        : [undefined, undefined];
  const [key, keyFrom] = from(KEY);
  const [baseUrl, baseUrlFrom] = from(BASE_URL);
  return { key: key ?? "", baseUrl, keyFrom, baseUrlFrom };
}
