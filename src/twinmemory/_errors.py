"""What can go wrong, one class per thing a caller would handle differently."""

from __future__ import annotations

from typing import cast


class TwinMemoryError(Exception):
    """Every error this package raises. `status` is the HTTP status, when there was a response;
    `detail` is the API's own explanation; `request_id` is the response's `X-Request-Id`, to
    quote when you ask for help."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        detail: object = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail
        self.request_id = request_id

    @property
    def outage(self) -> bool:
        """Whether this means memory is unavailable - unreachable, too slow, busy or failing -
        rather than that the request or the key is wrong. A `fail_open` client rides out an
        outage; a mistake still raises."""
        return self.status is not None and (self.status in (429, 503) or self.status >= 500)


class AuthenticationError(TwinMemoryError):
    """401: no key, or one the service did not issue."""


class PermissionDeniedError(TwinMemoryError):
    """403: the key reads, and the call writes."""


class NotFoundError(TwinMemoryError):
    """404: nothing was ever written for this end user, or `correct` named a fact this end user
    does not hold: not yet `read`, already retracted, or mistyped."""


class InvalidRequestError(TwinMemoryError):
    """400, 413 or 422: the request itself is wrong - a bad end user id, a body too large, or a
    field out of bounds. Retrying will not help."""


class RateLimitError(TwinMemoryError):
    """429: too many requests in flight, or reads too fast. Retried for you: after `Retry-After`
    seconds, or with backoff when there is none. A `Retry-After` over 60 seconds is not waited
    out; this error is raised instead."""


class ServiceUnavailableError(TwinMemoryError):
    """503: the service is busy or briefly unavailable. Retried for you: after `Retry-After`
    seconds, or with backoff when there is none. A `Retry-After` over 60 seconds is not waited
    out; this error is raised instead."""


class APIConnectionError(TwinMemoryError):
    """The service could not be reached. Retried for you."""

    @property
    def outage(self) -> bool:
        return True


class APITimeoutError(APIConnectionError):
    """The service did not answer in time. Retried for you."""


_BY_STATUS: dict[int, type[TwinMemoryError]] = {
    400: InvalidRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    413: InvalidRequestError,
    422: InvalidRequestError,
    429: RateLimitError,
    503: ServiceUnavailableError,
}


def for_status(status: int, detail: object, request_id: str | None) -> TwinMemoryError:
    """The error a response with this status and body is."""
    said = _said(detail)
    kind = _BY_STATUS.get(status, TwinMemoryError)
    return kind(
        f"{status}: {said}" if said else str(status),
        status=status,
        detail=detail,
        request_id=request_id,
    )


def _said(detail: object) -> str:
    if not isinstance(detail, list):
        return "" if detail is None else str(detail)
    # The API's validation errors (422): one line per field, as
    # `body.query: String should have at least 1 character`.
    lines: list[str] = []
    for error in cast("list[object]", detail):
        if isinstance(error, dict):
            fields = cast("dict[str, object]", error)
            where = ".".join(str(p) for p in cast("list[object]", fields.get("loc") or []))
            lines.append(f"{where}: {fields.get('msg', '')}")
    return "; ".join(lines)
