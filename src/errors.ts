/**
 * What can go wrong, one class per thing a caller would handle differently.
 *
 * The same classes as the Python client's, so what is true of an error there is true here.
 */

export class TwinMemoryError extends Error {
  /** The HTTP status, when there was a response. */
  readonly status: number | undefined;
  /** The API's own explanation. */
  readonly detail: unknown;
  /** Finds the request in the service's log. */
  readonly requestId: string | undefined;

  constructor(
    message: string,
    options: { status?: number; detail?: unknown; requestId?: string; cause?: unknown } = {},
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = new.target.name;
    this.status = options.status;
    this.detail = options.detail;
    this.requestId = options.requestId;
  }

  /**
   * Whether this means memory is unavailable - unreachable, too slow, busy or failing - rather
   * than that the request or the key is wrong. A `failOpen` client rides out an outage; a
   * mistake still throws.
   */
  get outage(): boolean {
    return this.status !== undefined && (this.status === 429 || this.status >= 500);
  }
}

/** 401: no key, or one the service did not issue. */
export class AuthenticationError extends TwinMemoryError {}

/** 403: the key reads, and the call writes. */
export class PermissionDeniedError extends TwinMemoryError {}

/** 404: nothing was ever written for this end user, or no such record. */
export class NotFoundError extends TwinMemoryError {}

/**
 * 400, 413 or 422: the request itself is wrong - a bad end user id, a body too large, or a field
 * out of bounds. Retrying will not help.
 */
export class InvalidRequestError extends TwinMemoryError {}

/** 429: too many requests in hand for this end user or organisation. Retried for you. */
export class RateLimitError extends TwinMemoryError {}

/** 503: the end user's memory is being rebuilt, or the service is at capacity. Retried for you. */
export class ServiceUnavailableError extends TwinMemoryError {}

/** The service could not be reached. Retried for you. */
export class APIConnectionError extends TwinMemoryError {
  override get outage(): boolean {
    return true;
  }
}

/** The service did not answer in time. Retried for you. */
export class APITimeoutError extends APIConnectionError {}

const BY_STATUS: Record<number, typeof TwinMemoryError> = {
  400: InvalidRequestError,
  401: AuthenticationError,
  403: PermissionDeniedError,
  404: NotFoundError,
  413: InvalidRequestError,
  422: InvalidRequestError,
  429: RateLimitError,
  503: ServiceUnavailableError,
};

/** The error a response with this status and body is. */
export function forStatus(
  status: number,
  detail: unknown,
  requestId: string | undefined,
): TwinMemoryError {
  const said = describe(detail);
  const Kind = BY_STATUS[status] ?? TwinMemoryError;
  return new Kind(said ? `${status}: ${said}` : String(status), { status, detail, requestId });
}

function describe(detail: unknown): string {
  if (!Array.isArray(detail)) {
    return detail === undefined || detail === null ? "" : String(detail);
  }
  // FastAPI's validation errors: one line per field, as `body.query: Field required`.
  return detail
    .filter((error): error is Record<string, unknown> => typeof error === "object" && !!error)
    .map((error) => {
      const where = Array.isArray(error.loc) ? error.loc.map(String).join(".") : "";
      return `${where}: ${String(error.msg ?? "")}`;
    })
    .join("; ");
}
