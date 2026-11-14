---
name: dev-release
description: Cut a release of The other door — check main is green, set the version, push the vX.Y.Z tag, watch release.yml build the installers into a draft release, write the release notes, and publish it only when the maintainer says so. Maintainer only. Invoked with /dev-release [X.Y.Z] [pre-release].
---

You are cutting a release of The other door. `docs/releasing.md` is the reference (the checklist before a draft is published); `.github/workflows/release.yml` is what a tag starts. Follow the steps in order and stop where a step says so.

**Repo constants**: `owner: synesenom`, `repo: the-other-door`, `base: main`.

**Arguments**: an optional version `X.Y.Z` (default: the one Step 1 suggests from the PRs merged since the last release) and an optional `pre-release`.

Every step that changes something outside this checkout (pushing a tag, editing or publishing the release, deleting a tag) is confirmed with the user first, with AskUserQuestion, naming exactly what will happen. A go-ahead covers that one step only.

---

## Step 1: Guard checks

Run these in parallel:

- `gh api repos/synesenom/the-other-door --jq .permissions.admin`: it must be `true`. If not, say "Only the maintainer can release The other door; a fork releases from its own repository" and **stop**.
- `git status --porcelain`: must be empty, else tell the user to commit or stash and **stop**.
- `git fetch origin --tags`, then `git branch --show-current` must be `main` and `git rev-parse HEAD` must equal `git rev-parse origin/main`; else say which and **stop** (offer `git checkout main && git pull`).
- `gh run list --branch main --limit 20 --json workflowName,conclusion,status,headSha`: the newest run of each workflow on `main`'s head commit must be `success` (a workflow that did not run for that commit is fine: its paths did not change). A run still `in_progress` → tell the user and **stop**; a failure → name it with its URL and **stop**.

Then run everything a release needs locally, in the background, and wait for it: `./scripts/run-test.sh --release` (the offline suite, the app's tests with every journey, and the skill tests, which CI cannot run: the real model runs /onboard against the app's test world on the plan; some plan usage). It ends with a PASS/FAIL/SKIP line per step. A FAIL → show that step's failures (for the skills, the transcript path it prints) and **stop**; a skipped skill test (claude not signed in, the app's packages missing) → say why and ask whether to go on without it.

Find the previous release tag: `git describe --tags --abbrev=0 --match 'v*'` (none = the first release).

### What is in it

Gather every PR merged since that tag:

```bash
gh pr list --state merged --base main --limit 200 \
  --search "merged:>=$(git log -1 --format=%cI <previous tag>)" \
  --json number,title,body,headRefName,mergedAt,mergeCommit,closingIssuesReferences
```

Keep only the PRs whose `mergeCommit.oid` is in this release: `git merge-base --is-ancestor <oid> HEAD` succeeds and `git merge-base --is-ancestor <oid> <previous tag>` fails (a PR merged the same day before the tag is not counted twice; this works for merge and squash commits alike). Also list the commits that came without a PR: `git log <previous tag>..HEAD --no-merges --format='%h %s'` minus the PRs' own.

Sort each PR into one kind. Use its body's **Type** line, else its branch prefix (`feat/`, `fix/`, `change/`, `docs/`; `refactor/`, `test/`, `ci/`, `chore/`, `dependabot/`, `release/` are internal), else read its title and body and judge:

- **Added**: something a user can do now that they could not before (`feat`).
- **Changed**: something that works differently in a way a user notices (`change`, or a `feat` that reworks an existing thing).
- **Fixed**: a bug a user could have hit (`fix`).
- **Removed**: anything the PR's "Removed or renamed" section names, whatever its type: a removed command, option, config key, screen or behaviour is always listed, with what replaces it.
- **Internal**: refactors, tests, CI, tooling, dependency bumps: counted, not described.

When a PR's body has no "For users" section (an older PR), read its diff (`gh pr diff <N>`) before you judge it; a PR you still cannot place goes under the kind its title suggests, marked `(?)` in the notes for the maintainer.

### The version

Suggest the version from what is in it, against the previous tag's `X.Y.Z` (while the version is `0.y.z`, nothing is promised between releases):

- anything **Added**, **Changed** or **Removed** → the next minor, `X.(Y+1).0`;
- only **Fixed** and **Internal** → the next patch, `X.Y.(Z+1)`;
- nothing but **Internal** → say there is nothing for users to release and ask whether to go on.

If the argument named a version, use it, but say so when it disagrees with the suggestion. Otherwise ask with AskUserQuestion, the suggestion first with a one-line reason ("3 added, 2 fixed"), the other bump second. The version must be `X.Y.Z`. `git tag -l vX.Y.Z` and `gh release view vX.Y.Z` must both find nothing; if either does, say so (a draft from an earlier attempt: see Step 4's retry) and **stop**.

### The data upgrade

A tester's `profile/` and `jobs/` written by the previous release must open in this one (#56). Data is upgraded only within a major version: on a major bump (`X` of `X.Y.Z` goes up) the agent writes no step but empties the step lists, and the notes say the previous major's data is not opened. Spawn the `data-migrator` agent with the previous tag, the new version and the PRs kept above (number, title, their "Removed or renamed" sections), and wait for its report:

- **"no step needed"**: keep its item-by-item list for the notes' maintainer summary and go on.
- **a PR**: tell the user to merge it once CI is green and **stop**. When it is merged, start again at Step 1 (the step's PR is now one of the release's). Keep its "Release note line" for Step 5.

Then the release test of #57 must pass (the saved data of every earlier release opens in this one); it runs in `./scripts/run-test.sh --release` once `tests/data_versions/` exists.

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

Write the release notes into `thoughts/release/vX.Y.Z.md` (gitignored), for the people who will install it, not for developers. They are a changelog, built from Step 1's sorted PRs:

```markdown
<one line on what The other door is: the first release only>

<one or two sentences on the release as a whole: its main thing, if it has one>

<the data-migrator's "Release note line", when it wrote a step: "Your data is upgraded on first start: …">

## Added
- <one bullet per user-facing change, taken from the PR's "For users" lines, in a user's words: no module, tool or file names> (#<PR>)

## Changed
- ...

## Fixed
- <what went wrong for a user, now right> (#<PR>)

## Removed
- <what is gone and what to use instead> (#<PR>)

<n> internal changes (tests, CI, dependencies, refactoring) are not listed. Full list: <compare URL, https://github.com/synesenom/the-other-door/compare/<previous tag>...vX.Y.Z>

## Install
...
```

- Leave out a section with nothing in it. Several PRs that make one change for a user (a feature and its follow-up fixes in the same release) are one bullet citing all of them; a fix to something new in this same release is not a **Fixed** bullet.
- Order each section by how much a user will notice, most first.
- **Install**: which file is for which computer (the table in `docs/releasing.md`), that you need a Claude Pro or Max plan, and, while the builds are unsigned (no signing secrets in `release.yml`'s run), that macOS and Windows ask once the first time, linking `docs/manual-app.md#opening-it-on-macos-the-first-time`.

Show the notes and ask whether to put them on the draft; on yes, `gh release edit vX.Y.Z --notes-file thoughts/release/vX.Y.Z.md`.

## Step 6: Publish

Point the user at the draft URL and at `docs/releasing.md`'s checklist: install each installer on a clean machine first (`DOOR_INSTALLER=<the downloaded file> ./scripts/run-test.sh --release` adds the install test to the rest; `npm run test:install` in `app/` runs it alone). Then ask with AskUserQuestion: "Publish vX.Y.Z?" Options:

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
