# Contributing

Notes for working on the client. This file does not ship: the wheel holds `src/twinmemory` and its metadata,
and the sdist adds `README.md`, `CHANGELOG.md` and `LICENSE` (hatchling also adds `pyproject.toml`,
`.gitignore` and `PKG-INFO`; see `[tool.hatch.build.targets.sdist]` in `pyproject.toml`).

## Checks

What CI runs (`.github/workflows/ci.yml`), on Python 3.10 to 3.13:

```bash
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest -q                    # unit and contract tests
```

`uv build` writes the sdist and the wheel to `dist/`. Before a release, list what they hold
(`tar -tzf dist/*.tar.gz`, `unzip -l dist/*.whl`): no tests, scripts, pinned documents or notes like this one.

## End to end, against a local stack

`tests/test_live.py` runs against a running service, and is skipped unless `TWIN_MEMORY_LIVE=1`. It needs a key
that writes. Its searches are `fast`, and it erases what it added.

```bash
TWIN_MEMORY_LIVE=1 TWIN_MEMORY_API_KEY=tm_... TWIN_MEMORY_BASE_URL=http://localhost:8210 uv run pytest tests/test_live.py
```

## The pinned API document

`tests/test_contract.py` holds every method to the API's own document, pinned at `tests/openapi-memory.json`,
so a field the API renames or drops fails here before a release does. Refresh it from a running service:

```bash
scripts/refresh-openapi.sh                  # from http://localhost:8210
scripts/refresh-openapi.sh <base-url>       # from another
```

## Public text

The README, the CHANGELOG, the package metadata, and the docstrings and comments in `src/` ship to PyPI, so
anyone can read them. They say what a call sends, what comes back and what is guaranteed, in the words of the
docs at https://docs.alexein.ai, and never how the service produces it: no internal components, vendors,
models, storage, tuning numbers or local-stack details. Those belong in this file, the tests or the scripts.
