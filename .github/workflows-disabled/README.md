# Disabled GitHub Actions workflows

These two workflows are **deliberately disabled**, not broken and not abandoned.

GitHub disabled Actions at the **account** level:

```
$ gh workflow run ci.yml --repo vibeic/vibe-ic --ref main
HTTP 422: Actions has been disabled for this user.
```

The appeal (support ticket 4613114) was rejected. Neither workflow ever ran once
— twelve pushes to `main` produced zero runs while `actions/permissions` kept
reporting `enabled:true`, because that endpoint reports the *repository* switch
and the account override sits above it. A self-hosted runner does not help:
**scheduling** is the blocked layer, not execution.

Measured scope of the block: push, issues, PRs, merges, releases and ghcr.io
packages all work. Only Actions is refused.

## What runs these checks now

`tools/gatekeeper-land.sh`, in two tiers:

* **cheap** — also run by `tools/git-hooks/pre-push` on EVERY push, so they are
  enforced rather than remembered: NDA message + content scans, version
  monotonicity, marketplace/plugin version sync, agent check-in scope, benchmark
  evidence structure, git prohibition guard, one-commit landing.
* **full** — `tools/ci/repo_hygiene_gates.sh` (37 gates) and
  `plugin_full_audit.py`. Minutes each, so they are not in the hook. On success
  the script writes the verified commit SHA to `.git/gatekeeper-stamp`, and the
  pre-push hook REFUSES any push whose commit does not match that stamp. Amend
  or add a commit and the stamp stops matching. That makes the expensive tier
  enforced without putting an eleven-minute wait in front of every push — a hook
  slow enough to be bypassed is a hook that gets bypassed.

Install the hooks (they do nothing until installed; `.git/hooks/` is untracked):

```
tools/install-git-hooks.sh
```

## If Actions is ever restored

```
gh workflow run ci.yml --repo vibeic/vibe-ic --ref main
```

A 422 means still blocked. If it dispatches, move these two files back to
`.github/workflows/` and drop the `.disabled` suffix. Keep the local path
regardless — it is faster than a hosted runner and it is what gates the tree
today.
