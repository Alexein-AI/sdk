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
    this.line(`  ${verb.padEnd(8)} ${what}`);
  }

  fail(why: string): void {
    this.line(`@alexein/cli: ${why}`);
  }

  async #reply(prompt: string, secret: boolean): Promise<string> {
    if (this.answers.length) {
      const reply = this.answers.shift()!;
      this.said.push(prompt + (secret && reply ? "***" : reply));
      return reply;
    }
    if (secret && process.stdin.isTTY) return hidden(prompt);
    const rl = createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    try {
      return await rl.question(prompt);
    } finally {
      rl.close();
    }
  }

  /** Yes with `--yes`; asked at a terminal, where Enter answers `byDefault`; no otherwise. */
  async confirm(question: string, byDefault = false): Promise<boolean> {
    if (this.yes) return true;
    if (!this.interactive) return false;
    const reply = await this.#reply(`  ${question} ${byDefault ? "[Y/n]" : "[y/N]"} `, false);
    const said = reply.trim().toLowerCase();
    return said ? ["y", "yes"].includes(said) : byDefault;
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

/**
 * A line typed at the terminal with nothing of it shown: the terminal in raw mode, each key read as it
 * comes, so no echo - the terminal's or readline's - can print a key. Enter ends it, Backspace takes a
 * character back, Ctrl-C stops the command as it does anywhere, and escape sequences (arrows) are
 * dropped. readline cannot be told to be quiet: Node 26 no longer writes through the `_writeToOutput`
 * an older version of this file replaced, and typed keys were shown.
 */
function hidden(prompt: string): Promise<string> {
  const input = process.stdin;
  process.stdout.write(prompt);
  input.setRawMode(true);
  input.setEncoding("utf8");
  input.resume();
  return new Promise((resolve) => {
    let typed = "";
    let escaping = false;
    const finish = () => {
      input.off("data", read);
      input.setRawMode(false);
      input.pause();
      process.stdout.write("\n");
    };
    const read = (chunk: string) => {
      for (const key of chunk) {
        if (escaping) {
          escaping = !/[A-Za-z~]/.test(key);
        } else if (key === "\u001b") {
          escaping = true;
        } else if (key === "\r" || key === "\n" || key === "\u0004") {
          finish();
          resolve(typed);
          return;
        } else if (key === "\u0003") {
          finish();
          process.kill(process.pid, "SIGINT");
          return;
        } else if (key === "\u007f" || key === "\b") {
          typed = typed.slice(0, -1);
        } else if (key >= " ") {
          typed += key;
        }
      }
    };
    input.on("data", read);
  });
}
