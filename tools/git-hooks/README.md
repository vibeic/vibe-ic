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
| `pre-push` | before a push reaches the remote | the same token in **any** commit message in the range being pushed |

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
