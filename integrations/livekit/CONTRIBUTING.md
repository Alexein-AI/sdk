# Working on alexein-livekit

For whoever works on this package. It is not part of what is published: the source distribution
holds `src/`, the README, the CHANGELOG and the license only (`[tool.hatch.build.targets.sdist]`
in `pyproject.toml`), so `tests/`, `e2e/` and `examples/` stay in this repository.

## Install from this repository

Until it is on PyPI, with access to the repository:

```bash
pip install "alexein @ git+ssh://git@github.com/Alexein-AI/sdk#subdirectory=python" \
  "alexein-livekit @ git+ssh://git@github.com/Alexein-AI/sdk#subdirectory=integrations/livekit"
```

In this repository `uv sync` installs the client from `../../python`, editable
(`[tool.uv.sources]` in `pyproject.toml`), so a change to the client is tested here at once.

## Development

```bash
uv sync
uv run ruff format --check . && uv run ruff check . && uv run pyright && uv run pytest -q
ALEXEIN_LIVE=1 uv run pytest -q tests/test_live.py       # against the memory API: ALEXEIN_API_URL
                                                         # and a key that writes in ALEXEIN_API_KEY
uv run python e2e/room.py                                # text, in a real LiveKit room
uv run --with "livekit-plugins-openai~=1.8" python e2e/scenarios.py      # real model
uv run --with "livekit-plugins-openai~=1.8" --with "livekit-plugins-silero~=1.8" \
  python e2e/voice.py                                    # real voice, see e2e/README.md
```

CI (`.github/workflows/livekit-ci.yml`, at the repository's root) runs the second line on Python
3.10 and 3.13, whenever this package, the client in `python/` or the API's contract changes, then
the tests again on the oldest LiveKit Agents the package supports:
`uv run --with "livekit-agents==1.5.1" pytest -q`.

- `tests/` runs whole turns through a real `AgentSession`, typed and spoken, with a scripted LLM
  and the memory API faked in process; `tests/test_hardening.py` holds what review found.
- `e2e/scenarios.py` is twenty callers ringing back with a real model (gpt-4.1-mini): a booking
  and its allergy, an appointment moved, a code corrected, a move to another city, "the second
  one", an order number, numbers said as words, Spanish, someone else's memory, a planted
  instruction, a card number, "don't remember this", "what do you know about me". On the final
  code: auto mode 19 of 19 on every run, tools mode 20 of 20 and 19 of 20, each failure since
  fixed and re-run five times.
- `e2e/voice.py` speaks to the agent in a real room, with real speech to text, model and speech,
  and checks what it said aloud, in both modes.
- `examples/chat.py` is a call typed at a terminal, through the same `AgentSession` and
  `AlexeinMemoryAgent` a voice agent uses.

## What ships

Everything under `src/alexein_livekit/` ships, docstrings and comments included, and so do the
README and the CHANGELOG: they are public text. They say what a customer sends, gets back and can
rely on, in the words of the public docs at https://docs.alexein.ai, and never how the service
works inside. The text this package parses out of a search result is matched as it is, and not
described.

A release is tagged `livekit-v<version>` (`livekit-v0.3.0`), once the `alexein` it needs is on PyPI.
Check what a build holds before one:

```bash
uv build --out-dir /tmp/alexein-livekit-build
tar tzf /tmp/alexein-livekit-build/alexein_livekit-*.tar.gz
unzip -l /tmp/alexein-livekit-build/alexein_livekit-*.whl
```
