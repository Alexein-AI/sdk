/**
 * `@alexein/cli create langgraph` and `@alexein/cli doctor`: a new project with memory wired in -
 * its graph run here, as written, with a stand-in model and a recorded memory API behind the real
 * `@alexein/sdk`, and checked as its developer's tools would - and the check of a project's setup.
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
import { afterAll, afterEach, describe, expect, it, vi } from "vitest";

import { create, DEFAULT_MODEL } from "../src/create.js";
import { doctor } from "../src/doctor.js";
import * as env from "../src/env.js";
import { GENERATED as ALL_GENERATED, Project, quiet, said } from "./helpers.js";
import { routes, serve, writeMemoryFile } from "./recorded.js";

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
        "@alexein/sdk@>=0.3",
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
    expect(said(console)).toContain("fill in ANTHROPIC_API_KEY and ALEXEIN_API_KEY in .env");
    expect(said(console)).toContain("npx @alexein/cli doctor");
    const memory = readFileSync(join(root, "src/memory.ts"), "utf8");
    expect(memory).toContain("export const memory = new AlexeinMemory(");
    const graph = readFileSync(join(root, "src/graph.ts"), "utf8");
    expect(graph).toContain(
      'import { memory, MemoryAnnotation, MemoryContext } from "./memory.js";',
    );
    expect(said(console)).not.toContain(".env is not in .gitignore");
  });

  it("installs @alexein/sdk from where --sdk says", async () => {
    const { p } = await made({ sdk: "/src/alexein-sdk/typescript" });
    expect(p.ran[0]!.slice(0, 3)).toEqual(["npm", "install", "/src/alexein-sdk/typescript"]);
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
  /** The created graph, imported as written, its memory answered by the recorded API. */
  async function run(preset: Record<string, unknown>, answers: AIMessage[]) {
    const { root } = await made({ ...preset, inside: GENERATED });
    replies.splice(0, replies.length, ...answers);
    const sent = serve();
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
    expect(out.memory).toContain("Dana lives in Lisbon.");
    expect(routes(sent)).toEqual(["search", "search", "add"]);
    expect(sent.at(-1)!.body.items.map((i: { id: string }) => i.id)).toEqual(["h-1", "ai-1"]);
  });

  it("chat: piped input, or Ctrl-D, ends the conversation after every line is answered", async () => {
    const { root } = await made({ inside: GENERATED });
    replies.splice(
      0,
      replies.length,
      new AIMessage({ content: "Lisbon.", id: "ai-1" }),
      new AIMessage({ content: "Dana.", id: "ai-2" }),
    );
    serve();
    const { Readable, Writable } = await import("node:stream");
    vi.doMock("node:process", async (original) => {
      const actual = await original<typeof import("node:process")>();
      return {
        ...actual,
        default: actual,
        stdin: Readable.from(["Where do I live?\nWho am I?\n"]),
        stdout: new Writable({ write: (_chunk, _encoding, done) => done() }),
      };
    });
    vi.doMock("dotenv/config", () => ({})); // the created project installs it; this one need not
    const logged = vi.spyOn(console, "log").mockImplementation(() => {});
    try {
      await import(pathToFileURL(join(root, "src/chat.ts")).href);
      const lines = logged.mock.calls.map((call) => String(call[0]));
      expect(lines).toContain("agent> Lisbon.");
      expect(lines).toContain("agent> Dana.");
    } finally {
      logged.mockRestore();
      vi.doUnmock("node:process");
      vi.doUnmock("dotenv/config");
    }
  });

  it("a run with no user says how to give one", async () => {
    const { root } = await made({ inside: GENERATED });
    const sent = serve();
    const { graph } = await import(pathToFileURL(join(root, "src/graph.ts")).href);
    await expect(
      graph.invoke(
        { messages: [new HumanMessage("Where do I live?")] },
        { configurable: { thread_id: "t-1" } },
      ),
    ).rejects.toThrow('context: { user_id: "..." }');
    expect(sent).toEqual([]);
  });

  it("nodes-only: recalls and remembers", async () => {
    const { sent } = await run({ parts: ["nodes"] }, [
      new AIMessage({ content: "Lisbon.", id: "ai-1" }),
    ]);
    expect(routes(sent)).toEqual(["search", "add"]);
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
    expect(routes(sent)).toEqual(["add"]);
    expect(sent[0]!.body.items).toEqual([
      { text: "Lives in Lisbon.", kind: "note", session: "t-1" },
    ]);
  });
});

describe("doctor", () => {
  /** A project set up as `init` leaves it, with a graph that uses `memory` as `wiring` says. */
  function healthy(wiring = '.addNode("remember", memory.remember)'): Project {
    const p = Project.scratch();
    projects.push(p);
    p.npm({
      "@langchain/langgraph": "^1",
      "@langchain/core": "^1",
      zod: "^4",
      "@alexein/sdk": "^0.3.0",
    });
    p.installed({
      "@langchain/langgraph": "1.5.2",
      "@langchain/core": "1.2.20",
      zod: "4.6.7",
      "@alexein/sdk": "0.3.0",
    });
    const written = writeMemoryFile(p.root + "/src", "langgraph/memory.ts.tmpl", {
      parts: ["nodes", "tools"],
    });
    renameSync(written, join(p.root, "src/memory.ts"));
    rmSync(join(written, ".."), { recursive: true });
    p.file(
      "src/graph.ts",
      `import { memory } from "./memory.js";\n// memory.remember\ngraph${wiring};\n`,
    );
    p.file(".env", `${env.KEY}=tm_x\n`).file(".gitignore", "node_modules\n.env\n");
    return p;
  }
  const answering =
    (check: env.Check): env.Checker =>
    async () =>
      check;
  const good = answering({ ok: true, writes: true, detail: "scratch/demo, reads and writes" });
  const readOnly = answering({ ok: true, writes: false, detail: "scratch/demo, reads only" });

  it("passes a project that is set up", async () => {
    vi.stubEnv(env.BASE_URL, "");
    const console = quiet();
    expect(await doctor(healthy().root, console, good)).toBe(0);
    const text = said(console);
    expect(text).toContain("@alexein/cli 0.3.0 - checking");
    expect(text).toContain("✓ memory file src/memory.ts (written by 0.3.0)");
    expect(text).toContain(
      "✓ dependencies: @alexein/sdk, @langchain/langgraph, @langchain/core, zod",
    );
    expect(text).toContain("✓ @alexein/sdk 0.3.0");
    expect(text).toContain("✓ @langchain/langgraph 1.5.2");
    expect(text).toContain("✓ ALEXEIN_API_KEY from .env");
    expect(text).toContain("✓ ALEXEIN_API_URL not set: https://api.alexein.ai");
    expect(text).toContain("✓ key: scratch/demo, reads and writes");
    expect(text).toContain("All good.");
  });

  it("checks the key at the address the project sets, in .env or the environment", async () => {
    const p = healthy().file(".env", `${env.BASE_URL}=https://memory.example.com\n`);
    vi.stubEnv(env.KEY, "tm_env");
    const checked: [string, string | undefined][] = [];
    const console = quiet();
    const recording: env.Checker = async (key, baseUrl) => {
      checked.push([key, baseUrl]);
      return good(key, baseUrl);
    };
    expect(await doctor(p.root, console, recording)).toBe(0);
    expect(checked).toEqual([["tm_env", "https://memory.example.com"]]);
    const text = said(console);
    expect(text).toContain("✓ ALEXEIN_API_KEY from the environment");
    expect(text).toContain("✓ ALEXEIN_API_URL from .env: https://memory.example.com");
    expect(text).toContain("✓ key at https://memory.example.com: scratch/demo, reads and writes");
  });

  it("stops at an address that is not one", async () => {
    const p = healthy();
    vi.stubEnv(env.BASE_URL, "localhost:8210");
    const console = quiet();
    let asked = false;
    expect(await doctor(p.root, console, async () => ((asked = true), good("", "")))).toBe(1);
    expect(said(console)).toContain(
      '✗ ALEXEIN_API_URL from the environment is not an address: "localhost:8210"',
    );
    expect(asked).toBe(false);
  });

  it("says what is missing, and how to fix it", async () => {
    vi.stubEnv(env.KEY, "");
    const p = Project.scratch();
    projects.push(p);
    p.npm({});
    const console = quiet();
    expect(await doctor(p.root, console, good)).toBe(1);
    const text = said(console);
    expect(text).toContain("✗ no memory file");
    expect(text).toContain(
      "run `npx @alexein/cli init langgraph` or `npx @alexein/cli init openai-agents`",
    );
    expect(text).toContain(
      "✗ not dependencies: @alexein/sdk, @langchain/langgraph, @langchain/core, zod",
    );
    expect(text).toContain("npm install '@alexein/sdk@>=0.3'");
    expect(text).toContain("✗ @alexein/sdk is not installed");
    expect(text).toContain(`✗ no ${env.KEY}, in .env or the environment`);
  });

  it("catches an old version, and a bad key", async () => {
    const p = healthy();
    p.installed({ "@langchain/langgraph": "0.4.0", "@alexein/sdk": "0.2.1" });
    const bad = quiet();
    const unknown = answering({
      ok: false,
      writes: undefined,
      detail: "the service does not know this key",
    });
    expect(await doctor(p.root, bad, unknown)).toBe(1);
    expect(said(bad)).toContain("✗ @langchain/langgraph 0.4.0 is older than 1.0");
    expect(said(bad)).toContain("✗ @alexein/sdk 0.2.1 is older than 0.3");
    expect(said(bad)).toContain("✗ key: the service does not know this key");
  });

  it("fails a read-only key where the project saves, and passes it where it only reads", async () => {
    for (const wiring of [
      '.addNode("remember", memory.remember)',
      "(memory.tools({ write: true }))",
    ]) {
      const console = quiet();
      expect(await doctor(healthy(wiring).root, console, readOnly), wiring).toBe(1);
      expect(said(console)).toContain("only reads, and the project saves");
    }
    const console = quiet();
    expect(await doctor(healthy("(memory.tools())").root, console, readOnly)).toBe(0);
    expect(said(console)).toContain("✓ key: scratch/demo, reads only");
  });

  it("stops outside a project", async () => {
    const p = Project.scratch();
    projects.push(p);
    expect(await doctor(p.root, quiet(), good)).toBe(1);
  });
});
