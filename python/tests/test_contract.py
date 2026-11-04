"""Every method against the API's own document, `openapi-memory.json`, pinned in this folder.

Refresh it from a running service with `scripts/refresh-openapi.sh`; a field the API renames or
drops then fails here, before a release does.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import memory, ok

DOCUMENT = json.loads((Path(__file__).parent / "openapi-memory.json").read_text())
SCHEMAS = DOCUMENT["components"]["schemas"]


def _every_call():
    client, sent = memory(lambda _: ok())
    dana = client.user("dana")
    client.me()
    dana.add(
        {"text": "t", "id": "i", "at": "2026-10-01", "about": ["project:atlas"]},
        wait=True, kind="note", session="s", role="user", author={"name": "Dana", "self": True},
        title="T", expires="2027-01-01", metadata={"k": 1},
    )  # fmt: skip
    dana.search("q", before="2026-12-01", after="2026-01-01", scope="passages/", fast=True)
    dana.grep("p", scope="passages/", limit=5)
    dana.read("a")
    dana.ls("a")
    dana.around("p", width=3)
    dana.history("s", attribute="a")
    dana.latest(k=3, place="slack", after="2026-01-01", before="2026-12-01")
    dana.overview()
    dana.forget(items=["i"], sessions=["s"], threads=["t"], events=["e"])
    dana.correct("r", "x")
    dana.versions("i")
    dana.status(["i"])
    dana.lineage("i")
    return sent.requests


def _fields(ref: str) -> tuple[set[str], set[str]]:
    schema = SCHEMAS[ref.rsplit("/", 1)[-1]]
    return set(schema.get("properties", {})), set(schema.get("required", []))


def test_every_request_is_a_path_method_and_body_the_api_documents():
    for request in _every_call():
        method = request.method.lower()
        operation = DOCUMENT["paths"].get(request.url.path, {}).get(method)
        assert operation, f"{request.method} {request.url.path} is not in the API's document"
        if method == "get":
            continue
        body = json.loads(request.content)
        if "requestBody" not in operation:
            assert body == {}, f"{request.url.path} takes no fields"
            continue
        ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        known, required = _fields(ref)
        assert set(body) <= known, f"{request.url.path}: {set(body) - known} not in the API"
        assert required <= set(body), f"{request.url.path}: {required - set(body)} missing"


def test_every_item_field_the_sdk_sends_is_one_the_api_takes():
    add = next(r for r in _every_call() if r.url.path == "/v1/memory/add")
    known, _ = _fields("Item")
    for item in json.loads(add.content)["items"]:
        assert set(item) <= known, set(item) - known


def test_every_route_in_the_document_has_a_method():
    reached = {(r.method.lower(), r.url.path) for r in _every_call()}
    documented = {(m, p) for p, spec in DOCUMENT["paths"].items() for m in spec}
    assert documented == reached, documented ^ reached
