# Working on twinmemory-cli

For whoever works on this package. It is not part of what is published: the source distribution
holds `src/`, the README, the CHANGELOG and the license only (`[tool.hatch.build.targets.sdist]`
in `pyproject.toml`).

## Development

```bash
uv sync                  # twinmemory comes from ../../vendor until it is on PyPI
uv run pytest            # the CLI, and every file it writes run inside real LangGraph graphs
                         # and CrewAI crews; the OpenAI Agents SDK's tests are skipped here
uv sync --no-default-groups --group dev --group openai-agents && uv run --no-sync pytest
                         # the same, with the OpenAI Agents SDK's Runner and its scripted model,
                         # as CI runs it; without --no-sync, uv run syncs the default groups
uv sync                  # back to the default groups
uv run ruff check . && uv run pyright
```

CI (`.github/workflows/python-ci.yml`) runs `ruff format --check`, `ruff check`, `pyright` and
`pytest` on Python 3.10 and 3.13, once with `--group crewai` and once with `--group openai-agents`:
CrewAI and the OpenAI Agents SDK need different majors of `openai`, so they never share an
environment.

From a checkout, installing a checkout of the client into the project instead of PyPI:

```bash
uvx --from . twinmemory-cli init langgraph --sdk /path/to/twin-memory-python
```

## What ships

Everything under `src/twinmemory_cli/` ships, and so does every file a template writes into a
customer's project: its comments and docstrings are public text. They say what a customer sends,
gets back and can rely on, in the words of the public docs at https://docs.alexein.ai, and never
how the service works inside.

Check what a build holds before a release:

```bash
uv build --out-dir /tmp/twinmemory-cli-build
tar tzf /tmp/twinmemory-cli-build/twinmemory_cli-*.tar.gz
unzip -l /tmp/twinmemory-cli-build/twinmemory_cli-*.whl
```
