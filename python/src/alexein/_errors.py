"""What can go wrong, one class per thing a caller would handle differently."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from alexein._types import listed


@dataclass(frozen=True)
class FieldError:
    """One field a request got wrong, as a 422 names it: `items[0].text`, and what it takes."""

    field: str
    message: str


class AlexeinError(Exception):
    """Every error this package raises.

    `status` is the HTTP status (None when no response came), `detail` the API's own sentence,
    `errors` each field a 422 names, and `request_id` the response's `X-Request-Id`, to quote
    when you ask for help. `outage` says whether memory is unavailable - unreachable, too slow,
    busy or failing - rather than the request or the key being wrong."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        detail: str | None = None,
        errors: list[FieldError] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail
        self.errors: list[FieldError] = errors or []
        self.request_id = request_id

    @property
    def outage(self) -> bool:
        return self.status is not None and (self.status == 429 or self.status >= 500)


class AuthenticationError(AlexeinError):
    """401: no key, or one the service did not issue."""


class PermissionDeniedError(AlexeinError):
    """403: the key reads, and the call writes."""


class NotFoundError(AlexeinError):
    """404: nothing was added for this app user yet, or a ref this memory did not give."""


class InvalidRequestError(AlexeinError):
    """400, 413, 422 or another 4xx: the request itself is wrong - an app user id the API
    refuses, a body too large, a field out of bounds. Retrying will not help."""


class RateLimitError(AlexeinError):
    """429, after retries: too many requests in flight, or reads too fast."""


class ServiceUnavailableError(AlexeinError):
    """5xx, after retries: the service is busy, briefly unavailable or failing."""


class APIConnectionError(AlexeinError):
    """The service could not be reached, after retries."""

    @property
    def outage(self) -> bool:
        return True


class APITimeoutError(APIConnectionError):
    """The service did not answer in time, after retries."""


_BY_STATUS: dict[int, type[AlexeinError]] = {
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    429: RateLimitError,
}


def for_status(status: int, body: object, request_id: str | None) -> AlexeinError:
    """The error a response with this status and JSON body (or None) is."""
    fields = cast("dict[str, Any]", body) if isinstance(body, dict) else {}
    detail = fields.get("detail")
    said = detail if isinstance(detail, str) else None
    errors = _errors(fields.get("errors"))
    if said is None and isinstance(detail, list):
        # A validation error in FastAPI's own shape, from a proxy or an older service.
        errors = errors or _errors(cast(object, detail))
        said = "; ".join(f"{e.field}: {e.message}" for e in errors) or None
    kind = _BY_STATUS.get(status)
    if kind is None:
        kind = ServiceUnavailableError if status >= 500 else InvalidRequestError
    message = f"{status}: {said}" if said else f"{status}"
    return kind(message, status=status, detail=said, errors=errors, request_id=request_id)


def _errors(given: object) -> list[FieldError]:
    if not isinstance(given, list):
        return []
    out: list[FieldError] = []
    for each in cast("list[object]", given):
        if not isinstance(each, dict):
            continue
        error = cast("dict[str, Any]", each)
        if "field" in error or "message" in error:
            out.append(FieldError(str(error.get("field", "")), str(error.get("message", ""))))
        else:
            loc = [str(p) for p in listed(error, "loc") if p != "body"]
            out.append(FieldError(".".join(loc), str(error.get("msg", ""))))
    return out
