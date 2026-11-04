"""Retries, and the error each failure becomes."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from conftest import memory, ok

from alexein import (
    AlexeinError,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    FieldError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
)


def then(*responses: httpx.Response | Exception):
    """Answers in order, the last one for good."""
    queue: Iterator[httpx.Response | Exception] = iter(responses)
    last: list[httpx.Response | Exception] = [responses[-1]]

    def next_answer(request: httpx.Request) -> httpx.Response:
        given = next(queue, last[0])
        if isinstance(given, Exception):
            raise given
        return given

    return next_answer


@pytest.mark.parametrize("status", [429, 503])
def test_429_and_503_are_retried_with_backoff(status: int, no_waiting: list[float]):
    client, recorded = memory(then(ok({"detail": "busy"}, status), ok({"facts": []})))
    assert client.user("dana").facts().facts == []
    assert len(recorded.requests) == 2
    (pause,) = no_waiting
    assert 0.375 <= pause <= 0.625


def test_backoff_doubles_with_jitter(no_waiting: list[float]):
    client, recorded = memory(then(ok({}, 503), ok({}, 503), ok({"facts": []})))
    client.user("dana").facts()
    assert len(recorded.requests) == 3
    assert 0.375 <= no_waiting[0] <= 0.625 and 0.75 <= no_waiting[1] <= 1.25


def test_retry_after_is_waited(no_waiting: list[float]):
    client, _ = memory(then(ok({"detail": "slow down"}, 429, **{"Retry-After": "7"}), ok({})))
    client.user("dana").summary()
    assert no_waiting == [7.0]


def test_a_retry_after_past_a_minute_raises_at_once(no_waiting: list[float]):
    client, recorded = memory(then(ok({"detail": "later"}, 503, **{"Retry-After": "120"})))
    with pytest.raises(ServiceUnavailableError):
        client.user("dana").summary()
    assert len(recorded.requests) == 1 and no_waiting == []


def test_retries_stop_at_max_retries(no_waiting: list[float]):
    client, recorded = memory(lambda r: ok({"detail": "busy"}, 429), max_retries=3)
    with pytest.raises(RateLimitError) as raised:
        client.user("dana").summary()
    assert len(recorded.requests) == 4 and len(no_waiting) == 3
    assert raised.value.outage and raised.value.status == 429


def test_no_retries_with_max_retries_zero():
    client, recorded = memory(lambda r: ok({}, 503), max_retries=0)
    with pytest.raises(ServiceUnavailableError):
        client.user("dana").summary()
    assert len(recorded.requests) == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 422, 500, 502])
def test_nothing_else_is_retried(status: int):
    client, recorded = memory(lambda r: ok({"detail": "no"}, status))
    with pytest.raises(AlexeinError):
        client.user("dana").summary()
    assert len(recorded.requests) == 1


def test_connection_failures_are_retried_then_raised(no_waiting: list[float]):
    client, recorded = memory(then(httpx.ConnectError("refused")))
    with pytest.raises(APIConnectionError) as raised:
        client.user("dana").summary()
    assert len(recorded.requests) == 3
    assert raised.value.status is None and raised.value.outage
    assert not isinstance(raised.value, APITimeoutError)


def test_a_timeout_is_a_connection_error_too():
    client, _ = memory(then(httpx.ReadTimeout("slow")))
    with pytest.raises(APITimeoutError) as raised:
        client.user("dana").summary()
    assert isinstance(raised.value, APIConnectionError) and raised.value.outage


def test_a_connection_failure_then_an_answer_is_an_answer():
    client, _ = memory(then(httpx.ConnectError("refused"), ok({"facts": [], "next": None})))
    assert client.user("dana").facts().next is None


@pytest.mark.parametrize(
    ("status", "kind", "outage"),
    [
        (400, InvalidRequestError, False),
        (401, AuthenticationError, False),
        (403, PermissionDeniedError, False),
        (404, NotFoundError, False),
        (409, InvalidRequestError, False),
        (413, InvalidRequestError, False),
        (422, InvalidRequestError, False),
        (429, RateLimitError, True),
        (500, ServiceUnavailableError, True),
        (502, ServiceUnavailableError, True),
        (503, ServiceUnavailableError, True),
    ],
)
def test_each_status_is_its_error(status: int, kind: type[AlexeinError], outage: bool):
    said = "no memory for app user 'dana' yet"
    response = ok({"detail": said}, status, **{"X-Request-Id": "req_1"})
    client, _ = memory(lambda r: response, max_retries=0)
    with pytest.raises(kind) as raised:
        client.user("dana").summary()
    error = raised.value
    assert type(error) is kind and isinstance(error, AlexeinError)
    assert (error.status, error.detail, error.request_id) == (status, said, "req_1")
    assert error.errors == [] and error.outage is outage
    assert str(error) == f"{status}: {said}"


def test_a_422_names_each_field():
    body = {
        "detail": "`items[0].text` must not be empty. See https://docs.alexein.ai/api/add for "
        "what this route takes.",
        "errors": [{"field": "items[0].text", "message": "`items[0].text` must not be empty"}],
    }
    client, _ = memory(lambda r: ok(body, 422))
    with pytest.raises(InvalidRequestError) as raised:
        client.user("dana").add({"text": "x"})
    assert raised.value.errors == [FieldError("items[0].text", "`items[0].text` must not be empty")]
    assert raised.value.detail == body["detail"]


def test_a_validation_list_in_fastapis_own_shape_is_read_too():
    body = {"detail": [{"loc": ["body", "query"], "msg": "Field required", "type": "missing"}]}
    client, _ = memory(lambda r: ok(body, 422))
    with pytest.raises(InvalidRequestError) as raised:
        client.user("dana").search("x")
    assert raised.value.errors == [FieldError("query", "Field required")]
    assert raised.value.detail == "query: Field required"


def test_a_body_that_is_not_json_is_still_an_error():
    client, _ = memory(lambda r: httpx.Response(502, text="Bad gateway"), max_retries=0)
    with pytest.raises(ServiceUnavailableError) as raised:
        client.user("dana").summary()
    assert raised.value.detail == "Bad gateway"


def test_every_call_sends_a_request_id_of_its_own_kept_across_its_retries(no_waiting: list[float]):
    client, recorded = memory(then(ok({"detail": "busy"}, 503), ok({"items": 0, "sources": []})))
    client.user("dana").summary()
    client.user("dana").summary()
    ids = [r.headers["X-Request-Id"] for r in recorded.requests]
    assert ids[0] == ids[1] != ids[2] and all(i.startswith("req_") for i in ids)


def test_an_error_carries_the_request_id_even_when_the_answer_has_none(no_waiting: list[float]):
    """A 500 a proxy answered, or no answer at all, can still be found in the request logs."""
    client, recorded = memory(then(httpx.Response(500, text="Internal Server Error")))
    with pytest.raises(ServiceUnavailableError) as raised:
        client.user("dana").summary()
    assert raised.value.request_id == recorded.last.headers["X-Request-Id"]
    client, recorded = memory(then(httpx.ConnectError("refused")))
    with pytest.raises(APIConnectionError) as unreached:
        client.user("dana").summary()
    assert unreached.value.request_id == recorded.last.headers["X-Request-Id"]
    client, _ = memory(then(ok({"detail": "no"}, 401, **{"X-Request-Id": "theirs"})))
    with pytest.raises(AuthenticationError) as refused:
        client.me()
    assert refused.value.request_id == "theirs"
