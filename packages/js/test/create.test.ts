/**
 * `twinmemory-cli create langgraph` and `twinmemory-cli doctor`: a new project with memory wired
 * in - its graph run here with a stand-in model and a recorded memory API, and checked as its
 * developer's tools would - and the check of a project's setup.
 */

import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { AIMessage, HumanMessage, type BaseMessage } from "@langchain/core/messages";
import { Memory } from "twinmemory";
import { afterAll, afterEach, describe, expect, it, vi } from "vitest";

import { create, DEFAULT_MODEL } from "../src/create.js";
import { doctor } from "../src/doctor.js";
import * as env from "../src/env.js";
import { render } from "../src/render.js";
import { GENERATED as ALL_GENERATED, Project, quiet, said } from "./helpers.js";

/** This file's own corner, so files running in parallel never remove each other's. */
const GENERATED = ALL_GENERATED + "create/";

const projects: Project[] = [];
afterEach(() => {
  projects.splice(0).forEach((p) => p.remove());
});
afterAll(() => rmSync(GENERATED, { recursive: true, force: true }));

function made(
  given: { name?: string; model?: string; inside?: string } & Record<string, unknown> = {},
) {
  const { name = "my-agent", model = DEFAULT_MODEL, inside, ...rest } = given;
  const p = Project.scratch(inside);
  projects.push(p);
  const console = quiet();
  return create(name, p.root, model, p.options(rest), console).then((code) => ({
    code,
    console,
    p,
    root: join(p.root, name),
  }));
}

describe("create", () => {
  it("makes a project with memory wired in", async () => {
    const { code, console, p, root } = await made();
    expect(code).toBe(0);
    for (const path of [
      "package.json",
      "tsconfig.json",
      "langgraph.json",
      "README.md",
      ".gitignore",
      ".env",
      ".env.example",
    ]) {
      expect(existsSync(join(root, path)), path).toBe(true);
    }
    for (const path of ["graph.ts", "chat.ts", "memory.ts"]) {
      expect(existsSync(join(root, "src", path)), path).toBe(true);
    }
    expect(JSON.parse(readFileSync(join(root, "langgraph.json"), "utf8")).graphs).toEqual({
      agent: "./src/graph.ts:graph",
    });
    expect(env.read(join(root, ".env"))).toEqual({
      MODEL: DEFAULT_MODEL,
      ANTHROPIC_API_KEY: "",
      [env.KEY]: "",
    });
    expect(p.ran).toEqual([
      [
        "npm",
        "install",
        "twinmemory@>=0.1",
        "@langchain/langgraph@>=1.0",
        "@langchain/core@>=1.0",
        "zod@>=3.25",
        "langchain@>=1.0",
        "dotenv",
        "@langchain/anthropic",
      ],
      [
        "npm",
        "install",
        "--save-dev",
        "typescript",
        "tsx",
        "@types/node",
        "@langchain/langgraph-cli",
      ],
    ]);
    expect(said(console)).toContain("npm run chat -- --user dana");
    expect(said(console)).toContain("fill in ANTHROPIC_API_KEY and TWIN_MEMORY_API_KEY in .env");
    expect(said(console)).not.toContain(".env is not in .gitignore");
  });

  it("takes another provider, and a key", async () => {
    const { root, p, console } = await made({
      model: "openai:gpt-5",
      key: "tm_k",
      baseUrl: "http://x",
    });
    const values = env.read(join(root, ".env"));
    expect(values.MODEL).toBe("openai:gpt-5");
    expect(values.OPENAI_API_KEY).toBe("");
    expect(values[env.KEY]).toBe("tm_k");
    expect(values[env.BASE_URL]).toBe("http://x");
    expect(p.ran[0]!.at(-1)).toBe("@langchain/openai");
    expect(said(console)).toContain("fill in OPENAI_API_KEY in .env");
  });

  it("says so for a provider it does not know", async () => {
    const { console, p } = await made({ model: "somecloud:model-1" });
    expect(said(console)).toContain('add the LangChain package for "somecloud:model-1" yourself');
    expect(p.ran[0]!.at(-1)).toBe("dotenv");
  });

  it("will not write into a full directory", async () => {
    const p = Project.scratch();
    projects.push(p);
    p.file("my-agent/notes.txt", "mine");
    const code = await create("my-agent", p.root, DEFAULT_MODEL, p.options(), quiet());
    expect(code).toBe(1);
    expect(readdirSync(join(p.root, "my-agent"))).toEqual(["notes.txt"]);
  });

  it("needs a name that is a name", async () => {
    expect((await made({ name: "../evil" })).code).toBe(2);
    expect((await made({ name: "9lives" })).code).toBe(2);
  });

  it("makes nothing on a dry run", async () => {
    const { code, p, console } = await made({ dryRun: true });
    expect(code).toBe(0);
    expect(p.ran).toEqual([]);
    expect(readdirSync(p.root)).toEqual([]);
    expect(said(console)).toContain("would    write src/graph.ts");
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
    for (const file of ["graph.ts", "chat.ts", "memory.ts"]) {
      execFileSync(
        "npx",
        [
          "prettier",
          "--no-config",
          "--ignore-path",
          "/dev/null",
          "--check",
          join(root, "src", file),
        ],
        { stdio: "pipe" },
      );
    }
  });
});

/** A stand-in for the model `initChatModel` would make: it answers from a list, in order. */
const replies: AIMessage[] = [];
vi.mock("langchain", async (original) => ({
  ...(await original<object>()),
  initChatModel: async () => {
    const model = {
      bindTools: () => model,
      invoke: async (_: BaseMessage[]) => replies.shift()!,
    };
    return model;
  },
}));

describe("the created graph, run", () => {
  async function run(preset: Record<string, unknown>, answers: AIMessage[]) {
    const { root } = await made({ ...preset, inside: GENERATED });
    replies.splice(0, replies.length, ...answers);
    const sent: string[] = [];
    const memory = new Memory({
      apiKey: "tm_test",
      fetch: async (input) => {
        const route = new URL(String(input)).pathname.split("/").pop()!;
        sent.push(route);
        if (route === "search")
          return Response.json({ query: "q", found: 1, known: ["Dana lives in Lisbon."] });
        return Response.json({ items: [], queued: 1, pending: 1 }, { status: 202 });
      },
    });
    const memoryModule = await import(pathToFileURL(join(root, "src/memory.ts")).href);
    memoryModule.useMemory(memory);
    const { graph } = await import(pathToFileURL(join(root, "src/graph.ts")).href);
    const out = await graph.invoke(
      { messages: [new HumanMessage({ content: "Where do I live?", id: "h-1" })] },
      { context: { user_id: "dana" }, configurable: { thread_id: "t-1" } },
    );
    return { out, sent };
  }

  const searchCall = new AIMessage({
    content: "",
    tool_calls: [{ name: "memory_search", args: { query: "home" }, id: "c1" }],
  });

  it("recalls, searches with the tool, and remembers", async () => {
    const { out, sent } = await run({}, [
      searchCall,
      new AIMessage({ content: "Lisbon.", id: "ai-1" }),
    ]);
    expect(out.messages.at(-1).text).toBe("Lisbon.");
    expect(sent).toEqual(["search", "search", "add"]);
  });

  it("nodes-only: recalls and remembers", async () => {
    const { sent } = await run({ parts: ["nodes"] }, [
      new AIMessage({ content: "Lisbon.", id: "ai-1" }),
    ]);
    expect(sent).toEqual(["search", "add"]);
  });

  it("tools-only: the model saves itself", async () => {
    const save = new AIMessage({
      content: "",
      tool_calls: [{ name: "memory_add", args: { text: "Lives in Lisbon." }, id: "c1" }],
    });
    const { sent } = await run({ parts: ["tools"] }, [
      save,
      new AIMessage({ content: "Noted.", id: "ai-1" }),
    ]);
    expect(sent).toEqual(["add"]);
  });
});

describe("doctor", () => {
  function healthy(): Project {
    const p = Project.scratch();
    projects.push(p);
    p.npm({ "@langchain/langgraph": "^1", "@langchain/core": "^1", zod: "^4", twinmemory: "^0.1" });
    p.installed({
      "@langchain/langgraph": "1.5.2",
      "@langchain/core": "1.2.20",
      zod: "4.6.7",
      twinmemory: "0.1.0",
    });
    p.file(
      "src/memory.ts",
      render("langgraph/memory.ts.tmpl", ["nodes"], { version: "0.1.0", fast: "false" }),
    );
    p.file(".env", `${env.KEY}=tm_x\n`).file(".gitignore", "node_modules\n.env\n");
    return p;
  }
  const answer =
    (check: env.Check): env.Checker =>
    async () =>
      check;
  const good = answer({ ok: true, writes: true, detail: "scratch/demo, reads and writes" });

  it("passes a project that is set up", async () => {
    const console = quiet();
    expect(await doctor(healthy().root, console, good)).toBe(0);
    const text = said(console);
    expect(text).toContain("✓ memory file src/memory.ts (written by 0.1.0)");
    expect(text).toContain("✓ @langchain/langgraph 1.5.2");
    expect(text).toContain("✓ key at the hosted service: scratch/demo, reads and writes");
    expect(text).toContain("All good.");
  });

  it("says what is missing, and how to fix it", async () => {
    const p = Project.scratch();
    projects.push(p);
    p.npm({});
    const console = quiet();
    expect(await doctor(p.root, console, good)).toBe(1);
    const text = said(console);
    expect(text).toContain("✗ no memory file");
    expect(text).toContain(
      "✗ not dependencies: twinmemory, @langchain/langgraph, @langchain/core, zod",
    );
    expect(text).toContain("✗ @langchain/langgraph is not installed");
    expect(text).toContain(`✗ no ${env.KEY}`);
  });

  it("catches an old version, a bad key, and a read-only key for a file that saves", async () => {
    const p = healthy();
    p.installed({ "@langchain/langgraph": "0.4.0" });
    const bad = quiet();
    expect(
      await doctor(
        p.root,
        bad,
        answer({ ok: false, writes: undefined, detail: "the service does not know this key" }),
      ),
    ).toBe(1);
    expect(said(bad)).toContain("✗ @langchain/langgraph 0.4.0 is older than 1.0");
    expect(said(bad)).toContain("✗ key at the hosted service: the service does not know this key");
    const readOnly = quiet();
    expect(
      await doctor(
        healthy().root,
        readOnly,
        answer({ ok: true, writes: false, detail: "reads only" }),
      ),
    ).toBe(1);
    expect(said(readOnly)).toContain("only reads, and the memory file saves");
  });

  it("passes a read-only key for a file that only reads", async () => {
    const p = healthy();
    p.file(
      "src/memory.ts",
      render("langgraph/memory.ts.tmpl", ["tools"], { version: "0.1.0", fast: "false" }).split(
        "export const memoryAdd",
      )[0]!,
    );
    expect(
      await doctor(p.root, quiet(), answer({ ok: true, writes: false, detail: "reads only" })),
    ).toBe(0);
  });

  it("stops outside a project", async () => {
    const p = Project.scratch();
    projects.push(p);
    expect(await doctor(p.root, quiet(), good)).toBe(1);
  });
});
