/**
 * `twinmemory-cli init <framework>`: write memory into a project as code its developer owns.
 *
 * The steps, in order, each of which can stop the command before anything is written: find the
 * project, make sure it uses the framework (or that adding it is wanted), make sure what is
 * installed is new enough, and pick where the file goes: beside the graph, or the agent. Then:
 * write the file, add the packages it imports, and set up the key - which can be skipped, and
 * added later.
 */

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import * as env from "./env.js";
import * as project from "./project.js";
import { render } from "./render.js";
import type { Console } from "./ui.js";
import { VERSION } from "./version.js";
import { nextSteps } from "./wiring.js";

/**
 * What each framework's file needs, at least. Every one needs `failOpen` and `integration`, in
 * the first `twinmemory` for JavaScript. LangGraph's: `StateSchema` and a run's `context` are
 * LangGraph.js 1 and LangChain core 1. The OpenAI Agents SDK's: a run's `callModelInputFilter`
 * and a result's `runContext` are in 0.6, which the file was run on as well as the newest; its
 * tools' schemas are zod 4, which the SDK asks for.
 */
export const MINIMUMS: Record<string, Record<string, string>> = {
  langgraph: {
    twinmemory: "0.1",
    "@langchain/langgraph": "1.0",
    "@langchain/core": "1.0",
    zod: "3.25",
  },
  "openai-agents": { twinmemory: "0.1", "@openai/agents": "0.6", zod: "4.0" },
};
/** How each is named to the developer. */
export const NAMES: Record<string, string> = {
  langgraph: "LangGraph",
  "openai-agents": "the OpenAI Agents SDK",
};
export const PARTS = ["nodes", "tools"] as const;
export type Part = (typeof PARTS)[number];

export type Runner = (command: string[], cwd: string) => number;

export const runCommand: Runner = (command, cwd) =>
  spawnSync(command[0]!, command.slice(1), {
    cwd,
    stdio: "inherit",
    shell: process.platform === "win32",
  }).status ?? 1;

/**
 * Everything `init` can be told. `parts` are what the file holds; `sdk` installs the client from
 * somewhere other than npm (a path, while it is not published).
 */
export interface Options {
  framework: string;
  directory?: string;
  filename: string;
  graph?: string;
  force: boolean;
  install: boolean;
  parts: readonly Part[];
  fast: boolean;
  key?: string;
  baseUrl?: string;
  skipKey: boolean;
  sdk?: string;
  dryRun: boolean;
  run: Runner;
  check: env.Checker;
}

export function options(given: Partial<Options> = {}): Options {
  return {
    framework: "langgraph",
    filename: "memory.ts",
    force: false,
    install: true,
    parts: PARTS,
    fast: false,
    skipKey: false,
    dryRun: false,
    run: runCommand,
    check: env.check,
    ...given,
  };
}

/** Why `init` stopped before writing anything, with the exit code to stop with. */
export class Stop extends Error {
  constructor(
    why: string,
    readonly code = 1,
  ) {
    super(why);
  }
}

/** Run `init`; the exit code: 0 done, 1 stopped or the install failed, 2 a bad command. */
export async function init(cwd: string, o: Options, console: Console): Promise<number> {
  let root: string, target: string;
  try {
    [root, target] = await prepare(cwd, o, console);
  } catch (error) {
    if (!(error instanceof Stop)) throw error;
    console.fail(error.message);
    return error.code;
  }
  if (o.dryRun) {
    plan(root, join(target, o.filename), o, console);
    return 0;
  }
  const written = write(target, o);
  console.step("wrote", shown(written, root));
  const installed = install(root, o, console);
  await setupKey(root, o, console);
  console.line();
  console.line(nextSteps(o));
  return installed ? 0 : 1;
}

async function prepare(cwd: string, o: Options, console: Console): Promise<[string, string]> {
  const framework = o.framework;
  if (!(framework in MINIMUMS)) {
    const known = Object.keys(MINIMUMS).join(", ");
    throw new Stop(`no template for ${JSON.stringify(framework)}; there is: ${known}`, 2);
  }
  if (framework !== "langgraph" && o.graph !== undefined)
    throw new Stop(`--graph is for langgraph; ${framework} has no langgraph.json`, 2);
  if (!/\.[cm]?ts$/.test(o.filename))
    throw new Stop(`--file must name a TypeScript file: ${JSON.stringify(o.filename)}`, 2);
  const root = project.findRoot(cwd);
  if (!root) {
    throw new Stop(
      "no JavaScript project here (no package.json or langgraph.json at or above this directory). " +
        `Run it from your project, or start one with \`twinmemory-cli create ${framework} <name>\`.`,
    );
  }
  console.step("found", `${project.installer(root, []).name} project at ${root}`);
  await requireFramework(root, framework, console);
  requireVersions(root, framework);
  const target = o.directory
    ? resolve(cwd, o.directory)
    : framework === "langgraph"
      ? await graphDir(root, o, console)
      : await agentDir(root, console);
  const written = join(target, o.filename);
  if (existsSync(written) && !o.force) {
    throw new Stop(`${shown(written, root)} exists; --force replaces it. Nothing changed.`);
  }
  return [root, target];
}

async function requireFramework(root: string, framework: string, console: Console): Promise<void> {
  if (project.uses(root, framework)) return;
  const name = NAMES[framework]!;
  console.step("note", `this project does not use ${name} yet`);
  if (!(await console.confirm(`Add ${name} to it and go on?`))) {
    throw new Stop(
      `this project does not use ${name}; run again with --yes to add it, or start a new one ` +
        `with \`twinmemory-cli create ${framework} <name>\`. Nothing changed.`,
    );
  }
}

function requireVersions(root: string, framework: string): void {
  const stale = Object.entries(MINIMUMS[framework]!)
    .filter(([name]) => name !== "twinmemory")
    .map(([name, minimum]) => [name, project.installed(root, name), minimum] as const)
    .filter(([, version, minimum]) => version && project.older(version, minimum));
  if (!stale.length) return;
  const found = stale.map(([n, v, m]) => `${n} ${v} (needs >=${m})`).join(", ");
  const upgrade = project.installer(
    root,
    stale.map(([n, , m]) => `'${n}@>=${m}'`),
  );
  throw new Stop(
    `this project has ${found} installed. Upgrade first - ${upgrade.command.join(" ")} - then run ` +
      "init again. Nothing changed.",
  );
}

async function graphDir(root: string, o: Options, console: Console): Promise<string> {
  const found = project.graphs(root);
  const names = Object.keys(found);
  if (o.graph !== undefined) {
    if (!(o.graph in found)) {
      throw new Stop(
        `no graph ${JSON.stringify(o.graph)} in langgraph.json (there is: ${names.join(", ") || "none"})`,
      );
    }
    return found[o.graph]!;
  }
  if (names.length <= 1) return project.targetDir(root, names[0] && found[names[0]]);
  const chosen = await console.choose("Which graph is memory for?", names);
  if (chosen === undefined) {
    throw new Stop(
      `langgraph.json has ${names.length} graphs (${names.join(", ")}); name one with --graph. Nothing changed.`,
    );
  }
  return found[chosen]!;
}

/** Beside the code that builds an `Agent`; with none found, `src/` or the root. */
async function agentDir(root: string, console: Console): Promise<string> {
  const found = project.agentDirs(root);
  if (!found.length) {
    console.step("note", "found no file that builds an Agent; writing to src/ or the root");
    return project.targetDir(root);
  }
  if (found.length === 1) return found[0]!;
  const named = found.map((d) => shown(d, root));
  const chosen = await console.choose("Which agent is memory for?", named);
  if (chosen === undefined) {
    throw new Stop(
      `${found.length} directories build an Agent (${named.join(", ")}); name one with --dir. ` +
        "Nothing changed.",
    );
  }
  return found[named.indexOf(chosen)]!;
}

export function write(target: string, o: Options): string {
  mkdirSync(target, { recursive: true });
  const written = join(target, o.filename);
  writeFileSync(
    written,
    render(`${o.framework.replace("-", "_")}/memory.ts.tmpl`, o.parts, {
      version: VERSION,
      fast: String(o.fast),
    }),
  );
  return written;
}

/** What still has to be added for the file to import, each with its minimum. */
export function requirements(root: string, o: Options): string[] {
  return Object.entries(MINIMUMS[o.framework]!)
    .filter(([name]) => !project.declares(root, name))
    .map(([name, minimum]) => (name === "twinmemory" && o.sdk ? o.sdk : `${name}@>=${minimum}`));
}

function quoted(command: string[]): string {
  return command.map((word) => (/[>]/.test(word) ? `'${word}'` : word)).join(" ");
}

function plan(root: string, written: string, o: Options, console: Console): void {
  console.step("would", `write ${shown(written, root)}`);
  const packages = requirements(root, o);
  if (!packages.length)
    console.step("would", "install nothing: every package is a dependency already");
  else
    console.step(
      "would",
      `${o.install ? "run" : "print"} ${quoted(project.installer(root, packages).command)}`,
    );
  const { key } = env.resolveKey(root);
  if (o.baseUrl) console.step("would", `set ${env.BASE_URL} in .env`);
  if (o.key) console.step("would", `set ${env.KEY} in .env, and check it`);
  else if (!key) console.step("would", `ask for the key, or add an empty ${env.KEY}= to .env`);
  else console.step("would", "check the key already in .env");
  console.line();
  console.line("Dry run: nothing was changed.");
}

/** Add what the project does not depend on yet, with its own tool; true unless that failed. */
export function install(root: string, o: Options, console: Console): boolean {
  const packages = requirements(root, o);
  if (!packages.length) {
    console.step("kept", `${Object.keys(MINIMUMS[o.framework]!).join(", ")}: already dependencies`);
    return true;
  }
  const command = project.installer(root, packages).command;
  if (!o.install) {
    console.step("run", quoted(command));
    return true;
  }
  console.step("running", quoted(command));
  if (o.run(command, root) !== 0) {
    console.fail(`\`${quoted(command)}\` failed; run it yourself, then go on.`);
    return false;
  }
  console.step("ran", quoted(command));
  return true;
}

/**
 * Put the key (and address) in `.env` and check it. Skippable: without one, an empty
 * `TWIN_MEMORY_API_KEY=` is left to fill in, and `twinmemory-cli doctor` checks it later.
 */
export async function setupKey(root: string, o: Options, console: Console): Promise<void> {
  const dotenv = join(root, ".env");
  if (o.baseUrl)
    console.step(env.put(dotenv, env.BASE_URL, o.baseUrl, true), `${env.BASE_URL} in .env`);
  let { key } = env.resolveKey(root);
  let given = o.key;
  if (given === undefined && !key && !o.skipKey) {
    given =
      (await console.secret(
        "Your twin memory API key (from the console, under API keys; Enter to skip):",
      )) || undefined;
  }
  if (given) {
    console.step(env.put(dotenv, env.KEY, given, true), `${env.KEY} in .env`);
  } else if (!key) {
    env.put(dotenv, env.KEY, "", false);
    console.step("added", `${env.KEY}= to .env: fill it in later (console, under API keys)`);
  }
  if (!env.ignored(root))
    console.step("warning", ".env is not in .gitignore; add it before a key goes in it");
  const resolved = env.resolveKey(root);
  key = resolved.key;
  if (!key) return;
  const checked = await o.check(key, resolved.baseUrl);
  if (!checked.ok) {
    console.step("warning", `the key did not check out: ${checked.detail}`);
    return;
  }
  console.step("checked", `key: ${checked.detail}`);
  if (checked.writes === false && o.parts.includes("nodes")) {
    console.step("warning", "this key only reads: remember and memory_add need one that writes");
  }
}

export function shown(path: string, root: string): string {
  const inside = relative(root, path);
  return inside.startsWith("..") ? path : `./${inside}`;
}
