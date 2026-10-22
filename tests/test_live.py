"""Against a running service, end to end. Skipped unless TWIN_MEMORY_LIVE=1, with
TWIN_MEMORY_API_KEY and TWIN_MEMORY_BASE_URL set (a local stack: http://localhost:8210).

Free: searches are `fast`, so no model is asked, and what was added is erased at the end. The
questions share words with what they look for, so a service with no embedding model finds it too.
"""

from __future__ import annotations

import os
import uuid

import pytest

from twinmemory import AsyncMemory, Memory, NotFoundError

pytestmark = pytest.mark.skipif(
    os.environ.get("TWIN_MEMORY_LIVE") != "1", reason="set TWIN_MEMORY_LIVE=1 to run"
)


def test_add_search_versions_forget():
    with Memory() as memory:
        me = memory.me()
        assert me.writes, "the live test needs a key that writes"
        user = memory.user(f"sdk-live-{uuid.uuid4().hex[:8]}")
        with pytest.raises(NotFoundError):
            user.search("anything", fast=True)

        added = user.add(
            [
                {"id": "diet", "kind": "note", "text": "Dana is vegetarian, allergic to peanuts."},
                {"text": "I moved to Lisbon for the job at Acme.", "role": "user"},
            ],
            session="onboarding",
            wait=True,
        )
        assert added.pending == 0 and len(added.items) == 2

        found = user.search("Which city did I take the job at Acme in?", fast=True)
        assert found.filtered is False
        assert any("Lisbon" in h.text for h in found.hits), found.context()
        assert "Lisbon" in found.context()
        assert user.status(["diet"])["diet"] in {"landed", "read", "folded"}
        assert user.versions("diet").state == "live"

        receipt = user.forget(items=["diet"], sessions=["onboarding"])
        assert receipt.events >= 1
        assert user.versions("diet").state == "forgotten"
        assert not any("peanuts" in m.text for m in user.grep("peanuts").matches)


@pytest.mark.anyio
async def test_the_async_client_against_the_same_service():
    async with AsyncMemory() as memory:
        user = memory.user(f"sdk-live-{uuid.uuid4().hex[:8]}")
        await user.add(
            {"id": "tea", "kind": "note", "text": "Prefers green tea over coffee."}, wait=True
        )
        found = await user.search("Which tea does she prefer?", fast=True)
        assert any("green tea" in h.text for h in found.hits)
        await user.forget(items=["tea"])
