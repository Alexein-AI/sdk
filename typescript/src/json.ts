/**
 * Reading the API's JSON without trusting its shape: each reader answers a value of the type asked
 * for, or the absent value, so a field the API leaves out or changes never throws while parsing.
 */

/** A JSON object, as the API sends it. */
export type Json = Record<string, unknown>;

export const object = (value: unknown): Json =>
  typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Json) : {};

export const list = <T = unknown>(value: unknown): T[] =>
  Array.isArray(value) ? (value as T[]) : [];

export const objects = (value: unknown): Json[] => list(value).map(object);

/** A string, or "" when there is none. */
export const text = (value: unknown): string =>
  typeof value === "string" ? value : value === undefined || value === null ? "" : String(value);

/** A string, or null when there is none. */
export const maybe = (value: unknown): string | null =>
  typeof value === "string" ? value : value === undefined || value === null ? null : String(value);

export const strings = (value: unknown): string[] => list(value).map(text);

/** A list of strings, or null when the field is absent. */
export const maybeStrings = (value: unknown): string[] | null =>
  Array.isArray(value) ? strings(value) : null;

/** A number, or 0 when there is none. */
export const count = (value: unknown): number =>
  typeof value === "number" ? value : Number(value) || 0;

/** A number, or null when there is none. */
export const maybeCount = (value: unknown): number | null =>
  value === undefined || value === null ? null : count(value);

export const bool = (value: unknown): boolean => value === true;

/** `body` without the fields left unset: the API's defaults apply to those. */
export function compact(body: Json): Json {
  return Object.fromEntries(
    Object.entries(body).filter(([, value]) => value !== undefined && value !== null),
  );
}
