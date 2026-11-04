/**
 * What a run says: whose memory it reads (its context), what the user asked, and the turn
 * `remember` saves - the user's latest message and the final output.
 */

import type { AgentInputItem } from "@openai/agents";

import { stableId } from "../integrations/shared.js";
import type { Item } from "../items.js";

/**
 * Whose memory a run reads: pass it as the run's `context`, or give a context of your own a
 * `userId` (and, if you like, a `sessionId`, which groups what is saved by conversation).
 */
export interface MemoryContext {
  userId: string;
  sessionId?: string;
}

/** The app user a run's context names; never the model. */
export function userIdOf(context: unknown): string {
  const found = (context as Partial<MemoryContext> | undefined)?.userId;
  if (!found) {
    throw new Error(
      "Alexein needs to know whose memory this is: run the agent with " +
        '{ context: { userId: "..." } }',
    );
  }
  return String(found);
}

export function sessionIdOf(context: unknown): string | undefined {
  const found = (context as Partial<MemoryContext> | undefined)?.sessionId;
  return found ? String(found) : undefined;
}

/** What a message says, whether its content is a string or a list of parts. */
export function textOf(item: AgentInputItem): string {
  const content = "content" in item ? item.content : undefined;
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .flatMap((part) => ("text" in part && typeof part.text === "string" ? [part.text] : []))
    .join("\n");
}

export const saidByUser = (item: AgentInputItem): boolean => "role" in item && item.role === "user";

/** What `remember` reads of a run's result: a `RunResult` or a completed `StreamedRunResult`. */
export interface SavedResult {
  readonly interruptions?: readonly unknown[];
  readonly runContext?: { readonly context: unknown };
  readonly input?: string | AgentInputItem[];
  readonly finalOutput?: unknown;
  readonly lastAgent?: { readonly name: string } | undefined;
  readonly lastResponseId?: string | undefined;
}

/** Ids made for results whose model gave no response id. */
const turns = new WeakMap<object, string>();

/**
 * What sets this run's saves apart from another's with the same words: the model's response id,
 * or - from a model that gives none, as Chat Completions does - one made for this result, so that
 * saving it again still edits rather than adds.
 */
function turnOf(result: SavedResult): string {
  if (result.lastResponseId) return result.lastResponseId;
  const made = turns.get(result) ?? crypto.randomUUID();
  turns.set(result, made);
  return made;
}

/** The final output as text: a string as it is, structured output as JSON. */
function answer(output: unknown): string {
  if (output === undefined || output === null) return "";
  return typeof output === "string" ? output : JSON.stringify(output);
}

async function item(
  said: string,
  role: string,
  turn: string,
  author?: string,
): Promise<Item | undefined> {
  if (!said.trim()) return undefined;
  const id = await stableId(turn, role, said);
  return { id, role, text: said, ...(author ? { author } : {}) };
}

/** The turn's items, each with an id made from the run's turn and its words. */
export async function turnItems(result: SavedResult, session: string | undefined): Promise<Item[]> {
  const input = result.input ?? [];
  const said: AgentInputItem[] =
    typeof input === "string" ? [{ role: "user", content: input }] : input;
  const asked = said.findLast(saidByUser);
  const turn = `${session ?? ""}|${turnOf(result)}`;
  const items = [
    await item(asked ? textOf(asked) : "", "user", turn),
    await item(answer(result.finalOutput), "assistant", turn, result.lastAgent?.name),
  ];
  return items.filter((i): i is Item => i !== undefined);
}
