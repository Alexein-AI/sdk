/**
 * `twinmemory-cli`, in the manner of shadcn: what it writes is the developer's own code from then
 * on, readable and editable, and nothing in this package reaches back into it.
 *
 *     twinmemory-cli init langgraph       memory for a LangGraph.js project you have
 *     twinmemory-cli create langgraph X   a new LangGraph.js project with memory wired in
 *     twinmemory-cli doctor               whether a project is set up for memory
 *
 * Node's standard library and the `twinmemory` client only. Never an installer of anything but the
 * packages the written files import, and never a writer of a key it was not given.
 */

import { parseArgs } from "node:util";

import { create, DEFAULT_MODEL } from "./create.js";
import { doctor } from "./doctor.js";
import { init, options, PARTS, type Part } from "./scaffold.js";
import { Console } from "./ui.js";
import { VERSION } from "./version.js";

const HELP = `twinmemory-cli ${VERSION} - twin memory for LangGraph.js, as code you own

Usage:
  twinmemory-cli init langgraph [options]          write memory into this project
  twinmemory-cli create langgraph <name> [options] a new project with memory wired in
  twinmemory-cli doctor                            check this project is set up for memory

What the memory file holds:
  --nodes-only          recall and remember, no tools
  --tools-only          tools for the model, no nodes
  --fast                search without the model filter: free, quicker

The key (all of it can be skipped, and done later):
  --key <key>           your API key, written into .env and checked
  --base-url <url>      memory's address, if not the hosted service
  --skip-key            do not ask for a key

init only:
  --dir <dir>           where to write the file (default: found)
  --file <name>         the file's name (default: memory.ts)
  --graph <name>        which graph in langgraph.json it is for
  --force               replace a file already there

create only:
  --model <model>       initChatModel's name for it (default: ${DEFAULT_MODEL})

  --yes, -y             answer yes; ask nothing
  --no-install          print install commands instead of running them
  --dry-run             check everything, say what would happen, change nothing
  --version, --help`;

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
  // Installs the client from a path instead of npm, while it is not published there.
  sdk: { type: "string" },
  version: { type: "boolean" },
  help: { type: "boolean", short: "h" },
} as const;

export async function main(argv: string[], given?: Console): Promise<number> {
  let parsed;
  try {
    parsed = parseArgs({ args: argv, options: FLAGS, allowPositionals: true, strict: true });
  } catch (error) {
    process.stderr.write(`twinmemory-cli: ${(error as Error).message}\n\n${HELP}\n`);
    return 2;
  }
  const { values: v, positionals } = parsed;
  if (v.version) {
    (given ?? new Console()).line(`twinmemory-cli ${VERSION}`);
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
    if (framework !== "langgraph") {
      console.fail(`no template for ${JSON.stringify(framework ?? "")}; there is: langgraph`);
      return 2;
    }
    if (!name) {
      console.fail("create needs the new project's name: twinmemory-cli create langgraph <name>");
      return 2;
    }
    return create(name, cwd, v.model ?? DEFAULT_MODEL, o, console);
  }
  console.fail(`no command ${JSON.stringify(command)}: init, create or doctor`);
  return 2;
}
