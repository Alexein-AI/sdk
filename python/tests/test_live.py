"""The quickstart, end to end, against a running service. Skipped unless ALEXEIN_API_KEY is set;
ALEXEIN_API_URL defaults to a local stack (http://localhost:8210). Needs a key that writes.

Free: searches are `fast`, so no model is asked, and the app user made here is deleted at the
end. The questions share words with what they look for, so a service with no embedding model
finds it too."""

from __future__ import annotations

import contextlib
import io
import os
import re
import time
import uuid
from pathlib import Path

import anyio
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


def _stored(user, ids: list[str]) -> None:
    """Wait until every id is searchable. `wait=True` waits only briefly (the API's word), and a
    busy service answers before its items land; a minute is what this test allows them."""
    deadline = time.monotonic() + 60
    while any(s == "queued" for s in user.status(ids).by_id.values()):
        assert time.monotonic() < deadline, f"still queued after a minute: {user.status(ids).raw}"
        time.sleep(1)


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
            assert len(added.items) == 2
            _stored(dana, added.ids)

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


README = Path(__file__).resolve().parents[2] / "README.md"


def test_the_readme_example_prints_the_answer_on_its_first_run():
    """The repository README's Python example, as written, for an app user with nothing yet: it
    printed an empty line (2026-11-23), its add not yet searchable and its words not naming Dana.
    Run with a fresh app user and a `fast` search, so it stays free; then that app user is
    deleted."""
    example = re.search(r"```python\n(.*?)```", README.read_text(), re.DOTALL)
    assert example, "no Python example in the README"
    user = f"sdk-readme-{uuid.uuid4().hex[:8]}"
    code = example.group(1).replace('memory.user("dana")', f'memory.user("{user}")')
    code = code.replace(
        '.search("Where does Dana live?")', '.search("Where does Dana live?", fast=True)'
    )
    assert user in code and "fast=True" in code, "the README's example changed: update this test"
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            exec(compile(code, str(README), "exec"), {})
        assert "Lisbon" in printed.getvalue(), printed.getvalue()
    finally:
        with Memory() as memory:
            memory.user(user).delete()


@pytest.mark.anyio
async def test_the_async_client_against_the_same_service():
    async with AsyncMemory() as memory:
        sam = memory.user(f"sdk-live-{uuid.uuid4().hex[:8]}")
        try:
            await sam.add({"id": "tea", "kind": "note", "text": "Prefers green tea."}, wait=True)
            deadline = time.monotonic() + 60  # as `_stored`: a busy service lands it later
            while (await sam.status(["tea"])).by_id["tea"] == "queued":
                assert time.monotonic() < deadline, "still queued after a minute"
                await anyio.sleep(1)
            found = await sam.search("Which tea does she prefer?", fast=True)
            assert "green tea" in found.context()
        finally:
            await sam.delete()
