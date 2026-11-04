# Releasing alexein/sdk

How the packages in this repository get from here to `pip install alexein` and `npm install @alexein/sdk`.
Part A is done once, by someone who owns the accounts. Part B is every release.

| Package | Registry | Folder | Tag | Workflow |
| --- | --- | --- | --- | --- |
| `alexein` | PyPI | `python/` | `python-v<version>` | `python-release.yml` |
| `@alexein/sdk` | npm | `typescript/` | `typescript-v<version>` | `typescript-release.yml` |
| `alexein-cli` | PyPI | `integrations/cli-python/` | `cli-python-v<version>` | `cli-python-release.yml` |
| `@alexein/cli` | npm | `integrations/cli-js/` | `cli-js-v<version>` | `cli-js-release.yml` |
| `alexein-livekit` | PyPI | `integrations/livekit/` | `livekit-v<version>` | `livekit-release.yml` |
| `@alexein/n8n-nodes-alexein` | npm | `integrations/n8n/` | `n8n-v<version>` | `n8n-publish.yml` |

Every workflow checks that the tag matches the package's version, runs the package's tests, and only then
publishes. Nothing publishes from a laptop.

## Part A: once

### A1. The GitHub repository

1. Create it and push (from this folder):

   ```bash
   gh repo create Alexein-AI/sdk --private --source . --push --description "Alexein's Python and TypeScript SDKs and integrations"
   ```

2. Before the first release, make it public: GitHub > Alexein-AI/sdk > Settings > General > Danger Zone > Change
   visibility > Public. npm only attaches provenance (`npm publish --provenance`, which both npm workflows use)
   to packages built from a public repository, and n8n's verified-node review requires provenance.
3. Create three environments: Settings > Environments > New environment, named exactly `pypi`, `testpypi` and
   `npm`. In `pypi` and `npm`, tick **Required reviewers** and add yourself: a pushed tag then waits for your
   click before anything is published.
4. Protect release tags: Settings > Rules > Rulesets > New tag ruleset, target `*-v*`, restrict creation to
   maintainers. Only people who may release can push a tag that releases.
5. Retire the old repositories. Each has a local branch `moved-to-alexein-sdk` (in
   `~/repos/alexein-sdk-work/<repo>`) whose README points here:

   ```bash
   for r in twin-memory-python twin-memory-js twin-memory-integrations; do
     git -C ~/repos/alexein-sdk-work/$r push origin moved-to-alexein-sdk:main
     gh repo archive Alexein-AI/$r --yes
   done
   ```

### A2. PyPI

1. Sign in at https://pypi.org (make an account if needed; PyPI requires two-factor authentication). Optional:
   Your organizations > Create organization "Alexein", so the projects belong to the company, not a person.
2. Your account > Publishing > **Add a new pending publisher**, three times (the projects do not exist yet, so
   the publisher is "pending" until the first upload creates them):

   | PyPI Project Name | Owner | Repository name | Workflow name | Environment name |
   | --- | --- | --- | --- | --- |
   | `alexein` | `Alexein-AI` | `sdk` | `python-release.yml` | `pypi` |
   | `alexein-cli` | `Alexein-AI` | `sdk` | `cli-python-release.yml` | `pypi` |
   | `alexein-livekit` | `Alexein-AI` | `sdk` | `livekit-release.yml` | `pypi` |

   No token is created or stored: at publish time GitHub proves to PyPI which repository, workflow and
   environment is asking.
3. Same on https://test.pypi.org (a separate account), with environment `testpypi`. A manual run of a Python
   release workflow (Actions > python-release > Run workflow) then uploads to TestPyPI instead, for a dry run:

   ```bash
   pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ alexein
   ```

4. After the first upload, if you made an organization: the project > Settings > Collaborators, and move it to
   the organization.

### A3. npm

1. Sign in at https://www.npmjs.com, turn on two-factor authentication.
2. Create the scope: profile menu > **Add Organization** > name `alexein` > Unlimited public packages (free). If
   `alexein` is taken, stop: every package name here would change.
3. Make a token for the first publish of each package: profile > Access Tokens > Generate New Token >
   **Granular Access Token**: packages and scopes, read and write, scope `@alexein`; organizations, none;
   expiry, 30 days. Store it on the `npm` environment only:

   ```bash
   gh secret set NPM_TOKEN --env npm --repo Alexein-AI/sdk   # paste the token when asked
   ```

4. After each npm package's first release, switch it to trusted publishing and stop needing the token:
   npmjs.com > the package > Settings > Trusted Publisher > GitHub Actions: organization `Alexein-AI`,
   repository `sdk`, workflow `typescript-release.yml` (or `cli-js-release.yml`, `n8n-publish.yml`),
   environment `npm`. Then, in the same settings, Publishing access > "Require two-factor authentication and
   disallow tokens". When all three are switched, delete the token on npmjs.com and
   `gh secret delete NPM_TOKEN --env npm --repo Alexein-AI/sdk`.

## Part B: every release

### B1. Before tagging

1. Every package's CI is green on `main`.
2. The live tests pass against production with a real key (make one in the console, API keys, read and write;
   use a project made for testing):

   ```bash
   export ALEXEIN_API_KEY=tm_... ALEXEIN_API_URL=https://api.alexein.ai
   (cd python && uv run pytest tests/test_live.py -v)
   (cd typescript && npm test -- test/live.test.ts)
   (cd integrations/livekit && ALEXEIN_LIVE=1 uv run pytest tests/test_live.py -v)
   (cd integrations/n8n && node e2e/run.mjs)   # starts n8n in Docker
   ```

3. The contract is current: `scripts/refresh-openapi.sh https://api.alexein.ai` changes nothing
   (`git diff --exit-code contract/`). If it changes, the API moved: update the clients first.
4. The release rehearsal passes: it publishes every package to registries on this machine only and follows
   the docs word for word.

   ```bash
   cd scripts/release-rehearsal && docker compose up -d && ./publish.sh
   python3 rehearse.py --key tm_... --base-url https://api.alexein.ai
   docker compose down -v
   ```

5. Each package's version is bumped and its CHANGELOG says what changed, its heading dated
   (`## 0.3.0 - 2026-11-10`, not `- unreleased`), in the same commit.

### B2. Tag, in this order

The clients first: the CLIs and LiveKit depend on them, and their release workflows install from the real
registries.

```bash
git tag python-v0.3.0     && git push origin python-v0.3.0
git tag typescript-v0.3.0 && git push origin typescript-v0.3.0
```

Approve each in GitHub > Actions (the environment waits for you), and wait until both are live:

```bash
pip index versions alexein
npm view @alexein/sdk version
```

Then `@alexein/cli` must depend on the published client, not the folder: in `integrations/cli-js`,

```bash
npm pkg set "dependencies.@alexein/sdk=^0.3.0" && npm install && npm run check
git commit -am "@alexein/cli depends on @alexein/sdk 0.3 from npm" && git push
```

(Its release refuses to run while that dependency is `file:`. Put `file:../../typescript` back afterwards for
development, as CONTRIBUTING says.) Then the rest:

```bash
for t in cli-python-v0.3.0 livekit-v0.3.0 cli-js-v0.3.0 n8n-v0.3.0; do
  git tag $t && git push origin $t
done
```

### B3. After

1. Check each as a new user would, in a fresh folder:

   ```bash
   uvx --from alexein python -c "import alexein; print(alexein.__version__)"
   uvx alexein-cli --version
   npx -y @alexein/cli --version
   npm view @alexein/n8n-nodes-alexein version
   ```

2. Docs: in twin-memory-docs, remove the "Preview: not published yet" callouts on the SDK and integration
   pages, merge, deploy. In the console (twin-memory-app `lib/site/integrations.ts`) and the website
   (twin-website `src/content/integrations.ts`), set `live: true` on what shipped.
3. A GitHub release per tag, its notes the CHANGELOG entry:

   ```bash
   gh release create python-v0.3.0 --title "alexein 0.3.0" --notes-file <(sed -n '/## 0.3.0/,/## /p' python/CHANGELOG.md | sed '$d')
   ```

4. n8n, first release only: submit `@alexein/n8n-nodes-alexein` in the n8n Creator Portal for verification, so
   it can be installed on n8n Cloud and found in the editor's node search.

## If something goes wrong

- A workflow fails before publishing: fix on `main`, delete the tag (`git push --delete origin python-v0.3.0`,
  `git tag -d python-v0.3.0`), tag again.
- A bad version is published: never reuse its number. PyPI: the project > Release history > the version >
  Options > **Yank** (installs that pin it still work; new ones skip it). npm:
  `npm deprecate @alexein/sdk@0.3.0 "use 0.3.1: <why>"` (`npm unpublish` works only within 72 hours and
  frees nothing for reuse). Then release a fixed patch version.
