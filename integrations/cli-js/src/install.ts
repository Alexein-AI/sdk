/**
 * The `alexein` command on PATH for good, so that after one `npx @alexein/cli ...` it is typed
 * directly. npx runs the CLI from its cache and never keeps it on PATH: `install` installs it with
 * npm, globally, where npm keeps the commands it installs - and the setup commands offer to, once,
 * when they run through npx at a terminal. `alexein-cli install` (Python) does the same through
 * `uv tool install`.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { delimiter, join } from "node:path";

import { type Host, localHost, onPath } from "./connect.js";
import { directory } from "./credentials.js";
import type { Console } from "./ui.js";

export const PACKAGE = "@alexein/cli";

/**
 * Whether `alexein` is on PATH for good. npx puts its cache's `node_modules/.bin` on the PATH of the
 * command it runs, and every project's above it, so those are not counted: they are this run's copy,
 * or a project's, not a command a new terminal has.
 */
export function installed(host: Host): boolean {
  const lasting = (host.env.PATH ?? "")
    .split(delimiter)
    .filter(
      (dir) =>
        dir && !/[\\/]node_modules[\\/]\.bin[\\/]?$/.test(dir) && !/[\\/]_npx[\\/]/.test(dir),
    );
  return onPath("alexein", { ...host.env, PATH: lasting.join(delimiter) }, host.platform);
}

/** Where npm puts the commands it installs globally; undefined when npm does not say. */
function npmBin(host: Host): string | undefined {
  const done = host.run("npm", ["prefix", "-g"]);
  const prefix = done.code === 0 ? done.out.trim().split("\n").at(-1)?.trim() : undefined;
  if (!prefix) return undefined;
  return host.platform === "win32" ? prefix : join(prefix, "bin");
}

/** `install`: 0 when `alexein` is on PATH, or installed with how to put its folder there. */
export function install(console: Console, host: Host = localHost()): number {
  if (installed(host)) {
    console.line("alexein is on your PATH already: type alexein in any terminal.");
    console.line(`  To upgrade it: npm update -g ${PACKAGE}`);
    return 0;
  }
  if (!host.has("npm")) {
    console.fail("npm is not on PATH: install Node 20 or newer, then run this again");
    return 1;
  }
  console.step("running", `npm install -g ${PACKAGE}`);
  if (host.attach("npm", ["install", "-g", PACKAGE]) !== 0) {
    console.fail(
      `npm install -g ${PACKAGE} failed. Where npm's global folder needs an administrator, ` +
        "run it with sudo, or set npm's prefix to a folder you own.",
    );
    return 1;
  }
  if (installed(host)) {
    console.step("installed", "alexein: type alexein in any terminal");
    return 0;
  }
  const bin = npmBin(host);
  console.step("installed", `alexein, in ${bin ?? "npm's global folder"}`);
  console.line(
    "  That folder is not on your PATH. Add it in your shell's profile, then open a new terminal:",
  );
  console.line(`    export PATH="${bin ?? "$(npm prefix -g)/bin"}:$PATH"`);
  return 0;
}

/** `state.json` beside the login: what the CLI remembers that is not a login. */
const stateFile = (host: Host) => join(directory(host), "state.json");

function declined(host: Host): boolean {
  try {
    return JSON.parse(readFileSync(stateFile(host), "utf8")).install === "declined";
  } catch {
    return false;
  }
}

function decline(host: Host): void {
  const path = stateFile(host);
  let state: Record<string, unknown> = {};
  try {
    if (existsSync(path)) state = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    state = {};
  }
  mkdirSync(directory(host), { recursive: true, mode: 0o700 });
  writeFileSync(path, JSON.stringify({ ...state, install: "declined" }, null, 2) + "\n");
}

/**
 * After a setup command that did what it was asked, at a terminal: when `alexein` is not on PATH,
 * ask once - Enter is yes - to install it. A no is kept, and it is not asked again. Never asked
 * where nobody can answer, or where what is printed goes somewhere other than a terminal.
 */
export async function offerInstall(
  console: Console,
  host: Host = localHost(),
  terminal: boolean = Boolean(process.stdout.isTTY),
): Promise<void> {
  if (!console.interactive || !terminal || installed(host) || declined(host)) return;
  console.line();
  if (
    await console.confirm(
      "Install the alexein command, so you can type alexein in any terminal?",
      true,
    )
  ) {
    install(console, host);
    return;
  }
  decline(host);
  console.line(`  Not installed, and not asked again. Any time: npx ${PACKAGE} install`);
}
