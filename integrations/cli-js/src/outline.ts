/**
 * What the memory commands print for a person to read. Memories - a search's, the latest - as a
 * list: each one's kind, day and ref, then its text. Anything else as an outline of the JSON that
 * came back, every field of it, so a field the API adds later shows without a change here. With
 * `--json` none of this is used: the commands print the API's JSON as it came.
 */

type Json = unknown;

const isObject = (value: Json): value is Record<string, Json> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Nothing to show: null, "", [], {}, or an object of nothing but those. */
function empty(value: Json): boolean {
  if (value === null || value === undefined || value === "") return true;
  if (Array.isArray(value)) return value.length === 0;
  if (isObject(value)) return Object.values(value).every(empty);
  return false;
}

function scalar(value: Json): string {
  if (value === null || value === undefined) return "-";
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** A string that runs over lines, its later lines under its first. */
const indented = (text: string, indent: string) => text.split("\n").join(`\n${indent}`);

/** JSON as indented lines, as YAML would show it, with nothing quoted. */
export function outline(value: Json, indent = ""): string[] {
  if (Array.isArray(value)) {
    if (!value.length) return [`${indent}(none)`];
    return value.flatMap((entry) => {
      const [first = "", ...rest] = outline(entry, `${indent}  `);
      return [`${indent}- ${first.slice(indent.length + 2)}`, ...rest];
    });
  }
  if (isObject(value)) {
    const entries = Object.entries(value);
    if (!entries.length) return [`${indent}(none)`];
    return entries.flatMap(([name, entry]) => {
      if ((Array.isArray(entry) || isObject(entry)) && empty(entry))
        return [`${indent}${name}: (none)`];
      if (isObject(entry) || Array.isArray(entry))
        return [`${indent}${name}:`, ...outline(entry, `${indent}  `)];
      return [`${indent}${name}: ${indented(scalar(entry), `${indent}  `)}`];
    });
  }
  return [`${indent}${indented(scalar(value), indent)}`];
}

/** One memory as a heading - its kind, its day, its ref - and its text under it. */
function memory(entry: Json, kind: string): string[] {
  if (!isObject(entry)) return outline(entry);
  if (typeof entry.type === "string") kind = entry.type;
  const day = typeof entry.date === "string" ? entry.date.slice(0, 10) : "";
  const ref = typeof entry.ref === "string" ? entry.ref : "";
  const session = typeof entry.session === "string" ? `  (session ${entry.session})` : "";
  const heading = ([kind.padEnd(8), day, ref].filter(Boolean).join("  ") + session).trimEnd();
  return [heading, `  ${indented(scalar(entry.text ?? ""), "  ")}`];
}

/**
 * Memories, one after another with a line between; `none` when there are none. `kind` names those
 * that do not say what they are: the latest are all excerpts, and say nothing.
 */
export function memories(list: Json, none: string, kind = "memory"): string[] {
  if (!Array.isArray(list) || !list.length) return [none];
  return list.flatMap((entry, n) => [...(n ? [""] : []), ...memory(entry, kind)]);
}
