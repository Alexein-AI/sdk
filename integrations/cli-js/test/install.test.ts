/** `install` and its offer: `alexein` put on PATH with npm, and npx's own copy not taken for it. */

import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import type { Host } from "../src/connect.js";
import { install, installed, offerInstall } from "../src/install.js";
import { Console } from "../src/ui.js";

const homes: string[] = [];
afterEach(() => homes.splice(0).forEach((home) => rmSync(home, { recursive: true, force: true })));

/**
 * A computer running the CLI through npx: npx's cache, with its own `alexein`, first on PATH, and
 * npm's global bin after it when `onPath`. npm installs by writing `alexein` there.
 */
class Computer implements Host {
  readonly home = mkdtempSync(join(tmpdir(), "home-"));
  readonly platform = "linux" as const;
  readonly env: NodeJS.ProcessEnv;
  readonly bin: string;
  readonly attached: string[] = [];

  constructor({ npm = true, onPath = true, fails = false } = {}) {
    homes.push(this.home);
    this.npm = npm;
    this.fails = fails;
    this.bin = join(this.home, "prefix", "bin");
    const npx = join(this.home, ".npm", "_npx", "150e98", "node_modules", ".bin");
    const project = join(this.home, "project", "node_modules", ".bin");
    for (const dir of [this.bin, npx, project]) mkdirSync(dir, { recursive: true });
    writeFileSync(join(npx, "alexein"), "");
    writeFileSync(join(project, "alexein"), "");
    const path = [npx, project, ...(onPath ? [this.bin] : [])];
    this.env = { PATH: path.join(":"), ALEXEIN_CONFIG_DIR: join(this.home, "config") };
  }

  readonly npm: boolean;
  readonly fails: boolean;

  has(command: string): boolean {
    return command === "npm" && this.npm;
  }

  run(command: string, args: string[]) {
    if (command === "npm" && args.join(" ") === "prefix -g")
      return { code: 0, out: `${join(this.home, "prefix")}\n` };
    return { code: 1, out: "" };
  }

  attach(command: string, args: string[]): number {
    this.attached.push([command, ...args].join(" "));
    if (this.fails) return 1;
    writeFileSync(join(this.bin, "alexein"), "");
    return 0;
  }
}

const quiet = (answers?: string[]) =>
  new Console({ interactive: answers !== undefined, answers, out: () => {} });

describe("install", () => {
  it("does not take npx's copy, or a project's, for alexein on PATH", () => {
    const computer = new Computer();
    expect(installed(computer)).toBe(false);
    writeFileSync(join(computer.bin, "alexein"), "");
    expect(installed(computer)).toBe(true);
  });

  it("installs alexein with npm, globally, where a new terminal finds it", () => {
    const computer = new Computer();
    const console = quiet();
    expect(install(console, computer)).toBe(0);
    expect(computer.attached).toEqual(["npm install -g @alexein/cli"]);
    expect(console.said.join("\n")).toContain("installed alexein: type alexein in any terminal");
    expect(installed(computer)).toBe(true);
  });

  it("says how to put npm's folder on PATH where it is not", () => {
    const computer = new Computer({ onPath: false });
    const console = quiet();
    expect(install(console, computer)).toBe(0);
    expect(console.said.join("\n")).toContain(`export PATH="${computer.bin}:$PATH"`);
  });

  it("leaves an alexein that is there, and says when npm is missing or fails", () => {
    const there = new Computer();
    writeFileSync(join(there.bin, "alexein"), "");
    const console = quiet();
    expect(install(console, there)).toBe(0);
    expect(there.attached).toEqual([]);
    expect(console.said.join("\n")).toContain("on your PATH already");

    const noNpm = quiet();
    expect(install(noNpm, new Computer({ npm: false }))).toBe(1);
    expect(noNpm.said.join("\n")).toContain("npm is not on PATH");

    const failing = quiet();
    expect(install(failing, new Computer({ fails: true }))).toBe(1);
    expect(failing.said.join("\n")).toContain("run it with sudo, or set npm's prefix");
  });
});

describe("the offer to install", () => {
  it("asks once at a terminal, and Enter installs", async () => {
    const computer = new Computer();
    const console = quiet([""]);
    await offerInstall(console, computer, true);
    expect(console.said.join("\n")).toContain(
      "Install the alexein command, so you can type alexein in any terminal? [Y/n]",
    );
    expect(computer.attached).toEqual(["npm install -g @alexein/cli"]);
  });

  it("keeps a no, and does not ask again", async () => {
    const computer = new Computer();
    const first = quiet(["n"]);
    await offerInstall(first, computer, true);
    expect(computer.attached).toEqual([]);
    expect(first.said.join("\n")).toContain("not asked again. Any time: npx @alexein/cli install");
    const state = JSON.parse(
      readFileSync(join(computer.env.ALEXEIN_CONFIG_DIR!, "state.json"), "utf8"),
    );
    expect(state).toEqual({ install: "declined" });

    const second = quiet(["y"]);
    await offerInstall(second, computer, true);
    expect(second.said).toEqual([]);
    expect(computer.attached).toEqual([]);
  });

  it("never asks where nobody can answer, or where the output is not a terminal", async () => {
    const computer = new Computer();
    await offerInstall(quiet(), computer, true);
    await offerInstall(quiet(["y"]), computer, false);
    expect(computer.attached).toEqual([]);
  });
});
