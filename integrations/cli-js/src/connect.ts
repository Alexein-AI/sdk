/**
 * `@alexein/cli connect`: Alexein AI's memory server added to the AI tools on this computer -
 * Claude Code, Cursor, VS Code, GitHub Copilot CLI, Codex, Gemini CLI, Antigravity and Devin
 * Desktop - so each searches the person's memory and saves what it learns.
 *
 * Each tool is told through its own command where it has one (`claude mcp add`, `code --add-mcp`),
 * so it writes its own settings; only Cursor and Devin Desktop without its CLI have their file
 * edited, the `alexein` entry alone, after a copy of the file is kept. Where a tool has an
 * Alexein AI plugin, the plugin goes in instead: the same server, and the guidance on when to
 * search and save. Nothing is replaced that is already there, short of `--force`.
 *
 * `--remove` takes out what this adds - the plugin, the `alexein` server, or its entry in a file -
 * through the tool's own command where it has one, and leaves anything else named for Alexein.
 *
 * The tools sign in to Alexein themselves, so no key is written anywhere. `--key` is for where
 * nobody is there to sign in: then each gets the key in a header, and no plugin.
 */

import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join } from "node:path";

import type { Console } from "./ui.js";
import { VERSION } from "./version.js";

export const URL = "https://api.alexein.ai/v1/mcp";
/** The server's name in every tool. A plugin's server is named by the plugin. */
export const NAME = "alexein";
/** What Claude Code calls the plugin's server: `plugin:<plugin>:<server>`. */
const CLAUDE_PLUGIN_SERVER = `plugin:alexein:${NAME}`;
const DOCS = "https://docs.alexein.ai/mcp";

/** What `connect` needs of the computer: a test hands in one over a scratch home. */
export interface Host {
  home: string;
  platform: NodeJS.Platform;
  env: NodeJS.ProcessEnv;
  /** Whether a command is on PATH. */
  has(command: string): boolean;
  /** A command run quietly: its exit code and what it printed. */
  run(command: string, args: string[]): { code: number; out: string };
  /** A command run in the terminal, for a sign-in that opens the browser. */
  attach(command: string, args: string[]): number;
}

export const localHost = (): Host => ({
  home: homedir(),
  platform: process.platform,
  env: process.env,
  has: (command) => onPath(command, process.env, process.platform),
  run(command, args) {
    const done = spawnSync(command, args, {
      encoding: "utf8",
      timeout: 120_000,
      shell: process.platform === "win32",
    });
    return { code: done.status ?? 1, out: `${done.stdout ?? ""}${done.stderr ?? ""}` };
  },
  attach: (command, args) =>
    spawnSync(command, args, { stdio: "inherit", shell: process.platform === "win32" }).status ?? 1,
});

export function onPath(command: string, env: NodeJS.ProcessEnv, platform: NodeJS.Platform) {
  const names = platform === "win32" ? [`${command}.cmd`, `${command}.exe`, command] : [command];
  return (env.PATH ?? "")
    .split(delimiter)
    .filter(Boolean)
    .some((dir) => names.some((name) => existsSync(join(dir, name))));
}

export interface ConnectOptions {
  only?: string[];
  key?: string;
  plugins: boolean;
  force: boolean;
  list: boolean;
  dryRun: boolean;
  /** Take out what `connect` added, instead of adding it. */
  remove?: boolean;
  /** With `list`: the same, as JSON. */
  json?: boolean;
}

/** What a tool is told, in one of the ways `Client.add` knows. */
interface Plan {
  how: string;
  steps: [string, string[]][];
}

interface Client {
  id: string;
  name: string;
  /** Whether it is on this computer. */
  found(host: Host): boolean;
  /** Whether Alexein is in it already, under any name. */
  present(host: Host): boolean;
  /** The commands that add it: with the plugin when there is one and plugins are on. */
  plan(host: Host, o: ConnectOptions): Plan | undefined;
  /** Edits a settings file instead of running a command. */
  write?(host: Host, o: ConnectOptions): string;
  /** The commands that take out what `plan` added, of what is here; undefined when none is. */
  removal?(host: Host): Plan | undefined;
  /** Takes the `alexein` entry out of a settings file; undefined when it has none by that name. */
  unwrite?(host: Host): string | undefined;
  /** A sign-in run from the terminal, when the tool has one. */
  login?(o: ConnectOptions): [string, string[]];
  /** Where the person signs in otherwise. */
  signIn: string;
}

const headers = (key: string) => ({ Authorization: `Bearer ${key}`, "X-Alexein-User": "me" });
const headerFlags = (flag: string, key: string) =>
  Object.entries(headers(key)).flatMap(([k, v]) => [flag, `${k}: ${v}`]);
const mentions = (out: string) => /\balexein(-ai)?\b/i.test(out);
/** What steps run, by each command's first words: `claude plugin uninstall`. */
const commands = (steps: [string, string[]][]) =>
  steps.map(([command, args]) => [command, ...args.slice(0, 2)].join(" ")).join(", ");

/** A JSON settings file, or `{}` when it is not there; undefined when it is not JSON. */
function readSettings(path: string): Record<string, unknown> | undefined {
  if (!existsSync(path)) return {};
  try {
    const parsed: unknown = JSON.parse(readFileSync(path, "utf8"));
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : undefined;
  } catch {
    return undefined;
  }
}

/** The servers under `field` in a settings file. */
function servers(path: string, field: string): Record<string, unknown> {
  const value = readSettings(path)?.[field];
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

const hasServer = (path: string, field: string) =>
  Object.keys(servers(path, field)).some((name) => mentions(name));

/** `entry` set as `NAME` under `field`, the rest of the file as it was, and a copy kept. */
function mergeServer(path: string, field: string, entry: Record<string, unknown>): string {
  const settings = readSettings(path);
  if (!settings) throw new Error(`${path} is not valid JSON; fix it, or add Alexein by hand`);
  if (existsSync(path)) copyFileSync(path, `${path}.bak`);
  else mkdirSync(dirname(path), { recursive: true });
  settings[field] = { ...servers(path, field), [NAME]: entry };
  writeFileSync(path, JSON.stringify(settings, null, 2) + "\n");
  return path;
}

/**
 * `NAME` taken out from under `field`, the rest of the file as it was, and a copy kept; undefined
 * when there is no server by that name - one under another name was not added by `connect`.
 */
function dropServer(path: string, field: string): string | undefined {
  const settings = readSettings(path);
  if (!settings) throw new Error(`${path} is not valid JSON; take alexein out by hand`);
  const kept = servers(path, field);
  if (!(NAME in kept)) return undefined;
  copyFileSync(path, `${path}.bak`);
  settings[field] = Object.fromEntries(Object.entries(kept).filter(([name]) => name !== NAME));
  writeFileSync(path, JSON.stringify(settings, null, 2) + "\n");
  return path;
}

function vscodeSettings(host: Host): string {
  if (host.platform === "darwin")
    return join(host.home, "Library", "Application Support", "Code", "User", "mcp.json");
  if (host.platform === "win32")
    return join(
      host.env.APPDATA ?? join(host.home, "AppData", "Roaming"),
      "Code",
      "User",
      "mcp.json",
    );
  return join(host.home, ".config", "Code", "User", "mcp.json");
}

function devinSettings(host: Host): string {
  return host.platform === "win32"
    ? join(host.env.APPDATA ?? join(host.home, "AppData", "Roaming"), "devin", "mcp_config.json")
    : join(host.home, ".config", "devin", "mcp_config.json");
}

const cursorSettings = (host: Host) => join(host.home, ".cursor", "mcp.json");

export const CLIENTS: Client[] = [
  {
    id: "claude-code",
    name: "Claude Code",
    found: (host) => host.has("claude"),
    present: (host) =>
      host.run("claude", ["mcp", "get", NAME]).code === 0 ||
      /alexein@alexein/.test(host.run("claude", ["plugin", "list"]).out),
    plan: (_host, o) =>
      o.plugins && !o.key
        ? {
            how: "the Alexein AI plugin",
            steps: [
              ["claude", ["plugin", "marketplace", "add", "Alexein-AI/claude-plugins"]],
              ["claude", ["plugin", "install", "alexein@alexein"]],
            ],
          }
        : {
            how: "claude mcp add",
            steps: [
              [
                "claude",
                [
                  "mcp",
                  "add",
                  "--transport",
                  "http",
                  "--scope",
                  "user",
                  ...(o.key ? headerFlags("--header", o.key) : []),
                  NAME,
                  URL,
                ],
              ],
            ],
          },
    login: (o) => ["claude", ["mcp", "login", o.plugins && !o.key ? CLAUDE_PLUGIN_SERVER : NAME]],
    signIn: "run /mcp in Claude Code and sign in",
    // The plugin, and the server at the user scope `plan` adds it at: never a project's own.
    removal: (host) => {
      const steps: [string, string[]][] = [];
      if (/alexein@alexein/.test(host.run("claude", ["plugin", "list"]).out))
        steps.push(["claude", ["plugin", "uninstall", "alexein@alexein"]]);
      if (host.run("claude", ["mcp", "get", NAME]).code === 0)
        steps.push(["claude", ["mcp", "remove", "--scope", "user", NAME]]);
      return steps.length ? { how: commands(steps), steps } : undefined;
    },
  },
  {
    id: "cursor",
    name: "Cursor",
    found: (host) => host.has("cursor") || existsSync(join(host.home, ".cursor")),
    present: (host) => hasServer(cursorSettings(host), "mcpServers"),
    plan: () => undefined,
    write: (host, o) =>
      mergeServer(cursorSettings(host), "mcpServers", {
        url: URL,
        ...(o.key ? { headers: headers(o.key) } : {}),
      }),
    signIn: "open Cursor Settings › MCP and select Connect on alexein",
    unwrite: (host) => dropServer(cursorSettings(host), "mcpServers"),
  },
  {
    id: "vscode",
    name: "VS Code",
    found: (host) => host.has("code"),
    present: (host) => hasServer(vscodeSettings(host), "servers"),
    plan: (_host, o) => ({
      how: "code --add-mcp",
      steps: [
        [
          "code",
          [
            "--add-mcp",
            JSON.stringify({
              name: NAME,
              type: "http",
              url: URL,
              ...(o.key ? { headers: headers(o.key) } : {}),
            }),
          ],
        ],
      ],
    }),
    signIn: "run MCP: List Servers, start alexein and allow the sign-in",
    // `code` adds a server but has no command that takes one out: its file is edited instead.
    unwrite: (host) => dropServer(vscodeSettings(host), "servers"),
  },
  {
    id: "copilot",
    name: "GitHub Copilot CLI",
    found: (host) => host.has("copilot"),
    present: (host) => mentions(host.run("copilot", ["mcp", "list"]).out),
    plan: (_host, o) =>
      o.plugins && !o.key
        ? {
            how: "the Alexein AI plugin",
            steps: [
              ["copilot", ["plugin", "marketplace", "add", "Alexein-AI/copilot-plugin"]],
              ["copilot", ["plugin", "install", "alexein-ai@alexein-ai"]],
            ],
          }
        : {
            how: "copilot mcp add",
            steps: [
              [
                "copilot",
                [
                  "mcp",
                  "add",
                  "--transport",
                  "http",
                  ...(o.key ? headerFlags("--header", o.key) : []),
                  NAME,
                  URL,
                ],
              ],
            ],
          },
    signIn: "run /mcp in copilot and authenticate",
    // The plugin's server goes with the plugin: `mcp remove` refuses it.
    removal: (host) =>
      mentions(host.run("copilot", ["plugin", "list"]).out)
        ? {
            how: "copilot plugin uninstall",
            steps: [["copilot", ["plugin", "uninstall", "alexein-ai@alexein-ai"]]],
          }
        : { how: "copilot mcp remove", steps: [["copilot", ["mcp", "remove", NAME]]] },
  },
  {
    id: "codex",
    name: "Codex",
    found: (host) => host.has("codex"),
    present: (host) => mentions(host.run("codex", ["mcp", "list"]).out),
    plan: (_host, o) =>
      o.key
        ? undefined
        : { how: "codex mcp add", steps: [["codex", ["mcp", "add", NAME, "--url", URL]]] },
    login: () => ["codex", ["mcp", "login", NAME]],
    signIn: "run codex mcp login alexein",
    removal: () => ({ how: "codex mcp remove", steps: [["codex", ["mcp", "remove", NAME]]] }),
  },
  {
    id: "gemini",
    name: "Gemini CLI",
    found: (host) => host.has("gemini"),
    present: (host) => mentions(host.run("gemini", ["mcp", "list"]).out),
    plan: (_host, o) => ({
      how: "gemini mcp add",
      steps: [
        [
          "gemini",
          [
            "mcp",
            "add",
            "--transport",
            "http",
            "--scope",
            "user",
            ...(o.key ? headerFlags("--header", o.key) : []),
            NAME,
            URL,
          ],
        ],
      ],
    }),
    signIn: "start Gemini CLI; it opens the sign-in (or run /mcp auth alexein)",
    // The user scope `plan` adds it at: without one, `gemini mcp remove` looks in the project's.
    removal: () => ({
      how: "gemini mcp remove",
      steps: [["gemini", ["mcp", "remove", "--scope", "user", NAME]]],
    }),
  },
  {
    id: "antigravity",
    name: "Antigravity",
    found: (host) => host.has("agy"),
    present: (host) =>
      mentions(host.run("agy", ["plugin", "list"]).out) ||
      mentions(host.run("agy", ["mcp", "list"]).out),
    plan: (_host, o) =>
      o.plugins && !o.key
        ? {
            how: "the Alexein AI plugin",
            steps: [
              ["agy", ["plugin", "install", "https://github.com/Alexein-AI/antigravity-plugin"]],
            ],
          }
        : {
            how: "agy mcp add",
            steps: [
              ["agy", ["mcp", "add", ...(o.key ? headerFlags("--header", o.key) : []), NAME, URL]],
            ],
          },
    signIn: "open /plugin in Antigravity, expand alexein-ai and choose Sign in",
    // The plugin, by its name. A server alone is taken out in Antigravity's settings: its CLI
    // documents no command for that.
    removal: (host) =>
      mentions(host.run("agy", ["plugin", "list"]).out)
        ? {
            how: "agy plugin uninstall",
            steps: [["agy", ["plugin", "uninstall", "alexein-ai"]]],
          }
        : undefined,
  },
  {
    id: "devin",
    name: "Devin Desktop",
    found: (host) => host.has("devin") || existsSync(dirname(devinSettings(host))),
    present: (host) => hasServer(devinSettings(host), "mcpServers"),
    plan: (host, o) =>
      host.has("devin") && !o.key
        ? { how: "devin mcp add", steps: [["devin", ["mcp", "add", NAME, URL, "-s", "user"]]] }
        : undefined,
    write: (host, o) =>
      mergeServer(devinSettings(host), "mcpServers", {
        url: URL,
        transport: "http",
        ...(o.key ? { headers: headers(o.key) } : {}),
      }),
    signIn: "open Customize › MCPs and select Authenticate on alexein",
    // Its CLI where it has it, at the user scope `plan` adds it at: that writes the file `present`
    // reads, which is edited instead without the CLI.
    removal: (host) =>
      host.has("devin") && NAME in servers(devinSettings(host), "mcpServers")
        ? {
            how: "devin mcp remove",
            steps: [["devin", ["mcp", "remove", "-s", "user", NAME]]],
          }
        : undefined,
    unwrite: (host) => dropServer(devinSettings(host), "mcpServers"),
  },
];

/** The tool names' column, for the sign-in lines. */
const WIDTH = Math.max(...CLIENTS.map((c) => c.name.length)) + 2;

/** The chat apps, which are added from the app itself. */
const ELSEWHERE = "claude.ai, Claude Desktop and ChatGPT: add Alexein from the app";

/** 0 when every tool asked for was set up or already had Alexein; 1 when any failed. */
export async function connect(
  o: ConnectOptions,
  console: Console,
  host: Host = localHost(),
): Promise<number> {
  const unknown = (o.only ?? []).filter((id) => !CLIENTS.some((c) => c.id === id));
  if (unknown.length) {
    console.fail(
      `no tool called ${unknown.join(", ")}; there is: ${CLIENTS.map((c) => c.id).join(", ")}`,
    );
    return 2;
  }
  const asked = CLIENTS.filter((c) => !o.only?.length || o.only.includes(c.id));
  const found = asked.filter((c) => c.found(host));
  if (o.json) {
    const present = new Set(found.filter((c) => c.present(host)).map((c) => c.id));
    const tools = asked.map((c) => ({
      id: c.id,
      name: c.name,
      found: found.includes(c),
      added: found.includes(c) ? present.has(c.id) : null,
    }));
    console.line(JSON.stringify({ tools }, null, 2));
    return 0;
  }
  console.line(`@alexein/cli ${VERSION} - Alexein AI for the AI tools on this computer`);
  console.line();
  if (!found.length) {
    console.line("  No AI tools found that connect from here.");
    console.line(`  ${ELSEWHERE}: ${DOCS}`);
    return o.only?.length ? 1 : 0;
  }
  const present = new Set(found.filter((c) => c.present(host)).map((c) => c.id));
  for (const c of found) console.step(present.has(c.id) ? "has" : "found", c.name);
  for (const c of asked.filter((c) => !found.includes(c))) console.step("missing", c.name);
  console.line();
  if (o.list) return 0;
  if (o.remove)
    return remove(
      found.filter((c) => present.has(c.id)),
      o,
      console,
      host,
    );

  const todo = found.filter((c) => o.force || !present.has(c.id));
  if (!todo.length) {
    console.line("  Every tool found has Alexein already. --force adds it again.");
    return 0;
  }
  const names = todo.map((c) => c.name).join(", ");
  if (!o.dryRun && !(await console.confirm(`Add Alexein AI to ${names}?`))) {
    console.line(
      console.interactive
        ? "  Nothing changed."
        : "  Nothing changed: run it at a terminal, or pass --yes.",
    );
    return 1;
  }

  let failed = 0;
  const signIns: Client[] = [];
  for (const c of todo) {
    const plan = c.plan(host, o);
    if (!plan && !c.write) {
      console.step("skipped", `${c.name}: a key goes in its settings by hand - see ${DOCS}`);
      continue;
    }
    if (o.dryRun) {
      console.step(
        "would",
        `add ${c.name}, with ${plan ? plan.steps.map(([cmd, args]) => shown(cmd, args, o.key)).join(" && ") : "an entry in its settings"}`,
      );
      continue;
    }
    try {
      let how: string;
      if (plan) {
        for (const [command, args] of plan.steps) {
          const done = host.run(command, args);
          // A marketplace already added is fine: the install after it is what matters.
          if (done.code !== 0 && !(args.includes("marketplace") && /already/i.test(done.out)))
            throw new Error(lastLine(done.out) || `${command} ${args[0]} failed`);
        }
        how = plan.how;
      } else how = c.write!(host, o).replace(host.home, "~");
      console.step("added", `${c.name} (${how})`);
      if (!o.key) signIns.push(c);
    } catch (error) {
      failed++;
      console.step("failed", `${c.name}: ${(error as Error).message}`);
    }
  }
  if (o.dryRun) return 0;

  if (signIns.length) {
    console.line();
    console.line("  Sign in to Alexein from each, and keep Read and save so it can save:");
    for (const c of signIns) {
      if (c.login && console.interactive && (await console.confirm(`Sign in to ${c.name} now?`))) {
        if (host.attach(...c.login(o)) === 0) {
          console.step("signed in", c.name);
          continue;
        }
      }
      console.line(`  ${c.name.padEnd(WIDTH)}${c.signIn}`);
    }
  }
  console.line();
  console.line(`  ${ELSEWHERE}: ${DOCS}`);
  return failed ? 1 : 0;
}

/**
 * `--remove`: what `connect` added taken out of each tool in `todo`, the ones that have Alexein -
 * the plugin, the `alexein` server, or its settings entry. A server under another name was not
 * added here and is left, with a line saying so. Memory and the tool's sign-in are untouched.
 */
async function remove(
  todo: Client[],
  o: ConnectOptions,
  console: Console,
  host: Host,
): Promise<number> {
  if (!todo.length) {
    console.line("  No tool found has Alexein: nothing to take out.");
    return 0;
  }
  const names = todo.map((c) => c.name).join(", ");
  if (!o.dryRun && !(await console.confirm(`Take Alexein AI out of ${names}?`))) {
    console.line(
      console.interactive
        ? "  Nothing changed."
        : "  Nothing changed: run it at a terminal, or pass --yes.",
    );
    return 1;
  }
  const byHand = (c: Client) =>
    console.step("skipped", `${c.name}: take Alexein out in its own settings`);
  let failed = 0;
  for (const c of todo) {
    try {
      const plan = c.removal?.(host);
      if (!plan && !c.unwrite) {
        byHand(c);
        continue;
      }
      if (o.dryRun) {
        console.step(
          "would",
          `remove ${c.name}, with ${plan ? plan.steps.map(([cmd, args]) => shown(cmd, args)).join(" && ") : "its alexein entry taken out of its settings"}`,
        );
        continue;
      }
      let how: string | undefined;
      if (plan) {
        for (const [command, args] of plan.steps) {
          const done = host.run(command, args);
          if (done.code !== 0)
            throw new Error(lastLine(done.out) || `${command} ${args[0]} failed`);
        }
        how = plan.how;
      } else how = c.unwrite!(host)?.replace(host.home, "~");
      if (how === undefined) byHand(c);
      else console.step("removed", `${c.name} (${how})`);
    } catch (error) {
      failed++;
      console.step("failed", `${c.name}: ${(error as Error).message}`);
    }
  }
  if (o.dryRun) return 0;
  console.line();
  console.line(
    "  Your memory is as it was. To end a tool's sign-in too, disconnect it in My memory.",
  );
  return failed ? 1 : 0;
}

function lastLine(out: string): string {
  return out.trim().split("\n").filter(Boolean).at(-1)?.trim() ?? "";
}

/** A command as it would be typed, with the key masked. */
function shown(command: string, args: string[], key?: string): string {
  const masked = args.map((a) => (key ? a.replaceAll(key, "tm_***") : a));
  return [command, ...masked.map((a) => (/[\s"{}]/.test(a) ? `'${a}'` : a))].join(" ");
}
