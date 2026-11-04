"""With `fail_open`, an outage answers `search` empty and skips `add`; nothing else changes."""

from __future__ import annotations

import httpx
import pytest
from conftest import async_memory, memory, ok

from alexein import (
    AlexeinError,
    AuthenticationError,
    InvalidRequestError,
    NotFoundError,
    PermissionDeniedError,
    ServiceUnavailableError,
)

OUTAGES = [
    pytest.param(lambda r: ok({"detail": "busy"}, 503), id="503"),
    pytest.param(lambda r: ok({"detail": "slow"}, 429), id="429"),
    pytest.param(lambda r: ok({"detail": "boom"}, 500), id="500"),
    pytest.param(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")), id="unreachable"),
    pytest.param(lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), id="timeout"),
]


@pytest.mark.parametrize("down", OUTAGES)
def test_an_outage_answers_search_empty_and_skips_add(down, caplog: pytest.LogCaptureFixture):
    client, _ = memory(down, fail_open=True)
    dana = client.user("dana")

    found = dana.search("Where does Dana live?")
    assert found.failed and found.memories == [] and found.context() == ""
    assert found.query == "Where does Dana live?" and found.answerable is None

    added = dana.add("I moved to Lisbon.")
    assert added.failed and added.items == [] and added.waiting == 0

    warnings = [r for r in caplog.records if r.name == "alexein"]
    assert len(warnings) == 2 and all(r.levelname == "WARNING" for r in warnings)
    assert "unavailable" in warnings[0].getMessage()


@pytest.mark.parametrize("down", OUTAGES)
def test_every_other_method_still_raises_an_outage(down):
    client, _ = memory(down, fail_open=True)
    for call in (lambda u: u.grep("x"), lambda u: u.summary(), lambda u: u.forget(items=["i"])):
        with pytest.raises(AlexeinError) as raised:
            call(client.user("dana"))
        assert raised.value.outage


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (400, InvalidRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (422, InvalidRequestError),
    ],
)
def test_a_mistake_raises_even_failing_open(status: int, kind: type[Exception]):
    client, _ = memory(lambda r: ok({"detail": "no"}, status), fail_open=True)
    with pytest.raises(kind):
        client.user("dana").search("q")
    with pytest.raises(kind):
        client.user("dana").add("x")


def test_without_fail_open_an_outage_raises():
    client, _ = memory(lambda r: ok({"detail": "busy"}, 503))
    with pytest.raises(ServiceUnavailableError):
        client.user("dana").search("q")
    with pytest.raises(ServiceUnavailableError):
        client.user("dana").add("x")


@pytest.mark.anyio
async def test_the_async_client_fails_open_the_same_way(caplog: pytest.LogCaptureFixture):
    client, _ = async_memory(lambda r: ok({"detail": "busy"}, 503), fail_open=True)
    dana = client.user("dana")
    assert (await dana.search("q")).failed
    assert (await dana.add("x")).failed
    with pytest.raises(ServiceUnavailableError):
        await dana.summary()
