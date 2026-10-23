/**
 * Templates into source: the parts a preset leaves out cut away, and the values filled in.
 *
 * A template marks each optional part with a pair of comment lines, `// >>> nodes` and
 * `// <<< nodes`, around whole lines; what is not asked for is dropped with its markers, and the
 * markers of what is kept are dropped too, so the written file carries none of this. Values are
 * `{name}` placeholders, filled by plain replacement, since the code around them is full of
 * braces of its own.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const TEMPLATES = fileURLToPath(new URL("../templates/", import.meta.url));

const MARK = /^\s*(?:#|\/\/) (>>>|<<<) ([a-z_]+)\s*$/;

/** The template at `templates/<template>`, keeping only `parts`, with `values` filled. */
export function render(
  template: string,
  parts: Iterable<string>,
  values: Record<string, string>,
): string {
  const kept = new Set(parts);
  const out: string[] = [];
  const skipping: string[] = [];
  for (const line of readFileSync(TEMPLATES + template, "utf8").split("\n")) {
    const mark = MARK.exec(line);
    if (mark) {
      const [, side, part] = mark as unknown as [string, string, string];
      if (side === ">>>" && !kept.has(part)) skipping.push(part);
      else if (side === "<<<" && skipping.at(-1) === part) skipping.pop();
      continue;
    }
    if (!skipping.length) out.push(line);
  }
  let text = out.join("\n").replace(/\n*$/, "\n");
  for (const [name, value] of Object.entries(values)) text = text.replaceAll(`{${name}}`, value);
  return text;
}
