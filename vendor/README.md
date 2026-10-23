# vendor/

The twin memory clients, built, for `twinmemory-cli` to depend on until they are published:

- `twinmemory-0.2.0-py3-none-any.whl` - [twin-memory-python](https://github.com/Alexein-AI/twin-memory-python),
  for `packages/python` (`tool.uv.sources` in its `pyproject.toml`).
- `twinmemory-0.1.0.tgz` - [twin-memory-js](https://github.com/Alexein-AI/twin-memory-js), for
  `packages/js` (a `file:` dependency in its `package.json`).

They are here so CI never needs access to those private repositories. `scripts/vendor-clients.sh` rebuilds
them from checkouts beside this one; run it after a change to either client and commit the result.

Once both clients are on PyPI and npm, delete this folder and the script, and depend on them by version.
