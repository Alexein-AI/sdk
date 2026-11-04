/** `@alexein/cli init`: what it checks before writing, where it writes, what it installs, and the key. */

import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { main } from "../src/cli.js";
import * as env from "../src/env.js";
import { Project, quiet, said } from "./helpers.js";
import { VERSION } from "../src/version.js";

const projects: Project[] = [];
function project(): Project {
  const made = Project.scratch();
  projects.push(made);
  return made;
}
afterEach(() => {
  projects.splice(0).forEach((p) => p.remove());
  delete process.env[env.KEY];
  delete process.env[env.BASE_URL];
});

const text = (p: Project, path: string) => readFileSync(join(p.root, path), "utf8");

describe("where it writes", () => {
  it("writes beside the graph langgraph.json names", async () => {
    const p = project().npm().graphs({ agent: "./src/agent/graph.ts:graph" });
    p.file("src/agent/graph.ts", "");
    const [code] = await p.init();
    expect(code).toBe(0);
    const written = text(p, "src/agent/memory.ts");
    expect(written).toContain("export const memory = new AlexeinMemory(");
    expect(written).toContain('from "@alexein/sdk/langgraph"');
    expect(written).not.toContain("{version}");
    expect(written).not.toContain(">>>");
    expect(p.ran).toEqual([
      ["npm", "install", "@alexein/sdk@>=0.3", "@langchain/core@>=1.0", "zod@>=3.25"],
    ]);
  });

  it("understands a graph given as an object", async () => {
    const p = project()
      .npm()
      .graphs({ agent: { path: "./agents/main.ts:graph" } });
    p.file("agents/main.ts", "");
    await p.init();
    expect(existsSync(join(p.root, "agents/memory.ts"))).toBe(true);
  });

  it("writes into src/ when there is no langgraph.json, else the root", async () => {
    const p = project().npm().file("src/index.ts", "");
    await p.init();
    expect(existsSync(join(p.root, "src/memory.ts"))).toBe(true);
    const bare = project().npm();
    await bare.init();
    expect(existsSync(join(bare.root, "memory.ts"))).toBe(true);
  });

  it("finds the root from a subdirectory", async () => {
    const p = project().npm().file("scripts/deep/x.ts", "");
    await p.init({ cwd: join(p.root, "scripts/deep") });
    expect(existsSync(join(p.root, "memory.ts"))).toBe(true);
    expect(existsSync(join(p.root, ".env"))).toBe(true);
  });

  it("puts it where --dir and --file say", async () => {
    const p = project().npm();
    await p.init({ directory: "lib/shared", filename: "alexein.ts" });
    expect(existsSync(join(p.root, "lib/shared/alexein.ts"))).toBe(true);
  });
});

describe("several graphs", () => {
  it("stops and names them when nobody can be asked", async () => {
    const p = project().npm().graphs({ a: "./a/g.ts:graph", b: "./b/g.ts:graph" });
    const [code, console] = await p.init();
    expect(code).toBe(1);
    expect(said(console)).toContain("2 graphs (a, b); name one with --graph");
  });

  it("takes --graph", async () => {
    const p = project().npm().graphs({ a: "./a/g.ts:graph", b: "./b/g.ts:graph" });
    await p.init({ graph: "b" });
    expect(existsSync(join(p.root, "b/memory.ts"))).toBe(true);
  });

  it("stops on a graph that is not there", async () => {
    const p = project().npm().graphs({ a: "./a/g.ts:graph" });
    const [code, console] = await p.init({ graph: "z" });
    expect(code).toBe(1);
    expect(said(console)).toContain('no graph "z"');
  });

  it("asks at a terminal", async () => {
    const p = project().npm().graphs({ a: "./a/g.ts:graph", b: "./b/g.ts:graph" });
    await p.init({ console: quiet({ interactive: true, answers: ["2"] }) });
    expect(existsSync(join(p.root, "b/memory.ts"))).toBe(true);
  });
});

describe("a LangGraph project, new enough", () => {
  const bare = () => project().npm({});

  it("stops on a project without LangGraph unless told", async () => {
    const p = bare();
    const [code, console] = await p.init();
    expect(code).toBe(1);
    expect(said(console)).toContain("this project does not use LangGraph;");
    expect(existsSync(join(p.root, "memory.ts"))).toBe(false);
    expect(p.ran).toEqual([]);
  });

  it("adds LangGraph with --yes", async () => {
    const p = bare();
    const [code] = await p.init({ console: quiet({ yes: true }) });
    expect(code).toBe(0);
    expect(p.ran[0]).toContain("@langchain/langgraph@>=1.0");
  });

  it("asks first at a terminal", async () => {
    const p = bare();
    await p.init({ console: quiet({ interactive: true, answers: ["y"] }) });
    expect(existsSync(join(p.root, "memory.ts"))).toBe(true);
  });

  it("counts an import of LangGraph, but not one inside node_modules", async () => {
    const inside = bare().file("node_modules/x/a.js", 'import "@langchain/langgraph";');
    expect((await inside.init())[0]).toBe(1);
    const own = bare().file("src/a.ts", 'import { StateGraph } from "@langchain/langgraph";');
    expect((await own.init())[0]).toBe(0);
  });

  it("stops on an old LangGraph, with the upgrade", async () => {
    const p = project()
      .npm()
      .installed({ "@langchain/langgraph": "0.4.9", "@langchain/core": "1.2.20" });
    const [code, console] = await p.init();
    expect(code).toBe(1);
    expect(said(console)).toContain("@langchain/langgraph 0.4.9 (needs >=1.0)");
    expect(said(console)).toContain("npm install '@langchain/langgraph@>=1.0'");
    expect(existsSync(join(p.root, "memory.ts"))).toBe(false);
  });

  it("goes ahead with new enough versions", async () => {
    const p = project()
      .npm()
      .installed({ "@langchain/langgraph": "1.5.2", "@langchain/core": "1.2.20" });
    expect((await p.init())[0]).toBe(0);
  });
});

describe("installing", () => {
  it.each([
    ["pnpm-lock.yaml", ["pnpm", "add"]],
    ["yarn.lock", ["yarn", "add"]],
    ["bun.lock", ["bun", "add"]],
  ])("uses the tool %s names", async (lock, tool) => {
    const p = project().file(
      "package.json",
      JSON.stringify({ dependencies: { "@langchain/langgraph": "1" } }),
    );
    p.file(lock, "");
    await p.init();
    expect(p.ran[0]!.slice(0, 2)).toEqual(tool);
  });

  it("follows packageManager in package.json", async () => {
    const p = project().file(
      "package.json",
      JSON.stringify({
        packageManager: "pnpm@9.0.0",
        dependencies: { "@langchain/langgraph": "1" },
      }),
    );
    await p.init();
    expect(p.ran[0]!.slice(0, 2)).toEqual(["pnpm", "add"]);
  });

  it("prints the command with --no-install", async () => {
    const p = project().npm();
    const [, console] = await p.init({ install: false });
    expect(p.ran).toEqual([]);
    expect(said(console)).toContain("npm install '@alexein/sdk@>=0.3'");
  });

  it("installs nothing when everything is declared", async () => {
    const p = project().npm({
      "@langchain/langgraph": "1",
      "@langchain/core": "1",
      zod: "4",
      "@alexein/sdk": "^0.3.0",
    });
    const [, console] = await p.init();
    expect(p.ran).toEqual([]);
    expect(said(console)).toContain("kept     @alexein/sdk, @langchain/langgraph");
  });

  it("installs the client from where --sdk says", async () => {
    const p = project().npm({ "@langchain/langgraph": "1", "@langchain/core": "1", zod: "4" });
    await p.init({ sdk: "/src/alexein-sdk/typescript" });
    expect(p.ran).toEqual([["npm", "install", "/src/alexein-sdk/typescript"]]);
  });

  it("still writes, and says so, when the install fails", async () => {
    const p = project().npm();
    p.code = 1;
    const [code, console] = await p.init();
    expect(code).toBe(1);
    expect(existsSync(join(p.root, "memory.ts"))).toBe(true);
    expect(said(console)).toContain("failed; run it yourself");
  });
});

describe("the key", () => {
  it("leaves an empty line once when skipped", async () => {
    const p = project().npm().file(".env", "OPENAI_API_KEY=sk-1");
    await p.init();
    await p.init({ force: true });
    expect(text(p, ".env")).toBe(`OPENAI_API_KEY=sk-1\n${env.KEY}=\n`);
    expect(p.checked).toEqual([]);
  });

  it("writes a key it is given, and checks it", async () => {
    const p = project().npm().file(".env", `${env.KEY}=\nOTHER=1\n`);
    const [, console] = await p.init({ key: "tm_new", baseUrl: "https://memory.example.com" });
    expect(env.read(join(p.root, ".env"))).toEqual({
      [env.KEY]: "tm_new",
      OTHER: "1",
      [env.BASE_URL]: "https://memory.example.com",
    });
    expect(p.checked).toEqual([["tm_new", "https://memory.example.com"]]);
    expect(said(console)).toContain("key: scratch/demo, reads and writes");
  });

  it("keeps and checks a key already there", async () => {
    const p = project().npm().file(".env", `${env.KEY}=tm_real\n`);
    await p.init();
    expect(text(p, ".env")).toBe(`${env.KEY}=tm_real\n`);
    expect(p.checked).toEqual([["tm_real", undefined]]);
  });

  it("asks at a terminal, and does not show what was typed", async () => {
    const p = project().npm();
    const console = quiet({ interactive: true, answers: ["tm_typed"] });
    await p.init({ console, skipKey: false });
    expect(env.read(join(p.root, ".env"))[env.KEY]).toBe("tm_typed");
    expect(said(console)).not.toContain("tm_typed");
  });

  it("skips on Enter", async () => {
    const p = project().npm();
    const console = quiet({ interactive: true, answers: [""] });
    await p.init({ console, skipKey: false });
    expect(env.read(join(p.root, ".env"))[env.KEY]).toBe("");
    expect(said(console)).toContain("fill it in later");
  });

  it("warns and goes on when the key does not work", async () => {
    const p = project().npm();
    p.check = { ok: false, writes: undefined, detail: "the service does not know this key" };
    const [code, console] = await p.init({ key: "tm_bad" });
    expect(code).toBe(0);
    expect(said(console)).toContain(
      "the key did not check out: the service does not know this key",
    );
  });

  it("warns about a key that only reads, when the file saves", async () => {
    const p = project().npm();
    p.check = { ok: true, writes: false, detail: "scratch/demo, reads only" };
    expect(said((await p.init({ key: "tm_read" }))[1])).toContain("this key only reads");
    const [, tools] = await p.init({ key: "tm_read", force: true, parts: ["tools"] });
    expect(said(tools)).not.toContain("this key only reads");
  });

  it("warns when .env is not ignored", async () => {
    const p = project().npm();
    expect(said((await p.init())[1])).toContain(".env is not in .gitignore");
    p.file(".gitignore", "node_modules\n.env\n");
    expect(said((await p.init({ force: true }))[1])).not.toContain(".env is not in .gitignore");
  });
});

describe("running it again", () => {
  it("refuses without --force, and changes nothing", async () => {
    const p = project().npm().file(".gitignore", ".env\n");
    expect((await p.init({ key: "tm_k" }))[0]).toBe(0);
    const before = Object.fromEntries(
      ["memory.ts", ".env", "package.json"].map((f) => [f, text(p, f)]),
    );
    const ran = p.ran.length;
    const [code, console] = await p.init({ key: "tm_other" });
    expect(code).toBe(1);
    expect(said(console)).toContain("./memory.ts exists; --force replaces it. Nothing changed.");
    for (const [f, was] of Object.entries(before)) expect(text(p, f), f).toBe(was);
    expect(p.ran.length).toBe(ran);
  });

  it("writes the same file again with --force, and installs only what is missing", async () => {
    const p = project().npm();
    await p.init();
    const first = text(p, "memory.ts");
    p.npm({ "@langchain/langgraph": "1", "@alexein/sdk": "^0.3.0" }); // as npm left it
    p.ran.length = 0;
    expect((await p.init({ force: true }))[0]).toBe(0);
    expect(text(p, "memory.ts")).toBe(first);
    expect(p.ran).toEqual([["npm", "install", "@langchain/core@>=1.0", "zod@>=3.25"]]);
  });
});

describe("what it says to do next", () => {
  it("shows the import and the graph that uses memory", async () => {
    const [, console] = await project().npm().init();
    const next = said(console);
    expect(next).toContain(
      'import { memory, MemoryAnnotation, MemoryContext } from "./memory.js";',
    );
    expect(next).toContain("new StateGraph(MemoryAnnotation, MemoryContext)");
    expect(next).toContain('.addNode("recall", memory.recall)');
    expect(next).toContain(
      "createAgent({ model, tools: memory.tools(), contextSchema: MemoryContext });",
    );
    expect(next).toContain('context: { user_id: "dana" }');
    expect(next).toContain("The key is ALEXEIN_API_KEY in .env.");
    expect(next).toContain("`npx @alexein/cli doctor` checks it all.");
  });

  it("gives the tools that save when there are no nodes, and names the file as given", async () => {
    const [, console] = await project()
      .npm()
      .init({ parts: ["tools"], filename: "alexein.mts" });
    const next = said(console);
    expect(next).toContain('import { memory, MemoryContext } from "./alexein.mjs";');
    expect(next).toContain("tools: memory.tools({ write: true })");
    expect(next).not.toContain("memory.recall");
  });
});

describe("refusals", () => {
  it("does not replace an existing file without --force", async () => {
    const p = project().npm().file("memory.ts", "// mine");
    const [code] = await p.init();
    expect(code).toBe(1);
    expect(text(p, "memory.ts")).toBe("// mine");
    expect(p.ran).toEqual([]);
    expect(existsSync(join(p.root, ".env"))).toBe(false);
  });

  it("writes nothing outside a project", async () => {
    const p = project();
    const [code, console] = await p.init();
    expect(code).toBe(1);
    expect(said(console)).toContain("npx @alexein/cli create langgraph <name>");
    expect(readdirSync(p.root)).toEqual([]);
  });

  it("names the framework it knows", async () => {
    const [code, console] = await project().init({ framework: "crewai" });
    expect(code).toBe(2);
    expect(said(console)).toContain("langgraph");
  });

  it("wants a TypeScript file", async () => {
    expect((await project().npm().init({ filename: "memory.py" }))[0]).toBe(2);
  });
});

describe("presets and dry run", () => {
  it("shapes the file", async () => {
    const p = project().npm();
    await p.init({ parts: ["tools"] });
    const tools = text(p, "memory.ts");
    expect(tools).toContain("memory.tools({ write: true })");
    expect(tools).not.toContain("memory.recall");
    expect(tools).not.toContain("MemoryState");
    expect(tools).toContain("export const FAST = false;");
    await p.init({ parts: ["nodes"], force: true, fast: true });
    const nodes = text(p, "memory.ts");
    expect(nodes).toContain("memory.recall");
    expect(nodes).not.toContain("memory.tools");
    expect(nodes).toContain("export const FAST = true;");
  });

  it("checks everything and changes nothing on a dry run", async () => {
    const p = project().npm().graphs({ agent: "./app/graph.ts:graph" }).file("app/graph.ts", "");
    const before = readdirSync(p.root, { recursive: true }).sort();
    const [code, console] = await p.init({ dryRun: true, key: "tm_k" });
    expect(code).toBe(0);
    expect(readdirSync(p.root, { recursive: true }).sort()).toEqual(before);
    expect(p.ran).toEqual([]);
    expect(p.checked).toEqual([]);
    expect(said(console)).toContain("would    write ./app/memory.ts");
    expect(said(console)).toContain(`would    set ${env.KEY} in .env, and check it`);
  });

  it("stops a dry run where init would stop", async () => {
    const p = project().npm().graphs({ a: "./a/g.ts:graph", b: "./b/g.ts:graph" });
    expect((await p.init({ dryRun: true }))[0]).toBe(1);
  });
});

describe("the command line", () => {
  it("parses init and its flags", async () => {
    const p = project().npm();
    const cwd = process.cwd();
    process.chdir(p.root);
    try {
      const code = await main(
        ["init", "langgraph", "--no-install", "--tools-only", "--yes"],
        quiet(),
      );
      expect(code).toBe(0);
    } finally {
      process.chdir(cwd);
    }
    expect(text(p, "memory.ts")).toContain("memory.tools({ write: true })");
  });

  it("refuses both --nodes-only and --tools-only", async () => {
    expect(await main(["init", "langgraph", "--nodes-only", "--tools-only"], quiet())).toBe(2);
  });

  it("says its version, and shows help", async () => {
    const console = quiet();
    expect(await main(["--version"], console)).toBe(0);
    expect(said(console)).toBe(`@alexein/cli ${VERSION}`);
    expect(await main(["--help"], quiet())).toBe(0);
    expect(await main(["nonsense"], quiet())).toBe(2);
  });
});

it("never leaves the written file holding markers or placeholders", async () => {
  const p = project().npm();
  for (const parts of [["nodes", "tools"], ["nodes"], ["tools"]] as const) {
    await p.init({ parts, force: true });
    expect(text(p, "memory.ts")).not.toMatch(/>>>|<<<|\{(version|fast)\}/);
  }
  writeFileSync(join(p.root, "x"), "");
});
