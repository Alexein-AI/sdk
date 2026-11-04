/** What each answer becomes: typed, camelCase, with the API's JSON kept as `raw`. */

import { describe, expect, it } from "vitest";
import * as F from "./fixtures.js";
import { memory, ok } from "./helpers.js";

/** A user whose every request is answered with `body`. */
const answering = (body: unknown) => memory(() => ok(body)).client.user("alice");

describe("reads", () => {
  it("grep: memories with the pattern and total, iterable", async () => {
    const found = await answering(F.GREP).grep("peanuts");
    expect([found.pattern, found.total, found.places]).toEqual(["peanuts", 1, null]);
    expect([...found].map((m) => m.type)).toEqual(["excerpt"]);
    const [excerpt] = found.memories;
    expect(excerpt).toEqual({
      type: "excerpt",
      ref: "mem_7cJ4mE9tRw5",
      text: "Alice is vegan and allergic to peanuts.",
      date: "2026-10-02T12:00:00+00:00",
      addedAt: "2026-10-02T12:00:03+00:00",
      session: null,
      roles: [],
      raw: F.GREP.memories[0],
    });
    expect(found.raw).toEqual(F.GREP);
  });

  it("latest: the places there are when a place matched nothing", async () => {
    const found = await answering(F.LATEST_NOWHERE).latest({ place: "nowhere" });
    expect(found.memories).toEqual([]);
    expect(found.places).toEqual(F.LATEST_NOWHERE.places);
    expect([found.pattern, found.total]).toEqual([null, null]);
  });

  it("around: excerpts in order", async () => {
    const found = await answering({ memories: [F.EXCERPT, F.EXCERPT] }).around("mem_1");
    expect(found.memories.map((m) => m.type)).toEqual(["excerpt", "excerpt"]);
  });

  it("open: a fact with its sources, or an excerpt alone", async () => {
    const fact = await answering(F.OPENED_FACT).open(F.FACT.ref);
    expect(fact.memory).toEqual({ ...F.FACT, date: null, raw: F.FACT });
    expect(fact.sources.map((s) => [s.ref, s.addedAt, s.roles])).toEqual([
      ["mem_9fK2xQ7aLp3", "2026-10-01T09:30:02+00:00", ["user"]],
    ]);
    const excerpt = await answering(F.OPENED_EXCERPT).open(F.EXCERPT.ref);
    expect(excerpt.memory.type).toBe("excerpt");
    expect(excerpt.sources).toEqual([]);
    expect(excerpt.raw).toEqual(F.OPENED_EXCERPT);
  });

  it("history: values, and suggestions for a subject that misses", async () => {
    const found = await answering(F.HISTORY).history("Alice Chen");
    expect(found.values.map((v) => [v.attribute, v.value, v.since, v.negated])).toEqual([
      ["home_city", "Berlin", "2024-03-01", false],
      ["home_city", "Lisbon", "2026-10-01", false],
    ]);
    expect(found.suggestions).toBeNull();
    expect((await answering(F.HISTORY_MISSED).history("Alice")).suggestions).toEqual([
      "Alice Chen",
    ]);
  });

  it("summary and sources", async () => {
    const summary = await answering(F.SUMMARY).summary();
    expect([summary.items, summary.first, summary.last, summary.known]).toEqual([
      214,
      "2024-06-01T10:02:00+00:00",
      "2026-10-03T08:00:00+00:00",
      F.SUMMARY.known,
    ]);
    const source = { ...F.SOURCE, raw: F.SOURCE };
    expect(summary.sources).toEqual([source]);
    expect((await answering({ sources: [F.SOURCE] }).sources()).sources).toEqual([source]);
  });

  it("openItems: items and follow-ups in camelCase", async () => {
    const open = await answering(F.OPEN_ITEMS).openItems();
    expect(open.items[0]).toMatchObject({ ref: "mem_2hN6dS1kVb8", ageDays: 3 });
    expect(open.items[0]!.addedAt).toBe("2026-10-01T08:00:02+00:00");
    expect(open.followUps).toEqual([
      {
        title: "Send the contract",
        who: "Bob",
        date: "2026-09-30",
        ageDays: 4,
        raw: F.OPEN_ITEMS.follow_ups[0],
      },
    ]);
  });
});

describe("pages", () => {
  it("facts: dated, with the cursor of the next page", async () => {
    const page = await answering(F.FACTS).facts();
    expect(page.facts[0]).toMatchObject({ type: "fact", date: "2026-10-01T09:30:00+00:00" });
    expect(page.next).toBe("Kx7pW2qLm9vR");
  });

  it("items: each as added, with its status", async () => {
    const page = await answering(F.ITEMS).items();
    expect(page.next).toBeNull();
    const [note, message] = page.items;
    expect(note).toMatchObject({
      id: "pref-diet",
      kind: "note",
      about: ["topic:diet"],
      metadata: { source: "crm" },
      author: null,
      role: null,
      status: "stored",
    });
    expect(message!.author).toEqual({ id: "u_42", name: "Alice Chen", self: true });
  });

  it("item: the item, or null when memory holds none by that id", async () => {
    const found = await answering({ found: true, item: F.STORED }).item("msg-001");
    expect(found).toMatchObject({ id: "msg-001", session: "onboarding", status: "stored" });
    expect(found!.raw).toEqual(F.STORED);
    expect(await answering({ found: false }).item("nope")).toBeNull();
  });

  it("export: records as sent, and what was withheld", async () => {
    const page = await answering(F.EXPORT).export();
    expect([page.user, page.exportedAt, page.next, page.withheld]).toEqual([
      "user_42",
      "2026-11-03T10:00:00+00:00",
      null,
      ["version"],
    ]);
    expect(page.records).toEqual(F.EXPORT.records);
  });

  it("users: each app user's counts and last write", async () => {
    const page = await memory(() => ok(F.USERS)).client.users();
    expect(page.users.map((u) => [u.user, u.items, u.facts, u.lastWrite])).toEqual([
      ["user_42", 18, 41, "2026-10-01T09:14:02Z"],
      ["user_7", 3, 5, null],
    ]);
  });

  it("me: the key", async () => {
    const me = await memory(() => ok(F.ME)).client.me();
    expect(me).toEqual({
      kind: "key",
      org: "o7k2m9qx4ab",
      project: "production",
      keyId: "key_3f9a1c2b7d4e",
      writes: true,
      label: "backend",
      createdBy: "dev@acme.com",
      orgName: "Acme",
      projectName: "Production",
      space: "project",
      raw: F.ME,
    });
    const bare = await memory(() => ok({ kind: "key", writes: false })).client.me();
    expect([bare.label, bare.space, bare.writes]).toEqual([null, null, false]);
  });
});

describe("writes", () => {
  it("status: each item, and by id", async () => {
    const statuses = await answering(F.STATUSES).status(["msg-001", "nope-404"]);
    expect(statuses.byId).toEqual({ "msg-001": "processed", "nope-404": "unknown" });
    expect(statuses.items[1]!.reason).toBe("Memory holds nothing by this id.");
  });

  it("forget: what was erased", async () => {
    const forgotten = await answering(F.FORGOTTEN).forget({ items: ["msg-001"] });
    expect(forgotten.erased).toEqual(F.FORGOTTEN.erased);
    expect(forgotten.complete).toBe(true);
  });

  it("correct: what was retracted, and the replacement's id", async () => {
    const corrected = await answering(F.CORRECTION).correct(F.FACT.ref, "Porto");
    expect(corrected).toEqual({ ...F.CORRECTION, raw: F.CORRECTION });
  });

  it("versions: each version, and when it went", async () => {
    const versions = await answering(F.VERSIONS).versions("pref-diet");
    expect(versions.state).toBe("forgotten");
    expect(versions.history.map((h) => [h.event, h.version, h.why])).toEqual([
      ["version", 1, null],
      ["gone", null, "forgotten"],
    ]);
    expect(versions.history[0]!.item).toMatchObject({ text: "Alice is vegetarian." });
  });

  it("delete: the app user erased", async () => {
    const deleted = await answering(F.DELETED).delete();
    expect([deleted.user, deleted.deleted]).toEqual(["user_42", true]);
  });
});

describe("a field the API adds later", () => {
  it("is in raw, and a memory of a type this version does not know is skipped", async () => {
    const body = { ...F.SEARCH, memories: [...F.SEARCH.memories, { type: "hunch" }], extra: 1 };
    const found = await answering(body).search("q");
    expect(found.memories).toHaveLength(3);
    expect(found.raw.extra).toBe(1);
  });
});
