/**
 * `@alexein/cli` (the `alexein-cli` command), in the manner of shadcn: what it writes is the
 * developer's own code from then on, readable and editable, and nothing in this package reaches
 * back into it. The memory itself comes from `@alexein/sdk`, which the written file imports.
 *
 *     npx @alexein/cli init langgraph          memory for a LangGraph.js project you have
 *     npx @alexein/cli init openai-agents      ... or an OpenAI Agents SDK one
 *     npx @alexein/cli create <framework> X    a new project with memory wired in
 *     npx @alexein/cli doctor                  whether a project is set up for memory
 *     npx @alexein/cli connect                 Alexein AI in the AI tools on this computer
 *     npx @alexein/cli connect --remove        ... and out of them again
 *
 * Node's standard library and `@alexein/sdk` only. Never an installer of anything but the
 * packages the written files import, and never a writer of a key it was not given.
 */

import { readFileSync } from "node:fs";
import { parseArgs } from "node:util";

import { connect } from "./connect.js";
import { create, DEFAULT_MODEL } from "./create.js";
import { doctor } from "./doctor.js";
import { init, MINIMUMS, options, PARTS, type Part } from "./scaffold.js";
import { Console } from "./ui.js";
import { VERSION } from "./version.js";

const HELP = `@alexein/cli ${VERSION} - memory from Alexein for LangGraph.js and the
OpenAI Agents SDK, wired in as code you own

Usage:
  npx @alexein/cli init <framework> [options]          write memory.ts into this project
  npx @alexein/cli create <framework> <name> [options] a new project with memory wired in
  npx @alexein/cli doctor [--json]                     check this project is set up for memory
  npx @alexein/cli connect [options]                   add Alexein AI to Claude Code, Cursor,
                                                       VS Code, Copilot CLI, Codex, Gemini CLI,
                                                       Antigravity and Devin Desktop

  <framework> is langgraph or openai-agents.

connect only:
  --only <tools>        just these, comma-separated: claude-code, cursor, vscode, copilot,
                        codex, gemini, antigravity, devin
  --no-plugin           add the server alone, not Alexein AI's plugin where a tool has one
  --list                say which tools are here and which have Alexein; change nothing
  --json                with --list (or doctor): the same, as JSON
  --remove              take out what connect added: the plugin, the server or its entry
  --key <key>           send this key in a header instead of signing in (for CI), no plugins
  --force               add it again where Alexein is already

What the wiring uses:
  --nodes-only          recall and remember, no tools
  --tools-only          tools for the model, no recall or remember
  --fast                searches skip the relevance check: free and quicker

The key (all of it can be skipped, and done later):
  --key <key>           your API key, written into .env as ALEXEIN_API_KEY and checked;
                        --key - reads it from stdin, so it stays out of your shell history
  --base-url <url>      memory's address, written into .env as ALEXEIN_API_URL
  --skip-key            do not ask for a key

init only:
  --dir <dir>           where to write the file (default: found)
  --file <name>         the file's name (default: memory.ts)
  --graph <name>        which graph in langgraph.json it is for (langgraph)
  --force               replace a file already there

create only:
  --model <model>       the model: initChatModel's name for it with langgraph (default:
                        ${DEFAULT_MODEL}); the SDK's with openai-agents (default: its own)

  --yes, -y             answer yes; ask nothing
  --no-install          print install commands instead of running them
  --dry-run             check everything, say what would happen, change nothing
  --version, --help`;

// `sdk` is for development only: it installs @alexein/sdk from a path or tarball instead of npm,
// and `--help` leaves it out. Its note sits here, not beside it, so the bundle does not carry it.
const FLAGS = {
  "nodes-only": { type: "boolean" },
  "tools-only": { type: "boolean" },
  fast: { type: "boolean" },
  key: { type: "string" },
  "base-url": { type: "string" },
  "skip-key": { type: "boolean" },
  dir: { type: "string" },
  file: { type: "string" },
  graph: { type: "string" },
  force: { type: "boolean" },
  model: { type: "string" },
  yes: { type: "boolean", short: "y" },
  "no-install": { type: "boolean" },
  "dry-run": { type: "boolean" },
  only: { type: "string" },
  "no-plugin": { type: "boolean" },
  list: { type: "boolean" },
  json: { type: "boolean" },
  remove: { type: "boolean" },
  sdk: { type: "string" },
  version: { type: "boolean" },
  help: { type: "boolean", short: "h" },
} as const;

/**
 * The key `--key` gives: `-` reads it from the first line of stdin, so it is in no shell's history.
 * Throws when `-` brings nothing.
 */
export function keyFrom(
  given: string | undefined,
  read: () => string | undefined,
): string | undefined {
  if (given !== "-") return given;
  const key = read()?.split("\n")[0]?.trim();
  if (!key) throw new Error("--key - reads the key from stdin, and none came: pipe it in");
  return key;
}

/** What was piped in; nothing at a terminal, where reading would wait for the key, echoed. */
function readStdin(): string | undefined {
  return process.stdin.isTTY ? undefined : readFileSync(0, "utf8");
}

export async function main(
  argv: string[],
  given?: Console,
  stdin: () => string | undefined = readStdin,
): Promise<number> {
  let parsed;
  try {
    parsed = parseArgs({ args: argv, options: FLAGS, allowPositionals: true, strict: true });
  } catch (error) {
    process.stderr.write(`@alexein/cli: ${(error as Error).message}\n\n${HELP}\n`);
    return 2;
  }
  const { values: v, positionals } = parsed;
  if (v.version) {
    (given ?? new Console()).line(`@alexein/cli ${VERSION}`);
    return 0;
  }
  const [command, framework, name] = positionals;
  if (v.help || !command) {
    (given ?? new Console()).line(HELP);
    return command || v.help ? 0 : 2;
  }
  const cwd = process.cwd();
  if (v.json && command !== "doctor" && !(command === "connect" && v.list)) {
    (given ?? new Console()).fail("--json is for doctor and connect --list");
    return 2;
  }
  if (command === "doctor")
    return doctor(cwd, given ?? Console.forTerminal(true), undefined, Boolean(v.json));
  const console = given ?? Console.forTerminal(Boolean(v.yes));
  let key: string | undefined;
  try {
    key = keyFrom(v.key, stdin);
  } catch (error) {
    console.fail((error as Error).message);
    return 2;
  }
  if (command === "connect") {
    if (v.remove && (v.key || v["no-plugin"] || v.force || v.list)) {
      console.fail("--remove goes with --only, --dry-run and --yes");
      return 2;
    }
    const only = v.only
      ?.split(",")
      .map((id) => id.trim())
      .filter(Boolean);
    return connect(
      {
        only,
        key,
        plugins: !v["no-plugin"],
        force: Boolean(v.force),
        list: Boolean(v.list),
        dryRun: Boolean(v["dry-run"]),
        remove: Boolean(v.remove),
        json: Boolean(v.json),
      },
      console,
    );
  }
  if (v["nodes-only"] && v["tools-only"]) {
    console.fail("--nodes-only and --tools-only: pick one");
    return 2;
  }
  const parts: readonly Part[] = v["nodes-only"] ? ["nodes"] : v["tools-only"] ? ["tools"] : PARTS;
  const o = options({
    framework: framework ?? "",
    directory: v.dir,
    filename: v.file ?? "memory.ts",
    graph: v.graph,
    force: Boolean(v.force),
    install: !v["no-install"],
    parts,
    fast: Boolean(v.fast),
    key,
    baseUrl: v["base-url"],
    skipKey: Boolean(v["skip-key"] || v.yes),
    sdk: v.sdk,
    dryRun: Boolean(v["dry-run"]),
  });
  if (command === "init") return init(cwd, o, console);
  if (command === "create") {
    if (!framework || !(framework in MINIMUMS)) {
      const known = Object.keys(MINIMUMS).join(", ");
      console.fail(`no template for ${JSON.stringify(framework ?? "")}; there is: ${known}`);
      return 2;
    }
    if (!name) {
      console.fail(
        `create needs the new project's name: npx @alexein/cli create ${framework} <name>`,
      );
      return 2;
    }
    const model = v.model ?? (framework === "langgraph" ? DEFAULT_MODEL : "");
    return create(name, cwd, model, o, console);
  }
  console.fail(`no command ${JSON.stringify(command)}: init, create, doctor or connect`);
  return 2;
}
