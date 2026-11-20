/**
 * What the routes about people and things answer: one subject whole, what a memory links to, how
 * the person works, and the lessons they taught assistants. Each keeps its JSON in `raw`.
 */

import { type Json, count, maybe, maybeStrings, object, objects, strings, text } from "./json.js";
import { type Fact, parseFact } from "./memories.js";
import type { Value } from "./reads.js";

/**
 * How one person or thing relates to another, in words (`link`): the day it was said, the ref of
 * the fact that says it, and the ref of the excerpt that fact was learned from (null when unknown,
 * and on `subject()` links).
 */
export interface Link {
  readonly link: string;
  readonly ref: string;
  readonly date: string | null;
  readonly source: string | null;
  readonly raw: Json;
}

const parseLink = (raw: Json): Link => ({
  link: text(raw.link),
  ref: text(raw.ref),
  date: maybe(raw.date),
  source: maybe(raw.source),
  raw,
});

/**
 * A line for a model, with the refs of the facts it rests on: a subject's `about`, and a
 * conversation about it (whose one ref is an excerpt of that conversation).
 */
export interface Line {
  readonly text: string;
  readonly refs: string[];
  readonly date: string | null;
  readonly raw: Json;
}

/**
 * One person or thing by name, whole: `about`, a few lines on how it went; `values`, each
 * property's newest value; `timeline`, its facts oldest first; `conversations` about it; `links`
 * to other people and things. `facts` is 0 when memory holds nothing by that name, and then
 * `suggestions` names the nearest it does.
 */
export interface Subject {
  readonly name: string;
  readonly facts: number;
  readonly about: Line[];
  readonly values: Value[];
  readonly timeline: Fact[];
  readonly conversations: Line[];
  readonly links: Link[];
  readonly suggestions: string[] | null;
  readonly raw: Json;
}

export function parseSubject(value: unknown): Subject {
  const raw = object(value);
  return {
    name: text(raw.name),
    facts: count(raw.facts),
    about: objects(raw.about).map((a) => ({
      text: text(a.text),
      refs: strings(a.refs),
      date: null,
      raw: a,
    })),
    values: objects(raw.values).map((v) => ({
      attribute: text(v.attribute),
      value: text(v.value),
      since: maybe(v.since),
      negated: v.negated === true,
      raw: v,
    })),
    timeline: objects(raw.timeline).map(parseFact),
    conversations: objects(raw.conversations).map((c) => ({
      text: text(c.text),
      refs: c.ref ? [text(c.ref)] : [],
      date: maybe(c.date),
      raw: c,
    })),
    links: objects(raw.links).map(parseLink),
    suggestions: maybeStrings(raw.suggestions),
    raw,
  };
}

/** What the people and things one memory names link to, newest said first. Iterable. */
export interface Related extends Iterable<Link> {
  readonly links: Link[];
  readonly raw: Json;
}

export function parseRelated(value: unknown): Related {
  const raw = object(value);
  const links = objects(raw.links).map(parseLink);
  return { links, raw, [Symbol.iterator]: () => links[Symbol.iterator]() };
}

/**
 * A plain line for a model, and the refs of the facts it cites. `kind` says what it is: `routine`
 * or `style` from `howTheyWork()` (`surface` names where a style is for), `lesson` from
 * `lessons()` (`from` says what it came from: `correction`, `feedback` or `said`), or `strategy`,
 * `failure` or `workflow` among a `Lessons`' `lessons`. The counts a card rests on are in `raw`.
 */
export interface Card {
  readonly kind: string;
  readonly text: string;
  readonly refs: string[];
  readonly surface: string | null;
  readonly from: string[];
  readonly raw: Json;
}

const parseCard = (raw: Json): Card => ({
  kind: text(raw.kind),
  text: text(raw.text),
  refs: strings(raw.refs),
  surface: maybe(raw.surface),
  from: strings(raw.from),
  raw,
});

/**
 * How someone works: `cards`, each a routine or a writing style; `procedures`, each routine's
 * counts written out for a model; `voice`, how they write, or null when memory has too few of
 * their messages to say.
 */
export interface Ways {
  readonly who: string;
  readonly cards: Card[];
  readonly procedures: string[];
  readonly voice: string | null;
  readonly raw: Json;
}

export function parseWays(value: unknown): Ways {
  const raw = object(value);
  return {
    who: text(raw.who),
    cards: objects(raw.cards).map(parseCard),
    procedures: strings(raw.procedures),
    voice: maybe(raw.voice),
    raw,
  };
}

/**
 * What an assistant should know before a task like `task`: `cards`, the lessons the person taught,
 * most like it first; `lessons`, what earlier attempts at similar tasks taught.
 */
export interface Lessons {
  readonly task: string;
  readonly cards: Card[];
  readonly lessons: Card[];
  readonly raw: Json;
}

export function parseLessons(value: unknown): Lessons {
  const raw = object(value);
  return {
    task: text(raw.task),
    cards: objects(raw.cards).map(parseCard),
    lessons: objects(raw.lessons).map(parseCard),
    raw,
  };
}
