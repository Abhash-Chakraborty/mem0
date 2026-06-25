# Keeping this fork in sync with upstream

This fork (`Abhash-Chakraborty/mem0`) tracks `mem0ai/mem0` while carrying its own
self-hosted changes (the `server/` stack, custom CI, removed cloud UI, etc.).
This document explains how the automated sync works, why it previously failed,
and how to resolve conflicts — including with `git rerere`.

## Branches

| Branch | Role |
|--------|------|
| `abhash-main` | Deploy trunk. Builds/pushes the Dokploy image (`server/**` pushes). |
| `integration/self-hosted-overhaul` | Staging branch for the self-hosted overhaul. |
| `main` | Plain mirror of upstream — kept only as a reference point. |
| `staging/upstream-sync-<date>` | Branch the sync workflow creates off `abhash-main`, merges upstream into, and opens a PR from (base `abhash-main`). |
| `upstream/main` (remote) | `mem0ai/mem0` `main`. The thing we sync from. |

## Why the sync action was not running

GitHub only fires `schedule:` and `workflow_dispatch:` triggers from the copy of
the workflow that lives on the repository's **default branch**. The default
branch was `main` (a plain upstream mirror) which does **not** contain
`upstream-sync.yml`, so the workflow was never scheduled and could not be
dispatched. `push:`-triggered workflows (like `server-deploy.yml`) are unaffected
because they run from the pushed branch — which is why deploys worked but sync
did not.

**Required one-time fix (pick one):**

1. **Recommended:** set the repository default branch to `abhash-main`
   (Settings > General > Default branch, or
   `gh api -X PATCH repos/Abhash-Chakraborty/mem0 -f default_branch=abhash-main`).
   All of this fork's workflows live there.
2. Or copy `upstream-sync.yml` onto `main` and keep `main` as default.

Also enable **Settings > Actions > General > "Allow GitHub Actions to create and
approve pull requests"**, otherwise `gh pr create` in the workflow cannot open
the PR (the run will push the branch but skip the PR with a warning).

## How the sync workflow now works

`.github/workflows/upstream-sync.yml` runs weekly (and on demand). For each run it:

1. Checks out `BASE_BRANCH` (default `abhash-main`; selectable when run manually).
2. Enables `rerere` and seeds it from the committed cache in `.github/sync/rr-cache`.
3. `git merge`es `upstream/main` into a fresh `staging/upstream-sync-<date>`
   branch (merge, **not** rebase — the published history is never rewritten).
4. Re-applies the fork's intentional deletions from
   [`removed-paths.txt`](./removed-paths.txt) so removed files/folders never
   silently reappear.
5. Persists any new `rerere` resolutions back into `.github/sync/rr-cache`.
6. Opens a normal PR if everything resolved, or a **draft** PR with conflict
   markers committed if manual resolution is still needed.

### The "deleted folder keeps coming back" problem

When the fork deletes a file and upstream later edits that same file, a plain
merge produces a *modify/delete* conflict and it is easy to accidentally re-add
the file. Worse, if upstream adds brand-new files under a path the fork dropped,
they appear silently. The fix is deterministic: list every path the fork drops in
`removed-paths.txt`. The workflow runs `git rm -r --ignore-unmatch` on each entry
after every merge, so those paths are guaranteed to stay gone. To bring something
back, just remove its line from that file.

## Resolving conflicts with `git rerere`

`rerere` = **RE**use **RE**corded **RE**solution. Git remembers how you resolved a
conflict and replays the same resolution automatically the next time the *same*
conflict appears. This is ideal for a long-lived fork that re-hits the same
customization conflicts (e.g. `server/main.py`) on every upstream sync.

### One-time local setup

```bash
git config --global rerere.enabled true
git config --global rerere.autoupdate true   # auto-stage replayed resolutions
```

### Resolving a sync PR locally

```bash
git fetch origin
git checkout staging/upstream-sync-<date>

# If it was a clean draft snapshot, redo the merge locally to get live markers:
#   git merge upstream/main

# 1. See what conflicts:
git status
git rerere status        # files rerere is tracking

# 2. Edit each conflicted file: remove <<<<<<<, =======, >>>>>>> and keep the
#    correct combined result. (Tip: `git diff` shows just the conflict hunks.)

# 3. Stage and finish. With rerere on, the resolution is RECORDED now.
git add -A
git commit
git push

# 4. Commit the learned resolution so CI replays it next time too:
git add .github/sync/rr-cache && git commit -m "chore(sync): record rerere resolution" && git push
```

### Handy `rerere` commands

| Command | What it does |
|---------|--------------|
| `git rerere status` | List files with a recorded pre-image being tracked. |
| `git rerere diff` | Show how rerere is resolving vs. the conflict. |
| `git rerere remaining` | List conflicts rerere has **not** resolved (need you). |
| `git rerere forget <path>` | Drop a wrong recorded resolution so you can redo it. |
| `git checkout --conflict=merge <file>` | Re-expose the conflict markers to redo a resolution. |

### If rerere replayed a WRONG resolution

```bash
git rerere forget path/to/file       # forget the bad recorded resolution
git checkout --conflict=merge path/to/file   # bring the markers back
# resolve correctly, then:
git add path/to/file
```

## Manual sync (until the default-branch fix is applied)

```bash
git fetch upstream
git switch abhash-main
git switch -c staging/upstream-sync-$(date +%Y%m%d)
git merge upstream/main
# resolve conflicts (rerere helps), re-apply removed paths:
while read -r p; do [ -n "$p" ] && [[ "$p" != \#* ]] && git rm -rq --ignore-unmatch -- "$p"; done < .github/sync/removed-paths.txt
git commit
git push -u origin HEAD
gh pr create --base abhash-main --fill
```
