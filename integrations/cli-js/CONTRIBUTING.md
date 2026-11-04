# Working on @alexein/cli

## Development

The CLI depends on `@alexein/sdk` from this repository, `file:../../typescript`, so build that first:

```bash
(cd ../../typescript && npm ci && npm run build)
npm ci               # .npmrc's install-links copies ../../typescript in, as npm would install it
npm run check        # types, formatting, and the tests: the CLI, and every file it writes run as
                     # written - through @alexein/sdk - inside real LangGraph.js graphs and the
                     # OpenAI Agents SDK's runner (with a scripted model), type-checked and
                     # formatted as written
npm run build        # dist/bin.js
node dist/bin.js init langgraph --sdk /path/to/alexein-sdk-0.3.0.tgz
```

`.npmrc` sets `install-links=true`: `@alexein/sdk` is installed as a copy, not a symlink, so it
resolves `@langchain/*`, `@openai/agents` and `zod` from this package's `node_modules` - one copy of
each, as in a developer's project. After changing `../../typescript`, rebuild it and run `npm ci`
(or `npm install`) here again to take the new build.

`--sdk` installs `@alexein/sdk` from a path or a tarball (`cd ../../typescript && npm pack`)
instead of npm, while it is not published there. It is not in `--help`.

## Publishing

`@alexein/sdk` goes to npm first; then depend on it here by version (`"@alexein/sdk": "^0.3.0"`),
take `.npmrc` and `--sdk` out, and publish this package after it. `npm publish` refuses while
`@alexein/sdk` is still a `file:` dependency. A release workflow, when there is one, publishes on a
tag `cli-js-v<version>`.

## What ships

The npm package holds what `files` in `package.json` names: `dist/`, `templates/`, `README.md`,
`CHANGELOG.md` and `LICENSE`. `README.md` is the package's page on npm, for the people who install it;
notes for working on the package belong here, which does not ship. Check with:

```bash
npm run build && npm pack --dry-run
```
