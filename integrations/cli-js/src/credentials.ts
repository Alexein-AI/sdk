/**
 * Where `alexein login` keeps a key, and where the memory commands find it again: the key in the
 * system's keychain where there is one - macOS's through `security`, Linux's through `secret-tool`
 * - else in a file only its owner can read; and beside it, in `credentials.json`, what is not
 * secret: where the key is kept, the address, the app user to use, and what the key is.
 *
 * `alexein-cli` (Python) reads and writes the same file and keychain entry, so a login with either
 * CLI serves both.
 */

import { spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { onPath } from "./connect.js";

/** The keychain entry: one key per computer user, as one login is. */
export const SERVICE = "alexein";
export const ACCOUNT = "api-key";
/** What a key is made of; anything else is not one, and never goes on a keychain's command line. */
const KEY_SHAPE = /^[A-Za-z0-9_-]+$/;

/**
 * The key `--key` gives: `-` reads it from the first line of stdin, so it is in no shell's history.
 * Throws when `-` brings nothing.
 */
export function keyFrom(
  given: string | undefined,
  read: () => string | undefined,
): string | undefined {
  if (given !== "-") return given;
  const key = read()?.split("\n")[0]?.trim();
  if (!key) throw new Error("--key - reads the key from stdin, and none came: pipe it in");
  return key;
}

/** What the credentials need of the computer: a test hands in one over a scratch directory. */
export interface Shell {
  home: string;
  platform: NodeJS.Platform;
  env: NodeJS.ProcessEnv;
  /** Whether a command is on PATH. */
  has(command: string): boolean;
  /** A command run quietly, with `input` on its stdin: its exit code and its stdout. */
  run(command: string, args: string[], input?: string): { code: number; out: string };
}

export const localShell = (): Shell => ({
  home: homedir(),
  platform: process.platform,
  env: process.env,
  has: (command) => onPath(command, process.env, process.platform),
  run(command, args, input) {
    const done = spawnSync(command, args, { input, encoding: "utf8", timeout: 30_000 });
    return { code: done.status ?? 1, out: done.stdout ?? "" };
  },
});

/** `credentials.json`: the key itself only when `store` is "file". */
export interface Saved {
  store: "keychain" | "file";
  key?: string;
  base_url?: string;
  user?: string;
  /** "personal" or "project", as the key's check said. */
  space?: string;
  /** What the key is, as `whoami` and `login` say it. */
  label?: string;
}

/** `ALEXEIN_CONFIG_DIR`, else `alexein` in the platform's place for settings. */
export function directory(shell: Shell): string {
  const env = shell.env;
  if (env.ALEXEIN_CONFIG_DIR) return env.ALEXEIN_CONFIG_DIR;
  if (shell.platform === "win32")
    return join(env.APPDATA || join(shell.home, "AppData", "Roaming"), "alexein");
  return join(env.XDG_CONFIG_HOME || join(shell.home, ".config"), "alexein");
}

export const credentialsFile = (shell: Shell) => join(directory(shell), "credentials.json");

interface Keychain {
  name: string;
  available(shell: Shell): boolean;
  put(shell: Shell, key: string): void;
  get(shell: Shell): string | undefined;
  drop(shell: Shell): boolean;
}

const MACOS: Keychain = {
  name: "the macOS keychain",
  available: (shell) => shell.has("security"),
  // Through `security -i`, so the key is on its stdin and never in the process list.
  put: (shell, key) =>
    void shell.run(
      "security",
      ["-i"],
      `add-generic-password -U -s ${SERVICE} -a ${ACCOUNT} -w ${key}\n`,
    ),
  get(shell) {
    const found = shell.run("security", [
      "find-generic-password",
      "-s",
      SERVICE,
      "-a",
      ACCOUNT,
      "-w",
    ]);
    return found.code === 0 ? found.out.trim() || undefined : undefined;
  },
  drop: (shell) =>
    shell.run("security", ["delete-generic-password", "-s", SERVICE, "-a", ACCOUNT]).code === 0,
};

const ATTRIBUTES = ["service", SERVICE, "account", ACCOUNT];

const SECRET_SERVICE: Keychain = {
  name: "the system keyring",
  available: (shell) => shell.has("secret-tool"),
  put: (shell, key) =>
    void shell.run("secret-tool", ["store", "--label=Alexein API key", ...ATTRIBUTES], key),
  get(shell) {
    const found = shell.run("secret-tool", ["lookup", ...ATTRIBUTES]);
    return found.code === 0 ? found.out.trim() || undefined : undefined;
  },
  drop: (shell) => shell.run("secret-tool", ["clear", ...ATTRIBUTES]).code === 0,
};

function keychain(shell: Shell): Keychain | undefined {
  const chosen =
    shell.platform === "darwin" ? MACOS : shell.platform === "linux" ? SECRET_SERVICE : undefined;
  return chosen?.available(shell) ? chosen : undefined;
}

/** `credentials.json`, or undefined when there is none. Throws when it is not one. */
export function readSaved(shell: Shell): Saved | undefined {
  const path = credentialsFile(shell);
  if (!existsSync(path)) return undefined;
  let saved: unknown;
  try {
    saved = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    saved = undefined;
  }
  const store = (saved as Saved | undefined)?.store;
  if (store !== "keychain" && store !== "file")
    throw new Error(`${path} is not a login this CLI wrote; run alexein logout, then log in again`);
  return saved as Saved;
}

function writeSaved(shell: Shell, saved: Saved): string {
  const dir = directory(shell);
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  const path = credentialsFile(shell);
  writeFileSync(path, JSON.stringify(saved, null, 2) + "\n", { mode: 0o600 });
  chmodSync(path, 0o600); // a file that was there keeps its mode through a write
  return path;
}

export interface Login {
  key: string;
  baseUrl?: string;
  user?: string;
  space?: string;
  label?: string;
  /** The key in the file even where there is a keychain. */
  insecure?: boolean;
}

/**
 * Keep a login: the key in the keychain, checked by reading it back, else in the file. Returns
 * where the key went, as a person reads it, and whether that was the file for want of a keychain.
 */
export function save(shell: Shell, login: Login): { where: string; fellBack: boolean } {
  const rest = {
    ...(login.baseUrl ? { base_url: login.baseUrl } : {}),
    ...(login.user ? { user: login.user } : {}),
    ...(login.space ? { space: login.space } : {}),
    ...(login.label ? { label: login.label } : {}),
  };
  const chain = login.insecure ? undefined : keychain(shell);
  if (chain && KEY_SHAPE.test(login.key)) {
    chain.put(shell, login.key);
    if (chain.get(shell) === login.key) {
      writeSaved(shell, { store: "keychain", ...rest });
      return { where: chain.name, fellBack: false };
    }
  }
  chain?.drop(shell); // a key an earlier login kept there is not left behind
  const path = writeSaved(shell, { store: "file", key: login.key, ...rest });
  return { where: path.replace(shell.home, "~"), fellBack: !login.insecure };
}

/**
 * The login kept, with its key and where that is: undefined when there is none. Throws when the key
 * is in a keychain that does not give it back - locked, or on a computer reached without its desktop.
 */
export function load(shell: Shell): { key: string; saved: Saved; where: string } | undefined {
  const saved = readSaved(shell);
  if (!saved) return undefined;
  if (saved.store === "file") {
    const path = credentialsFile(shell);
    if (!saved.key) throw new Error(`${path} holds no key; log in again`);
    return { key: saved.key, saved, where: path.replace(shell.home, "~") };
  }
  const chain = keychain(shell);
  const key = chain?.get(shell);
  if (!key)
    throw new Error(
      `the key is in ${chain?.name ?? "a keychain"} and it did not give it back; ` +
        "unlock it, log in again, or set ALEXEIN_API_KEY",
    );
  return { key, saved, where: chain!.name };
}

/** Take the login out: the keychain entry and the file. Says what went; empty when nothing did. */
export function forgetLogin(shell: Shell): string[] {
  const gone: string[] = [];
  const chain = keychain(shell);
  if (chain?.drop(shell)) gone.push(`the key, from ${chain.name}`);
  const path = credentialsFile(shell);
  if (existsSync(path)) {
    rmSync(path);
    gone.push(path.replace(shell.home, "~"));
  }
  return gone;
}
