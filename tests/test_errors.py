"""What a failed response becomes, and which ones are tried again."""

from __future__ import annotations

import httpx
import pytest
from conftest import async_memory, memory, ok

from twinmemory import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    TwinMemoryError,
)


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (400, InvalidRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (413, InvalidRequestError),
        (500, TwinMemoryError),
    ],
)
def test_each_status_is_its_own_error_with_the_apis_detail(status, kind):
    client, sent = memory(lambda _: ok({"detail": "said why"}, status, **{"X-Request-Id": "r1"}))
    with pytest.raises(kind) as raised:
        client.user("dana").search("x")
    assert type(raised.value) is kind
    assert raised.value.status == status and raised.value.detail == "said why"
    assert raised.value.request_id == "r1" and "said why" in str(raised.value)
    assert len(sent.requests) == 1, "not retried"


def test_a_validation_error_says_which_field():
    detail = [{"loc": ["body", "query"], "msg": "Field required", "type": "missing"}]
    client, _ = memory(lambda _: ok({"detail": detail}, 422))
    with pytest.raises(InvalidRequestError, match=r"body\.query: Field required"):
        client.user("dana").search("x")


def test_a_429_waits_as_retry_after_says_then_succeeds(no_waiting):
    answers = iter([ok({"detail": "slow"}, 429, **{"Retry-After": "1"}), ok({"hits": []})])
    client, sent = memory(lambda _: next(answers))
    client.user("dana").search("x")
    assert len(sent.requests) == 2 and no_waiting == [1.0]


def test_a_503_is_tried_three_times_in_all_then_raised(no_waiting):
    client, sent = memory(lambda _: ok({"detail": "rebuilding"}, 503))
    with pytest.raises(ServiceUnavailableError):
        client.user("dana").search("x")
    assert len(sent.requests) == 3
    assert 0.375 <= no_waiting[0] <= 0.625 and 0.75 <= no_waiting[1] <= 1.25


def test_a_retry_after_too_long_to_wait_is_raised_at_once(no_waiting):
    client, sent = memory(lambda _: ok({"detail": "later"}, 429, **{"Retry-After": "600"}))
    with pytest.raises(RateLimitError):
        client.user("dana").search("x")
    assert len(sent.requests) == 1 and not no_waiting


def test_max_retries_zero_never_retries():
    client, sent = memory(lambda _: ok({"detail": "busy"}, 503), max_retries=0)
    with pytest.raises(ServiceUnavailableError):
        client.user("dana").search("x")
    assert len(sent.requests) == 1


def test_an_unreachable_service_is_retried_then_a_connection_error():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client, sent = memory(refuse)
    with pytest.raises(APIConnectionError, match="could not be reached"):
        client.user("dana").search("x")
    assert len(sent.requests) == 3


def test_a_timeout_is_its_own_error():
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client, _ = memory(slow)
    with pytest.raises(APITimeoutError):
        client.user("dana").search("x")


def test_a_retried_add_resends_the_same_idempotency_key():
    answers = iter([ok({"detail": "busy"}, 503), ok({"items": [], "queued": 0, "pending": 0})])
    client, sent = memory(lambda _: next(answers))
    client.user("dana").add("Prefers green tea.")
    first, second = (r.headers["Idempotency-Key"] for r in sent.requests)
    assert first == second


def test_a_body_that_is_not_json_still_says_what_came_back():
    client, _ = memory(lambda _: httpx.Response(502, text="Bad Gateway"))
    with pytest.raises(TwinMemoryError, match="502: Bad Gateway"):
        client.user("dana").search("x")


@pytest.mark.anyio
async def test_the_async_client_retries_and_raises_the_same_way(no_waiting):
    client, sent = async_memory(lambda _: ok({"detail": "rebuilding"}, 503))
    with pytest.raises(ServiceUnavailableError):
        await client.user("dana").search("x")
    assert len(sent.requests) == 3 and len(no_waiting) == 2
