/**
 * The memory commands, `login`, `logout` and `whoami`: what each sends through the real
 * `@alexein/sdk` to a recorded API, what it prints, and where a login keeps its key - with the
 * keychain a stand-in over a scratch directory.
 */

import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { main } from "../src/cli.js";
import type { Shell } from "../src/credentials.js";
import { memoryMain } from "../src/memory.js";
import { outline } from "../src/outline.js";
import { Console } from "../src/ui.js";
import { answer, KEY, REF, SEARCHED, serve, type Respond, type Sent } from "./recorded.js";

const homes: string[] = [];
afterEach(() => {
  homes.splice(0).forEach((home) => rmSync(home, { recursive: true, force: true }));
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

const PROJECT = {
  kind: "key",
  writes: true,
  org: "org_1",
  org_name: "Acme",
  project: "production",
  project_name: "Production",
  space: "project",
};
const PERSONAL = { kind: "key", writes: true, org: "org_1", org_name: "Dana", space: "personal" };

/** The API as `recorded.ts` answers it, with `me` the key `who` describes. */
const as =
  (who: object, more: Respond = answer): Respond =>
  (route, body) =>
    route === "me" ? Response.json(who) : more(route, body);

/** A computer whose keychain is a map: `secret-tool` on Linux, `security` on macOS, or none. */
class Computer implements Shell {
  readonly home = mkdtempSync(join(tmpdir(), "home-"));
  readonly env: NodeJS.ProcessEnv;
  readonly ran: string[] = [];
  readonly inputs: string[] = [];
  kept: string | undefined;

  constructor(
    readonly platform: NodeJS.Platform = "linux",
    readonly commands: string[] = ["secret-tool"],
    env: NodeJS.ProcessEnv = {},
  ) {
    homes.push(this.home);
    this.env = { ALEXEIN_CONFIG_DIR: join(this.home, "config"), ...env };
  }

  has(command: string): boolean {
    return this.commands.includes(command);
  }

  run(command: string, args: string[], input?: string) {
    this.ran.push([command, ...args].join(" "));
    if (input !== undefined) this.inputs.push(input);
    const verb =
      command === "security" ? (args[0] === "-i" ? input?.split(" ")[0] : args[0]) : args[0];
    if (verb === "store") this.kept = input;
    if (verb === "add-generic-password") this.kept = / -w (\S+)/.exec(input ?? "")?.[1];
    if (verb === "lookup" || verb === "find-generic-password")
      return this.kept ? { code: 0, out: `${this.kept}\n` } : { code: 44, out: "" };
    if (verb === "clear" || verb === "delete-generic-password") {
      const had = this.kept !== undefined;
      this.kept = undefined;
      return { code: had ? 0 : 1, out: "" };
    }
    return { code: 0, out: "" };
  }

  get file() {
    return join(this.env.ALEXEIN_CONFIG_DIR!, "credentials.json");
  }
}

async function run(
  argv: string[],
  {
    shell = new Computer(),
    stdin,
    answers,
  }: { shell?: Shell; stdin?: string; answers?: string[] } = {},
) {
  const console = new Console({ interactive: Boolean(answers), answers, out: () => {} });
  const [name, ...rest] = argv;
  const code = await memoryMain(name!, rest, { console, stdin: () => stdin, shell });
  return { code, said: console.said.join("\n") };
}

const header = (sent: Sent[], name: string) => sent.map((s) => s.headers[name]);

describe("the memory commands", () => {
  it("search what the key's app user holds, and print it to read", async () => {
    const sent = serve();
    const shell = new Computer("linux", [], { ALEXEIN_API_KEY: KEY });
    const { code, said } = await run(
      ["search", "where", "does", "dana", "live", "--user", "dana", "--fast"],
      { shell },
    );
    expect(code).toBe(0);
    expect(sent.map((s) => s.route)).toEqual(["search"]);
    expect(sent[0]!.body).toMatchObject({ query: "where does dana live", fast: true });
    expect(header(sent, "X-Alexein-User")).toEqual(["dana"]);
    expect(said).toContain("known\n  Dana lives in Lisbon.");
    expect(said).toContain(
      `excerpt   2026-10-01  ${REF}  (session t-1)\n  Dana: I moved to Lisbon.`,
    );
  });

  it("prints the API's JSON as it came with --json", async () => {
    serve();
    const shell = new Computer("linux", [], { ALEXEIN_API_KEY: KEY });
    const { said } = await run(["search", "q", "--user", "dana", "--json"], { shell });
    expect(JSON.parse(said)).toEqual(SEARCHED);
  });

  it("reads a personal key's own memory, me, unless told otherwise; a project's key names its user", async () => {
    const personal = serve(as(PERSONAL));
    const shell = new Computer("linux", [], { ALEXEIN_API_KEY: KEY });
    expect((await run(["latest"], { shell })).code).toBe(0);
    expect(personal.map((s) => s.route)).toEqual(["me", "latest"]);
    expect(header(personal, "X-Alexein-User")[1]).toBe("me");

    const project = serve(as(PROJECT));
    const unnamed = await run(["latest"], { shell });
    expect(unnamed.code).toBe(2);
    expect(unnamed.said).toContain(
      "this key is a project's: name the app user with --user or ALEXEIN_USER",
    );
    expect(project.map((s) => s.route)).toEqual(["me"]);

    const named = serve(as(PROJECT));
    const env = new Computer("linux", [], { ALEXEIN_API_KEY: KEY, ALEXEIN_USER: "dana" });
    expect((await run(["latest", "--limit", "3"], { shell: env })).code).toBe(0);
    expect(named.map((s) => s.route)).toEqual(["latest"]);
    expect(named[0]!.body).toMatchObject({ k: 3 });
  });

  it("adds what stdin brings with -, as the person's own words with --self", async () => {
    const sent = serve();
    const shell = new Computer("linux", [], { ALEXEIN_API_KEY: KEY });
    const argv = [
      "add",
      "-",
      "--user",
      "dana",
      "--id",
      "note-1",
      "--session",
      "s-1",
      "--self",
      "--wait",
    ];
    const { code } = await run(argv, { shell, stdin: "I moved to Lisbon.\n\n" });
    expect(code).toBe(0);
    expect(sent.map((s) => s.route)).toEqual(["add"]);
    expect(sent[0]!.body.items[0]).toMatchObject({
      id: "note-1",
      text: "I moved to Lisbon.",
      session: "s-1",
      author: { self: true },
    });
    expect(sent[0]!.body.wait).toBe(true);

    const empty = await run(["add", "-", "--user", "dana"], { shell, stdin: "  \n" });
    expect(empty.code).toBe(2);
  });

  it("asks before forgetting, and forgets nothing unasked without --yes", async () => {
    const sent = serve();
    const shell = new Computer("linux", [], { ALEXEIN_API_KEY: KEY });
    const argv = [
      "forget",
      "--user",
      "dana",
      "--item",
      "note-1",
      "--item",
      "note-2",
      "--session",
      "s-1",
    ];
    const unasked = await run(argv, { shell });
    expect(unasked.code).toBe(1);
    expect(unasked.said).toContain("Nothing forgotten: pass --yes to forget.");
    expect(sent).toEqual([]);

    const declined = await run(argv, { shell, answers: ["n"] });
    expect(declined.said).toContain(
      "Forget 2 items, 1 session of dana, for good? It cannot be undone.",
    );
    expect(sent).toEqual([]);

    expect((await run([...argv, "--yes"], { shell })).code).toBe(0);
    expect(sent.map((s) => s.route)).toEqual(["forget"]);
    expect(sent[0]!.body).toEqual({ items: ["note-1", "note-2"], sessions: ["s-1"] });

    expect((await run(["forget", "--user", "dana", "--yes"], { shell })).code).toBe(2);
  });

  it("exports every page as JSON lines, to a file only its owner can read", async () => {
    const pages: Record<string, object> = {
      "": { records: [{ type: "item", id: "a" }], next: "p2" },
      p2: { records: [{ type: "fact", ref: REF }], next: null },
    };
    const sent = serve((route, body) =>
      route === "export" ? Response.json(pages[body.cursor ?? ""]) : answer(route),
    );
    const shell = new Computer("linux", [], { ALEXEIN_API_KEY: KEY });
    const printed = await run(["export", "--user", "dana"], { shell });
    expect(printed.said.split("\n").map((line) => JSON.parse(line))).toEqual([
      { type: "item", id: "a" },
      { type: "fact", ref: REF },
    ]);

    const out = join(shell.home, "dana.jsonl");
    const written = await run(["export", "--user", "dana", "--out", out], { shell });
    expect(written.said).toBe(`2 records in ${out}`);
    expect(readFileSync(out, "utf8").trim().split("\n")).toHaveLength(2);
    expect(statSync(out).mode & 0o777).toBe(0o600);
    expect(sent.filter((s) => s.route === "export")).toHaveLength(4);
  });

  it("opens, and shows a subject, a summary, a history and a status as an outline", async () => {
    const sent = serve();
    const shell = new Computer("linux", [], { ALEXEIN_API_KEY: KEY, ALEXEIN_USER: "dana" });
    const opened = await run(["open", REF], { shell });
    expect(opened.said).toContain(`memory:\n  type: excerpt\n  ref: ${REF}`);
    for (const argv of [
      ["subject", "Dana", "Chen"],
      ["summary"],
      ["history", "Dana"],
      ["status", "a", "b"],
    ])
      expect((await run(argv, { shell })).code, argv.join(" ")).toBe(0);
    expect(sent.map((s) => s.route)).toEqual(["open", "subject", "summary", "history", "status"]);
    expect(sent[1]!.body).toMatchObject({ name: "Dana Chen" });
    expect(sent[4]!.body).toMatchObject({ items: ["a", "b"] });
  });

  it("refuses words and flags a command does not take, and says how with --help", async () => {
    serve();
    const shell = new Computer("linux", [], { ALEXEIN_API_KEY: KEY, ALEXEIN_USER: "dana" });
    for (const argv of [
      ["open", "a", "b"],
      ["latest", "now"],
      ["search"],
      ["search", "q", "--session", "s"],
      ["latest", "--limit", "many"],
    ])
      expect((await run(argv, { shell })).code, argv.join(" ")).toBe(2);
    const help = await run(["search", "--help"], { shell });
    expect(help.code).toBe(0);
    expect(help.said).toContain("Usage: alexein search <question> [options]");
    expect(help.said).toContain("--fast");
  });

  it("says when there is no key, and when the service does not know the one there is", async () => {
    const none = await run(["latest", "--user", "dana"]);
    expect(none.code).toBe(1);
    expect(none.said).toContain("no key: run alexein login, or set ALEXEIN_API_KEY");

    serve(() => Response.json({ detail: "bad key" }, { status: 401 }));
    const shell = new Computer("linux", [], { ALEXEIN_API_KEY: KEY });
    const wrong = await run(["latest", "--user", "dana"], { shell });
    expect(wrong.code).toBe(1);
    expect(wrong.said).toContain("the service does not know this key");
  });
});

describe("login, whoami and logout", () => {
  it("keeps the key in the keychain, and only what is not secret in the file", async () => {
    const sent = serve(as(PERSONAL));
    const shell = new Computer("linux", ["secret-tool"]);
    const { code, said } = await run(["login", "--key", "-"], { shell, stdin: "tm_kept\n" });
    expect(code).toBe(0);
    expect(said).toContain("Logged in: Dana, a personal key");
    expect(said).toContain("The key is in the system keyring.");
    expect(said).toContain("your own memory (me)");
    expect(shell.kept).toBe("tm_kept");
    const file = JSON.parse(readFileSync(shell.file, "utf8"));
    expect(file).toMatchObject({ store: "keychain", space: "personal" });
    expect(JSON.stringify(file)).not.toContain("tm_kept");
    expect(statSync(shell.file).mode & 0o777).toBe(0o600);

    expect((await run(["latest"], { shell })).code).toBe(0);
    expect(sent.at(-1)!.headers.Authorization).toBe("Bearer tm_kept");
    expect(sent.at(-1)!.headers["X-Alexein-User"]).toBe("me");

    const who = await run(["whoami", "--json"], { shell });
    expect(JSON.parse(who.said)).toMatchObject({
      space: "personal",
      key_from: "the system keyring, from alexein login",
      user: "me",
    });

    const out = await run(["logout"], { shell });
    expect(out.said).toContain("Logged out: took out the key, from the system keyring and");
    expect(shell.kept).toBeUndefined();
    expect(existsSync(shell.file)).toBe(false);
    expect((await run(["logout"], { shell })).said).toContain("Not logged in.");
  });

  it("writes the key to macOS's keychain on stdin, never on a command line", async () => {
    serve(as(PROJECT));
    const shell = new Computer("darwin", ["security"]);
    await run(["login", "--key", "tm_mac", "--user", "dana"], { shell });
    expect(shell.kept).toBe("tm_mac");
    expect(shell.inputs[0]).toBe("add-generic-password -U -s alexein -a api-key -w tm_mac\n");
    expect(shell.ran.join("\n")).not.toContain("tm_mac");
    expect(JSON.parse(readFileSync(shell.file, "utf8"))).toMatchObject({
      store: "keychain",
      user: "dana",
    });
  });

  it("keeps the key in a file only its owner can read where there is no keychain, or when asked", async () => {
    serve(as(PROJECT));
    for (const [shell, argv, fellBack] of [
      [new Computer("linux", []), ["login", "--key", "tm_file"], true],
      [
        new Computer("linux", ["secret-tool"]),
        ["login", "--key", "tm_file", "--insecure-storage"],
        false,
      ],
    ] as const) {
      const { said } = await run([...argv], { shell });
      expect(JSON.parse(readFileSync(shell.file, "utf8"))).toMatchObject({
        store: "file",
        key: "tm_file",
      });
      expect(statSync(shell.file).mode & 0o777).toBe(0o600);
      expect(said.includes("There is no keychain here")).toBe(fellBack);
      expect(said).toContain("This is a project's key: name an app user");
    }
  });

  it("keeps nothing for a key the service does not know", async () => {
    serve(() => Response.json({ detail: "bad key" }, { status: 401 }));
    const shell = new Computer();
    const { code, said } = await run(["login", "--key", "tm_wrong"], { shell });
    expect(code).toBe(1);
    expect(said).toContain("the service does not know this key; nothing was kept");
    expect(shell.kept).toBeUndefined();
    expect(existsSync(shell.file)).toBe(false);
  });

  it("puts --key and ALEXEIN_API_KEY before the login, and says which it used", async () => {
    serve(as(PROJECT));
    const shell = new Computer("linux", ["secret-tool"], { ALEXEIN_API_KEY: "tm_env" });
    await run(["login", "--key", "tm_kept", "--user", "dana"], { shell });
    const who = await run(["whoami"], { shell });
    expect(who.said).toContain("from     ALEXEIN_API_KEY");
    // The login's user goes with the login's key, not with another.
    expect(who.said).toContain("user     none: name one with --user or ALEXEIN_USER");
  });
});

describe("the command line", () => {
  it("hands the memory commands on, and lists them in --help", async () => {
    const console = new Console({ out: () => {} });
    expect(await main(["--help"], console)).toBe(0);
    const help = console.said.join("\n");
    expect(help).toContain("alexein search <question>");
    expect(help).toContain("alexein login");
    expect(await main(["search"], new Console({ out: () => {} }))).toBe(2);
  });

  it("prints the skill that teaches an agent the commands", async () => {
    const console = new Console({ out: () => {} });
    expect(await main(["skill"], console)).toBe(0);
    const skill = console.said.join("\n");
    expect(skill.startsWith("---\nname: alexein-memory\n")).toBe(true);
    expect(skill).toContain('alexein search "<a plain question>" --json');
  });

  it("outlines JSON as a person reads it", () => {
    expect(
      outline({ name: "Dana", values: [{ city: "Lisbon", since: null }], tags: [], note: "a\nb" }),
    ).toEqual([
      "name: Dana",
      "values:",
      "  - city: Lisbon",
      "    since: -",
      "tags: (none)",
      "note: a\n  b",
    ]);
  });
});
