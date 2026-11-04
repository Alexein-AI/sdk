/** A memory API that answers as the real one does, and a client whose requests are recorded. */

import { Memory } from "../../src/index.js";

export interface Sent {
  route: string;
  headers: Record<string, string>;
  body: Record<string, any>;
}

export type Respond = (route: string, body: any) => Response;

export const REF = "mem_9fK2xQ7aLp3";
export const FACT_REF = "mem_5pQ1zX8gHd2";

export const SEARCHED = {
  query: "q",
  answerable: true,
  notes: [],
  memories: [
    { type: "known", text: "Dana lives in Lisbon." },
    { type: "fact", ref: FACT_REF, text: "Dana moved to Lisbon.", source: REF },
    {
      type: "excerpt",
      ref: REF,
      text: "Dana: I moved to Lisbon.",
      date: "2026-10-01T09:30:00+00:00",
      added_at: "2026-10-01T09:30:02+00:00",
      session: "t-1",
      roles: ["user"],
    },
  ],
};

export const OPENED = { memory: SEARCHED.memories[2] };

/** The route after `/v2/memory/`. */
const routeOf = (url: string) => new URL(url).pathname.replace(/^\/v2\/(memory\/)?/, "");

export function answer(route: string): Response {
  if (route === "search") return Response.json(SEARCHED);
  if (route === "open") return Response.json(OPENED);
  if (route === "add") return Response.json({ items: [], waiting: 1 }, { status: 202 });
  return Response.json({});
}

export const down = () => Response.json({ detail: "briefly unavailable" }, { status: 503 });
export const wrongKey = () => Response.json({ detail: "bad key" }, { status: 401 });

/** A client answered by `respond`, as an integration makes its own: fail-open unless strict. */
export function recorded(respond: Respond = answer, integration: string, failOpen = true) {
  const sent: Sent[] = [];
  const memory = new Memory({
    apiKey: "ak_test",
    failOpen,
    integration,
    maxRetries: 0,
    logger: () => {},
    fetch: async (input, init) => {
      const route = routeOf(String(input));
      const body = init?.body ? JSON.parse(String(init.body)) : {};
      sent.push({ route, headers: init?.headers as Record<string, string>, body });
      return respond(route, body);
    },
  });
  return { memory, sent };
}

export const routes = (sent: Sent[]) => sent.map((s) => s.route);
export const bodies = (sent: Sent[], route: string) =>
  sent.filter((s) => s.route === route).map((s) => s.body);
export const users = (sent: Sent[]) => new Set(sent.map((s) => s.headers["X-Alexein-User"]));
