# Releasing alexein/sdk

How the packages in this repository get from here to `pip install alexein` and `npm install @alexein/sdk`, and
every step to get there, in order. Read part 1 once; follow part 3 step by step, ticking boxes as you go.

1. [How releasing works here](#1-how-releasing-works-here): environments, tags, releases, trusted publishing
2. [What is done](#2-what-is-done)
3. [The steps](#3-the-steps): once (A-D), then release day (E), then after (F)
4. [Every later release](#4-every-later-release)
5. [When something goes wrong](#5-when-something-goes-wrong)

| Package | Registry | Folder | Tag | Workflow | Environment |
| --- | --- | --- | --- | --- | --- |
| `alexein` | PyPI | `python/` | `python-v<version>` | `python-release.yml` | `pypi` |
| `@alexein/sdk` | npm | `typescript/` | `typescript-v<version>` | `typescript-release.yml` | `npm` |
| `alexein-cli` | PyPI | `integrations/cli-python/` | `cli-python-v<version>` | `cli-python-release.yml` | `pypi` |
| `@alexein/cli` | npm | `integrations/cli-js/` | `cli-js-v<version>` | `cli-js-release.yml` | `npm` |
| `alexein-livekit` | PyPI | `integrations/livekit/` | `livekit-v<version>` | `livekit-release.yml` | `pypi` |
| `@alexein/n8n-nodes-alexein` | npm | `integrations/n8n/` | `n8n-v<version>` | `n8n-publish.yml` | `npm` |

## 1. How releasing works here

Nothing is ever published from a laptop. A person pushes a **tag**; a **workflow** builds and tests that one
package; it pauses at an **environment** until a maintainer approves; then it publishes to PyPI or npm, proving
who it is by **trusted publishing**. After, a **GitHub release** records it for people reading the repository.

### Tags

A tag is a name pinned to one commit, forever: `python-v0.3.0` means "the code of `alexein` 0.3.0 is this
commit". Here one tag releases one package; its prefix says which.

```bash
git tag python-v0.3.0            # pin the name to the commit you are on (main, after pulling)
git push origin python-v0.3.0    # send it to GitHub: this is what starts the release
git tag                          # list tags;  git push --delete origin <tag> && git tag -d <tag> removes one
```

Each workflow starts on its own prefix (`on: push: tags: ["python-v*"]`) and first checks that the tag's
version is the version in the package's `pyproject.toml` or `package.json`, so a typo'd tag fails before
anything happens.

### Workflows

A workflow is a YAML file in `.github/workflows/` that GitHub runs on its own machines. This repository has
two kinds per package:

- `<package>-ci.yml` runs on every push and pull request that touches the package (lint, types, tests,
  build), and by hand: GitHub > Actions > the workflow > **Run workflow**. It publishes nothing.
- `<package>-release.yml` (`n8n-publish.yml` for n8n) runs on the package's tag: the same checks, then the
  build is published.

Watch them at github.com/Alexein-AI/sdk/actions, or `gh run list`, `gh run watch`.

### Environments

An environment is a named gate in the repository's settings that a workflow job declares it runs in
(`environment: pypi`). It does two things:

1. **Protection rules.** With *Required reviewers* set, a job that names the environment stops before its
   first step, shows "Waiting for review", and runs only when a listed reviewer clicks **Review deployments >
   Approve and deploy**. A tag pushed by mistake publishes nothing until someone approves.
2. **Secrets of its own.** A secret stored on an environment (`gh secret set NPM_TOKEN --env npm`) is given
   only to jobs that run in it, after approval; no other workflow can read it.

This repository uses three: `pypi` (the three Python releases), `npm` (the three npm releases, and the npm
token), and `testpypi` (a manual dry run of a Python release, no reviewer). The names matter: PyPI's trusted
publisher is told the environment, and refuses a publish from any other.

### Trusted publishing

How a workflow proves to PyPI or npm that it may publish, with no password stored anywhere. GitHub gives each
run a short-lived signed token saying "repository Alexein-AI/sdk, workflow python-release.yml, environment
pypi" (that is what `permissions: id-token: write` allows). On PyPI and npm you register exactly that
combination as a trusted publisher for a package; they then accept an upload from it and from nothing else.
A stolen laptop or leaked token cannot publish. PyPI lets you register a *pending* publisher before the
project exists, so the first upload needs no token. npm allows a trusted publisher only on a package that
already exists, so each npm package's first release uses a token (`NPM_TOKEN`), and you switch it to
trusted publishing straight after.

### Provenance

`npm publish --provenance` attaches a signed statement, shown on the package's npm page, that this tarball was
built by that workflow from that commit of a public repository. npm only issues it for public repositories,
so this repository must be public before the first npm release, and n8n requires it of every community node
it verifies.

### GitHub releases

A release is a page on the repository (github.com/Alexein-AI/sdk/releases) attached to a tag: a title, notes
(here, the CHANGELOG entry), and optional files. It publishes nothing to PyPI or npm; it is how someone
reading the repository finds out what shipped and when. Make one after each tag's package is live
(`gh release create`, step F5).

## 2. What is done

- [x] One repository, Alexein-AI/sdk, with the history of twin-memory-python, twin-memory-js and
      twin-memory-integrations; pushed, private.
- [x] twin-memory-python and twin-memory-integrations archived, their READMEs pointing here.
- [x] CI green on GitHub for all six packages (2026-11-04).
- [x] Tested against production with a real key (2026-11-04): both clients' live tests, the n8n end to end, and
      the release rehearsal - 48 of 48 steps, the second conversation recalling the first for LangGraph, the
      OpenAI Agents SDK and CrewAI in Python and TypeScript.
- [x] Package names free on PyPI and npm (2026-11-04).
- [x] Docs (twin-memory-docs, branch `docs/alexein-sdk`), console and website (twin-memory-app and
      twin-website, branch `feat/alexein-sdk-names`) updated, not pushed.

## 3. The steps

### A. Production, before anything is published

- [ ] **A1. The write queue moves.** On 2026-11-04 an add to api.alexein.ai stayed `queued` for over four
      minutes (earlier the same day, seconds). Until adds land, every SDK's "remember" does nothing visible.
      Check the memory consumer in production (its logs, that it is running, its Redis queue), then confirm:

      ```bash
      export ALEXEIN_API_KEY=tm_...   # a test project's key that writes
      cd python && ALEXEIN_API_URL=https://api.alexein.ai uv run pytest tests/test_live.py -v
      ```

      Both tests pass when an add becomes searchable within 30 seconds.

- [ ] **A2. Let Python's built-in HTTP client through Cloudflare.** Cloudflare in front of api.alexein.ai
      answers `403 error code: 1010` to any request whose User-Agent is `Python-urllib/...`, the default of
      Python's standard library (`urllib.request`). Its *Browser Integrity Check* treats that User-Agent as a
      bot. The SDKs, `requests`, `httpx`, Node's `fetch`, curl and Go are not affected, but a customer
      following "plain HTTP" with the standard library, or any script without dependencies, is refused with a
      message that names nothing of ours. An API has no browsers to check, so turn it off for the API alone:

      1. dash.cloudflare.com > the `alexein.ai` zone > **Rules > Configuration Rules > Create rule**.
      2. Name: `api: no browser checks`. When incoming requests match: Field **Hostname**, Operator **equals**,
         Value `api.alexein.ai`.
      3. Then the settings are: **Browser Integrity Check: Off**. Deploy.
      4. Check (expect `200`, not `403`):

         ```bash
         curl -s -o /dev/null -w "%{http_code}\n" https://api.alexein.ai/v2/me \
           -H "Authorization: Bearer $ALEXEIN_API_KEY" -A "Python-urllib/3.12"
         ```

      If *Security > Bots* (Bot Fight Mode) is on for the zone, it can block the same requests: add a skip
      for `api.alexein.ai` there too, or leave it off for the API.

### B. GitHub (about 10 minutes)

- [ ] **B1. Archive the last old repository:** `gh repo archive Alexein-AI/twin-memory-js --yes` (its README
      already points here).
- [ ] **B2. Environments.** github.com/Alexein-AI/sdk > **Settings > Environments > New environment**:
  - `pypi`: tick **Required reviewers**, add yourself (and anyone else who may release), **Save protection
    rules**. Under *Deployment branches and tags*, choose **Selected branches and tags > Add rule > Tag**,
    pattern `*-v*`: only a release tag can use it.
  - `npm`: the same.
  - `testpypi`: no reviewers, no rules.
- [ ] **B3. Protect release tags**, so only maintainers can push a tag that releases: **Settings > Rules >
      Rulesets > New ruleset > New tag ruleset**. Name `releases`; Enforcement status **Active**; Target tags
      **Add target > Include by pattern** `*-v*`; tick **Restrict creations**, **Restrict updates**,
      **Restrict deletions**; **Bypass list > Add bypass > Repository admin** (or yourself). **Create**.
- [ ] **B4. Public on release day, not before** (step E1).

### C. PyPI (about 10 minutes, no tokens)

- [ ] **C1.** pypi.org > Register (or sign in). **Account settings > Two factor authentication**: add an
      authenticator app; PyPI requires it to publish.
- [ ] **C2. Optional, recommended:** **Your organizations > Create organization** `Alexein` (company), so the
      projects belong to the company rather than a person. (PyPI reviews new organizations; it can take days.
      Publishing does not wait for it: move the projects in later, step F6.)
- [ ] **C3. Pending publishers.** pypi.org/manage/account/publishing/ > **Add a new pending publisher** >
      **GitHub**, once per row, exactly:

      | PyPI Project Name | Owner | Repository name | Workflow name | Environment name |
      | --- | --- | --- | --- | --- |
      | `alexein` | `Alexein-AI` | `sdk` | `python-release.yml` | `pypi` |
      | `alexein-cli` | `Alexein-AI` | `sdk` | `cli-python-release.yml` | `pypi` |
      | `alexein-livekit` | `Alexein-AI` | `sdk` | `livekit-release.yml` | `pypi` |

      A pending publisher also reserves the name for you until its first upload (for a while; publish within
      days).
- [ ] **C4. Dry run on TestPyPI (recommended).** test.pypi.org is a separate site with separate accounts:
      register there, add one pending publisher - project `alexein`, owner `Alexein-AI`, repository `sdk`,
      workflow `python-release.yml`, environment `testpypi`. Then GitHub > Actions > **python-release > Run
      workflow** (branch `main`). It builds, tests and uploads to TestPyPI. Check it installs:

      ```bash
      cd "$(mktemp -d)" && uv venv -q && uv pip install -q -i https://test.pypi.org/simple/ \
        --extra-index-url https://pypi.org/simple/ alexein && uv run python -c "import alexein; print(alexein.__version__)"
      ```

### D. npm (about 10 minutes)

- [ ] **D1.** npmjs.com > sign in > avatar > **Account > Two-Factor Authentication**: enable, for
      authorization and writes.
- [ ] **D2. The scope.** avatar > **Add Organization** > name `alexein` > **Unlimited public packages**
      (free). Every npm package here is `@alexein/...`: if `alexein` is taken, stop and decide a new scope
      before anything else.
- [ ] **D3. A token for the first publishes.** avatar > **Access Tokens > Generate New Token > Granular
      Access Token**: name `alexein-sdk-first-publish`; expiration 30 days; **Packages and scopes**:
      permissions **Read and write**, **Only select packages and scopes** > `@alexein`; **Organizations**: no
      access. Generate, copy it.
- [ ] **D4. Store it on the `npm` environment only** (paste it when asked; it is never shown again):

      ```bash
      gh secret set NPM_TOKEN --env npm --repo Alexein-AI/sdk
      ```

### E. Release day

Order matters: the CLIs and LiveKit depend on the clients, and their release checks install from the real
registries. Do it on a day you can watch the whole thing (about an hour).

- [ ] **E1. Make the repository public.** github.com/Alexein-AI/sdk > **Settings > General > Danger Zone >
      Change repository visibility > Make public**.
- [ ] **E2. The last checks**, from `main`:

      ```bash
      cd ~/repos/alexein-sdk && git pull
      gh run list --limit 12                                     # every *-ci green on the latest commit
      scripts/refresh-openapi.sh https://api.alexein.ai && git diff --exit-code contract/   # no change: the API is what the clients were built for
      export ALEXEIN_API_KEY=tm_... ALEXEIN_API_URL=https://api.alexein.ai
      (cd python && uv run pytest tests/test_live.py -v)
      (cd typescript && npx vitest run test/live.test.ts)
      (cd integrations/livekit && ALEXEIN_LIVE=1 uv run pytest tests/test_live.py -v)
      ```

      If `contract/` changed, the API moved since the clients were built: stop and update them first.
- [ ] **E3. Date the changelogs.** In each of the six `CHANGELOG.md`, change `## 0.3.0 - unreleased` to the
      day's date (`## 0.3.0 - 2026-11-12`), then:

      ```bash
      git commit -am "0.3.0, released $(date +%F)" && git push
      ```

- [ ] **E4. The clients.**

      ```bash
      git tag python-v0.3.0     && git push origin python-v0.3.0
      git tag typescript-v0.3.0 && git push origin typescript-v0.3.0
      ```

      GitHub > **Actions**: each run builds and tests, then waits at its environment. Open it > **Review
      deployments** > tick the environment > **Approve and deploy**. When both are green:

      ```bash
      pip index versions alexein          # alexein (0.3.0)
      npm view @alexein/sdk version       # 0.3.0
      ```

- [ ] **E5. `@alexein/cli` depends on the published client.** In the repository it depends on the folder
      (`file:../../typescript`), for development; its release refuses that.

      ```bash
      cd integrations/cli-js
      npm pkg set "dependencies.@alexein/sdk=^0.3.0" && npm install && npm run check
      cd ../.. && git commit -am "@alexein/cli depends on @alexein/sdk 0.3 from npm" && git push
      ```

      (The Python packages need nothing: their path to `../../python` is a development setting of uv, and
      the published wheel already asks for `alexein>=0.3`.)
- [ ] **E6. The rest**, approving each in Actions as in E4:

      ```bash
      for t in cli-python-v0.3.0 livekit-v0.3.0 cli-js-v0.3.0 n8n-v0.3.0; do
        git tag $t && git push origin $t
      done
      ```

- [ ] **E7. Install each as a new user would**, in an empty folder:

      ```bash
      cd "$(mktemp -d)"
      uvx --from alexein python -c "import alexein; print(alexein.__version__)"      # 0.3.0
      uvx alexein-cli --version && npx -y @alexein/cli --version                       # 0.3.0, 0.3.0
      uvx --from alexein-livekit python -c "import alexein_livekit"
      npm view @alexein/n8n-nodes-alexein version                                     # 0.3.0
      uvx alexein-cli create langgraph demo && cd demo && uvx alexein-cli doctor
      ```

### F. Right after

- [ ] **F1. npm: switch to trusted publishing, then drop the token.** For each of `@alexein/sdk`,
      `@alexein/cli`, `@alexein/n8n-nodes-alexein`: npmjs.com > the package > **Settings > Trusted
      Publisher > GitHub Actions**: organization or user `Alexein-AI`, repository `sdk`, workflow filename
      `typescript-release.yml` / `cli-js-release.yml` / `n8n-publish.yml`, environment `npm` > **Set up
      connection**. Then on the same page, **Publishing access > Require two-factor authentication and
      disallow tokens** > Update. When all three are done:

      ```bash
      gh secret delete NPM_TOKEN --env npm --repo Alexein-AI/sdk
      ```

      and on npmjs.com > Access Tokens, delete `alexein-sdk-first-publish`.
- [ ] **F2. Docs.** In twin-memory-docs: remove the "Preview: not published yet" callouts and the "not on
      PyPI / npm yet" sentences on the SDK and integration pages (`content/docs/(integrations)/`), then

      ```bash
      git push -u origin docs/alexein-sdk && gh pr create --fill
      ```

      Review, merge, deploy as usual. Then check docs.alexein.ai/sdks/python and /integrations/langgraph.
- [ ] **F3. Console and website.** In twin-memory-app (`lib/site/integrations.ts`) and twin-website
      (`src/content/integrations.ts`), on branch `feat/alexein-sdk-names`, set `live: true` on Python,
      TypeScript, LangGraph, CrewAI, OpenAI Agents SDK, n8n and LiveKit; push, open a PR each, merge, deploy.
- [ ] **F4. Release the local stack's docs too** (alexein-stack builds from the clones' `main`):
      `./setup.sh pull && docker compose up --build -d` in alexein-stack after F2 and F3 merge.
- [ ] **F5. GitHub releases**, one per tag, notes from each CHANGELOG's 0.3.0 entry:

      ```bash
      notes() { awk '/^## 0.3.0/{on=1;next} /^## /{on=0} on' "$1"; }
      gh release create python-v0.3.0      --title "alexein 0.3.0"                    --notes "$(notes python/CHANGELOG.md)"
      gh release create typescript-v0.3.0  --title "@alexein/sdk 0.3.0"               --notes "$(notes typescript/CHANGELOG.md)"
      gh release create cli-python-v0.3.0  --title "alexein-cli 0.3.0"                --notes "$(notes integrations/cli-python/CHANGELOG.md)"
      gh release create cli-js-v0.3.0      --title "@alexein/cli 0.3.0"               --notes "$(notes integrations/cli-js/CHANGELOG.md)"
      gh release create livekit-v0.3.0     --title "alexein-livekit 0.3.0"            --notes "$(notes integrations/livekit/CHANGELOG.md)"
      gh release create n8n-v0.3.0         --title "@alexein/n8n-nodes-alexein 0.3.0" --notes "$(notes integrations/n8n/CHANGELOG.md)"
      ```

- [ ] **F6. PyPI ownership**, if you made the organization (C2) and it is approved: each project > **Settings
      > Transfer project** (or Collaborators) to `Alexein`; add a second owner, so the projects never depend on
      one person's account.
- [ ] **F7. n8n Cloud.** creators.n8n.io > submit `@alexein/n8n-nodes-alexein` for verification. It checks the
      npm provenance (E1 makes that possible) and that the node has no runtime dependencies (it has none).
      Once verified, it appears in n8n Cloud and in the editor's node search.
- [ ] **F8. Development again:** put `@alexein/cli`'s dependency back on the folder, so it is developed against
      the client beside it:

      ```bash
      cd integrations/cli-js && npm pkg set "dependencies.@alexein/sdk=file:../../typescript" && npm install
      cd ../.. && git commit -am "@alexein/cli develops against ../../typescript again" && git push
      ```

- [ ] **F9. Optional.** GitHub's secret-scanning partner program for the `tm_` key prefix (so keys pushed to
      public repositories are reported to you); listings in LangChain's integrations docs, LiveKit's
      plugins, the CrewAI and OpenAI Agents SDK community pages.

## 4. Every later release

1. Change the package; its CI goes green on `main`.
2. Bump its version everywhere it is written - `pyproject.toml` or `package.json`, and also
   `python/src/alexein/_version.py`, `typescript/src/version.ts`, `integrations/cli-python/src/alexein_cli/_version.py`,
   `integrations/cli-js/src/version.ts` for those four (`git grep -n '"0.3.0"'` finds them) - and add a dated
   CHANGELOG entry, in one commit. The release fails if the tag and `pyproject.toml`/`package.json` disagree. Semantic versions: a patch (0.3.1) fixes, a minor (0.4.0) adds or,
   while below 1.0, may change behaviour - say so in the CHANGELOG.
3. A client released before what depends on it; `@alexein/cli` pointed at the published client (E5), and
   back after (F8).
4. `git tag <prefix>-v<version> && git push origin <prefix>-v<version>`; approve in Actions; check as in E7.
5. `gh release create` (F5). If the API changed, `scripts/refresh-openapi.sh https://api.alexein.ai` first,
   and update the clients in the same release.

## 5. When something goes wrong

- **A workflow fails before publishing** (tests, a version that does not match the tag): nothing was
  published. Fix on `main`, then move the tag: `git push --delete origin python-v0.3.0 && git tag -d
  python-v0.3.0`, and tag again.
- **It waits forever:** it is waiting for approval (Actions > the run > Review deployments).
- **PyPI says "invalid-publisher"**: the pending publisher's five fields do not match the run exactly
  (repository `sdk`, the workflow's file name, environment `pypi`).
- **npm says 404 or E403 on publish**: the `@alexein` organization does not exist or the token cannot write
  to it (D2, D3), or `NPM_TOKEN` was set on the repository instead of the `npm` environment (D4).
- **npm says provenance requires a public repository**: E1.
- **A bad version was published:** never publish that number again; fix and release a patch. PyPI: the project
  > Release history > the version > Options > **Yank** (pinned installs still work; new ones skip it). npm:
  `npm deprecate @alexein/sdk@0.3.0 "use 0.3.1: <why>"` (`npm unpublish` works only within 72 hours, and never
  frees the number).
