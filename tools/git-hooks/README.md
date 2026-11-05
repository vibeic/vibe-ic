# Tracked git hooks

`.git/hooks/` is not tracked by git, so these hooks do nothing until installed.

## Install (one line)

```bash
tools/install-git-hooks.sh
```

Re-running is safe (idempotent). Pass `--force` to replace a pre-existing hook
of the same name. The installer creates **symlinks**, so a later `git pull` that
improves a hook takes effect with no re-install.

## The hooks

| Hook | When it runs | What it blocks |
|------|--------------|----------------|
| `commit-msg` | as a commit is created | an NDA foundry / SKU / process token in the commit **message** |
| `pre-push` | before a push reaches the remote | the same token in **any** commit message in the range being pushed, plus the cheap governance gates, a **version bump in the branch's own delta** (see below), and — pushing to `main` — a commit with no matching `gatekeeper-land.sh` stamp |

## A branch may not carry its own version bump (vibe-ic#2096)

The version is assigned **at landing**, by the lander. Running the plugin test
suite WRITES the six version-bearing files — `plugin.json`, both
`marketplace.json`s and the three shipped READMEs — and `git add -A` then sweeps
them into the commit. A lane measured exactly that on 2026-09-07 and caught it by
hand; nothing in the hook or the landing gate would have.

`pre-push` therefore runs
`vibe-ic-marketplace/plugins/vibe-ic/programs/branch_version_bump_guard.py`,
which refuses a push whose HEAD declares a version value the **merge base with
`main`** did not declare at that site, and names every file:

```
pre-push: FAILED — branch carries no version bump (the lander assigns it)
    [FAIL] vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json
        x plugin.json version: this branch declares 1.18.53 where cf316de71 declares 1.18.52
    ...
    x restore: git checkout cf316de71 -- <file>
```

`refs/heads/main` and the landing branch (`refs/heads/land/<short-sha>`) are
exempt — they carry the lander's own assignment. Editing a README **without**
touching its version claim is not refused, and neither is a branch cut from an
older `main`: the comparison is against the fork point, not `main`'s tip.

## A HOOK CANNOT SEE A MERGE.

`pre-push` is the only enforced gate on what reaches `main`, and it is enforced
**on `git push`**. **`gh pr merge --squash` creates the commit SERVER-SIDE:
nothing is pushed from a local clone, so no hook fires and
`tools/gatekeeper-land.sh` never runs.** Merging is not pushing.

There is no server-side fallback and none can be created — measured 2026-08-12
(vibe-ic#1019): Actions is disabled at the **account** level
(`actions/permissions` → `{"enabled": false}`, appeal rejected; a self-hosted
runner does not help because *scheduling* is the blocked layer), and `main`
returns `404 Branch not protected`, so there is no required status check to
satisfy.

## Why the message surface needs its own guard

`source_chip_agnostic_check.py` scans **source files** only. A commit whose
*message* names the commercial foundry therefore passed every existing gate — and
one really did land on `origin/main` *after* the full-history NDA rewrite. A
commit message is a permanent, publicly mirrored artifact (`git log`, the GitHub
UI, release notes), so a token there leaks exactly as badly as one in a `.py`
file.

`commit-msg` stops it at authoring time; `pre-push` catches whatever arrives by
another route — `--no-verify`, a rebase or amend that reuses an old message, a
cherry-pick, a squash, or a tool that never ran the hook.

## Manual scan

```bash
# what am I about to push?
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/commit_msg_nda_check.py \
    --rev-range origin/main..HEAD

# audit the whole published history
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/commit_msg_nda_check.py \
    --rev-range origin/main
```

The checker never prints the literal token — a finding is reported as
`<NDA-TOKEN:<role>>` plus the surrounding words, so its own output (and its
`--json` report) is safe to paste into a CI log or an issue.

## If a message is blocked

Reword it to the generic term — "commercial PDK", "commercial foundry", "the
foundry deck":

```bash
git commit --amend        # the commit being written
git rebase -i <base>      # an older commit: mark it `reword`
```
