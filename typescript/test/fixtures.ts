/** What the API answers, route by route, as its reference shows it (docs.alexein.ai/api). */

export const EXCERPT = {
  type: "excerpt",
  ref: "mem_9fK2xQ7aLp3",
  text: "I just moved to Lisbon from Berlin\nfor the new job at Acme.",
  date: "2026-10-01T09:30:00+00:00",
  added_at: "2026-10-01T09:30:02+00:00",
  session: "onboarding",
  roles: ["user"],
};

export const FACT = {
  type: "fact",
  ref: "mem_5pQ1zX8gHd2",
  text: "(said 2026-10-01) Alice lives in Lisbon",
  source: "mem_9fK2xQ7aLp3",
};

export const SEARCH = {
  query: "Where does Alice live?",
  answerable: true,
  notes: ["Values are listed as stated, newest first."],
  memories: [
    {
      type: "known",
      text: "Alice Chen · home city: Lisbon (said 2026-10-01); Berlin (said 2024-06-01)",
    },
    FACT,
    EXCERPT,
  ],
};

export const GREP = {
  pattern: "peanuts",
  total: 1,
  memories: [
    {
      type: "excerpt",
      ref: "mem_7cJ4mE9tRw5",
      text: "Alice is vegan and allergic to peanuts.",
      date: "2026-10-02T12:00:00+00:00",
      added_at: "2026-10-02T12:00:03+00:00",
      session: null,
      roles: [],
    },
  ],
};

export const LATEST_NOWHERE = {
  memories: [],
  places: ["memory/documents", "memory/messages", "memory/notes"],
};

export const OPENED_FACT = { memory: FACT, sources: [EXCERPT] };
export const OPENED_EXCERPT = { memory: EXCERPT };

export const HISTORY = {
  subject: "Alice Chen",
  values: [
    { attribute: "home_city", value: "Berlin", since: "2024-03-01", negated: false },
    { attribute: "home_city", value: "Lisbon", since: "2026-10-01", negated: false },
  ],
};
export const HISTORY_MISSED = { subject: "Alice", values: [], suggestions: ["Alice Chen"] };

export const SOURCE = {
  provider: "github",
  source: "items",
  connection: "acme-org",
  items: 96,
  ended: 3,
  newest: "2026-10-02T17:21:40+00:00",
};

export const SUMMARY = {
  items: 214,
  first: "2024-06-01T10:02:00+00:00",
  last: "2026-10-03T08:00:00+00:00",
  sources: [SOURCE],
  known: ["Alice Chen · diet: vegan (said 2026-10-02)"],
};

export const FACTS = {
  facts: [{ ...FACT, date: "2026-10-01T09:30:00+00:00" }],
  next: "Kx7pW2qLm9vR",
};

export const OPEN_ITEMS = {
  items: [
    {
      ref: "mem_2hN6dS1kVb8",
      text: "acme/api#41 Fix the login redirect",
      date: "2026-10-01T08:00:00+00:00",
      added_at: "2026-10-01T08:00:02+00:00",
      age_days: 3,
    },
  ],
  follow_ups: [{ title: "Send the contract", who: "Bob", date: "2026-09-30", age_days: 4 }],
};

export const STORED = {
  id: "msg-001",
  kind: "message",
  text: "I just moved to Lisbon from Berlin for the new job at Acme.",
  at: "2026-10-01T09:30:00+00:00",
  author: { id: "u_42", name: "Alice Chen", self: true },
  role: "user",
  session: "onboarding",
  status: "stored",
};

export const ITEMS = {
  items: [
    {
      id: "pref-diet",
      kind: "note",
      text: "Alice is vegan and allergic to peanuts.",
      at: "2026-10-02T12:00:00+00:00",
      about: ["topic:diet"],
      metadata: { source: "crm" },
      status: "stored",
    },
    STORED,
  ],
  next: null,
};

export const ADDED = {
  items: [
    { id: "msg-001", status: "queued" },
    { id: "pref-diet", status: "stored", redacted: { PHONE: 1 } },
  ],
  waiting: 1,
};

export const STATUSES = {
  items: [
    { id: "msg-001", status: "processed", reason: null },
    { id: "nope-404", status: "unknown", reason: "Memory holds nothing by this id." },
  ],
};

export const FORGOTTEN = {
  erased: { items: 1, facts: 1, versions: 2, waiting: 0, relearning: 3 },
  complete: true,
};

export const CORRECTION = {
  retracted: "mem_5pQ1zX8gHd2",
  text: "(said 2026-10-01) Alice lives in Lisbon",
  replacement: "correction-334be8de711f8fde",
};

export const VERSIONS = {
  id: "pref-diet",
  state: "forgotten",
  history: [
    {
      event: "version",
      at: "2026-10-02T12:00:05+00:00",
      version: 1,
      item: { id: "pref-diet", kind: "note", text: "Alice is vegetarian." },
    },
    { event: "gone", at: "2026-10-21T16:40:09+00:00", why: "forgotten" },
  ],
};

export const EXPORT = {
  user: "user_42",
  exported_at: "2026-11-03T10:00:00+00:00",
  records: [
    { type: "item", id: "pref-diet", text: "Alice is vegan.", status: "stored" },
    { type: "fact", ref: "mem_3vB7yT0nKe6", text: "Alice is vegan", date: "2026-10-02" },
  ],
  next: null,
  withheld: ["version"],
};

export const USERS = {
  users: [
    { user: "user_42", items: 18, facts: 41, last_write: "2026-10-01T09:14:02Z" },
    { user: "user_7", items: 3, facts: 5, last_write: null },
  ],
  next: null,
};

export const ME = {
  kind: "key",
  org: "o7k2m9qx4ab",
  project: "production",
  key_id: "key_3f9a1c2b7d4e",
  writes: true,
  label: "backend",
  created: "2026-09-01T00:00:00Z",
  created_by: "dev@acme.com",
  org_name: "Acme",
  project_name: "Production",
  space: "project",
};

export const DELETED = { user: "user_42", deleted: true };
