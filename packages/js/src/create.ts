/**
 * `twinmemory-cli create <framework> <name>`: a new project with memory already wired in - for
 * LangGraph.js a graph, a terminal chat, `langgraph.json` for `langgraph dev`; for the OpenAI
 * Agents SDK an agent and a terminal chat; and `memory.ts` as `init` writes it - so there is
 * something to run before there is anything to wire.
 *
 * The project is an npm one, in TypeScript, run with tsx.
 */

import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

import * as env from "./env.js";
import { render } from "./render.js";
import * as scaffold from "./scaffold.js";
import type { Console } from "./ui.js";

/**
 * LangGraph's, as `initChatModel` names it. The OpenAI Agents SDK has a default of its own, which
 * an agent gets when it names none.
 */
export const DEFAULT_MODEL = "anthropic:claude-sonnet-5-5";

/**
 * The LangChain package each `initChatModel` provider needs, and the key it reads. A provider not
 * named here still works; its package and key are the developer's to add.
 */
export const PROVIDERS: Record<string, [string, string]> = {
  anthropic: ["@langchain/anthropic", "ANTHROPIC_API_KEY"],
  openai: ["@langchain/openai", "OPENAI_API_KEY"],
  azure_openai: ["@langchain/openai", "AZURE_OPENAI_API_KEY"],
  "google-genai": ["@langchain/google-genai", "GOOGLE_API_KEY"],
  google_genai: ["@langchain/google-genai", "GOOGLE_API_KEY"],
  mistralai: ["@langchain/mistralai", "MISTRAL_API_KEY"],
  groq: ["@langchain/groq", "GROQ_API_KEY"],
  ollama: ["@langchain/ollama", ""],
  bedrock: ["@langchain/aws", ""],
};

const NAME = /^[a-z][a-z0-9-]{0,63}$/;
const DEV = ["typescript", "tsx", "@types/node"];
/** The file each framework's project is built around, beside `memory.ts` and `chat.ts`. */
const MAIN: Record<string, string> = { langgraph: "graph.ts", "openai-agents": "agent.ts" };

/** Make the project; 0 when it is ready, 1 when something stopped it, 2 a bad command. */
export async function create(
  name: string,
  cwd: string,
  model: string,
  o: scaffold.Options,
  console: Console,
): Promise<number> {
  if (!NAME.test(name)) {
    console.fail(
      `${JSON.stringify(name)} is not a project name: lowercase letters, digits and '-', starting with a letter`,
    );
    return 2;
  }
  const root = resolve(cwd, name);
  if (existsSync(root) && readdirSync(root).length) {
    console.fail(`${root} exists and is not empty. Nothing changed.`);
    return 1;
  }
  const langgraph = o.framework === "langgraph";
  const provider = langgraph && model.includes(":") ? model.split(":")[0]! : "";
  const [library, providerKey] = langgraph
    ? (PROVIDERS[provider] ?? ["", ""])
    : ["", "OPENAI_API_KEY"];
  const packages = [
    ...Object.entries(scaffold.MINIMUMS[o.framework]!).map(([n, m]) =>
      n === "twinmemory" && o.sdk ? o.sdk : `${n}@>=${m}`,
    ),
    ...(langgraph ? ["langchain@>=1.0"] : []),
    "dotenv",
    ...(library ? [library] : []),
  ];
  const commands = [
    ["npm", "install", ...packages],
    ["npm", "install", "--save-dev", ...DEV, ...(langgraph ? ["@langchain/langgraph-cli"] : [])],
  ];
  if (o.dryRun) {
    console.step("would", `make ${root}`);
    for (const path of [
      "package.json",
      "tsconfig.json",
      ...(langgraph ? ["langgraph.json"] : []),
      "README.md",
      ".gitignore",
      ".env",
    ]) {
      console.step("would", `write ${path}`);
    }
    for (const path of [MAIN[o.framework]!, "chat.ts", "memory.ts"])
      console.step("would", `write src/${path}`);
    for (const command of commands)
      console.step("would", `${o.install ? "run" : "print"} ${quoted(command)}`);
    console.line();
    console.line("Dry run: nothing was made.");
    return 0;
  }
  skeleton(root, name, model, providerKey, o);
  console.step("made", root);
  scaffold.write(join(root, "src"), { ...o, filename: "memory.ts" });
  console.step("wrote", `src/memory.ts, ${MAIN[o.framework]}, chat.ts`);
  let installed = true;
  for (const command of commands) {
    if (!o.install) {
      console.step("run", quoted(command));
      continue;
    }
    console.step("running", quoted(command));
    if (o.run(command, root) !== 0) {
      console.fail(`\`${quoted(command)}\` failed; run it in ${root} yourself, then go on.`);
      installed = false;
      break;
    }
    console.step("ran", quoted(command));
  }
  if (langgraph && !library)
    console.step("note", `add the LangChain package for ${JSON.stringify(model)} yourself`);
  await scaffold.setupKey(root, o, console);
  const { key } = env.resolveKey(root);
  const unset = [...(providerKey ? [providerKey] : []), ...(key ? [] : [env.KEY])];
  console.line();
  console.line(next(name, unset, langgraph));
  return installed ? 0 : 1;
}

function quoted(command: string[]): string {
  return command.map((word) => (/[>]/.test(word) ? `'${word}'` : word)).join(" ");
}

/** The graph's parts, from the file's: which of nodes and tools, or both. */
export function preset(o: scaffold.Options): string[] {
  const nodes = o.parts.includes("nodes");
  const tools = o.parts.includes("tools");
  return [
    ...(nodes ? ["nodes"] : []),
    ...(tools ? ["tools"] : []),
    nodes && tools ? "both" : nodes ? "nodes_only" : "tools_only",
  ];
}

function skeleton(
  root: string,
  name: string,
  model: string,
  providerKey: string,
  o: scaffold.Options,
): void {
  const values = { name, model, provider_key: providerKey };
  const parts = preset(o);
  const langgraph = o.framework === "langgraph";
  const envParts = langgraph
    ? providerKey
      ? ["provider_key"]
      : []
    : model
      ? ["model"]
      : ["no_model"];
  const files: Record<string, [string, string[]]> = {
    "package.json": ["package.json.tmpl", []],
    "tsconfig.json": ["tsconfig.json.tmpl", []],
    ...(langgraph ? { "langgraph.json": ["langgraph.json.tmpl", []] as [string, string[]] } : {}),
    ".gitignore": ["gitignore.tmpl", []],
    "README.md": ["README.md.tmpl", []],
    ".env.example": ["env.example.tmpl", envParts],
    [`src/${MAIN[o.framework]}`]: [`${MAIN[o.framework]}.tmpl`, parts],
    "src/chat.ts": ["chat.ts.tmpl", parts],
  };
  const directory = `${o.framework.replace("-", "_")}/project`;
  for (const [path, [template, kept]] of Object.entries(files)) {
    const target = join(root, path);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(target, render(`${directory}/${template}`, kept, values));
  }
  const example = render(`${directory}/env.example.tmpl`, envParts, values);
  writeFileSync(
    join(root, ".env"),
    example
      .split("\n")
      .filter((line) => line && !line.startsWith("#"))
      .join("\n") + "\n",
  );
}

function next(name: string, unset: string[], langgraph: boolean): string {
  return [
    "  Next:",
    "",
    `    cd ${name}`,
    ...(unset.length ? [`    # fill in ${unset.join(" and ")} in .env`] : []),
    "    npm run chat -- --user dana       # talk to it",
    ...(langgraph
      ? ["    npm run dev                       # or open it in LangGraph Studio"]
      : []),
    "    npx twinmemory-cli doctor         # check the setup",
  ].join("\n");
}
