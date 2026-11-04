"""The two clients, `Memory` and `AsyncMemory`: a key, a connection pool, and the views of one
app user's memory they hand out (`_user.py`)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from types import TracebackType

import httpx

from alexein import _calls
from alexein._async_user import AsyncUser
from alexein._http import (
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT,
    AsyncTransport,
    Transport,
    headers,
)
from alexein._http import base_url as _base
from alexein._results import AppUser, Me, UsersPage
from alexein._user import User


class Memory:
    """An Alexein client.

    ```python
    memory = Memory()                # ALEXEIN_API_KEY from the environment
    dana = memory.user("dana")       # your own id for one of your app users
    dana.add("I moved to Lisbon for the job at Acme.")
    print(dana.search("Where does Dana live?").context())
    ```

    `base_url` (or ALEXEIN_API_URL) is the host, `https://api.alexein.ai` by default.
    `timeout` is seconds per attempt; 429, 503 and connection failures are retried up to
    `max_retries` times. With `fail_open`, an outage answers `search` empty and skips `add`
    instead of raising. `integration` adds one word to the User-Agent. `http_client` replaces
    the client's own `httpx.Client` (its timeout is then yours to set).
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
        sent = headers(api_key, integration)
        self.base_url = _base(base_url)
        self.max_retries = max_retries
        self.fail_open = fail_open
        self.integration = integration
        http = http_client or httpx.Client(timeout=timeout)
        self._transport = Transport(http, self.base_url, sent, max_retries)

    def __repr__(self) -> str:
        return f"Memory(base_url={self.base_url!r})"

    def me(self) -> Me:
        """What this key is: its organisation, project, and whether it writes."""
        return self._transport.send(_calls.me())

    def user(self, user_id: str) -> User:
        """The memory of one of your app users, by your own id for them: 1 to 35 letters,
        digits, '.', '_' or '-', starting with a letter or digit."""
        return User(self._transport, _calls.checked_user(user_id), fail_open=self.fail_open)

    def users(self, limit: int | None = None, cursor: str | None = None) -> UsersPage:
        """A page of this key's project's app users with memory, in id order (50 by default).
        Pass `next` as `cursor` for the page after."""
        return self._transport.send(_calls.users(limit=limit, cursor=cursor))

    def iter_users(self, limit: int | None = None) -> Iterator[AppUser]:
        """Every app user with memory, page after page."""
        cursor: str | None = None
        while True:
            page = self.users(limit=limit, cursor=cursor)
            yield from page.users
            if not page.next:
                return
            cursor = page.next

    def close(self) -> None:
        self._transport.http.close()

    def __enter__(self) -> Memory:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()


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
        sent = headers(api_key, integration)
        self.base_url = _base(base_url)
        self.max_retries = max_retries
        self.fail_open = fail_open
        self.integration = integration
        http = http_client or httpx.AsyncClient(timeout=timeout)
        self._transport = AsyncTransport(http, self.base_url, sent, max_retries)

    def __repr__(self) -> str:
        return f"AsyncMemory(base_url={self.base_url!r})"

    async def me(self) -> Me:
        """What this key is: its organisation, project, and whether it writes."""
        return await self._transport.send(_calls.me())

    def user(self, user_id: str) -> AsyncUser:
        """The memory of one of your app users, by your own id for them: 1 to 35 letters,
        digits, '.', '_' or '-', starting with a letter or digit."""
        return AsyncUser(self._transport, _calls.checked_user(user_id), fail_open=self.fail_open)

    async def users(self, limit: int | None = None, cursor: str | None = None) -> UsersPage:
        """A page of this key's project's app users with memory, in id order (50 by default).
        Pass `next` as `cursor` for the page after."""
        return await self._transport.send(_calls.users(limit=limit, cursor=cursor))

    async def iter_users(self, limit: int | None = None) -> AsyncIterator[AppUser]:
        """Every app user with memory, page after page."""
        cursor: str | None = None
        while True:
            page = await self.users(limit=limit, cursor=cursor)
            for user in page.users:
                yield user
            if not page.next:
                return
            cursor = page.next

    async def close(self) -> None:
        await self._transport.http.aclose()

    async def __aenter__(self) -> AsyncMemory:
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await self.close()
