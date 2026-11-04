/**
 * `@alexein/cli` (the `alexein-cli` command), in the manner of shadcn: what it writes is the
 * developer's own code from then on, readable and editable, and nothing in this package reaches
 * back into it. The memory itself comes from `@alexein/sdk`, which the written file imports.
 *
 *     npx @alexein/cli init langgraph          memory for a LangGraph.js project you have
 *     npx @alexein/cli init openai-agents      ... or an OpenAI Agents SDK one
 *     npx @alexein/cli create <framework> X    a new project with memory wired in
 *     npx @alexein/cli doctor                  whether a project is set up for memory
 *
 * Node's standard library and `@alexein/sdk` only. Never an installer of anything but the
 * packages the written files import, and never a writer of a key it was not given.
 */

import { parseArgs } from "node:util";

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
  npx @alexein/cli doctor                              check this project is set up for memory

  <framework> is langgraph or openai-agents.

What the wiring uses:
  --nodes-only          recall and remember, no tools
  --tools-only          tools for the model, no recall or remember
  --fast                searches skip the relevance check: free and quicker

The key (all of it can be skipped, and done later):
  --key <key>           your API key, written into .env as ALEXEIN_API_KEY and checked
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
  sdk: { type: "string" },
  version: { type: "boolean" },
  help: { type: "boolean", short: "h" },
} as const;

export async function main(argv: string[], given?: Console): Promise<number> {
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
  if (command === "doctor") return doctor(cwd, given ?? Console.forTerminal(true));
  const console = given ?? Console.forTerminal(Boolean(v.yes));
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
    key: v.key,
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
  console.fail(`no command ${JSON.stringify(command)}: init, create or doctor`);
  return 2;
}
