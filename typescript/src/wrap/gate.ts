/**
 * What decides whether a model call is given memory, and what it may see: a turn worth looking
 * up, the memories that bear on it, text that cannot pass for markup, and a query with no secret
 * in it. The Python client's `alexein/_gate.py` is the same.
 */

import type { MemoryEntry } from "../memories.js";

/**
 * Words that say nothing about a topic: how questions and requests are asked, and code's own
 * keywords. A topic is the rest (`terms`).
 */
const STOP = new Set(
  `about above after again against all also always and another any anything are around because
  been before being below between both but can cannot could did does doing done down during
  each either else even ever every few for from further get gets getting give going gone got
  had has have having her here hers him his how however into its itself just keep know last
  least less let lets like likely look looks made make makes many may maybe might mine more
  most much must need needs never new next not now off once one only onto other others our
  ours out over own please put quite rather really right said same say says see seem seems set
  shall she should show since some something still such sure take than thank thanks that the
  their theirs them then there these they thing things think this those though through too
  try under until upon use used uses using very want wants was way well were what whatever
  when where whether which while who whom whose why will with within without would yes yet
  you your yours yourself okay hello hey hi
  const var function return import export class def self true false null none async await
  type interface string number int str bool void public private static elif while try catch
  except raise throw lambda yield pass break continue new this from`.split(/\s+/),
);
const WORD = /[A-Za-z][A-Za-z0-9]+/g;
const CAMEL = /([a-z0-9])([A-Z])/g;
/** A go-ahead or a thank-you: no question to look up, unless it goes on to name a topic at length. */
const ACK =
  /^\s*(?:yes|yeah|yep|no|nope|ok|okay|sure|thanks|thank you|great|cool|nice|perfect|go ahead|continue|proceed|do it|sounds good|lgtm|looks good)\b/i;

function stem(word: string): string {
  for (const suffix of ["ing", "ed", "es", "s"]) {
    if (word.endsWith(suffix) && word.length - suffix.length >= 4) {
      return word.slice(0, -suffix.length);
    }
  }
  return word;
}

/** A text's topic words: lower case, camelCase split, short and common words left out, stemmed. */
export function terms(text: string): Set<string> {
  const out = new Set<string>();
  for (const found of (text ?? "").replace(CAMEL, "$1 $2").matchAll(WORD)) {
    const word = found[0].toLowerCase();
    if (word.length >= 3 && !STOP.has(word)) out.add(stem(word));
  }
  return out;
}

function matches(term: string, words: Set<string>): boolean {
  if (words.has(term)) return true;
  if (term.length < 5) return false;
  for (const w of words) if (w.length >= 5 && w.slice(0, 5) === term.slice(0, 5)) return true;
  return false;
}

function overlap(wanted: Set<string>, text: string): number {
  const words = terms(text);
  let n = 0;
  for (const term of wanted) if (matches(term, words)) n++;
  return n;
}

/**
 * Whether the user's message is worth a lookup: it names a topic, and is not a go-ahead or a
 * thank-you ("thanks!", "ok, do it", "sounds good") with few words of its own.
 */
export function worthRecall(said: string): boolean {
  const text = said.trim();
  if (!text || text.startsWith("/")) return false;
  const named = terms(text);
  if (!named.size) return false;
  return !(ACK.test(text) && named.size < 6);
}

/** What a memory is known by, so it is shown once in a session: its ref, else its words. */
export function markOf(memory: MemoryEntry): string {
  const ref = memory.type === "known" ? memory.raw.ref : memory.ref;
  return typeof ref === "string" && ref
    ? ref
    : memory.text.split(/\s+/).filter(Boolean).join(" ").slice(0, 200);
}

/**
 * Of a search's memories, in order, those that bear on `query`: the lines the API lists after the
 * excerpts - the rest of what it holds, which bore on nothing asked - left out; of the rest, those
 * sharing a topic word with the query (two for a query of more than three), and not shown before
 * in this session.
 */
export function relevant(
  memories: readonly MemoryEntry[],
  query: string,
  shown: ReadonlySet<string>,
): MemoryEntry[] {
  const wanted = terms(query);
  if (!wanted.size) return [];
  const need = wanted.size <= 3 ? 1 : 2;
  const kept: MemoryEntry[] = [];
  let past = false;
  for (const memory of memories) {
    if (memory.type === "excerpt") past = true;
    else if (past) continue;
    if (shown.has(markOf(memory))) continue;
    if (overlap(wanted, memory.text) >= need) kept.push(memory);
  }
  return kept;
}

/**
 * Every character a model may read as an angle bracket - the ASCII ones, their fullwidth, small,
 * vertical, mathematical, ornamental and quotation-mark forms - made a parenthesis, which no tag
 * is written with; and the ampersand that starts an entity.
 */
const OPENS =
  "\u003c\u00ab\u2039\u02c2\u1438\u2329\u27e8\u27ea\u276c\u276e\u2770\u2991\u29fc\u3008\u300a\ufe3d\ufe3f\ufe64\uff1c\u226a";
const CLOSES =
  "\u003e\u00bb\u203a\u02c3\u1433\u232a\u27e9\u27eb\u276d\u276f\u2771\u2992\u29fd\u3009\u300b\ufe3e\ufe40\ufe65\uff1e\u226b";
const MARKUP = new Map<string, string>([
  ...[...OPENS].map((c): [string, string] => [c, "("]),
  ...[...CLOSES].map((c): [string, string] => [c, ")"]),
  ["&", "+"],
]);
const MARKED = new RegExp(`[${[...MARKUP.keys()].join("")}]`, "gu");

/**
 * `text` on one line, as it cannot be read as markup or hide anything unseen: format characters
 * (zero-width, bidi, tag characters) dropped, every control and line break a space.
 */
export function inert(text: string): string {
  return text
    .replace(/\p{Cf}/gu, "")
    .replace(MARKED, (c) => MARKUP.get(c) ?? c)
    .replace(/[\s\p{Cc}]+/gu, " ")
    .trim();
}

const SECRET = "[secret]";
/** Secrets, by their shape: never sent as a search. Simple patterns, as a backstop. */
const SECRETS: [RegExp, string][] = [
  [
    /-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)/g,
    SECRET,
  ],
  [
    new RegExp(
      "\\b(?:sk-(?:ant-|proj-)?[A-Za-z0-9_\\-]{16,}" +
        "|tm_[A-Za-z0-9_\\-]{12,}" +
        "|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}" +
        "|glpat-[A-Za-z0-9_\\-]{16,}" +
        "|xox[abposr]-[A-Za-z0-9\\-]{10,}" +
        "|(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}" +
        "|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}" +
        "|AIza[0-9A-Za-z_\\-]{30,}" +
        "|npm_[A-Za-z0-9]{30,}" +
        "|pypi-[A-Za-z0-9_\\-]{40,}" +
        "|hf_[A-Za-z0-9]{30,})",
      "g",
    ),
    SECRET,
  ],
  [/\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}/g, SECRET],
  [/\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}/gi, `$1 ${SECRET}`],
  [/\b([a-z][a-z0-9+.-]*:\/\/[^\s:/@]+):[^\s@/]+@/gi, `$1:${SECRET}@`],
  [
    /(["']?[A-Za-z0-9_-]*(?:passw(?:or)?d|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|credential|auth[_-]?key)[A-Za-z0-9_-]*["']?\s*[:=]\s*)("[^"\n]*"|'[^'\n]*'|[^\s,;"'}{)]+)/gi,
    `$1${SECRET}`,
  ],
];
/** A run of digits as people write one: groups split by single spaces, dashes or dots. */
const DIGITS = /(?<![\w])\+?\d(?:[ .-]?\d){6,}(?![\w])/g;

function luhn(digits: string): boolean {
  let total = 0;
  [...digits].reverse().forEach((d, i) => {
    let n = Number(d) * (i % 2 ? 2 : 1);
    if (n > 9) n -= 9;
    total += n;
  });
  return total % 10 === 0;
}

function numberShown(found: string): string {
  const digits = found.replace(/\D/g, "");
  if (digits.length >= 13 && digits.length <= 19 && luhn(digits)) return "[card number]";
  // Nine digits at least, or a leading +: a date (2026-10-01) has eight.
  if (digits.length <= 15 && (digits.length >= 9 || found.startsWith("+"))) return "[phone number]";
  return found;
}

/** A search query with no key, token or password in it; with `redact`, no card or phone number. */
export function queryText(text: string, redact: boolean): string {
  let out = text;
  for (const [pattern, replacement] of SECRETS) out = out.replace(pattern, replacement);
  return redact ? out.replace(DIGITS, numberShown) : out;
}
