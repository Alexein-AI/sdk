/**
 * `@alexein/cli init openai-agents`, `create openai-agents` and `doctor` on what they make: where
 * the file goes, what is checked and installed, and the created agent run as written, with a
 * scripted model, through the real `@alexein/sdk`, against a recorded memory API.
 */

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { setTracingDisabled } from "@openai/agents";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { main } from "../src/cli.js";
import { create } from "../src/create.js";
import { doctor } from "../src/doctor.js";
import * as env from "../src/env.js";
import { calls, says, Scripted } from "./agents.js";
import { GENERATED as ALL_GENERATED, Project, quiet, said } from "./helpers.js";
import { bodies, routes, serve, users, writeMemoryFile } from "./recorded.js";
import { VERSION } from "../src/version.js";

/** This file's own corner, so files running in parallel never remove each other's. */
const GENERATED = ALL_GENERATED + "openai-agents-cli/";
const AGENT =
  'import { Agent, run } from "@openai/agents";\n\nconst a = new Agent({ name: "S" });\n';

const projects: Project[] = [];
afterEach(() => {
  projects.splice(0).forEach((p) => p.remove());
});
afterAll(() => rmSync(GENERATED, { recursive: true, force: true }));
beforeAll(() => setTracingDisabled(true));

function project(deps: Record<string, string> = { "@openai/agents": "^0.21.0" }): Project {
  const p = Project.scratch();
  projects.push(p);
  return p.npm(deps);
}

const init = (p: Project, given: Parameters<Project["init"]>[0] = {}) =>
  p.init({ framework: "openai-agents", ...given });

// ------------------------------------------------------------------------- where it goes --

describe("init openai-agents: where it writes", () => {
  it("writes beside the file that builds the agent", async () => {
    const p = project().file("src/support/bot.ts", AGENT);

    const [code, console] = await init(p);

    expect(code).toBe(0);
    const written = readFileSync(join(p.root, "src/support/memory.ts"), "utf8");
    expect(written).toContain(`\`npx @alexein/cli init openai-agents\` (@alexein/cli ${VERSION})`);
    expect(written).toContain('import { AlexeinMemory } from "@alexein/sdk/openai-agents";');
    expect(written).not.toContain("// >>>");
    expect(p.ran).toEqual([["npm", "install", "@alexein/sdk@>=0.3", "zod@>=4.0"]]);
    const text = said(console);
    expect(text).toContain('import { memory, type MemoryContext } from "./memory.js";');
    expect(text).toContain(
      'const agent = new Agent({ name: "Assistant", tools: memory.tools() });',
    );
    expect(text).toContain("callModelInputFilter: memory.recall,");
    expect(text).toContain("await memory.remember(result);");
  });

  it("finds Agent.create, and a require", async () => {
    const p = project().file(
      "bots/main.js",
      'const { Agent } = require("@openai/agents");\nAgent.create({ name: "a" });\n',
    );
    await init(p);
    expect(existsSync(join(p.root, "bots/memory.ts"))).toBe(true);
  });

  it("stops naming them when several build an agent and nobody can be asked", async () => {
    const p = project().file("a/bot.ts", AGENT).file("b/bot.ts", AGENT);
    const [code, console] = await init(p);
    expect(code).toBe(1);
    expect(said(console)).toContain("2 directories build an Agent (./a, ./b); name one with --dir");
  });

  it("asks which at a terminal", async () => {
    const p = project().file("a/bot.ts", AGENT).file("b/bot.ts", AGENT);
    await init(p, { console: quiet({ interactive: true, answers: ["2"] }) });
    expect(existsSync(join(p.root, "b/memory.ts"))).toBe(true);
  });

  it("goes in src/ when it finds no agent, and says so", async () => {
    const p = project().file("src/index.ts", "export {};\n");
    const [, console] = await init(p);
    expect(existsSync(join(p.root, "src/memory.ts"))).toBe(true);
    expect(said(console)).toContain("found no file that builds an Agent");
  });

  it("does not take a memory file it wrote for an agent", async () => {
    const p = project().file("app/bot.ts", AGENT);
    await init(p);
    const [code] = await init(p, { force: true });
    expect(code).toBe(0);
    expect(existsSync(join(p.root, "app/memory.ts"))).toBe(true);
  });

  it("refuses --graph, which is LangGraph's", async () => {
    const [code, console] = await init(project(), { graph: "agent" });
    expect(code).toBe(2);
    expect(said(console)).toContain("--graph is for langgraph");
  });
});

// --------------------------------------------------------------- the SDK, new enough --

describe("init openai-agents: the SDK there, new enough", () => {
  it("stops in a project without it, unless told", async () => {
    const p = project({});
    const [code, console] = await init(p);
    expect(code).toBe(1);
    expect(said(console)).toContain("does not use the OpenAI Agents SDK;");
    expect(said(console)).toContain("npx @alexein/cli create openai-agents <name>");

    const [yes] = await init(p, { console: quiet({ yes: true }) });
    expect(yes).toBe(0);
    expect(p.ran).toEqual([
      ["npm", "install", "@alexein/sdk@>=0.3", "@openai/agents@>=0.21", "zod@>=4.0"],
    ]);
  });

  it("takes an import of it as enough", async () => {
    const p = project({}).file("bot.ts", AGENT);
    expect((await init(p))[0]).toBe(0);
  });

  it("stops at an old SDK with the upgrade", async () => {
    const p = project().installed({ "@openai/agents": "0.6.3" });
    const [code, console] = await init(p);
    expect(code).toBe(1);
    expect(said(console)).toContain("@openai/agents 0.6.3 (needs >=0.21)");
  });

  it("is run from the command line", async () => {
    const p = project();
    const cwd = vi.spyOn(process, "cwd").mockReturnValue(p.root);
    const argv = ["init", "openai-agents", "--no-install", "--nodes-only", "--yes"];
    expect(await main(argv, quiet())).toBe(0);
    const written = readFileSync(join(p.root, "memory.ts"), "utf8");
    expect(written).toContain("memory.recall");
    expect(written).not.toContain("memory.tools");
    cwd.mockRestore();
  });
});

// ------------------------------------------------------------------------------ doctor --

describe("doctor, for an OpenAI Agents SDK memory file", () => {
  it("checks the SDK and not LangGraph", async () => {
    const p = project({ "@openai/agents": "^0.21.0", "@alexein/sdk": "^0.3.0", zod: "^4.0.0" })
      .installed({ "@openai/agents": "0.6.0", "@alexein/sdk": "0.3.0", zod: "4.1.0" })
      .file(".env", `${env.KEY}=tm_x\n`)
      .file(".gitignore", ".env\n");
    p.file(
      "memory.ts",
      readFileSync(
        writeMemoryFile(GENERATED, "openai_agents/memory.ts.tmpl", { parts: ["nodes"] }),
        "utf8",
      ),
    );
    const console = quiet();

    expect(await doctor(p.root, console, async () => p.check)).toBe(1);

    const text = said(console);
    expect(text).toContain("✓ memory file memory.ts (written by 0.3.0)");
    expect(text).toContain("✓ dependencies: @alexein/sdk, @openai/agents, zod");
    expect(text).toContain("✗ @openai/agents 0.6.0 is older than 0.21");
    expect(text).not.toContain("langgraph");
  });
});

// ------------------------------------------------------------------------------ create --

function made(given: { model?: string; inside?: string } & Record<string, unknown> = {}) {
  const { model = "", inside, ...rest } = given;
  const p = Project.scratch(inside);
  projects.push(p);
  const console = quiet();
  const o = p.options({ framework: "openai-agents", ...rest });
  return create("my-agent", p.root, model, o, console).then((code) => ({
    code,
    console,
    p,
    root: join(p.root, "my-agent"),
  }));
}

describe("create openai-agents", () => {
  it("makes a project with memory wired in", async () => {
    const { code, console, p, root } = await made();
    expect(code).toBe(0);
    for (const path of [
      "package.json",
      "tsconfig.json",
      "README.md",
      ".gitignore",
      ".env",
      ".env.example",
      "src/agent.ts",
      "src/chat.ts",
      "src/memory.ts",
    ]) {
      expect(existsSync(join(root, path)), path).toBe(true);
    }
    expect(existsSync(join(root, "langgraph.json"))).toBe(false);
    expect(env.read(join(root, ".env"))).toEqual({ MODEL: "", OPENAI_API_KEY: "", [env.KEY]: "" });
    expect(p.ran).toEqual([
      ["npm", "install", "@alexein/sdk@>=0.3", "@openai/agents@>=0.21", "zod@>=4.0", "dotenv"],
      ["npm", "install", "--save-dev", "typescript", "tsx", "@types/node"],
    ]);
    const text = said(console);
    expect(text).toContain("fill in OPENAI_API_KEY and ALEXEIN_API_KEY in .env");
    expect(text).toContain("npx @alexein/cli doctor");
    expect(readFileSync(join(root, "src/agent.ts"), "utf8")).toContain(
      'import { memory, type MemoryContext } from "./memory.js";',
    );
    expect(text).toContain("npm run chat -- --user dana");
    expect(text).not.toContain("LangGraph");
  });

  it("names the model it is given", async () => {
    const { root } = await made({ model: "gpt-5-mini" });
    expect(env.read(join(root, ".env")).MODEL).toBe("gpt-5-mini");
  });

  it("makes nothing on a dry run", async () => {
    const { code, console, p, root } = await made({ dryRun: true });
    expect(code).toBe(0);
    expect(p.ran).toEqual([]);
    expect(existsSync(root)).toBe(false);
    expect(said(console)).toContain("would    write src/agent.ts");
    expect(said(console)).not.toContain("langgraph");
  });
});

/** The created files, in a project inside the package, through strict TypeScript and prettier. */
describe("created files are clean", () => {
  const PRESETS: [string, Record<string, unknown>][] = [
    ["both", {}],
    ["nodes-only", { parts: ["nodes"] }],
    ["tools-only", { parts: ["tools"] }],
  ];

  it.each(PRESETS)("%s", async (_, preset) => {
    const { root } = await made({ ...preset, inside: GENERATED });
    execFileSync("npx", ["tsc", "-p", join(root, "tsconfig.json")], { stdio: "pipe" });
    for (const file of ["agent.ts", "chat.ts", "memory.ts"]) {
      const path = join(root, "src", file);
      const prettier = ["prettier", "--no-config", "--ignore-path", "/dev/null", "--check", path];
      execFileSync("npx", prettier, { stdio: "pipe" });
    }
  });
});

describe("the created agent, run", () => {
  /** The created agent, imported as written, its memory answered by the recorded API. */
  async function turn(preset: Record<string, unknown>, model: Scripted, input: string) {
    const { root } = await made({ ...preset, inside: GENERATED });
    const sent = serve();
    const agentModule = await import(pathToFileURL(join(root, "src/agent.ts")).href);
    agentModule.agent.model = model;
    const result = await agentModule.reply(input, { userId: "dana", sessionId: "s-1" });
    return { result, sent };
  }

  it("recalls, searches with the tool, and remembers", async () => {
    const model = new Scripted([
      [calls("memory_search", { query: "home" }, "c1")],
      [says("Lisbon.")],
    ]);
    const { result, sent } = await turn({}, model, "Where do I live?");
    expect(result.finalOutput).toBe("Lisbon.");
    expect(routes(sent)).toEqual(["search", "search", "add"]); // recall, the tool, remember
    expect(users(sent)).toEqual(new Set(["dana"]));
    expect(model.calls[0]!.systemInstructions).toContain("Dana lives in Lisbon.");
    expect(bodies(sent, "add")[0]!.items.map((i: any) => [i.role, i.session])).toEqual([
      ["user", "s-1"],
      ["assistant", "s-1"],
    ]);
  });

  it("nodes-only: recalls and remembers", async () => {
    const { sent } = await turn({ parts: ["nodes"] }, new Scripted([[says("Lisbon.")]]), "Hi");
    expect(routes(sent)).toEqual(["search", "add"]);
  });

  it("tools-only: the model saves itself", async () => {
    const model = new Scripted([
      [calls("memory_add", { text: "Lives in Lisbon." }, "c1")],
      [says("Noted.")],
    ]);
    const { sent } = await turn({ parts: ["tools"] }, model, "I live in Lisbon.");
    expect(routes(sent)).toEqual(["add"]);
    expect(bodies(sent, "add")[0]!.items).toEqual([
      { text: "Lives in Lisbon.", kind: "note", session: "s-1" },
    ]);
  });
});
