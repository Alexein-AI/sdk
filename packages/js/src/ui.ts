/**
 * How the CLI talks to the person running it: lines of output, and questions when there is
 * someone at a terminal to answer them. A test hands in a `Console` with answers ready; a script
 * or CI gets one that asks nothing and takes every default.
 */

import { createInterface } from "node:readline/promises";

export interface ConsoleOptions {
  interactive?: boolean;
  yes?: boolean;
  answers?: string[];
  out?: (text: string) => void;
}

export class Console {
  readonly interactive: boolean;
  readonly yes: boolean;
  readonly answers: string[];
  readonly said: string[] = [];
  readonly #out: (text: string) => void;

  constructor(options: ConsoleOptions = {}) {
    this.interactive = options.interactive ?? false;
    this.yes = options.yes ?? false;
    this.answers = options.answers ?? [];
    this.#out = options.out ?? ((text) => process.stdout.write(text + "\n"));
  }

  static forTerminal(yes: boolean): Console {
    return new Console({ interactive: Boolean(process.stdin.isTTY) && !yes, yes });
  }

  line(text = ""): void {
    this.said.push(text);
    this.#out(text);
  }

  step(verb: string, what: string): void {
    this.line(`  ${verb.padEnd(9)}${what}`);
  }

  fail(why: string): void {
    this.line(`twinmemory-cli: ${why}`);
  }

  async #reply(prompt: string, secret: boolean): Promise<string> {
    if (this.answers.length) {
      const reply = this.answers.shift()!;
      this.said.push(prompt + (secret && reply ? "***" : reply));
      return reply;
    }
    const rl = createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    if (secret) {
      // Echo nothing of what is typed: the prompt is written once, keystrokes never.
      const quiet = rl as unknown as { _writeToOutput: (s: string) => void };
      let shown = false;
      quiet._writeToOutput = (s: string) => {
        if (!shown) process.stdout.write(s);
        shown = true;
      };
    }
    try {
      return await rl.question(prompt);
    } finally {
      if (secret) process.stdout.write("\n");
      rl.close();
    }
  }

  /** Yes with `--yes`; asked at a terminal; no otherwise. */
  async confirm(question: string): Promise<boolean> {
    if (this.yes) return true;
    if (!this.interactive) return false;
    const reply = await this.#reply(`  ${question} [y/N] `, false);
    return ["y", "yes"].includes(reply.trim().toLowerCase());
  }

  /** A key, typed without echo; empty when skipped or when nobody can answer. */
  async secret(question: string): Promise<string> {
    if (!this.interactive) return "";
    return (await this.#reply(`  ${question} `, true)).trim();
  }

  /** One of `options` by number or name; undefined when nobody can answer. */
  async choose(question: string, options: string[]): Promise<string | undefined> {
    if (!this.interactive) return undefined;
    options.forEach((option, n) => this.line(`    ${n + 1}. ${option}`));
    const reply = (await this.#reply(`  ${question} `, false)).trim();
    const n = Number(reply);
    if (Number.isInteger(n) && n >= 1 && n <= options.length) return options[n - 1];
    return options.includes(reply) ? reply : undefined;
  }
}
