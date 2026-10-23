/**
 * What the CLI finds out about the project it is run in: where its root is, which graphs it has,
 * where generated code should go, whether it uses a framework, which versions are installed, and
 * how it adds a dependency. It only reads; the commands do the writing.
 */

import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

/** A directory holding either of these is a JavaScript project's root. */
const MARKERS = ["package.json", "langgraph.json"];

export function findRoot(start: string): string | undefined {
  for (let directory = resolve(start); ; directory = dirname(directory)) {
    if (MARKERS.some((marker) => existsSync(join(directory, marker)))) return directory;
    if (dirname(directory) === directory) return undefined;
  }
}

function readJson(path: string): Record<string, unknown> | undefined {
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
    return typeof parsed === "object" && parsed !== null
      ? (parsed as Record<string, unknown>)
      : undefined;
  } catch {
    return undefined;
  }
}

export function packageJson(root: string): Record<string, unknown> {
  return readJson(join(root, "package.json")) ?? {};
}

/** Every dependency `package.json` declares, of any kind, with the range it asks for. */
export function dependencies(root: string): Record<string, string> {
  const pkg = packageJson(root);
  const all: Record<string, string> = {};
  for (const kind of [
    "dependencies",
    "devDependencies",
    "peerDependencies",
    "optionalDependencies",
  ]) {
    Object.assign(all, (pkg[kind] as Record<string, string> | undefined) ?? {});
  }
  return all;
}

export function declares(root: string, name: string): boolean {
  return name in dependencies(root);
}

/** Each graph `langgraph.json` names, and the directory its file is in. */
export function graphs(root: string): Record<string, string> {
  const config = readJson(join(root, "langgraph.json"));
  const named = config?.graphs;
  if (typeof named !== "object" || named === null) return {};
  const found: Record<string, string> = {};
  for (const [name, spec] of Object.entries(named as Record<string, unknown>)) {
    const where =
      typeof spec === "object" && spec !== null ? (spec as { path?: unknown }).path : spec;
    if (typeof where === "string" && where.includes(":")) {
      found[name] = dirname(resolve(root, where.split(":")[0]!));
    }
  }
  return found;
}

/** Where generated code goes: beside the chosen graph, else `src/`, else the root. */
export function targetDir(root: string, graph?: string): string {
  if (graph) return graph;
  const src = join(root, "src");
  return existsSync(src) && statSync(src).isDirectory() ? src : root;
}

/** Directories that hold other people's code, never the project's own. */
const SKIPPED = new Set([
  "node_modules",
  ".git",
  "dist",
  "build",
  ".next",
  ".turbo",
  ".langgraph_api",
]);
/** The package each framework is, and is imported as. */
const PACKAGES: Record<string, string> = { langgraph: "@langchain/langgraph" };
const SOURCE = /\.(?:[cm]?[jt]sx?)$/;

export function* sources(root: string): Generator<string> {
  const pending = [root];
  while (pending.length) {
    const directory = pending.pop()!;
    let entries;
    try {
      entries = readdirSync(directory, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (entry.isDirectory()) {
        if (!SKIPPED.has(entry.name)) pending.push(join(directory, entry.name));
      } else if (SOURCE.test(entry.name)) {
        yield join(directory, entry.name);
      }
    }
  }
}

/** Whether the project depends on the framework or imports it anywhere of its own. */
export function uses(root: string, framework: string, limit = 2000): boolean {
  const name = PACKAGES[framework]!;
  if (declares(root, name)) return true;
  if (framework === "langgraph" && existsSync(join(root, "langgraph.json"))) return true;
  const escaped = name.replaceAll("/", "\\/");
  const imports = new RegExp(
    `(?:from\\s+|require\\(\\s*|import\\(\\s*)["']${escaped}(?:\\/[^"']*)?["']`,
  );
  let n = 0;
  for (const path of sources(root)) {
    if (n++ >= limit) break;
    try {
      if (imports.test(readFileSync(path, "utf8"))) return true;
    } catch {
      continue;
    }
  }
  return false;
}

/** The version of `name` installed in the project's `node_modules`, if it is there. */
export function installed(root: string, name: string): string | undefined {
  const found = readJson(join(root, "node_modules", name, "package.json"))?.version;
  return typeof found === "string" ? found : undefined;
}

/** Whether `version` is below `minimum`, by their leading numbers (`0.6.2` < `1.0`). */
export function older(version: string, minimum: string): boolean {
  const numbers = (text: string) =>
    (text.split("+")[0]!.match(/\d+/g) ?? []).slice(0, 3).map(Number);
  const [a, b] = [numbers(version), numbers(minimum)];
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const [x, y] = [a[i] ?? 0, b[i] ?? 0];
    if (x !== y) return x < y;
  }
  return false;
}

export interface Installer {
  name: string;
  command: string[];
}

/**
 * How to add `packages` here: the tool the project's lock file (or `packageManager`) names,
 * else npm.
 */
export function installer(root: string, packages: string[], dev = false): Installer {
  const named = String(packageJson(root).packageManager ?? "").split("@")[0];
  const has = (file: string) => existsSync(join(root, file));
  const tool =
    named ||
    (has("pnpm-lock.yaml")
      ? "pnpm"
      : has("yarn.lock")
        ? "yarn"
        : has("bun.lock") || has("bun.lockb")
          ? "bun"
          : "npm");
  if (tool === "npm")
    return { name: tool, command: ["npm", "install", ...(dev ? ["--save-dev"] : []), ...packages] };
  return { name: tool, command: [tool, "add", ...(dev ? ["-D"] : []), ...packages] };
}
