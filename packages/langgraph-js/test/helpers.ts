/** Projects in a scratch directory, and `init` run over them with commands recorded, not run. */

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import type { Check } from "../src/env.js";
import { init, options, type Options } from "../src/scaffold.js";
import { Console } from "../src/ui.js";

/** Inside the package, so what is written there resolves this package's dependencies. */
export const GENERATED = fileURLToPath(new URL("./.generated/", import.meta.url));

export class Project {
  readonly ran: string[][] = [];
  readonly checked: [string, string | undefined][] = [];
  code = 0;
  check: Check = { ok: true, writes: true, detail: "scratch/demo, reads and writes" };

  constructor(readonly root: string) {}

  static scratch(inside = tmpdir()): Project {
    mkdirSync(inside, { recursive: true });
    return new Project(mkdtempSync(join(inside, "project-")));
  }

  remove(): void {
    rmSync(this.root, { recursive: true, force: true });
  }

  file(path: string, text: string): this {
    mkdirSync(dirname(join(this.root, path)), { recursive: true });
    writeFileSync(join(this.root, path), text);
    return this;
  }

  npm(deps: Record<string, string> = { "@langchain/langgraph": "^1.0.0" }): this {
    this.file(
      "package.json",
      JSON.stringify({ name: "my-agent", type: "module", dependencies: deps }),
    );
    return this.file("package-lock.json", "{}");
  }

  graphs(specs: Record<string, unknown>): this {
    return this.file("langgraph.json", JSON.stringify({ graphs: specs }));
  }

  installed(versions: Record<string, string>): this {
    for (const [name, version] of Object.entries(versions)) {
      this.file(`node_modules/${name}/package.json`, JSON.stringify({ name, version }));
    }
    return this;
  }

  options(given: Partial<Options> = {}): Options {
    return options({
      skipKey: true,
      run: (command) => {
        this.ran.push(command);
        return this.code;
      },
      check: async (key, baseUrl) => {
        this.checked.push([key, baseUrl]);
        return this.check;
      },
      ...given,
    });
  }

  async init(
    given: Partial<Options> & { cwd?: string; console?: Console; framework?: string } = {},
  ): Promise<[number, Console]> {
    const { cwd, console = quiet(), framework = "langgraph", ...rest } = given;
    const code = await init(framework, cwd ?? this.root, this.options(rest), console);
    return [code, console];
  }
}

export function quiet(fields: ConstructorParameters<typeof Console>[0] = {}): Console {
  return new Console({ out: () => {}, ...fields });
}

export function said(console: Console): string {
  return console.said.join("\n");
}
