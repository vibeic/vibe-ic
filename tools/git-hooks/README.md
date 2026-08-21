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
| `pre-push` | before a push reaches the remote | the same token in **any** commit message in the range being pushed, plus the cheap governance gates and — pushing to `main` — a commit with no matching `gatekeeper-land.sh` stamp |

## A HOOK CANNOT SEE A MERGE. Use `tools/gatekeeper-verify-merge.sh`.

`pre-push` is the only enforced gate on what reaches `main`, and it is enforced
**on `git push`**. **`gh pr merge --squash` creates the commit SERVER-SIDE:
nothing is pushed from a local clone, so no hook fires and
`tools/gatekeeper-land.sh` never runs.** Merging is not pushing.

There is no server-side fallback and none can be created — measured 2026-08-12
(vibe-ic#1019): Actions is disabled at the **account** level
(`actions/permissions` → `{"enabled": false}`, appeal rejected; a self-hosted
runner does not help because *scheduling* is the blocked layer), and `main`
returns `404 Branch not protected`, so there is no required status check to
satisfy. That is not a gap in this file — it is the reason the merge path needs
its own tool:

```bash
tools/gatekeeper-verify-merge.sh <pr-number> --json /tmp/v.json   # MUST exit 0
gh pr merge <pr-number> --squash
tools/gatekeeper-verify-merge.sh --reassert /tmp/v.json           # if time passed
```

It rebases the PR onto the current base in a throwaway worktree, proves that
tree is the tree the merge would produce, and runs the same
`gatekeeper-land.sh` the push path runs. What went unnoticed without it:
`test_matrix_d2_falsifiable.py` stayed RED on `main` across five merges.

Proving the replay IS the merge tree needs `git merge-tree --write-tree`, i.e.
**git >= 2.38** — which four of six hosts here, the orchestrator included, do
not have. On those the script falls back to verifying the rebase replay and
says so, in the printed verdict and in the JSON
(`"verification_tier": "rebase-replay"`, `"tier_degraded": true`). Every other
refusal reason is unchanged; only that one cross-check is dropped.

Both delegate to
`vibe-ic-marketplace/plugins/vibe-ic/programs/commit_msg_nda_check.py`.

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
