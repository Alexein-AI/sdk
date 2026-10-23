"""The two clients, `Memory` and `AsyncMemory`, and the end user views they hand out.

A client holds a key and a connection pool; `client.user("dana")` is a view that sends
`X-Twin-Account: dana` on every call. What each call sends is in `_calls.py`, once; here is only
how it is sent: the key, the retries, and the error a failed response becomes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from collections.abc import Awaitable, Sequence
from types import TracebackType
from typing import Protocol, TypeVar, cast

import httpx

from twinmemory import _calls
from twinmemory._errors import (
    APIConnectionError,
    APITimeoutError,
    TwinMemoryError,
    for_status,
)
from twinmemory._types import (
    AddResult,
    Author,
    Correction,
    File,
    GrepResult,
    History,
    Item,
    Json,
    Lineage,
    Listing,
    Me,
    Overview,
    Passages,
    Receipt,
    SearchResult,
    Versions,
)
from twinmemory._version import __version__

T = TypeVar("T")

DEFAULT_BASE_URL = "https://api.twinmemory.dev"
# Long enough for a search that waits on the model filter at its slowest and an add that waits
# for its items to land; a person-facing caller that cannot wait sets its own.
DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 2
# What the API asks to be retried: too many requests in hand, or memory being rebuilt.
_RETRIED = {429, 503}
# A Retry-After past this is not waited out; the error is raised instead.
_LONGEST_WAIT = 60.0
# What `integration=` may add to the User-Agent: one short token, so the request log can count
# requests by where they came from (`twinmemory-python/0.2.0 langgraph`).
_INTEGRATION = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")

log = logging.getLogger("twinmemory")


class _Sends(Protocol):
    def __call__(self, call: _calls.Call[T], user: str | None) -> T: ...


class _AsyncSends(Protocol):
    def __call__(self, call: _calls.Call[T], user: str | None) -> Awaitable[T]: ...


def _ride_out(error: TwinMemoryError, fail_open: bool, what: str, user: str) -> None:
    """Raise `error` unless the client fails open and it is an outage; then log it, and the
    caller answers empty. Memory being down costs a reply its memory, not the reply."""
    if not (fail_open and error.outage):
        raise error
    log.warning("twin memory unavailable, %s for %s skipped: %s", what, user, error)


def _settings(
    api_key: str | None, base_url: str | None, integration: str | None
) -> tuple[str, dict[str, str]]:
    key = api_key if api_key is not None else os.environ.get("TWIN_MEMORY_API_KEY", "")
    if not key:
        raise TwinMemoryError(
            "no API key: pass api_key=..., or set TWIN_MEMORY_API_KEY. Keys are made in the "
            "console, under API keys."
        )
    url = base_url or os.environ.get("TWIN_MEMORY_BASE_URL") or DEFAULT_BASE_URL
    agent = f"twinmemory-python/{__version__}"
    if integration is not None:
        if not _INTEGRATION.fullmatch(integration):
            raise ValueError(f"integration must be one short lowercase word: {integration!r}")
        agent += f" {integration}"
    headers = {"Authorization": f"Bearer {key}", "User-Agent": agent}
    return url.rstrip("/"), headers


def _request(
    http: httpx.Client | httpx.AsyncClient, call: _calls.Call[T], user: str | None
) -> httpx.Request:
    headers = dict(call.headers)
    if user is not None:
        headers["X-Twin-Account"] = user
    return http.build_request(call.method, call.path, json=call.body, headers=headers)


def _answer(response: httpx.Response, call: _calls.Call[T]) -> T:
    """The parsed answer, or the error the response is."""
    if response.is_success:
        return call.parse(response.json())
    try:
        body: object = response.json()
    except ValueError:
        body = {"detail": response.text or None}
    detail = cast("dict[str, object]", body).get("detail") if isinstance(body, dict) else body
    raise for_status(response.status_code, detail, response.headers.get("X-Request-Id"))


def _pause(attempt: int, response: httpx.Response | None) -> float | None:
    """Seconds to wait before trying again, or None if this should not be retried."""
    if response is not None:
        if response.status_code not in _RETRIED:
            return None
        after = response.headers.get("Retry-After", "")
        if after.replace(".", "", 1).isdigit():
            return float(after) if float(after) <= _LONGEST_WAIT else None
    # 0.5 s, then 1 s, each with up to a quarter either way, so clients that failed together
    # do not come back together.
    return 0.5 * 2**attempt * random.uniform(0.75, 1.25)


def _unreached(error: httpx.TransportError) -> APIConnectionError:
    if isinstance(error, httpx.TimeoutException):
        return APITimeoutError(f"the service did not answer in time: {error}")
    return APIConnectionError(f"the service could not be reached: {error}")


class Memory:
    """A twin memory client.

    ```python
    memory = Memory()                # TWIN_MEMORY_API_KEY from the environment
    dana = memory.user("dana")       # your own id for one of your end users
    dana.add("I moved to Lisbon for the job at Acme.")
    print(dana.search("Where does Dana live?").context())
    ```
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
        fail_open: bool = False,
        integration: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        url, headers = _settings(api_key, base_url, integration)
        self.base_url = url
        self.max_retries = max_retries
        self.fail_open = fail_open
        self._http = http_client or httpx.Client(timeout=timeout)
        self._http.base_url = url
        self._http.headers.update(headers)

    def me(self) -> Me:
        """What this key is: its organisation, project, and whether it writes."""
        return self._send(_calls.me(), None)

    def user(self, user_id: str) -> User:
        """The memory of one of your end users, by your own id for them."""
        return User(self._send, _calls.checked_user(user_id), fail_open=self.fail_open)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Memory:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()

    def _send(self, call: _calls.Call[T], user: str | None) -> T:
        attempt = 0
        while True:
            response, failure = None, None
            try:
                response = self._http.send(_request(self._http, call, user))
            except httpx.TransportError as error:
                failure = _unreached(error)
            pause = _pause(attempt, response) if attempt < self.max_retries else None
            if pause is None:
                if failure:
                    raise failure
                assert response is not None
                return _answer(response, call)
            time.sleep(pause)
            attempt += 1


class AsyncMemory:
    """`Memory`, for asyncio: the same methods, awaited."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
        fail_open: bool = False,
        integration: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        url, headers = _settings(api_key, base_url, integration)
        self.base_url = url
        self.max_retries = max_retries
        self.fail_open = fail_open
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._http.base_url = url
        self._http.headers.update(headers)

    async def me(self) -> Me:
        """What this key is: its organisation, project, and whether it writes."""
        return await self._send(_calls.me(), None)

    def user(self, user_id: str) -> AsyncUser:
        """The memory of one of your end users, by your own id for them."""
        return AsyncUser(self._send, _calls.checked_user(user_id), fail_open=self.fail_open)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncMemory:
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await self.close()

    async def _send(self, call: _calls.Call[T], user: str | None) -> T:
        attempt = 0
        while True:
            response, failure = None, None
            try:
                response = await self._http.send(_request(self._http, call, user))
            except httpx.TransportError as error:
                failure = _unreached(error)
            pause = _pause(attempt, response) if attempt < self.max_retries else None
            if pause is None:
                if failure:
                    raise failure
                assert response is not None
                return _answer(response, call)
            await asyncio.sleep(pause)
            attempt += 1


class User:
    """One end user's memory. Every call sends their id as `X-Twin-Account`."""

    def __init__(self, send: _Sends, user_id: str, *, fail_open: bool = False) -> None:
        self._send = send
        self.id = user_id
        self._fail_open = fail_open

    def __repr__(self) -> str:
        return f"User({self.id!r})"

    def add(
        self,
        items: str | Item | Sequence[str | Item],
        *,
        wait: bool = False,
        kind: str | None = None,
        session: str | None = None,
        role: str | None = None,
        author: str | Author | None = None,
        title: str | None = None,
        about: list[str] | None = None,
        expires: str | None = None,
        at: str | None = None,
        metadata: Json | None = None,
    ) -> AddResult:
        """Remember text: a string, an item dict, or a list of either. The keyword fields apply
        to every item that does not set its own. With `wait`, returns once they are searchable."""
        defaults: Json = {
            "kind": kind, "session": session, "role": role, "author": author, "title": title,
            "about": about, "expires": expires, "at": at, "metadata": metadata,
        }  # fmt: skip
        calls = _calls.add(items, wait=wait, defaults=defaults)
        try:
            return _calls.merged([self._send(c, self.id) for c in calls])
        except TwinMemoryError as error:
            _ride_out(error, self._fail_open, "add", self.id)
            return AddResult([], 0, 0, failed=True)

    def search(
        self,
        query: str,
        *,
        before: str | None = None,
        after: str | None = None,
        scope: str | None = None,
        fast: bool = False,
    ) -> SearchResult:
        """What memory holds for a question. `fast` skips the model filter: free and quicker,
        less precise. `before` and `after` are ISO dates."""
        call = _calls.search(query, before=before, after=after, scope=scope, fast=fast)
        try:
            return self._send(call, self.id)
        except TwinMemoryError as error:
            _ride_out(error, self._fail_open, "search", self.id)
            return SearchResult.unavailable(query)

    def grep(self, pattern: str, *, scope: str | None = None, limit: int = 50) -> GrepResult:
        """Every passage holding an exact phrase, ignoring case."""
        return self._send(_calls.grep(pattern, scope=scope, limit=limit), self.id)

    def read(self, path: str) -> File:
        """One file whole, by a path a result gave you."""
        return self._send(_calls.read(path), self.id)

    def ls(self, path: str = "") -> Listing:
        """A directory's entries."""
        return self._send(_calls.ls(path), self.id)

    def around(self, passage_id: str, *, width: int = 2) -> Passages:
        """The passages either side of one you hold, in the same thread."""
        return self._send(_calls.around(passage_id, width=width), self.id)

    def history(self, subject: str, *, attribute: str | None = None) -> History:
        """Every dated value recorded for one subject."""
        return self._send(_calls.history(subject, attribute=attribute), self.id)

    def latest(
        self, *, k: int = 10, place: str = "", after: str | None = None, before: str | None = None
    ) -> Passages:
        """The most recent passages, newest first; with `after` and `before`, all between."""
        call = _calls.latest(k=k, place=place, after=after, before=before)
        return self._send(call, self.id)

    def overview(self) -> Overview:
        """The shape of this memory: directories, counts and its written index."""
        return self._send(_calls.overview(), self.id)

    def forget(
        self,
        *,
        items: Sequence[str] = (),
        sessions: Sequence[str] = (),
        threads: Sequence[str] = (),
        events: Sequence[str] = (),
    ) -> Receipt:
        """Erase every copy of what is named, for good. Needs a key that writes."""
        call = _calls.forget(items=items, sessions=sessions, threads=threads, events=events)
        return self._send(call, self.id)

    def correct(self, record_id: str, replacement: str | None = None) -> Correction:
        """Retract one fact by the id search gave it, and optionally say what is true instead."""
        return self._send(_calls.correct(record_id, replacement), self.id)

    def versions(self, item_id: str) -> Versions:
        """An added item's versions, as they were sent."""
        return self._send(_calls.versions(item_id), self.id)

    def status(self, ids: Sequence[str]) -> dict[str, str]:
        """How far each item has got: accepted, landed, read, folded, or unknown."""
        return self._send(_calls.status(ids), self.id)

    def lineage(self, ident: str) -> Lineage:
        """What an item or event became, or what a fact was read from."""
        return self._send(_calls.lineage(ident), self.id)


class AsyncUser:
    """`User`, for asyncio: the same methods, awaited."""

    def __init__(self, send: _AsyncSends, user_id: str, *, fail_open: bool = False) -> None:
        self._send = send
        self.id = user_id
        self._fail_open = fail_open

    def __repr__(self) -> str:
        return f"AsyncUser({self.id!r})"

    async def add(
        self,
        items: str | Item | Sequence[str | Item],
        *,
        wait: bool = False,
        kind: str | None = None,
        session: str | None = None,
        role: str | None = None,
        author: str | Author | None = None,
        title: str | None = None,
        about: list[str] | None = None,
        expires: str | None = None,
        at: str | None = None,
        metadata: Json | None = None,
    ) -> AddResult:
        """Remember text: a string, an item dict, or a list of either. The keyword fields apply
        to every item that does not set its own. With `wait`, returns once they are searchable."""
        defaults: Json = {
            "kind": kind, "session": session, "role": role, "author": author, "title": title,
            "about": about, "expires": expires, "at": at, "metadata": metadata,
        }  # fmt: skip
        calls = _calls.add(items, wait=wait, defaults=defaults)
        try:
            return _calls.merged([await self._send(c, self.id) for c in calls])
        except TwinMemoryError as error:
            _ride_out(error, self._fail_open, "add", self.id)
            return AddResult([], 0, 0, failed=True)

    async def search(
        self,
        query: str,
        *,
        before: str | None = None,
        after: str | None = None,
        scope: str | None = None,
        fast: bool = False,
    ) -> SearchResult:
        """What memory holds for a question. `fast` skips the model filter: free and quicker,
        less precise. `before` and `after` are ISO dates."""
        call = _calls.search(query, before=before, after=after, scope=scope, fast=fast)
        try:
            return await self._send(call, self.id)
        except TwinMemoryError as error:
            _ride_out(error, self._fail_open, "search", self.id)
            return SearchResult.unavailable(query)

    async def grep(self, pattern: str, *, scope: str | None = None, limit: int = 50) -> GrepResult:
        """Every passage holding an exact phrase, ignoring case."""
        return await self._send(_calls.grep(pattern, scope=scope, limit=limit), self.id)

    async def read(self, path: str) -> File:
        """One file whole, by a path a result gave you."""
        return await self._send(_calls.read(path), self.id)

    async def ls(self, path: str = "") -> Listing:
        """A directory's entries."""
        return await self._send(_calls.ls(path), self.id)

    async def around(self, passage_id: str, *, width: int = 2) -> Passages:
        """The passages either side of one you hold, in the same thread."""
        return await self._send(_calls.around(passage_id, width=width), self.id)

    async def history(self, subject: str, *, attribute: str | None = None) -> History:
        """Every dated value recorded for one subject."""
        return await self._send(_calls.history(subject, attribute=attribute), self.id)

    async def latest(
        self, *, k: int = 10, place: str = "", after: str | None = None, before: str | None = None
    ) -> Passages:
        """The most recent passages, newest first; with `after` and `before`, all between."""
        call = _calls.latest(k=k, place=place, after=after, before=before)
        return await self._send(call, self.id)

    async def overview(self) -> Overview:
        """The shape of this memory: directories, counts and its written index."""
        return await self._send(_calls.overview(), self.id)

    async def forget(
        self,
        *,
        items: Sequence[str] = (),
        sessions: Sequence[str] = (),
        threads: Sequence[str] = (),
        events: Sequence[str] = (),
    ) -> Receipt:
        """Erase every copy of what is named, for good. Needs a key that writes."""
        call = _calls.forget(items=items, sessions=sessions, threads=threads, events=events)
        return await self._send(call, self.id)

    async def correct(self, record_id: str, replacement: str | None = None) -> Correction:
        """Retract one fact by the id search gave it, and optionally say what is true instead."""
        return await self._send(_calls.correct(record_id, replacement), self.id)

    async def versions(self, item_id: str) -> Versions:
        """An added item's versions, as they were sent."""
        return await self._send(_calls.versions(item_id), self.id)

    async def status(self, ids: Sequence[str]) -> dict[str, str]:
        """How far each item has got: accepted, landed, read, folded, or unknown."""
        return await self._send(_calls.status(ids), self.id)

    async def lineage(self, ident: str) -> Lineage:
        """What an item or event became, or what a fact was read from."""
        return await self._send(_calls.lineage(ident), self.id)
