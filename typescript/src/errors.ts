/**
 * What can go wrong, one class per thing a caller would handle differently: the same classes as
 * the Python client's, so what is true of an error there is true here.
 */

import { type Json, list, maybe, maybeCount, object, text } from "./json.js";

/** One field a 422 named, and what it takes. */
export interface FieldError {
  /** Where in the body: `query`, `items[0].text`; empty for the body itself. */
  field: string;
  message: string;
}

export interface ErrorFields {
  status?: number | null;
  detail?: string;
  errors?: FieldError[];
  requestId?: string | null;
  cause?: unknown;
}

/** Every error this client throws. */
export class AlexeinError extends Error {
  /** The HTTP status, or null when no response came back. */
  readonly status: number | null;
  /** The API's own explanation; for a transport failure, what went wrong. */
  readonly detail: string;
  /** On a 422: each field the body got wrong. Empty otherwise. */
  readonly errors: FieldError[];
  /**
   * The request's id: the `X-Request-Id` this client sent, which the API logs and answers with.
   * Quote it when you ask for help, or find the request in the console's request logs.
   */
  readonly requestId: string | null;

  constructor(message: string, fields: ErrorFields = {}) {
    super(message, fields.cause === undefined ? undefined : { cause: fields.cause });
    this.name = new.target.name;
    this.status = fields.status ?? null;
    this.detail = fields.detail ?? message;
    this.errors = fields.errors ?? [];
    this.requestId = fields.requestId ?? null;
  }

  /**
   * Whether this means memory is unavailable - unreachable, too slow, too busy or failing - rather
   * than that the request or the key is wrong. A `failOpen` client rides out an outage; a mistake
   * still throws.
   */
  get outage(): boolean {
    return this.status !== null && (this.status === 429 || this.status >= 500);
  }
}

/** 401: no key, or one the service did not issue. */
export class AuthenticationError extends AlexeinError {}

/** 403: the key reads, and the call writes; or the key's organisation is closed. */
export class PermissionDeniedError extends AlexeinError {}

/**
 * 404: nothing was ever added for this app user, or memory holds nothing by the ref or id given.
 * Search answers an empty result instead.
 */
export class NotFoundError extends AlexeinError {}

/** 400, 413, 422 and any other 4xx: the request itself is wrong. Retrying will not help. */
export class InvalidRequestError extends AlexeinError {}

/**
 * 402: the organisation has used this month's events or retrievals. Never retried, and not an
 * outage, so a `failOpen` client throws it too: it lasts until `resetsAt`, the 1st of next month,
 * or until the plan is upgraded. `limit` is which one ("events" or "retrievals"), `used` and
 * `included` its figures, `upgrade` where to raise it.
 */
export class QuotaExceededError extends AlexeinError {
  readonly limit: string | null;
  readonly used: number | null;
  readonly included: number | null;
  readonly resetsAt: string | null;
  readonly upgrade: string | null;

  constructor(message: string, fields: ErrorFields = {}, body: Json = {}) {
    super(message, fields);
    this.limit = maybe(body.limit);
    this.used = maybeCount(body.used);
    this.included = maybeCount(body.included);
    this.resetsAt = maybe(body.resets_at);
    this.upgrade = maybe(body.upgrade);
  }
}

/**
 * 429, after retries: too many requests in flight, or reads too fast. Retried for you, after
 * `Retry-After` seconds (when at most 60) or with backoff.
 */
export class RateLimitError extends AlexeinError {}

/** 5xx, after retries (503 is retried; the rest are not): the service is busy or failing. */
export class ServiceUnavailableError extends AlexeinError {}

/** The service could not be reached, after retries. */
export class APIConnectionError extends AlexeinError {
  override get outage(): boolean {
    return true;
  }
}

/** The service did not answer in time, after retries. */
export class APITimeoutError extends APIConnectionError {}

function kindOf(
  status: number,
): new (message: string, fields: ErrorFields, body: Json) => AlexeinError {
  if (status === 401) return AuthenticationError;
  if (status === 402) return QuotaExceededError;
  if (status === 403) return PermissionDeniedError;
  if (status === 404) return NotFoundError;
  if (status === 429) return RateLimitError;
  if (status >= 500) return ServiceUnavailableError;
  if (status >= 400) return InvalidRequestError;
  return AlexeinError;
}

/** `[{field, message}]` from a 422's `errors`, or from a validator's `[{loc, msg}]`. */
function fieldErrors(value: unknown): FieldError[] {
  return list(value).map((entry) => {
    const error = object(entry);
    if (Array.isArray(error.loc)) {
      const at = error.loc[0] === "body" ? error.loc.slice(1) : error.loc;
      return { field: at.map(String).join("."), message: text(error.msg) };
    }
    return { field: text(error.field), message: text(error.message) };
  });
}

/** The error an answer with this status and body is. */
export function errorFor(status: number, body: Json, requestId: string | null): AlexeinError {
  const errors = fieldErrors(body.errors ?? (Array.isArray(body.detail) ? body.detail : []));
  const detail =
    typeof body.detail === "string"
      ? body.detail
      : errors.map((e) => (e.field ? `${e.field}: ${e.message}` : e.message)).join("; ");
  const Kind = kindOf(status);
  return new Kind(
    detail ? `${status}: ${detail}` : String(status),
    { status, detail, errors, requestId },
    body,
  );
}

/** What a request that got no answer became: a timeout, or a connection that failed. */
export function unreached(error: unknown, requestId: string | null = null): AlexeinError {
  const name = error instanceof Error ? error.name : "";
  const said = error instanceof Error ? error.message : String(error);
  if (name === "TimeoutError" || name === "AbortError") {
    return new APITimeoutError(`Alexein did not answer in time: ${said}`, {
      cause: error,
      requestId,
    });
  }
  return new APIConnectionError(`Alexein could not be reached: ${said}`, {
    cause: error,
    requestId,
  });
}
