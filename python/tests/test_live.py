"""The quickstart, end to end, against a running service. Skipped unless ALEXEIN_API_KEY is set;
ALEXEIN_API_URL defaults to a local stack (http://localhost:8210). Needs a key that writes.

Free: searches are `fast`, so no model is asked, and the app user made here is deleted at the
end. The questions share words with what they look for, so a service with no embedding model
finds it too."""

from __future__ import annotations

import os
import uuid

import pytest

from alexein import AsyncMemory, Memory

pytestmark = pytest.mark.skipif(
    not os.environ.get("ALEXEIN_API_KEY"), reason="set ALEXEIN_API_KEY to run"
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real environment, unlike the other tests', with a local stack by default."""
    if not os.environ.get("ALEXEIN_API_URL"):
        monkeypatch.setenv("ALEXEIN_API_URL", "http://localhost:8210")


def test_the_quickstart():
    with Memory() as memory:
        assert memory.me().writes, "the live test needs a key that writes"
        dana = memory.user(f"sdk-live-{uuid.uuid4().hex[:8]}")
        try:
            added = dana.add(
                [
                    {
                        "id": "diet",
                        "kind": "note",
                        "text": "Dana is vegetarian, allergic to peanuts.",
                    },
                    {"text": "I moved to Lisbon for the job at Acme.", "role": "user"},
                ],
                session="onboarding",
                wait=True,
            )
            assert added.waiting == 0 and len(added.items) == 2

            found = dana.search("Which city did I take the job at Acme in?", fast=True)
            assert "Lisbon" in found.context(), found.raw
            ref = found.excerpts[0].ref
            assert "Lisbon" in dana.open(ref).memory.text or found.facts
            assert any("peanuts" in m.text for m in dana.grep("peanuts"))
            assert dana.status(["diet"]).by_id["diet"] in {"stored", "processed"}
            assert dana.item("diet") is not None
            assert dana.versions("diet").state == "live"
            assert dana.summary().items >= 2

            forgotten = dana.forget(items=["diet"])
            assert forgotten.erased.items >= 1
            assert dana.versions("diet").state == "forgotten"
            assert not any("peanuts" in m.text for m in dana.grep("peanuts"))
        finally:
            assert dana.delete().deleted


@pytest.mark.anyio
async def test_the_async_client_against_the_same_service():
    async with AsyncMemory() as memory:
        sam = memory.user(f"sdk-live-{uuid.uuid4().hex[:8]}")
        try:
            await sam.add({"id": "tea", "kind": "note", "text": "Prefers green tea."}, wait=True)
            found = await sam.search("Which tea does she prefer?", fast=True)
            assert "green tea" in found.context()
        finally:
            await sam.delete()
