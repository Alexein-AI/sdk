# Working on twinmemory-cli for JavaScript

## Development

```bash
npm install          # twinmemory comes from ../../vendor until it is on npm
npm run check        # types, formatting, and the tests: the CLI, and every file it writes run
                     # inside real LangGraph.js graphs and the OpenAI Agents SDK's runner (with
                     # a scripted model), type-checked and formatted as written
npm run build        # dist/bin.js
node dist/bin.js init langgraph --sdk /path/to/twin-memory-js
```

`--sdk` installs the `twinmemory` client from a path instead of npm, while it is not published there.
It is not in `--help`.

## The twinmemory client

Until `twinmemory` is on npm, it comes from `../../vendor`, which `../../scripts/vendor-clients.sh`
builds. After that script rebuilds it, update the lockfile here with:

```bash
npm install ../../vendor/twinmemory-0.1.0.tgz
```

A plain `npm install` keeps the lockfile's old integrity and quietly installs the old client from
npm's cache, and `npm ci` on a machine without that cache then fails. Commit the new tarball and
this lockfile together.

Once `twinmemory` is on npm, depend on it by version, take `--sdk` out, and publish this package only
after it. `npm publish` refuses while `twinmemory` is still a `file:` dependency.

## What ships

The npm package holds what `files` in `package.json` names: `dist/`, `templates/`, `README.md`,
`CHANGELOG.md` and `LICENSE`. `README.md` is the package's page on npm, for the people who install it;
notes for working on the package belong here, which does not ship. Check with:

```bash
npm run build && npm pack --dry-run
```
