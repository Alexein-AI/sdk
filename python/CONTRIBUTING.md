# Contributing

Notes for working on the Python client. This file does not ship: the wheel holds `src/alexein` and its
metadata, and the sdist adds `README.md`, `CHANGELOG.md` and `LICENSE` (hatchling also adds `pyproject.toml`
and `PKG-INFO`; see `[tool.hatch.build.targets.sdist]` in `pyproject.toml`).

## Layout

- `_calls.py` describes each request once: route, body, how to read the answer. Both clients send it.
- `_http.py` sends it: settings, headers, retries, and the error a response becomes.
- `_client.py` (`Memory`, `AsyncMemory`), `_user.py` (`User`) and `_async_user.py` (`AsyncUser`, kept line
  for line beside `_user.py`).
- `_memories.py`, `_results.py`, `_writes.py`: the results, each parsed from the JSON the API sends.
- `langgraph.py`, `openai_agents.py`, `crewai.py`: the integrations, on the client alone, never HTTP;
  `_integration.py` is what they share. `import alexein` must never import a framework.

`../docs/DESIGN.md` is the surface every client in this repository exposes; change it there first.

## Checks

What CI runs (`../.github/workflows/python-ci.yml`), on Python 3.10 and 3.13, once per framework group. CrewAI
needs `openai<3` and the OpenAI Agents SDK `openai>=3`, so they never share an environment: `crewai` is a
default group, and `openai-agents` replaces it.

```bash
uv run --exact ruff format --check .
uv run --exact ruff check .
uv run --exact pyright
uv run --exact pytest -q

uv run --exact --no-group crewai --group openai-agents pyright
uv run --exact --no-group crewai --group openai-agents pytest -q
```

`--exact` matters when switching: without it, `uv run` leaves the other group's packages installed.

`uv build` writes the sdist and the wheel to `dist/`. Before a release, list what they hold
(`tar -tzf dist/*.tar.gz`, `unzip -l dist/*.whl`): no tests, examples or notes like this one.

## The contract

`tests/test_contract.py` holds every request the client can send - every route, every field, every header -
to the API's own document, `../contract/openapi.json`, so a field the API renames or drops fails here before a
release does. Refresh it from a running service with `../scripts/refresh-openapi.sh`.

## End to end, against a local stack

`tests/test_live.py` runs the quickstart against a running service, and is skipped unless `ALEXEIN_API_KEY` is
set. It needs a key that writes; its searches are `fast`, and it deletes the app user it made.

```bash
ALEXEIN_API_KEY=tm_... uv run pytest tests/test_live.py      # http://localhost:8210 by default
ALEXEIN_API_KEY=tm_... ALEXEIN_API_URL=https://... uv run pytest tests/test_live.py
```

## Releasing

Push a tag `python-v<version>` matching `pyproject.toml`'s version; `python-release.yml` tests, builds and
publishes to PyPI through trusted publishing. A manual run publishes to TestPyPI instead.

## Public text

The README, the CHANGELOG, the package metadata, and the docstrings and comments in `src/` ship to PyPI, so
anyone can read them. They say what a call sends, what comes back and what is guaranteed, in the words of the
docs at https://docs.alexein.ai, and never how the service produces it: no internal components, vendors,
models, storage, tuning numbers or local-stack details. Those belong in this file and the tests.
