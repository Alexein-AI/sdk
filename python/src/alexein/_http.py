"""How a call is sent: the settings, the headers, the retries, and the error a failed response
becomes. One `Transport` for each client kind, both over httpx."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
import uuid
from typing import Any, TypeVar, cast

import httpx

from alexein._calls import Call
from alexein._errors import AlexeinError, APIConnectionError, APITimeoutError, for_status
from alexein._version import __version__

T = TypeVar("T")

DEFAULT_BASE_URL = "https://api.alexein.ai"
# Long enough for the slowest search and for an add that waits for its items to be stored; a
# person-facing caller that cannot wait sets its own.
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 2
# What the API asks to be retried: too many requests in flight, or the service busy.
_RETRIED = {429, 503}
# A Retry-After past this is not waited out; the error is raised instead.
_LONGEST_WAIT = 60.0
# What `integration=` may add to the User-Agent: one short token, so the request log can count
# requests by where they came from (`alexein-python/0.3.0 langgraph`).
_INTEGRATION = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")
KEYS_PAGE = "https://app.alexein.ai/console/keys"

log = logging.getLogger("alexein")


def base_url(given: str | None) -> str:
    """The host, as given or from ALEXEIN_API_URL: a trailing `/` or `/v2` names the same one."""
    url = (given or os.environ.get("ALEXEIN_API_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    return url.removesuffix("/v2").rstrip("/")


def headers(api_key: str | None, integration: str | None) -> dict[str, str]:
    key = api_key if api_key is not None else os.environ.get("ALEXEIN_API_KEY", "")
    if not key:
        raise AlexeinError(
            "no API key: pass api_key=..., or set ALEXEIN_API_KEY. Make one in the console, "
            f"under API keys: {KEYS_PAGE}"
        )
    agent = f"alexein-python/{__version__}"
    if integration is not None:
        if not _INTEGRATION.fullmatch(integration):
            raise ValueError(f"integration must be one short lowercase word: {integration!r}")
        agent += f" {integration}"
    return {"Authorization": f"Bearer {key}", "User-Agent": agent}


def request_id() -> str:
    """An id for one call, sent as `X-Request-Id` on each attempt of it. The API logs it and
    answers with it, so an error can always be quoted and found in the console's request logs -
    even one a proxy answered, which carries no id of the service's own."""
    return f"req_{uuid.uuid4().hex}"


def _request(
    http: httpx.Client | httpx.AsyncClient,
    base: str,
    call: Call[Any],
    user: str | None,
    rid: str,
) -> httpx.Request:
    sent = dict(call.headers) | {"X-Request-Id": rid}
    if user is not None:
        sent["X-Alexein-User"] = user
    if call.body is None:
        return http.build_request(call.method, base + call.path, headers=sent)
    return http.build_request(call.method, base + call.path, json=call.body, headers=sent)


def _answer(response: httpx.Response, call: Call[T], rid: str) -> T:
    """The parsed answer, or the error the response is."""
    if response.is_success:
        return call.parse(response.json())
    try:
        body: object = response.json()
    except ValueError:
        body = {"detail": response.text.strip() or None}
    raise for_status(response.status_code, body, response.headers.get("X-Request-Id") or rid)


def _pause(attempt: int, response: httpx.Response | None) -> float | None:
    """Seconds to wait before trying again, or None if this should not be retried."""
    if response is not None:
        if response.status_code not in _RETRIED:
            return None
        after = response.headers.get("Retry-After", "").strip()
        try:
            wait = float(after)
        except ValueError:
            wait = None
        if wait is not None and wait >= 0:
            return wait if wait <= _LONGEST_WAIT else None
    # 0.5 s, then 1 s, each with up to a quarter either way, so clients that failed together
    # do not come back together.
    return 0.5 * 2**attempt * random.uniform(0.75, 1.25)


def _unreached(error: httpx.TransportError, rid: str) -> APIConnectionError:
    if isinstance(error, httpx.TimeoutException):
        return APITimeoutError(f"the service did not answer in time: {error}", request_id=rid)
    return APIConnectionError(f"the service could not be reached: {error}", request_id=rid)


class Transport:
    """Sends calls over an `httpx.Client`, retrying what the API asks to be retried."""

    def __init__(self, http: httpx.Client, base: str, sent: dict[str, str], retries: int) -> None:
        self.http, self.base, self.retries = http, base, retries
        http.headers.update(sent)

    def send(self, call: Call[T], user: str | None = None) -> T:
        attempt, rid = 0, request_id()
        while True:
            response, failure = None, None
            try:
                response = self.http.send(_request(self.http, self.base, call, user, rid))
            except httpx.TransportError as error:
                failure = _unreached(error, rid)
            pause = _pause(attempt, response) if attempt < self.retries else None
            if pause is None:
                if failure:
                    raise failure
                return _answer(cast("httpx.Response", response), call, rid)
            time.sleep(pause)
            attempt += 1


class AsyncTransport:
    """`Transport`, over an `httpx.AsyncClient`."""

    def __init__(
        self, http: httpx.AsyncClient, base: str, sent: dict[str, str], retries: int
    ) -> None:
        self.http, self.base, self.retries = http, base, retries
        http.headers.update(sent)

    async def send(self, call: Call[T], user: str | None = None) -> T:
        attempt, rid = 0, request_id()
        while True:
            response, failure = None, None
            try:
                response = await self.http.send(_request(self.http, self.base, call, user, rid))
            except httpx.TransportError as error:
                failure = _unreached(error, rid)
            pause = _pause(attempt, response) if attempt < self.retries else None
            if pause is None:
                if failure:
                    raise failure
                return _answer(cast("httpx.Response", response), call, rid)
            await asyncio.sleep(pause)
            attempt += 1


def ride_out(error: AlexeinError, fail_open: bool, what: str, user: str) -> None:
    """Raise `error` unless the client fails open and it is an outage; then log it once, and
    the caller answers empty. Memory being down costs a reply its memory, not the reply."""
    if not (fail_open and error.outage):
        raise error
    log.warning("Alexein unavailable, %s for %s skipped: %s", what, user, error)
