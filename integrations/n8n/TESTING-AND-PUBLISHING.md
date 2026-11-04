# Testing and publishing the Alexein n8n node

Step by step, in order. Part A tests the node on your machine and needs no accounts. Part B is a quick publish
from your laptop. Part C is the proper publish, the one n8n Cloud needs. How the node works is in
[HOW-IT-WORKS.md](HOW-IT-WORKS.md).

## Before you start

- **Accounts:** none for Part A. An npmjs.com account, a member of the `alexein` organisation (which owns the
  `@alexein` scope), for B and C.
- **Tools:** Docker Desktop running, Node.js 20 or newer, `npm`, `git` and `gh` (logged in to GitHub).
- **Repos:** `Alexein-AI/sdk` (this repository) and `Alexein-AI/alexein-stack` (the whole of Alexein on one
  machine), cloned side by side, each on `main`.

**One fact that shapes Parts B and C.** npm only accepts a package published from GitHub Actions _with provenance_
(signed proof of which repo and commit built it) when the GitHub repo is **public**. n8n requires that provenance
to verify a node for n8n Cloud.

- **Part B** (from your laptop) works with the repo private, and any self-hosted n8n can install the result. It
  has no provenance.
- **Part C** needs the repo public, and is what n8n Cloud needs.

---

## A. Test it locally (free, no accounts)

### A1. Get the code

```bash
cd ~/repos/alexein-sdk
git switch main && git pull
cd integrations/n8n
npm ci
npm test            # builds, then 23 unit tests, checked against contract/openapi.json
npm run lint        # n8n's own rules; should print no errors
```

### A2. Start the stack

```bash
cd ~/repos/alexein-stack
./setup.sh pull                 # or ./setup.sh, the first time
docker compose up --build -d
```

Check it is up:

- the console at http://localhost:3000;
- the Alexein API at http://localhost:8210/health.

### A3. Make a key

1. Open http://localhost:3000 and sign in, or sign up; verification emails are at http://localhost:3000/dev/mailbox.
2. Go to **API keys** > **Create key**, choose a key that **writes**, and copy the `tm_...` value. It's shown
   once.
3. Check it: `curl -s http://localhost:8210/v2/me -H "Authorization: Bearer tm_..."` should print
   `{"kind":"key", ..., "writes":true}`.

### A4. Run the end-to-end test

```bash
cd ~/repos/alexein-sdk/integrations/n8n
ALEXEIN_API_KEY=tm_... ALEXEIN_API_URL=http://localhost:8210 node e2e/run.mjs
```

It takes about a minute: it starts n8n 2.44.6 in Docker with the node installed. Every line should say `ok:`,
ending with `all passed`. Its search is fast and its MCP check greps, so the only budget it spends is on the facts
learned from the two items it adds.

A wrong key should fail the credential Test, because your stack has real keys. To see it, run the test once with
`ALEXEIN_API_KEY=tm_wrong`. It stops at the credential step, and the line printed for the wrong key's Test is no
longer OK.

### A5. Try it by hand in n8n

The test leaves n8n running at **http://localhost:5679**. Log in as `e2e@example.com` / `E2e-test-password-1`.

1. **A credential.** Go to **Credentials > Add credential > Alexein API**.
   - API Key: your `tm_...`
   - Base URL: `http://host.docker.internal:8210`. n8n runs in Docker, so `localhost` would be the container
     itself.
   - Click **Test**. It should say the connection succeeded.
2. **A workflow.** Make a new workflow: **Manual Trigger** > **Alexein** (operation **Add**).
   - App User: `test_user`
   - Text: `I prefer green tea.`
   - Kind: Note
   - Wait Until Searchable: on
   - Run it.
3. **A search.** Add another **Alexein** node (operation **Search**).
   - App User: `test_user`
   - Query: `What tea do I like?`
   - Fast: on
   - Run it. Its output has `context` with the tea, and each memory a `ref`.
4. **Open.** Add an **Alexein** node (operation **Open**) with Ref set to a `ref` from the search, and run it.
5. **The template.** Go to **Workflows > Import from File** and pick `templates/telegram-assistant-memory.json`.
   - It imports with every node known.
   - Running it needs a Telegram bot token (from @BotFather) and an OpenAI key. That model call costs money, on
     your OpenAI account.
6. **In the console.** At http://localhost:3000, **App users** lists `test_user` and **Logs** shows the requests.

Stop n8n when done:

```bash
docker compose -f e2e/docker-compose.yml down -v
```

### A6. Optional: n8n's own dev mode

```bash
cd ~/repos/alexein-sdk/integrations/n8n
npm run dev
```

This runs n8n at http://localhost:5678 with the node linked, and rebuilds as you edit. The node is the same; this
is the loop to use while changing it. Because this n8n runs on your machine rather than in Docker, the
credential's Base URL is `http://localhost:8210`.

---

## B. Quick publish from your laptop (no provenance)

Any self-hosted n8n can install the result. n8n Cloud can't, and n8n won't verify it. Afterwards that version
number is used up on npm for good, so the first provenance release (Part C) has to be the next version.

### B1. npm account

1. Sign up at https://www.npmjs.com, or log in.
2. Turn on two-factor authentication: **Account > Two-Factor Authentication**.
3. Be a member of the `alexein` organisation, with publish rights: it owns the `@alexein` scope.

### B2. Publish

```bash
cd ~/repos/alexein-sdk/integrations/n8n
npm login                                  # opens the browser
npm run lint && npm test                   # must be clean
RELEASE_MODE=true npm publish
```

`RELEASE_MODE=true` is needed because the package's `prepublishOnly` step (n8n's guard) refuses a plain
`npm publish` and tells you to use the release command instead. `publishConfig.access` in `package.json` makes the
scoped package public. npm asks for your 2FA code.

### B3. Check it

```bash
npm view @alexein/n8n-nodes-alexein
```

Then, in a self-hosted n8n: **Settings > Community Nodes > Install** > `@alexein/n8n-nodes-alexein` > Install. The
node appears as **Alexein**. The test n8n from A4 works for this: run `node e2e/run.mjs` again, open
http://localhost:5679, and install from the UI.

### B4. Bump the version for Part C

In `package.json` set `version` to the next patch version, add its entry to `CHANGELOG.md`, then commit, open a
PR and merge.

---

## C. The proper publish: GitHub Actions, with provenance

This is the release n8n Cloud verification needs. `.github/workflows/n8n-publish.yml` (at the repository root)
does the work; you set it up once.

### C1. Make the repo public

```bash
gh repo edit Alexein-AI/sdk --visibility public --accept-visibility-change-consequences
```

Check nothing private is in it first: `git log -p | grep -i "tm_\|secret\|password"` should only show test
values. The e2e password is a local throwaway. Making the repository public is the owner's decision, taken before
this step.

### C2. An npm token, for the first publish only

npm only lets you add a trusted publisher to a package that already exists, so the very first publish uses a
token. If B published a version, the package exists: skip to C6 first, then carry on from C3.

1. On npmjs.com, go to **Access Tokens > Generate New Token > Granular Access Token**:
   - Name: `alexein sdk n8n first publish`
   - Expiration: 7 days
   - Packages and scopes: **Read and write**, scope `@alexein`.
   - If your account requires 2FA to publish, tick **Bypass two-factor authentication**. CI can't type a code.
2. Copy the token (`npm_...`).
3. Store it in the repo: `gh secret set NPM_TOKEN -R Alexein-AI/sdk`, then paste it when asked.

### C3. Check the version

`integrations/n8n/package.json` `version` is what gets published, and the tag must match it. The commands below
assume 0.3.0, the first release.

### C4. Tag and push

```bash
cd ~/repos/alexein-sdk
git switch main && git pull
git tag n8n-v0.3.0
git push origin n8n-v0.3.0
```

### C5. Watch it

```bash
gh run watch -R Alexein-AI/sdk
```

The workflow runs these steps:

1. Checks the tag matches the version.
2. `npm ci`.
3. `npm test`.
4. `npm run release`, which in GitHub Actions means lint, build, then `npm publish` with provenance.

When it finishes, https://www.npmjs.com/package/@alexein/n8n-nodes-alexein shows the version with a
**Provenance** badge.

If it fails:

| Error                                                            | Fix                                                                                                              |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| "tag ... is not n8n-v<version>"                                  | the tag doesn't match `package.json`. Delete the tag (`git push --delete origin n8n-v0.3.0`), fix, and tag again |
| `E403` or "You do not have permission"                           | the token lacks publish rights on `@alexein`, or 2FA blocked it: make a new token with Bypass 2FA                |
| `E402` or "You must sign up for private packages"                | the package was published as private: check `publishConfig.access` is `public`                                   |
| "provenance ... private repository"                              | the repo is still private: do C1                                                                                 |
| `E409` or "cannot publish over the previously published version" | that version exists already: bump the version                                                                    |

### C6. Switch to tokenless publishing

1. On npmjs.com, open the package > **Settings > Trusted Publisher > Add > GitHub Actions**:
   - Organization or user: `Alexein-AI`
   - Repository: `sdk`
   - Workflow filename: `n8n-publish.yml`
   - Environment: leave empty
2. Delete the token in both places: `gh secret delete NPM_TOKEN -R Alexein-AI/sdk`, and on npmjs.com under
   **Access Tokens**.
3. Optional, safer: under **Settings > Publishing access**, choose "Require two-factor authentication and
   disallow tokens". Trusted publishing keeps working.

Every later release is: bump the version and changelog, merge, tag `n8n-v<version>`, push the tag.

### C7. Run n8n's own check

```bash
npx @n8n/scan-community-package @alexein/n8n-nodes-alexein
```

It should print "has passed all security checks". This is the same scanner n8n runs on submission.

### C8. Submit for n8n Cloud

1. Open https://creators.n8n.io/nodes and sign in.
2. Submit `@alexein/n8n-nodes-alexein`. The text for every field is in the console repository's
   `notes/outreach-n8n.md`, section 1.
3. n8n reviews it. There is no published timeline. Once approved, it appears in n8n Cloud's nodes panel.

### C9. Afterwards

- **The badge:** the n8n integration changes from "Soon" to "Live" in the console repository
  (`lib/site/integrations.ts`, which the app's Integrations pages read).
- **The docs:** `content/docs/(integrations)/integrations/n8n.mdx` in the docs repository says the node is "Soon"
  on npm. Change it to the version just released.
- **The template:** submit it to n8n's library with the text in `notes/outreach-n8n.md`, section 2.
- **The MCP registry:** send the request in section 3, once `api.alexein.ai/v1/mcp` is live with sign-in.

---

## Checklist

- [ ] A1-A4: unit tests, lint and e2e all pass against the local stack
- [ ] A5: credential Test, Add, Search, Open by hand; template imports
- [ ] (optional) B: published from laptop, installed in self-hosted n8n, version bumped
- [ ] C1: repo public
- [ ] C2: `NPM_TOKEN` secret (first publish only)
- [ ] C4-C5: tag pushed, workflow green, Provenance badge on npm
- [ ] C6: trusted publisher added, token deleted
- [ ] C7: scanner passes
- [ ] C8: submitted to creators.n8n.io
- [ ] C9: badge Live and the docs page's opening line updated; template and MCP registry requests sent
