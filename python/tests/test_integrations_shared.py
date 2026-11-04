"""What every integration shares: `import alexein` imports no framework, and the client each makes
for itself."""

from __future__ import annotations

import subprocess
import sys

import pytest

from alexein import Excerpt, Fact, Known, Opened, SearchResult
from alexein._integration import found_text, made, made_async, opened_text

FRAMEWORKS = ("langgraph", "langchain", "langchain_core", "agents", "crewai", "openai")


def test_importing_alexein_imports_no_framework():
    code = (
        "import sys, alexein; "
        f"print(sorted(m for m in sys.modules if m.split('.')[0] in {FRAMEWORKS!r}))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


@pytest.mark.parametrize(
    ("module", "framework"),
    [("langgraph", "langgraph"), ("openai_agents", "agents"), ("crewai", "crewai")],
)
def test_importing_an_integration_needs_no_key(module: str, framework: str):
    pytest.importorskip(framework)
    code = f"import alexein.{module}"
    env = {"PATH": "", "CREWAI_DISABLE_TELEMETRY": "true", "OTEL_SDK_DISABLED": "true"}
    subprocess.run([sys.executable, "-c", code], check=True, env=env, capture_output=True)


def test_the_client_an_integration_makes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ALEXEIN_API_KEY", "tm_env")
    client = made("langgraph", strict=False)
    assert client.fail_open and client.integration == "langgraph"
    assert client._transport.http.timeout.read == 10.0  # pyright: ignore[reportPrivateUsage]
    assert not made("crewai", strict=True).fail_open
    assert made_async("openai-agents", strict=False).fail_open


def test_what_memory_search_answers_a_model():
    found = SearchResult(
        query="q",
        answerable=None,
        notes=[],
        memories=[Known("K."), Fact("mem_f1", "F."), Excerpt("mem_e1", "E.", date="2026-10-01")],
    )
    assert found_text(found, 4000) == (
        "- K.\n- F.\n- 2026-10-01: E.\n\nTo read one whole, memory_open:\n- mem_f1\n- mem_e1"
    )
    # Only the refs of what fitted are offered.
    assert found_text(found, 9) == "- K.\n- F.\n\nTo read one whole, memory_open:\n- mem_f1"
    assert found_text(None, 4000) == "Nothing remembered about that."
    assert found_text(SearchResult.unavailable("q"), 4000).startswith("Memory is unavailable")


def test_what_memory_open_answers_a_model():
    excerpt = Excerpt("mem_e1", "Dana: hi.", date="2026-10-01T09:00:00Z")
    assert opened_text(Opened(excerpt, [])) == "2026-10-01: Dana: hi."
    assert opened_text(Opened(Fact("mem_f1", "Dana says hi."), [])) == "Dana says hi."
    assert opened_text(Opened(Fact("mem_f1", "Dana says hi."), [excerpt])) == (
        "Dana says hi.\n\nLearned from:\n\n2026-10-01: Dana: hi."
    )
