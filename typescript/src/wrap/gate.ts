/**
 * What decides whether a model call is given memory, and what it may see: a turn worth looking
 * up, the memories that bear on it, text that cannot pass for markup, and a query with no secret
 * in it. The Python client's `alexein/_gate.py` is the same.
 */

import type { MemoryEntry } from "../memories.js";

/**
 * Words a go-ahead, a thank-you or a greeting is made of. A message of these alone (and perhaps one
 * name: "Thanks Claude!") asks nothing memory could answer.
 */
const ACK_WORDS = new Set(
  `thanks thank thx ty you so much very many ok okay kk yes yeah yep yup no nope nah sure great
  cool nice perfect perfectly awesome good fine lgtm works worked working got it sounds sound
  looks look please do go ahead continue proceed done alright right wonderful excellent amazing
  brilliant appreciated appreciate cheers hi hello hey bye goodbye that this thats all for now
  then will lol haha the and just really too again also well indeed exactly correct agreed
  agree understood makes sense love is was`.split(/\s+/),
);
/** The words such a message opens with, when it adds one name of its own ("Thanks Claude"). */
const ACK_OPENERS = new Set(
  `thanks thank thx ty ok okay kk yes yeah yep yup no nope nah sure great cool nice perfect
  awesome good fine lgtm sounds looks got hi hello hey cheers lol haha alright`.split(/\s+/),
);

/**
 * Whether the user's message is worth a lookup: anything but a slash command, and a message that
 * is only a go-ahead, a thank-you or a greeting ("thanks!", "ok, do it", "sounds good", "Thanks
 * Claude, that worked perfectly", "👍"). A question always is, and so is anything about the user
 * ("What do you know about me?").
 */
export function worthRecall(said: string): boolean {
  const text = said.trim();
  if (!text || text.startsWith("/")) return false;
  if (text.includes("?")) return true;
  const words = text.toLowerCase().match(/[a-z]+/g) ?? [];
  const extra = words.filter((w) => w.length > 1 && !ACK_WORDS.has(w));
  if (!extra.length) return false;
  return !(extra.length === 1 && ACK_OPENERS.has(words[0]!));
}

/** What a memory is known by, so it is shown once in a session: its ref, else its words. */
export function markOf(memory: MemoryEntry): string {
  const ref = memory.type === "known" ? memory.raw.ref : memory.ref;
  return typeof ref === "string" && ref
    ? ref
    : memory.text.split(/\s+/).filter(Boolean).join(" ").slice(0, 200);
}

/**
 * Of a search's memories, in the order memory ranked them, those to show: the lines the API lists
 * after the excerpts - the rest of what it holds, which bore on nothing asked - left out, and none
 * shown before in this session.
 */
export function relevant(
  memories: readonly MemoryEntry[],
  shown: ReadonlySet<string>,
): MemoryEntry[] {
  const kept: MemoryEntry[] = [];
  let past = false;
  for (const memory of memories) {
    if (memory.type === "excerpt") past = true;
    else if (past) continue;
    if (!shown.has(markOf(memory))) kept.push(memory);
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
