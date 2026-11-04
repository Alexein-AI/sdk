# Working on alexein-cli

For whoever works on this package. It is not part of what is published: the source distribution
holds `src/`, the README, the CHANGELOG and the license only (`[tool.hatch.build.targets.sdist]`
in `pyproject.toml`).

## Development

The `alexein` client comes from `../../python` (`[tool.uv.sources]`), editable, so the CLI is
always tested against the client it ships beside.

```bash
uv sync                  # the default groups: dev and crewai
uv run --exact pytest    # the CLI, and every file it writes run inside real LangGraph graphs
                         # and CrewAI crews; the OpenAI Agents SDK's tests are skipped here
uv run --exact --no-group crewai --group openai-agents pytest
                         # the same, with the OpenAI Agents SDK's Runner and its scripted model
uv run ruff check . && uv run ruff format --check . && uv run pyright
```

`--exact` makes `uv run` sync the environment to the groups named, removing the other's
packages: CrewAI and the OpenAI Agents SDK need different majors of `openai`, so they never
share an environment. CI (`.github/workflows/cli-python-ci.yml`) runs `ruff format --check`,
`ruff check`, `pyright` and `pytest` on Python 3.10 and 3.13, once with each group.

Running the CLI from a checkout, with the client installed into the project from this repository
(it is not on PyPI yet):

```bash
cd /tmp && uvx --from /path/to/sdk/integrations/cli-python alexein-cli \
  create langgraph demo --sdk /path/to/sdk/python
```

`--sdk` (hidden from `--help`) takes a path or a URL, and adds `alexein[<framework>] @ <it>`
in place of `alexein[<framework>]>=0.3`.

## What ships

Everything under `src/alexein_cli/` ships, and so does every file a template writes into a
customer's project: its comments and docstrings are public text. They say what a customer sends,
gets back and can rely on, in the words of the public docs at https://docs.alexein.ai, and never
how the service works inside.

The memory file is the developer's settings and wiring only. Behaviour belongs in the client's
integration modules (`python/src/alexein/langgraph.py`, `openai_agents.py`, `crewai.py`), where a
fix reaches every project by an upgrade; a template that grows logic of its own is a sign it
should move there.

Check what a build holds before a release (tagged `cli-python-v<version>`, after the `alexein`
it needs is on PyPI):

```bash
uv build --out-dir /tmp/alexein-cli-build
tar tzf /tmp/alexein-cli-build/alexein_cli-*.tar.gz
unzip -l /tmp/alexein-cli-build/alexein_cli-*.whl
```
