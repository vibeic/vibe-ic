# Making an unchecked landing impossible

`main` was red — `49 failed, 3871 passed` on a clean detached `origin/main`
worktree over a 184-file targeted selection — and nobody saw it. This document
records why that was *possible*, what was measured about the platform, and what
now prevents it.

## The three holes

1. **`gh pr merge` ran no gate.** GitHub Actions is disabled at the **account**
   level (support ticket 4613114, appeal rejected).
2. **`main` was unprotected**, so nothing server-side inspected a push.
3. **Enforcement lived only in a local `pre-push` hook**, and `.git/hooks/` is
   untracked — on the machine where this was written it was **empty**, and
   `core.hooksPath` was unset. A hook that is not installed is not a gate.

A fourth, smaller one: a change under repo-root `tools/` selects only ~15
generic test files, so tests added there ran under nothing automatic.

## What was measured, 2026-08-12

Not assumed — every line here is a command that was run.

| probe | result |
|---|---|
| `gh api repos/vibeic/vibe-ic/actions/permissions` | `{"enabled":false}` |
| forced repo switch to `enabled:true`, pushed a branch with a matching `on: push` workflow | **zero runs in 105 s**; GitHub never even *registered* the workflow |
| `gh api .../actions/workflows` | only GitHub's internal `dynamic/dependabot/update-graph` |
| `gh api repos/vibeic/vibe-ic/branches/main/protection` | `404 Branch not protected` |
| `PUT .../branches/<throwaway>/protection` with an arbitrary required context, `enforce_admins:true` | **accepted** |
| `POST .../statuses/<sha>` | **accepted**, reads back on the commit |

Two conclusions follow, and the second overturns an assumption:

* **A self-hosted runner does not help.** *Scheduling* is the blocked layer, not
  execution. A runner would sit idle forever. The repo switch reading
  `enabled:true` while the account override blocks above it is a trap that has
  already fooled one reader — see `.github/workflows-disabled/README.md`.
* **Branch protection is available**, on a free org plan, because the repo is
  public. That is what makes real prevention — not merely detection — possible.

## The mechanism

```
   open PR / candidate SHA
            │
            ▼
   tools/ci/gatekeeper_status_poller.py        (a machine we own, every 5 min)
            │   runs tools/gatekeeper-land.sh  ← THE SAME GATE A HUMAN RUNS
            ▼
   POST /statuses/<sha>  context=vibe-ic/gatekeeper-land
            │
            ▼
   branch protection on main REQUIRES that context
            │
            ▼
   red or unrun ⇒ GitHub itself refuses the push/merge
```

The poller **never reimplements the gate** — it shells out to
`tools/gatekeeper-land.sh` and only transports the verdict. Two gates that can
disagree is a new lie waiting to happen.

### The verdict is three-valued

A gate that could not **run** is not a gate that **failed**.

| state | meaning |
|---|---|
| `success` | exit 0 **and** tests were observably collected and run |
| `failure` | the gate ran and disagreed — real violations |
| `error` | the gate could not run, or the poller itself broke |

`error` blocks a merge exactly as `failure` does, so fail-closed holds either
way. The distinction only changes what a human is *told* — which matters,
because the first person to see a `failure` that was really a collection death
goes hunting for a bug that does not exist.

Guarded explicitly, each anchored to a real shape:

* `no tests ran` / `INTERNALERROR` / collection errors ⇒ `error`;
* exit 0 with **no** test count ⇒ `error` ("exited 0 but no test ran");
* exit 0 that *also* reports failures ⇒ `error` (contradiction is unmeasured);
* `--cheap-only` success ⇒ `error`, never `success` — a partial measurement must
  not stand in for the full tier.

## Both arms, proven

On throwaway protected branches, before any of this touched `main`:

```
push a commit with NO status
  remote: error: GH006: Protected branch update failed for refs/heads/…
  remote: - Required status check "vibe-ic/gatekeeper-land" is expected.
  ! [remote rejected]                                        REJECTED

post green status, push the SAME SHA
  3febf537..d3ea5ff6                                          ACCEPTED
```

The rejection happened to a repository **admin** with `enforce_admins:true`.

## Your direct-push flow survives

The required status binds to a **SHA**, not to a pull request, so the
2026-06-26 direct-push directive still works — with one extra hop:

```bash
git push origin HEAD:refs/heads/land/$(git rev-parse --short HEAD)
tools/ci/gatekeeper_status_poller.py --sha $(git rev-parse HEAD)
git push origin $(git rev-parse HEAD):main     # accepted once green
```

## Deploying on 8HD-4 (192.168.1.120)

```bash
# on the runner host, as the account the gate should speak as
git clone https://github.com/vibeic/vibe-ic.git ~/vibe-ic     # if absent
gh auth login                                                  # needs repo scope
sudo ~/vibe-ic/tools/ci/install_gatekeeper_poller.sh
```

The installer writes the two machine-specific pieces the unit files no longer
carry -- `/etc/default/gatekeeper-poller` (the checkout to gate, derived from
where the script itself lives) and a `User=` drop-in for the account behind
`sudo` -- then copies the units, reloads, and enables the timer. It refuses
rather than guesses: not a git checkout, no such user, or running as root all
stop it with a named reason.

`--print` shows exactly what it would write, and needs no root:

```bash
tools/ci/install_gatekeeper_poller.sh --print
```

Until v1.12.x the unit files named one developer's account and home directory
in four places, so they could only be installed on that one machine. They no
longer contain either; `tools/tests/test_no_machine_pinned_paths_in_tools.py`
holds that.

Verify one tick by hand before trusting the timer:

```bash
python3 ~/vibe-ic/tools/ci/gatekeeper_status_poller.py --pr <n>
```

Then, once the tree is green, arm it:

```bash
tools/ci/gatekeeper_protect_main.sh on
tools/ci/gatekeeper_protect_main.sh status
```

## What this does NOT close

Anyone with write access can `POST` a green status by hand. This closes the
**accident** path completely — which is what produced a red `main` nobody saw —
and reduces the deliberate path to a single auditable API call. No plan-level
control exists for that on this repo, so it is stated here rather than hidden.

Also: while `main` is red, **every** branch off it is red too, because the
targeted selection carries a smoke floor. That is correct fail-closed behaviour,
and it means protection should be armed *after* the tree is green, not before.
