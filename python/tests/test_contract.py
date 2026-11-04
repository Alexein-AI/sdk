"""Every request the client can send, against the API's own document: `contract/openapi.json` at
the repository's root, pinned by `scripts/refresh-openapi.sh`. A route or a field the API renames
or drops fails here before a release does."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from conftest import answer, memory

DOCUMENT = json.loads((Path(__file__).parents[2] / "contract" / "openapi.json").read_text())
SCHEMAS = DOCUMENT["components"]["schemas"]
PREFIX = "/v2"  # the document's server is `https://api.alexein.ai/v2`


def every_request() -> list[httpx.Request]:
    """Every method, with every field it can send set."""
    client, recorded = memory(answer)
    dana = client.user("dana")
    client.me()
    client.users(limit=10, cursor="ann")
    dana.add(
        {"text": "t", "id": "i", "at": "2026-10-01", "about": ["project:atlas"]},
        wait=True,
        redact=True,
        kind="note",
        session="s",
        role="user",
        title="T",
        author={"id": "u1", "name": "Dana", "email": "d@example.com", "handle": "d", "self": True},
        expires="2027-01-01",
        metadata={"k": 1},
    )
    dana.search(
        "q",
        before="2026-12-01",
        after="2026-01-01",
        filters={"author": "dana"},
        provider="github",
        source="items",
        kind=["issue"],
        fast=True,
    )
    dana.grep("p", limit=5, provider="slack", source="eng", kind="message")
    dana.latest(
        k=3,
        place="eng",
        after="2026-01-01",
        before="2026-12-01",
        filters={"author": "d"},
        provider="slack",
        source="eng",
        kind=["message"],
    )
    dana.around("mem_e1", width=3)
    dana.open("mem_f1")
    dana.history("s", attribute="a")
    dana.summary()
    dana.facts(limit=5, cursor="cur_1")
    dana.open_items(kind="issue", provider="github", place="r", mine=False, within_days=3, limit=5)
    dana.sources()
    dana.items(limit=5, cursor="cur_1", filters={"metadata": {"k": 1}})
    dana.item("i")
    dana.status(["i"])
    dana.forget(items=["i"], sessions=["s"], refs=["mem_f1"])
    dana.correct("mem_f1", "x")
    dana.versions("i")
    dana.export(limit=5, cursor="cur_1")
    dana.delete()
    return recorded.requests


def operation(request: httpx.Request) -> dict[str, Any]:
    path = request.url.path
    assert path.startswith(PREFIX), path
    found = DOCUMENT["paths"].get(path.removeprefix(PREFIX), {}).get(request.method.lower())
    assert found, f"{request.method} {path} is not in the API's document"
    return found


def schema(ref: str) -> dict[str, Any]:
    return SCHEMAS[ref.rsplit("/", 1)[-1]]


def test_every_request_is_a_route_and_body_the_api_documents():
    for request in every_request():
        spec = operation(request)
        if request.method == "GET":
            assert request.content == b""
            continue
        body = json.loads(request.content)
        if "requestBody" not in spec:
            assert body == {}, f"{request.url.path} takes no fields"
            continue
        taken = schema(spec["requestBody"]["content"]["application/json"]["schema"]["$ref"])
        known, required = set(taken.get("properties", {})), set(taken.get("required", []))
        assert set(body) <= known, f"{request.url.path}: {set(body) - known} not in the API"
        assert required <= set(body), f"{request.url.path}: {required - set(body)} missing"


def test_every_header_the_client_sends_is_one_the_route_takes():
    ours = {"x-alexein-user", "idempotency-key"}
    for request in every_request():
        taken = {p["name"].lower() for p in operation(request).get("parameters", [])}
        sent = ours & set(request.headers)
        assert sent <= taken, f"{request.url.path}: {sent - taken}"
        if "x-alexein-user" in taken:
            assert "x-alexein-user" in sent, f"{request.url.path} needs its app user"


def test_every_item_and_author_field_is_one_the_api_takes():
    add = next(r for r in every_request() if r.url.path.endswith("/add"))
    (item,) = json.loads(add.content)["items"]
    assert set(item) <= set(SCHEMAS["Item"]["properties"])
    assert set(item["author"]) <= set(SCHEMAS["Author"]["properties"])


# Documented, and left out of the client on purpose. `events/lookup` (2026-11-04) is the console's:
# it takes the ingestion service's own event ids, which a customer never holds, and answers in a
# shape no other route has (`phase`, `queueComplete`, `occurredAt`). The TypeScript client leaves
# out the same routes (`test/contract.test.ts`).
NOT_OFFERED = {("post", "/memory/events/lookup")}


def test_every_route_in_the_document_has_a_method():
    reached = {(r.method.lower(), r.url.path.removeprefix(PREFIX)) for r in every_request()}
    documented = {(m, p) for p, spec in DOCUMENT["paths"].items() for m in spec}
    assert documented - NOT_OFFERED == reached, (documented - NOT_OFFERED) ^ reached
    assert documented >= NOT_OFFERED, "a route left out is no longer documented: drop it here"


def test_the_document_is_the_version_this_client_speaks():
    from alexein import __version__

    # A patch release (0.3.1) is the client's own; any 0.3.x speaks the API's 0.3.
    def minor(version: str) -> list[str]:
        return version.split(".")[:2]

    assert minor(DOCUMENT["info"]["version"]) == minor(__version__)
