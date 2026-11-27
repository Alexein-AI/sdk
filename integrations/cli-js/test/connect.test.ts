/** `connect`: which tools it finds, what it runs or writes for each, and what it leaves alone. */

import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { connect, NAME, URL, type ConnectOptions, type Host } from "../src/connect.js";
import { Console } from "../src/ui.js";

const homes: string[] = [];
afterEach(() => homes.splice(0).forEach((home) => rmSync(home, { recursive: true, force: true })));

/** A computer with `commands` on PATH, each answering `list` with `listed`, over a scratch home. */
class Computer implements Host {
  readonly home = mkdtempSync(join(tmpdir(), "home-"));
  readonly platform = "linux" as const;
  readonly env = {};
  readonly ran: string[] = [];
  readonly attached: string[] = [];
  failing = new Set<string>();

  constructor(
    readonly commands: string[],
    readonly listed: Record<string, string> = {},
  ) {
    homes.push(this.home);
  }

  has(command: string): boolean {
    return this.commands.includes(command);
  }

  run(command: string, args: string[]) {
    const line = [command, ...args].join(" ");
    const reading = ["list", "get"].includes(args[1] ?? "");
    if (!reading) this.ran.push(line);
    if (reading) {
      const out = this.listed[`${command} ${args[0]}`] ?? "";
      return { code: args[1] === "get" && !out ? 1 : 0, out };
    }
    return this.failing.has(command)
      ? { code: 1, out: "something went wrong\nError: not signed in" }
      : { code: 0, out: "" };
  }

  attach(command: string, args: string[]): number {
    this.attached.push([command, ...args].join(" "));
    return 0;
  }

  file(path: string, text: string): this {
    mkdirSync(dirname(join(this.home, path)), { recursive: true });
    writeFileSync(join(this.home, path), text);
    return this;
  }

  json(path: string): Record<string, any> {
    return JSON.parse(readFileSync(join(this.home, path), "utf8"));
  }
}

const OPTIONS: ConnectOptions = {
  plugins: true,
  force: false,
  list: false,
  dryRun: false,
};

async function run(computer: Computer, o: Partial<ConnectOptions> = {}, answers: string[] = []) {
  const console = new Console({
    interactive: answers.length > 0,
    yes: !answers.length,
    answers,
    out: () => {},
  });
  const code = await connect({ ...OPTIONS, ...o }, console, computer);
  return { code, said: console.said.join("\n") };
}

describe("connect", () => {
  it("installs the plugin where a tool has one, and the server where it has not", async () => {
    const computer = new Computer(["claude", "copilot", "codex", "gemini", "code"]);
    const { code, said } = await run(computer);
    expect(code).toBe(0);
    expect(computer.ran).toEqual([
      "claude plugin marketplace add Alexein-AI/claude-plugins",
      "claude plugin install alexein@alexein",
      `code --add-mcp {"name":"${NAME}","type":"http","url":"${URL}"}`,
      "copilot plugin marketplace add Alexein-AI/copilot-plugin",
      "copilot plugin install alexein-ai@alexein-ai",
      `codex mcp add ${NAME} --url ${URL}`,
      `gemini mcp add --transport http --scope user ${NAME} ${URL}`,
    ]);
    expect(said).toContain("added    Claude Code (the Alexein AI plugin)");
    expect(said).toMatch(/Codex\s+run codex mcp login alexein/);
    expect(said).toContain("claude.ai, Claude Desktop and ChatGPT");
  });

  it("adds the server alone with --no-plugin", async () => {
    const computer = new Computer(["claude", "copilot", "agy"]);
    await run(computer, { plugins: false });
    expect(computer.ran).toEqual([
      `claude mcp add --transport http --scope user ${NAME} ${URL}`,
      `copilot mcp add --transport http ${NAME} ${URL}`,
      `agy mcp add ${NAME} ${URL}`,
    ]);
  });

  it("leaves a tool that has Alexein already, unless --force", async () => {
    const computer = new Computer(["copilot", "gemini"], {
      "copilot mcp": "User servers:\n  alexein (http)",
    });
    const { said } = await run(computer);
    expect(said).toMatch(/has\s+GitHub Copilot CLI/);
    expect(computer.ran).toEqual([`gemini mcp add --transport http --scope user ${NAME} ${URL}`]);

    const again = new Computer(["copilot"], { "copilot mcp": "alexein-ai (http)" });
    await run(again, { force: true, plugins: false });
    expect(again.ran).toEqual([`copilot mcp add --transport http ${NAME} ${URL}`]);
  });

  it("merges into Cursor's mcp.json, keeping its other servers and a copy", async () => {
    const computer = new Computer([]).file(
      ".cursor/mcp.json",
      JSON.stringify({ mcpServers: { other: { url: "https://x.test/mcp" } }, theme: "dark" }),
    );
    const { code, said } = await run(computer);
    expect(code).toBe(0);
    expect(computer.json(".cursor/mcp.json")).toEqual({
      mcpServers: { other: { url: "https://x.test/mcp" }, [NAME]: { url: URL } },
      theme: "dark",
    });
    expect(existsSync(join(computer.home, ".cursor/mcp.json.bak"))).toBe(true);
    expect(said).toContain("added    Cursor (~/.cursor/mcp.json)");
  });

  it("does not touch a settings file that is not JSON", async () => {
    const computer = new Computer([]).file(".cursor/mcp.json", "{ not json");
    const { code, said } = await run(computer);
    expect(code).toBe(1);
    expect(readFileSync(join(computer.home, ".cursor/mcp.json"), "utf8")).toBe("{ not json");
    expect(said).toContain("is not valid JSON");
  });

  it("writes Devin Desktop's file when its CLI is not installed", async () => {
    const computer = new Computer([]).file(".config/devin/mcp_config.json", "{}");
    await run(computer);
    expect(computer.json(".config/devin/mcp_config.json").mcpServers[NAME]).toEqual({
      url: URL,
      transport: "http",
    });
  });

  it("sends a key in headers with --key, installs no plugin, and skips Codex", async () => {
    const computer = new Computer(["claude", "codex"]).file(".cursor/mcp.json", "{}");
    const { said } = await run(computer, { key: "tm_secret" });
    expect(computer.ran).toEqual([
      `claude mcp add --transport http --scope user --header Authorization: Bearer tm_secret --header X-Alexein-User: me ${NAME} ${URL}`,
    ]);
    expect(computer.json(".cursor/mcp.json").mcpServers[NAME].headers).toEqual({
      Authorization: "Bearer tm_secret",
      "X-Alexein-User": "me",
    });
    expect(said).toContain("skipped  Codex");
    expect(said).not.toContain("tm_secret");
  });

  it("changes nothing with --dry-run or --list, and masks the key", async () => {
    const computer = new Computer(["gemini"]).file(".cursor/mcp.json", "{}");
    const { said } = await run(computer, { dryRun: true, key: "tm_secret" });
    expect(computer.ran).toEqual([]);
    expect(computer.json(".cursor/mcp.json")).toEqual({});
    expect(said).toMatch(/would\s+add/);
    expect(said).toContain("tm_***");
    expect(said).not.toContain("tm_secret");

    const listing = await run(computer, { list: true });
    expect(computer.ran).toEqual([]);
    expect(listing.said).toMatch(/found\s+Gemini CLI/);
  });

  it("runs only the tools named with --only, and refuses a name it does not know", async () => {
    const computer = new Computer(["claude", "gemini"]);
    await run(computer, { only: ["gemini"] });
    expect(computer.ran).toEqual([`gemini mcp add --transport http --scope user ${NAME} ${URL}`]);
    expect((await run(computer, { only: ["emacs"] })).code).toBe(2);
  });

  it("says what failed and goes on to the next tool", async () => {
    const computer = new Computer(["claude", "gemini"]);
    computer.failing.add("claude");
    const { code, said } = await run(computer);
    expect(code).toBe(1);
    expect(said).toContain("failed   Claude Code: Error: not signed in");
    expect(said).toContain("added    Gemini CLI");
  });

  it("asks before adding, and offers a sign-in where the tool has one", async () => {
    const computer = new Computer(["codex"]);
    const { code } = await run(computer, {}, ["y", "y"]);
    expect(code).toBe(0);
    expect(computer.attached).toEqual([`codex mcp login ${NAME}`]);

    const declined = new Computer(["codex"]);
    const { said } = await run(declined, {}, ["n"]);
    expect(declined.ran).toEqual([]);
    expect(said).toContain("Nothing changed.");
  });

  it("signs Claude Code in to the plugin's server, which the plugin names, not to alexein", async () => {
    const computer = new Computer(["claude"]);
    await run(computer, {}, ["y", "y"]);
    expect(computer.attached).toEqual(["claude mcp login plugin:alexein:alexein"]);

    const bare = new Computer(["claude"]);
    await run(bare, { plugins: false }, ["y", "y"]);
    expect(bare.attached).toEqual([`claude mcp login ${NAME}`]);
  });

  it("takes out what it added with --remove: the plugin, the user server, the entries", async () => {
    const other = { url: "https://x.test/mcp" };
    const computer = new Computer(["claude", "code"], {
      "claude plugin": "alexein@alexein  enabled",
      "claude mcp": "alexein:\n  Scope: User config",
    })
      .file(".cursor/mcp.json", JSON.stringify({ mcpServers: { [NAME]: { url: URL }, other } }))
      .file(".config/Code/User/mcp.json", JSON.stringify({ servers: { [NAME]: { url: URL } } }));
    const { code, said } = await run(computer, { remove: true });
    expect(code).toBe(0);
    expect(computer.ran).toEqual([
      "claude plugin uninstall alexein@alexein",
      `claude mcp remove --scope user ${NAME}`,
    ]);
    expect(computer.json(".cursor/mcp.json")).toEqual({ mcpServers: { other } });
    expect(existsSync(join(computer.home, ".cursor/mcp.json.bak"))).toBe(true);
    expect(computer.json(".config/Code/User/mcp.json")).toEqual({ servers: {} });
    expect(said).toContain("removed  Claude Code (claude plugin uninstall, claude mcp remove)");
    expect(said).toContain("removed  Cursor (~/.cursor/mcp.json)");
    expect(said).toContain("disconnect it in My memory");
  });

  it("takes Alexein out of the other tools with their own commands, at the scope it added it", async () => {
    const computer = new Computer(["copilot", "codex", "gemini", "agy", "devin"], {
      "copilot plugin": "alexein-ai@alexein-ai",
      "copilot mcp": "alexein-ai (plugin)",
      "codex mcp": "alexein  https://api.alexein.ai/v1/mcp",
      "gemini mcp": "alexein (http)",
      "agy plugin": "alexein-ai",
    }).file(
      ".config/devin/mcp_config.json",
      JSON.stringify({ mcpServers: { [NAME]: { url: URL } } }),
    );
    const { code } = await run(computer, { remove: true });
    expect(code).toBe(0);
    expect(computer.ran).toEqual([
      "copilot plugin uninstall alexein-ai@alexein-ai",
      `codex mcp remove ${NAME}`,
      `gemini mcp remove --scope user ${NAME}`,
      "agy plugin uninstall alexein-ai",
      `devin mcp remove -s user ${NAME}`,
    ]);

    const servers = new Computer(["copilot", "agy"], {
      "copilot mcp": "alexein (http)",
      "agy mcp": "alexein",
    }).file(
      ".config/devin/mcp_config.json",
      JSON.stringify({ mcpServers: { [NAME]: { url: URL } } }),
    );
    const { said } = await run(servers, { remove: true });
    expect(servers.ran).toEqual([`copilot mcp remove ${NAME}`]);
    expect(said).toContain("skipped  Antigravity: take Alexein out in its own settings");
    expect(servers.json(".config/devin/mcp_config.json")).toEqual({ mcpServers: {} });
  });

  it("leaves a server it did not add, under another name, and says so", async () => {
    const theirs = JSON.stringify({ mcpServers: { "alexein-ai": { url: URL } } });
    const computer = new Computer([]).file(".cursor/mcp.json", theirs);
    const { code, said } = await run(computer, { remove: true });
    expect(code).toBe(0);
    expect(readFileSync(join(computer.home, ".cursor/mcp.json"), "utf8")).toBe(theirs);
    expect(said).toContain("skipped  Cursor: take Alexein out in its own settings");
  });

  it("changes nothing with --remove --dry-run, and has nothing to take from a tool without it", async () => {
    const computer = new Computer(["claude"], { "claude mcp": "alexein:" }).file(
      ".cursor/mcp.json",
      JSON.stringify({ mcpServers: { [NAME]: { url: URL } } }),
    );
    const { said } = await run(computer, { remove: true, dryRun: true });
    expect(computer.ran).toEqual([]);
    expect(computer.json(".cursor/mcp.json").mcpServers[NAME]).toEqual({ url: URL });
    expect(said).toMatch(/would\s+remove Claude Code, with claude mcp remove --scope user alexein/);
    expect(said).toMatch(/would\s+remove Cursor/);

    const bare = new Computer(["gemini"]);
    const nothing = await run(bare, { remove: true });
    expect(nothing.code).toBe(0);
    expect(bare.ran).toEqual([]);
    expect(nothing.said).toContain("nothing to take out");
  });

  it("asks before taking anything out", async () => {
    const computer = new Computer(["claude"], { "claude mcp": "alexein:" });
    const { code, said } = await run(computer, { remove: true }, ["n"]);
    expect(code).toBe(1);
    expect(computer.ran).toEqual([]);
    expect(said).toContain("Take Alexein AI out of Claude Code?");
  });

  it("lists the tools as JSON with --list --json, and runs nothing", async () => {
    const computer = new Computer(["claude"], { "claude mcp": "alexein:" });
    const { code, said } = await run(computer, {
      list: true,
      json: true,
      only: ["claude-code", "gemini"],
    });
    expect(code).toBe(0);
    expect(computer.ran).toEqual([]);
    expect(JSON.parse(said)).toEqual({
      tools: [
        { id: "claude-code", name: "Claude Code", found: true, added: true },
        { id: "gemini", name: "Gemini CLI", found: false, added: null },
      ],
    });
  });

  it("finds nothing on a bare computer and points at the chat apps", async () => {
    const { code, said } = await run(new Computer([]));
    expect(code).toBe(0);
    expect(said).toContain("No AI tools found");
  });
});
