---
name: dev-release
description: Cut a release of The other door — check main is green, set the version, push the vX.Y.Z tag, watch release.yml build the installers into a draft release, write the release notes, and publish it only when the maintainer says so. Maintainer only. Invoked with /dev-release [X.Y.Z] [pre-release].
---

You are cutting a release of The other door. `docs/releasing.md` is the reference (the checklist before a draft is published); `.github/workflows/release.yml` is what a tag starts. Follow the steps in order and stop where a step says so.

**Repo constants**: `owner: synesenom`, `repo: the-other-door`, `base: main`.

**Arguments**: an optional version `X.Y.Z` (default: the version in `app/package.json`) and an optional `pre-release`.

Every step that changes something outside this checkout (pushing a tag, editing or publishing the release, deleting a tag) is confirmed with the user first, with AskUserQuestion, naming exactly what will happen. A go-ahead covers that one step only.

---

## Step 1: Guard checks

Run these in parallel:

- `gh api repos/synesenom/the-other-door --jq .permissions.admin`: it must be `true`. If not, say "Only the maintainer can release The other door; a fork releases from its own repository" and **stop**.
- `git status --porcelain`: must be empty, else tell the user to commit or stash and **stop**.
- `git fetch origin --tags`, then `git branch --show-current` must be `main` and `git rev-parse HEAD` must equal `git rev-parse origin/main`; else say which and **stop** (offer `git checkout main && git pull`).
- `gh run list --branch main --limit 20 --json workflowName,conclusion,status,headSha`: the newest run of each workflow on `main`'s head commit must be `success` (a workflow that did not run for that commit is fine: its paths did not change). A run still `in_progress` → tell the user and **stop**; a failure → name it with its URL and **stop**.

Then work out the version: the argument, or `node -p "require('./app/package.json').version"`. It must be `X.Y.Z`. `git tag -l vX.Y.Z` and `gh release view vX.Y.Z` must both find nothing; if either does, say so (a draft from an earlier attempt: see Step 4's retry) and **stop**. Find the previous release tag: `git describe --tags --abbrev=0 --match 'v*'` (none = the first release).

## Step 2: The version

If `app/package.json`, `pyproject.toml` and `src/door/version.py` already say `X.Y.Z`, go to Step 3.

Otherwise `main` takes the change through a pull request (the `main` ruleset):

```bash
git checkout -b release/vX.Y.Z
python3 scripts/set_version.py X.Y.Z
git commit -am "release: vX.Y.Z"
```

Then open the PR with `/dev-pr` and tell the user to merge it once CI is green. **Stop here**; when the user says it is merged, run `git checkout main && git pull` and start again at Step 1.

## Step 3: Tag

Ask with AskUserQuestion: "Push the tag vX.Y.Z on <short sha> (<subject>)? It starts release.yml, which builds the installers for macOS (Apple silicon, Intel), Windows and Linux into a draft release only you can see (about 20 minutes)." Options: "Push the tag", "Not now". On "Not now", **stop**.

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

## Step 4: Watch the build

Find the run (it can take a few seconds to appear): `gh run list --workflow release.yml --branch vX.Y.Z --limit 1 --json databaseId,url`. Then watch it in the background, `gh run watch <id> --exit-status`, and wait for its notification; do not poll.

- **Green**: go to Step 5.
- **Red**: `gh run view <id> --log-failed | tail -80`, say which job failed and why in a few lines. Do not fix it on the tag. The fix goes to `main` through a PR; then a retry needs the draft and the tag gone: ask before `gh release delete vX.Y.Z --yes --cleanup-tag`, then start again at Step 1. A job that failed for a runner reason (a timeout, a download) can be re-run instead: ask, then `gh run rerun <id> --failed`.

## Step 5: The draft

`gh release view vX.Y.Z --json url,isDraft,assets --jq '{url, isDraft, assets: [.assets[].name]}'`: it must be a draft holding `the-other-door-X.Y.Z-mac-arm64.dmg`, `-mac-x64.dmg`, `-windows-x64.exe`, `-linux-x64.AppImage` and a `.deb`. Name anything missing.

Write the release notes into `thoughts/release/vX.Y.Z.md` (gitignored), for the people who will install it, not for developers:

- one line on what The other door is, on the first release only;
- what changed for a user since the previous tag, a few bullets, from `gh pr list --state merged --search "merged:>=<previous tag's date>" --limit 100 --json number,title` and `git log <previous>..vX.Y.Z --no-merges --oneline` (leave out Dependabot, tests, CI and internal refactors);
- **Install**: which file is for which computer (the table in `docs/releasing.md`), that you need a Claude Pro or Max plan, and, while the builds are unsigned (no signing secrets in `release.yml`'s run), that macOS and Windows ask once the first time, linking `docs/manual-app.md#opening-it-on-macos-the-first-time`.

Show the notes and ask whether to put them on the draft; on yes, `gh release edit vX.Y.Z --notes-file thoughts/release/vX.Y.Z.md`.

## Step 6: Publish

Point the user at the draft URL and at `docs/releasing.md`'s checklist: install each installer on a clean machine first (`npm run test:install` in `app/` with `DOOR_INSTALLER=<file>` covers most of it). Then ask with AskUserQuestion: "Publish vX.Y.Z?" Options:

- "Publish as the latest release": the README's download link and the apps' update check (`DOOR_UPDATE_FEED`, GitHub's `releases/latest`) find it. `gh release edit vX.Y.Z --draft=false --latest`
- "Publish as a pre-release": public on the releases page, but `releases/latest` skips it, so the README link and the update check don't see it; share the release URL instead. `gh release edit vX.Y.Z --draft=false --prerelease`
- "Keep it a draft": nothing changes; the user publishes later from the release page or with this skill's Step 6.

Recommend the pre-release when the argument said `pre-release`, else the latest release. Never publish without this answer.

## Step 7: Report

```
Release:   vX.Y.Z (draft | pre-release | latest)
Tag:       <short sha> <subject>
Build:     <run url>, <minutes> min
Installers: <n>/5
URL:       <release url>
```

Then what is left of `docs/releasing.md`'s checklist for this release, if anything.
