/**
 * The memory commands - `alexein search`, `add`, `latest`, `open`, `subject`, `summary`, `history`,
 * `status`, `forget` and `export` - each one route of the memory API through `@alexein/sdk`, and
 * `login`, `logout` and `whoami` for the key they use. Each prints what came back for a person to
 * read, or with `--json` the API's JSON as it came, for a script or an agent.
 *
 * The key is `--key`, else `ALEXEIN_API_KEY`, else the one `alexein login` kept. Whose memory is
 * `--user`, else `ALEXEIN_USER`, else the one `login --user` kept, else `me` for a personal key -
 * the person's own memory, as the console and every connected app name it. A project's key has no
 * such default: its app users are its project's, and a command names one.
 */

import { chmodSync, closeSync, openSync, writeSync } from "node:fs";
import { parseArgs } from "node:util";

import {
  AlexeinError,
  AuthenticationError,
  DEFAULT_BASE_URL,
  type Me,
  Memory,
  type User,
} from "@alexein/sdk";

import * as credentials from "./credentials.js";
import { described } from "./env.js";
import { memories, outline } from "./outline.js";
import { Console } from "./ui.js";

/** A command given wrongly: exit 2, as a usage error is everywhere in this CLI. */
class Usage extends Error {}

type Value = string | boolean | (string | boolean)[] | undefined;
type Values = Record<string, Value>;

interface Flag {
  type: "string" | "boolean";
  multiple?: boolean;
  short?: string;
  /** How the value is shown in the help: `<date>`. */
  value?: string;
  help: string;
}

interface Run {
  user: User;
  v: Values;
  /** The words after the command. */
  args: string[];
  console: Console;
  json: boolean;
  stdin: () => string | undefined;
}

interface Command {
  /** What follows the command in its usage line. */
  usage: string;
  about: string;
  /** The words it takes: none, exactly one, or one or more. */
  takes: "none" | "one" | "some";
  flags: Record<string, Flag>;
  run(r: Run): Promise<number>;
}

const text = (value: Value) => (typeof value === "string" ? value : undefined);
const texts = (value: Value) =>
  Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];

function count(value: Value, flag: string): number | undefined {
  const given = text(value);
  if (given === undefined) return undefined;
  const n = Number(given);
  if (!Number.isInteger(n) || n < 1) throw new Usage(`--${flag} takes a whole number: ${given}`);
  return n;
}

const print = (console: Console, raw: unknown) => {
  console.line(JSON.stringify(raw, null, 2));
  return 0;
};
const show = (console: Console, lines: string[]) => {
  lines.forEach((line) => console.line(line));
  return 0;
};

const DATES = {
  after: { type: "string", value: "<date>", help: "only memory from this day on (YYYY-MM-DD)" },
  before: { type: "string", value: "<date>", help: "as of this day (YYYY-MM-DD)" },
} as const satisfies Record<string, Flag>;
const ORIGIN = {
  provider: { type: "string", value: "<app>", help: "only what this connected app delivered" },
  source: { type: "string", value: "<source>", help: "only this one of the app's sources" },
} as const satisfies Record<string, Flag>;

export const COMMANDS: Record<string, Command> = {
  search: {
    usage: "<question>",
    about: "What memory holds for a question.",
    takes: "some",
    flags: {
      ...DATES,
      ...ORIGIN,
      fast: { type: "boolean", help: "sooner, a little less precisely, and free" },
    },
    async run({ user, v, args, console, json }) {
      const found = await user.search(args.join(" "), {
        after: text(v.after),
        before: text(v.before),
        provider: text(v.provider),
        source: text(v.source),
        ...(v.fast ? { fast: true } : {}),
      });
      if (json) return print(console, found.raw);
      if (found.answerable === false)
        console.line("Memory does not seem to hold the answer. The closest it has:\n");
      show(console, memories(found.raw.memories, "Nothing found."));
      for (const note of found.notes) console.line(`\nnote: ${note}`);
      return 0;
    },
  },
  latest: {
    usage: "",
    about: "The most recent memories, newest first.",
    takes: "none",
    flags: {
      limit: { type: "string", value: "<n>", help: "how many (10 unless set)" },
      ...DATES,
      ...ORIGIN,
    },
    async run({ user, v, console, json }) {
      const found = await user.latest({
        k: count(v.limit, "limit"),
        after: text(v.after),
        before: text(v.before),
        provider: text(v.provider),
        source: text(v.source),
      });
      if (json) return print(console, found.raw);
      return show(console, memories(found.raw.memories, "Nothing yet.", "excerpt"));
    },
  },
  open: {
    usage: "<ref>",
    about: "One memory by its ref, whole: an excerpt in full, or a fact and what it came from.",
    takes: "one",
    flags: {},
    async run({ user, args, console, json }) {
      const opened = await user.open(args[0]!);
      return json ? print(console, opened.raw) : show(console, outline(opened.raw));
    },
  },
  subject: {
    usage: "<name>",
    about: "One person or thing by name: its values now, its facts, and what it relates to.",
    takes: "some",
    flags: { limit: { type: "string", value: "<n>", help: "how many facts at most" } },
    async run({ user, v, args, console, json }) {
      const found = await user.subject(args.join(" "), { limit: count(v.limit, "limit") });
      return json ? print(console, found.raw) : show(console, outline(found.raw));
    },
  },
  summary: {
    usage: "",
    about: "What this memory holds, in brief.",
    takes: "none",
    flags: {},
    async run({ user, console, json }) {
      const found = await user.summary();
      return json ? print(console, found.raw) : show(console, outline(found.raw));
    },
  },
  history: {
    usage: "<subject>",
    about: "Every value a subject was stated to have, and since when.",
    takes: "some",
    flags: { attribute: { type: "string", value: "<name>", help: "only this attribute's values" } },
    async run({ user, v, args, console, json }) {
      const found = await user.history(args.join(" "), { attribute: text(v.attribute) });
      return json ? print(console, found.raw) : show(console, outline(found.raw));
    },
  },
  add: {
    usage: "<text> | -",
    about: "Save something to memory. - reads the text from stdin.",
    takes: "some",
    flags: {
      id: { type: "string", value: "<id>", help: "its id: the same id again edits it" },
      session: { type: "string", value: "<id>", help: "the conversation it belongs to" },
      role: { type: "string", value: "<role>", help: "user or assistant, for a message" },
      author: { type: "string", value: "<name>", help: "who said or wrote it" },
      self: { type: "boolean", help: "said by the person whose memory this is" },
      kind: { type: "string", value: "<kind>", help: "message, document or note" },
      title: { type: "string", value: "<title>", help: "a document's title" },
      wait: { type: "boolean", help: "answer once it can be searched" },
    },
    async run({ user, v, args, console, json, stdin }) {
      const said = args.length === 1 && args[0] === "-" ? (stdin() ?? "") : args.join(" ");
      if (!said.trim()) throw new Usage("nothing to add: give the text, or - and pipe it in");
      const name = text(v.author);
      const added = await user.add(said.replace(/\s+$/, ""), {
        id: text(v.id),
        session: text(v.session),
        role: text(v.role),
        author: v.self ? { self: true, ...(name ? { name } : {}) } : name,
        kind: text(v.kind) as "message" | "document" | "note" | undefined,
        title: text(v.title),
        wait: Boolean(v.wait),
      });
      return json ? print(console, added.raw) : show(console, outline(added.raw));
    },
  },
  status: {
    usage: "<item id>...",
    about: "How far each added item has got: queued, stored, processed or unknown.",
    takes: "some",
    flags: {},
    async run({ user, args, console, json }) {
      const found = await user.status(args);
      return json ? print(console, found.raw) : show(console, outline(found.raw));
    },
  },
  forget: {
    usage: "",
    about: "Erase items, sessions or memories for good, with everything learned from them.",
    takes: "none",
    flags: {
      item: { type: "string", multiple: true, value: "<id>", help: "an item, by its id" },
      session: { type: "string", multiple: true, value: "<id>", help: "a whole session" },
      ref: { type: "string", multiple: true, value: "<ref>", help: "a fact or excerpt, by ref" },
      yes: { type: "boolean", short: "y", help: "do not ask first" },
    },
    async run({ user, v, console, json }) {
      const lists = { items: texts(v.item), sessions: texts(v.session), refs: texts(v.ref) };
      const named = Object.fromEntries(Object.entries(lists).filter(([, ids]) => ids.length));
      const counted = (n: number, one: string, many: string) =>
        n ? [`${n} ${n === 1 ? one : many}`] : [];
      const what = [
        ...counted(lists.items.length, "item", "items"),
        ...counted(lists.sessions.length, "session", "sessions"),
        ...counted(lists.refs.length, "memory", "memories"),
      ];
      if (!what.length) throw new Usage("name what to forget: --item, --session or --ref");
      const sure =
        Boolean(v.yes) ||
        (await console.confirm(
          `Forget ${what.join(", ")} of ${user.id}, for good? It cannot be undone.`,
        ));
      if (!sure) {
        console.line(
          console.interactive ? "Nothing forgotten." : "Nothing forgotten: pass --yes to forget.",
        );
        return 1;
      }
      const done = await user.forget(named);
      return json ? print(console, done.raw) : show(console, outline(done.raw));
    },
  },
  export: {
    usage: "",
    about: "Everything memory holds for this user, as JSON lines: one record a line.",
    takes: "none",
    flags: {
      out: { type: "string", value: "<file>", help: "write it to this file, readable only by you" },
    },
    async run({ user, v, console }) {
      const out = text(v.out);
      const file = out === undefined ? undefined : openSync(out, "w", 0o600);
      if (out !== undefined) chmodSync(out, 0o600);
      let records = 0;
      try {
        for await (const record of user.iterExport()) {
          const line = JSON.stringify(record);
          if (file === undefined) console.line(line);
          else writeSync(file, line + "\n");
          records++;
        }
      } finally {
        if (file !== undefined) closeSync(file);
      }
      if (out !== undefined) console.line(`${records} record${records === 1 ? "" : "s"} in ${out}`);
      return 0;
    },
  },
};

/** What every memory command takes besides its own flags. */
const COMMON: Record<string, Flag> = {
  user: {
    type: "string",
    value: "<id>",
    help: "whose memory: an app user of the key's project; me, your own, for a personal key",
  },
  key: {
    type: "string",
    value: "<key>",
    help: "the key, instead of ALEXEIN_API_KEY or your login; - reads it from stdin",
  },
  "base-url": {
    type: "string",
    value: "<url>",
    help: "memory's address, instead of ALEXEIN_API_URL or your login's",
  },
  json: { type: "boolean", help: "the API's JSON, as it came" },
  help: { type: "boolean", short: "h", help: "this" },
};

const ACCOUNT: Record<string, { about: string; flags: Record<string, Flag> }> = {
  login: {
    about: "Keep a key for the memory commands: in the system's keychain where there is one.",
    flags: {
      key: { type: "string", value: "<key>", help: "the key; - reads it from stdin (else asked)" },
      "base-url": { type: "string", value: "<url>", help: "memory's address, kept with it" },
      user: { type: "string", value: "<id>", help: "the app user the commands use, kept with it" },
      "insecure-storage": {
        type: "boolean",
        help: "keep the key in a file only you can read, even where there is a keychain",
      },
      help: { type: "boolean", short: "h", help: "this" },
    },
  },
  logout: {
    about: "Take the kept key out of the keychain, and the login with it.",
    flags: { help: { type: "boolean", short: "h", help: "this" } },
  },
  whoami: {
    about: "Which key the memory commands use, where it is from, and whose memory they read.",
    flags: {
      key: COMMON.key!,
      "base-url": COMMON["base-url"]!,
      user: COMMON.user!,
      json: COMMON.json!,
      help: COMMON.help!,
    },
  },
};

/** The commands this module answers. */
export const NAMES = new Set([...Object.keys(COMMANDS), ...Object.keys(ACCOUNT)]);

/** The lines for `--help`'s list of commands. */
export function summaries(): string[] {
  const all = [
    ...Object.entries(COMMANDS).map(([name, c]) => [`${name} ${c.usage}`.trim(), c.about] as const),
    ...Object.entries(ACCOUNT).map(([name, c]) => [name, c.about] as const),
  ];
  return all.map(([usage, about]) => `  alexein ${usage.padEnd(22)} ${about}`);
}

function usageOf(name: string, usage: string, about: string, flags: Record<string, Flag>): string {
  const lines = Object.entries(flags).map(([flag, f]) => {
    const shown = `${f.short ? `-${f.short}, ` : ""}--${flag}${f.value ? ` ${f.value}` : ""}`;
    return `  ${shown.padEnd(24)} ${f.help}${f.multiple ? " (again for more)" : ""}`;
  });
  return [
    `Usage: alexein ${name}${usage ? ` ${usage}` : ""} [options]`,
    "",
    about,
    "",
    "Options:",
    ...lines,
  ].join("\n");
}

function parse(argv: string[], flags: Record<string, Flag>) {
  const options = Object.fromEntries(
    Object.entries(flags).map(([name, f]) => [
      name,
      {
        type: f.type,
        ...(f.multiple ? { multiple: true } : {}),
        ...(f.short ? { short: f.short } : {}),
      },
    ]),
  );
  try {
    return parseArgs({ args: argv, options, allowPositionals: true, strict: true });
  } catch (error) {
    throw new Usage((error as Error).message);
  }
}

/** The key the commands use, and where it came from: `--key`, the environment, or the login. */
interface Found {
  key: string;
  from: string;
  saved?: credentials.Saved;
}

/** `--key`, with `-` read from stdin; nothing piped to `-` is a command given wrongly. */
function keyGiven(v: Values, stdin: () => string | undefined): string | undefined {
  try {
    return credentials.keyFrom(text(v.key), stdin);
  } catch (error) {
    throw new Usage((error as Error).message);
  }
}

function findKey(v: Values, shell: credentials.Shell, stdin: () => string | undefined): Found {
  const given = keyGiven(v, stdin);
  if (given) return { key: given, from: "--key" };
  const set = shell.env.ALEXEIN_API_KEY?.trim();
  if (set) return { key: set, from: "ALEXEIN_API_KEY" };
  const kept = credentials.load(shell);
  if (kept) return { key: kept.key, from: `${kept.where}, from alexein login`, saved: kept.saved };
  throw new Error("no key: run alexein login, or set ALEXEIN_API_KEY");
}

/** The address: `--base-url`, else `ALEXEIN_API_URL`, else the login's with its key. */
function baseUrlFor(v: Values, shell: credentials.Shell, found: Found): string | undefined {
  return (
    text(v["base-url"]) || shell.env.ALEXEIN_API_URL?.trim() || found.saved?.base_url || undefined
  );
}

/** Whose memory, by the order the module's note gives; undefined for a project's key unnamed. */
function userFor(v: Values, shell: credentials.Shell, found: Found, space: string | undefined) {
  return (
    text(v.user) ||
    shell.env.ALEXEIN_USER?.trim() ||
    found.saved?.user ||
    (space === "personal" ? "me" : undefined)
  );
}

const client = (key: string, baseUrl: string | undefined) =>
  new Memory({ apiKey: key, baseUrl, integration: "cli" });

/** What the memory commands share: how they end on an error. */
function failed(console: Console, error: unknown): number {
  if (error instanceof Usage) {
    console.fail(error.message);
    return 2;
  }
  if (error instanceof AuthenticationError) {
    console.fail("the service does not know this key: run alexein login, or check ALEXEIN_API_KEY");
    return 1;
  }
  if (error instanceof AlexeinError || error instanceof Error) {
    console.fail(error.message);
    return 1;
  }
  throw error;
}

export interface Io {
  /** The console to use; else one for the terminal, asking unless `--yes`. */
  console?: Console;
  stdin: () => string | undefined;
  shell?: credentials.Shell;
}

/** `alexein <name> ...` for a name in `NAMES`. 0 when it did what it was asked. */
export async function memoryMain(name: string, argv: string[], io: Io): Promise<number> {
  const shell = io.shell ?? credentials.localShell();
  const account = ACCOUNT[name];
  const command = COMMANDS[name];
  const flags = account ? account.flags : { ...command!.flags, ...COMMON };
  let console = io.console ?? new Console();
  try {
    const { values: v, positionals: args } = parse(argv, flags);
    console = io.console ?? Console.forTerminal(Boolean(v.yes));
    if (v.help) {
      console.line(
        usageOf(name, account ? "" : command!.usage, account?.about ?? command!.about, flags),
      );
      return 0;
    }
    if (name === "login") return await login(v, args, console, shell, io.stdin);
    if (name === "logout") return logout(args, console, shell);
    if (name === "whoami") return await whoami(v, args, console, shell, io.stdin);

    const c = command!;
    if (c.takes === "none" && args.length)
      throw new Usage(`${name} takes no words: ${args.join(" ")}`);
    if (c.takes === "one" && args.length !== 1) throw new Usage(`${name} takes one: ${c.usage}`);
    if (c.takes === "some" && !args.length) throw new Usage(`${name} needs ${c.usage}`);
    const found = findKey(v, shell, io.stdin);
    const memory = client(found.key, baseUrlFor(v, shell, found));
    let space = found.saved?.space;
    let user = userFor(v, shell, found, space);
    if (!user && space === undefined) {
      space = (await memory.me()).space ?? undefined;
      user = userFor(v, shell, found, space);
    }
    if (!user)
      throw new Usage(
        "this key is a project's: name the app user with --user or ALEXEIN_USER, " +
          "or keep one with alexein login --user",
      );
    return await c.run({
      user: memory.user(user),
      v,
      args,
      console,
      json: Boolean(v.json),
      stdin: io.stdin,
    });
  } catch (error) {
    return failed(console, error);
  }
}

async function login(
  v: Values,
  args: string[],
  console: Console,
  shell: credentials.Shell,
  stdin: () => string | undefined,
): Promise<number> {
  if (args.length)
    throw new Usage(`login takes no words: ${args.join(" ")}; give the key with --key`);
  const key =
    keyGiven(v, stdin) ??
    (await console.secret(
      "Your Alexein API key (the console's API keys, or My memory › Personal keys):",
    ));
  if (!key)
    throw new Usage(
      "no key given: pass --key (or --key - and pipe it in), or run it at a terminal",
    );
  const baseUrl = text(v["base-url"]);
  let me: Me;
  try {
    me = await new Memory({
      apiKey: key,
      baseUrl,
      timeout: 10_000,
      maxRetries: 0,
      integration: "cli",
    }).me();
  } catch (error) {
    if (error instanceof AuthenticationError) {
      console.fail("the service does not know this key; nothing was kept");
      return 1;
    }
    throw error;
  }
  const label = described(me);
  const user = text(v.user);
  const kept = credentials.save(shell, {
    key,
    baseUrl,
    user,
    space: me.space ?? undefined,
    label,
    insecure: Boolean(v["insecure-storage"]),
  });
  console.line(`Logged in: ${label}.`);
  console.line(
    kept.fellBack
      ? `There is no keychain here: the key is in ${kept.where}, a file only you can read.`
      : `The key is in ${kept.where}.`,
  );
  if (user) console.line(`The memory commands use the app user ${user}.`);
  else if (me.space === "personal") console.line("The memory commands use your own memory (me).");
  else
    console.line(
      "This is a project's key: name an app user with --user or ALEXEIN_USER, or log in with --user.",
    );
  return 0;
}

function logout(args: string[], console: Console, shell: credentials.Shell): number {
  if (args.length) throw new Usage(`logout takes no words: ${args.join(" ")}`);
  const gone = credentials.forgetLogin(shell);
  console.line(gone.length ? `Logged out: took out ${gone.join(" and ")}.` : "Not logged in.");
  if (shell.env.ALEXEIN_API_KEY?.trim())
    console.line("ALEXEIN_API_KEY is still set, and the memory commands use it.");
  return 0;
}

async function whoami(
  v: Values,
  args: string[],
  console: Console,
  shell: credentials.Shell,
  stdin: () => string | undefined,
): Promise<number> {
  if (args.length) throw new Usage(`whoami takes no words: ${args.join(" ")}`);
  const found = findKey(v, shell, stdin);
  const baseUrl = baseUrlFor(v, shell, found);
  const me = await client(found.key, baseUrl).me();
  const user = userFor(v, shell, found, me.space ?? undefined);
  const address = baseUrl ?? DEFAULT_BASE_URL;
  if (v.json)
    return print(console, {
      ...me.raw,
      key_from: found.from,
      base_url: address,
      user: user ?? null,
    });
  const own = user === "me" && me.space === "personal" ? " (your own memory)" : "";
  return show(console, [
    `key      ${described(me)}`,
    `from     ${found.from}`,
    `address  ${address}`,
    `user     ${user ? `${user}${own}` : "none: name one with --user or ALEXEIN_USER"}`,
  ]);
}
