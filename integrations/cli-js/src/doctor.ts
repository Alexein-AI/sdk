/**
 * `@alexein/cli doctor`: whether a project is set up for memory, one line per check, each with how
 * to fix it when it is not - the memory file, `@alexein/sdk` and the framework's packages declared
 * and installed, and `ALEXEIN_API_KEY` / `ALEXEIN_API_URL` (from `.env`, else the environment),
 * the key checked with `memory.me()`. Reads everything and changes nothing; the one request it
 * makes is the key's check, which is free.
 */

import { readFileSync } from "node:fs";
import { relative } from "node:path";

import { DEFAULT_BASE_URL } from "@alexein/sdk";

import * as env from "./env.js";
import * as project from "./project.js";
import { MINIMUMS } from "./scaffold.js";
import type { Console } from "./ui.js";
import { VERSION } from "./version.js";

function mark(console: Console, ok: boolean | undefined, what: string, fix = ""): boolean {
  console.line(`  ${ok === undefined ? "-" : ok ? "✓" : "✗"} ${what}`);
  if (ok === false && fix) console.line(`      ${fix}`);
  return ok !== false;
}

/** 0 when every check passes, 1 when any fails. */
export async function doctor(
  cwd: string,
  console: Console,
  check: env.Checker = env.check,
): Promise<number> {
  const root = project.findRoot(cwd);
  if (!root) {
    console.fail("no JavaScript project here; run it from your project.");
    return 1;
  }
  console.line(`@alexein/cli ${VERSION} - checking ${root}`);
  const written = memoryFiles(root, console);
  const minimums = minimumsFor(
    root,
    written.map(([, framework]) => framework),
  );
  const results = [
    written.length > 0,
    dependencies(root, minimums, console),
    versions(root, minimums, console),
  ];
  results.push(await key(root, console, saves(root), check));
  console.line();
  const good = results.every(Boolean);
  console.line(good ? "All good." : "Fix what is marked ✗, then run doctor again.");
  return good ? 0 : 1;
}

/** The memory files `init` wrote here, each with its framework, and marked. */
function memoryFiles(root: string, console: Console): [string, string][] {
  const found: [string, string][] = [];
  for (const path of project.sources(root)) {
    const match = project.GENERATED.exec(readFileSync(path, "utf8").slice(0, 2000));
    if (match) {
      if (match[1]! in MINIMUMS) found.push([path, match[1]!]);
      mark(console, true, `memory file ${relative(root, path)} (written by ${match[2]})`);
    }
  }
  if (!found.length) {
    const commands = Object.keys(MINIMUMS).map((f) => `\`npx @alexein/cli init ${f}\``);
    mark(console, false, "no memory file", `run ${commands.join(" or ")}`);
  }
  return found;
}

/** Comments, which show wiring without doing it. */
const COMMENTS = /\/\*[\s\S]*?\*\/|^\s*\/\/.*$/gm;
/** Code that saves: `memory.remember`, or tools given `write: true` (which adds `memory_add`). */
const SAVING = /\.remember\b|\bremember\(|write:\s*true/;

/** Whether the project's own code - not its comments - saves to memory. */
function saves(root: string): boolean {
  for (const path of project.sources(root)) {
    try {
      if (SAVING.test(readFileSync(path, "utf8").replace(COMMENTS, ""))) return true;
    } catch {
      continue;
    }
  }
  return false;
}

/**
 * What the project needs: for the frameworks its memory files are for, else for those it uses,
 * else for LangGraph's.
 */
function minimumsFor(root: string, frameworks: string[]): Record<string, string> {
  const used = Object.keys(MINIMUMS).filter((f) => project.uses(root, f));
  const chosen = frameworks.length ? frameworks : used.length ? used : ["langgraph"];
  return Object.assign({}, ...[...new Set(chosen)].map((f) => MINIMUMS[f]));
}

function dependencies(root: string, minimums: Record<string, string>, console: Console): boolean {
  const missing = Object.keys(minimums).filter((name) => !project.declares(root, name));
  if (missing.length) {
    const add = project
      .installer(
        root,
        missing.map((n) => `'${n}@>=${minimums[n]}'`),
      )
      .command.join(" ");
    return mark(console, false, `not dependencies: ${missing.join(", ")}`, add);
  }
  return mark(console, true, `dependencies: ${Object.keys(minimums).join(", ")}`);
}

function versions(root: string, minimums: Record<string, string>, console: Console): boolean {
  let ok = true;
  for (const [name, minimum] of Object.entries(minimums)) {
    const version = project.installed(root, name);
    if (version === undefined)
      ok =
        mark(console, false, `${name} is not installed`, "install the project's dependencies") &&
        ok;
    else if (project.older(version, minimum))
      ok =
        mark(
          console,
          false,
          `${name} ${version} is older than ${minimum}`,
          `upgrade it to >=${minimum}`,
        ) && ok;
    else mark(console, true, `${name} ${version}`);
  }
  return ok;
}

async function key(
  root: string,
  console: Console,
  saves: boolean,
  check: env.Checker,
): Promise<boolean> {
  const { key, baseUrl, keyFrom, baseUrlFrom } = env.resolveKey(root);
  if (!key)
    return mark(
      console,
      false,
      `no ${env.KEY}, in .env or the environment`,
      `put a key in .env as ${env.KEY}= (console, under API keys)`,
    );
  mark(console, true, `${env.KEY} from ${keyFrom}`);
  if (baseUrl && !/^https?:\/\/[^/\s]+/.test(baseUrl))
    return mark(
      console,
      false,
      `${env.BASE_URL} from ${baseUrlFrom} is not an address: ${JSON.stringify(baseUrl)}`,
      `set it to the API's host, like ${DEFAULT_BASE_URL}, or leave it out`,
    );
  mark(
    console,
    true,
    baseUrl
      ? `${env.BASE_URL} from ${baseUrlFrom}: ${baseUrl}`
      : `${env.BASE_URL} not set: ${DEFAULT_BASE_URL}`,
  );
  const where = baseUrl ? ` at ${baseUrl}` : "";
  const keptOut =
    keyFrom !== ".env" ||
    env.ignored(root) ||
    mark(console, false, ".env is not in .gitignore", "add .env to .gitignore");
  const checked = await check(key, baseUrl);
  if (!checked.ok)
    return mark(
      console,
      false,
      `key${where}: ${checked.detail}`,
      `check ${env.KEY} and ${env.BASE_URL}`,
    );
  if (saves && checked.writes === false) {
    return mark(
      console,
      false,
      `key${where} only reads, and the project saves: memory.remember and memory_add will be refused`,
      "use a key that writes (console, under API keys)",
    );
  }
  return mark(console, true, `key${where}: ${checked.detail}`) && keptOut;
}
