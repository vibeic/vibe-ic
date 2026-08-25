---
name: gatekeeper-loop
description: Infinite-loop single gatekeeper agent that OWNS main. Under the 2026-06-26 owner directive (direct-push, supersedes the 2026-06-17 PR-method) the maintainer ships its OWN fixes by direct commit + `git push origin main` with this same gate sequence applied PRE-PUSH (gatekeeper_review MERGE_OK → Step-2.7 → gatekeeper_assign_version --write → push); the PR-merge-queue machinery here is RETAINED for any externally-filed PR and the gatekeeper is the SOLE merger of those. Invoke as a cron prompt; each tick polls open non-draft PRs against main (poll_prs.py), runs the MACHINE gates (gatekeeper_review.py — required status checks, cadence-aware) on base=origin/main head=PR-branch, and on green runs the ONE irreducible agent gate (Step-2.7 adversarial review). Machine-red OR a reproducible HIGH agent finding -> `gh pr review --request-changes` with a 繁中 5-section comment; otherwise the PR ENQUEUES to a SERIALIZED merge queue guarded by a repo-level .merge.lock — rebase onto current origin/main, RE-RUN required checks on the rebased tree (catches semantic conflicts a 3-way merge misses), ASSIGN the version (authoring PRs are VERSION-LESS — the gatekeeper alone assigns the next strictly-monotonic version at merge via gatekeeper_assign_version.py, so two in-flight PRs can't collide; then re-run the checks WITHOUT --version-by-gatekeeper to ENFORCE the bump + cadence-correct suite), squash-merge (one PR = one squash commit = one gatekeeper-assigned version bump, honoring one-version-per-push), release lock, next. The gatekeeper MAY be the same identity as the PR author and MAY merge its own authored PRs — quality is guaranteed by the GATES (machine required checks + Step-2.7 + the serialized re-test-on-rebase merge queue), not by identity separation. Hard rules: NEVER force/--no-verify/--admin/bypass branch-protection, squash-only, and a documented break-glass path exists so a PR that FIXES a wedged gate cannot deadlock the queue. STOP CONDITION = healthy idle when no open PR; never self-terminate.
---


<!-- WAVE_76_CHIP_AGNOSTIC_BANNER -->

> **Case-study notation.** This skill uses `PR-A` / `branch-A` as the
> canonical example PR — substitute the real PR number and branch. The
> rules themselves are chip-AGNOSTIC and apply to any PR against `main`,
> independent of which IC / vendor / SKU the PR touches. When you adopt
> this skill, swap `PR-A` → `#<your PR number>` and `branch-A` →
> `<your head ref>`; the structural gates and the merge-queue protocol
> do not depend on those values.

# Gatekeeper Loop — Single-Owner PR-Merge Loop for `main`

## Purpose

> **DOCTRINE NOTE (2026-06-26 owner directive — STANDING preference; supersedes
> the 2026-06-17 PR-method).** The maintainer now ships its OWN fixes by **direct
> push** to `main` (direct commit + `git push origin main`, NO `gh pr create` —
> see `vibe-ic:core-agent-loop` §Step 3). The gatekeeper's **gate SEQUENCE is
> unchanged and still authoritative** — it is just applied PRE-PUSH on the main
> checkout (drive `gatekeeper_review.py` to MERGE_OK → Step-2.7 on any
> guard/transform diff → `gatekeeper_assign_version.py --write` → `git push`)
> instead of on a PR branch. The **PR-merge-queue machinery in this skill is
> RETAINED** for any PR filed from ELSEWHERE (an external contributor, or a legacy
> in-flight branch): such a PR is still gated + version-assigned + squash-merged
> exactly as below. Doctrine history (so the flip-flop is legible): direct-push
> through v1.1.5 → PR-method 2026-06-17 → direct-push again 2026-06-26; the gates
> are retained in every era, only the landing ceremony changed.

> **Two-layer framing.** The maintainer's own direct-push fixes are **Layer 2**
> (the internal improvement-phase shortcut). The PR-merge-queue machinery in this
> skill is **Layer 1** — the public contribution model: an external contributor
> files a **backlog** (a report) or a **PR** (a fix), and you are the sole merger
> of those PRs. Both layers cross the identical gate sequence; only Layer-1 adds
> the PR ceremony. External contributors never push to `main`.

The gatekeeper is the **review-gate-and-merge** half of the Vibe-IC
contribution model. Where `core-agent-loop` is an issue-**fix** loop
(poll open issues → ship a fix → close), the gatekeeper is a PR-**merge**
loop (poll open PRs → gate them → squash-merge the green ones) for any
EXTERNALLY-filed PR, AND the pre-push gate authority for the maintainer's
own direct-push fixes. It is the **single agent that owns `main`** and the
**sole party allowed to merge** an external PR.
Centralising the merge authority in one looped identity is what makes the
contribution model trustworthy: every PR — including one the gatekeeper
authored itself — passes through the SAME machine gates, the SAME one
agent gate (Step-2.7), and the SAME serialized re-test-on-rebase merge
queue before it lands. The gate is the quality guarantee, not a separation
of author from approver: a single identity MAY both author and merge,
because nothing lands without surviving the gates on the rebased tree.

The loop is **infinite** and **stateless across ticks** (all state lives
in git + GitHub — the PR's open/merged/closed state, its review state,
its required-check statuses, the `.merge.lock` file). Every cron wake-up
is a fresh, independent tick:

1. **poll** open, non-draft PRs against `main` (`poll_prs.py`).
2. for each PR: run the **machine gates** (`gatekeeper_review.py`).
   Any machine gate red → `request-changes` with the failing program
   output, in a 繁中 5-section comment; continue to the next PR.
3. machine-green → run the **one agent gate** (Step-2.7 adversarial
   review). Only a **reproducible HIGH** finding blocks → request-changes;
   continue.
4. green + no reproducible HIGH → **enqueue to the serialized merge
   queue**: acquire `.merge.lock`, rebase onto current `origin/main`,
   **re-run** the required checks on the rebased tree, squash-merge,
   release the lock, next.

The loop is **chip-AGNOSTIC**: every gate and queue rule reads generic PR
metadata + program verdicts; nothing references `PR-A`, any IC name,
`Vendor`, or any SKU as control logic.

## The machine-vs-agent-judgment split (the central doctrine)

This is the load-bearing idea, and it mirrors the rest of the plugin's
"program-first, agent-only-on-failure" doctrine:

| Layer | What it is | How it runs | Who/what decides |
|-------|------------|-------------|------------------|
| **Machine gates** | The **required status checks** — the full deterministic gate set (`gatekeeper_review.py`: the plugin test suite the CI way, `source_chip_agnostic_check.py`, `marketplace_version_sync_check.py`, `version_bump_monotonic_check.py`, `git_prohibition_guard.py`, `full_suite_run_check.py`, the per-step compliance checkers, …) | DETERMINISTICALLY, cadence-aware (see §Cadence) | a PROGRAM exit code — no LLM |
| **The one agent gate** | **Step-2.7 adversarial review** — the *irreducible* judgement: General-not-overfit / §4.05 no-leak / root-cause-not-bypass | the gatekeeper agent reads the diff and tries to BREAK it | an LLM, but ONLY blocks on a **reproducible HIGH** |

Everything that **can** reduce to a program **is** a machine gate; the
agent gate is the single residue that cannot. The poll itself
(`poll_prs.py`) is deterministic too — it enumerates candidates and makes
**no** merge decision. Judgement enters the loop in exactly one place:
Step-2.7. Anywhere else, "the agent decided" is a smell.

## The four-step loop

### Step 1 — poll

Run **before** any other action, deterministically:

```bash
python3 plugins/vibe-ic/skills/gatekeeper-loop/programs/poll_prs.py
```

The program lists every open, **non-draft** PR against `main`,
**newest-first** (highest PR number first). Exit codes are the cron
driver's signal:

| rc | Meaning | Gatekeeper action |
|----|---------|-------------------|
| 0  | No actionable PRs | Output `(no actionable PRs)` and idle this tick (healthy idle — see §STOP CONDITION) |
| 1  | ≥1 actionable | Process each PR listed, newest-first |
| 2  | I/O / auth error | Log + exit; retry next tick (do NOT treat as actionable) |

One rule: **actionable = ANY open, non-draft PR targeting `main`.** A
draft PR is the author still declaring "not ready" — excluded (the author
has not asked for the gate). No label gating, no comment classifier. The
poll surfaces `mergeable` / `mergeStateStatus` / `labels` as **advisory
context only** — it never filters on them. A PR GitHub currently reports
`CONFLICTING` is **still** actionable, because the gatekeeper must eject
it back to the author; silently dropping it from the poll would **wedge**
the PR with no path forward (a §4.05 leak at the poll layer — the poll
must not mask a PR that needs the gate to say "fix your branch").

### Step 2 — machine gates (required status checks)

For each actionable PR, run the deterministic gate aggregator against
`base=origin/main`, `head=<the PR branch>`:

```bash
git fetch origin
python3 plugins/vibe-ic/skills/gatekeeper-loop/programs/gatekeeper_review.py \
    --repo <owner/repo> --pr <num> --base origin/main --head <headRef>
```

`gatekeeper_review.py` is the **machine-gate aggregator** — it checks out
the PR head against current `origin/main`, runs the required status checks
**cadence-aware** (§Cadence), and returns:

- **exit 0** — all required checks green → proceed to Step 2.7.
- **exit 1** — ≥1 required check RED → the gatekeeper **request-changes**.

On a RED, request changes with the **verbatim failing program output**,
in a 繁體中文 5-section comment (see §Comment shape), then **continue**
to the next PR — do NOT block the queue on a red PR:

```bash
gh pr review <num> --request-changes --body-file <comment_file.md>
```

> **why this is a program, not judgement:** "did the suite pass", "is the
> version monotonically bumped", "is the source chip-agnostic" are all
> exit-code questions. No LLM reads them. The gatekeeper only *relays*
> the failing output into the review.

### Step 2.7 — the one agent gate (adversarial review)

When **and only when** the machine gates are green, run the irreducible
agent-judgment gate on the PR diff. This is the Step-2.7 adversarial
review doctrine carried over from `core-agent-loop` — **try to BREAK the
change, do not validate it** — with three concrete attack lenses:

1. **General-not-overfit** — does the change encode a chip / vendor / SKU
   / benchmark-name literal as *logic* (vs the chip-agnostic deny-list /
   structural form)? A green `source_chip_agnostic_check.py` catches the
   *known* deny-list tokens; the agent gate catches a *novel* overfit the
   deny-list hasn't learned yet (e.g. a magic constant tuned to one
   golden file, a regex that only matches the motivating example).
2. **§4.05 no-leak** — does a relaxation / new SKIP / widened guard make a
   gate that was BLOCKING a real defect now PASS it? A relaxation must
   never mask a real defect. Re-derive: what shape did this gate block
   before, and does the diff let that shape through now?
3. **Root-cause-not-bypass** — does the change fix the cause, or
   `--no-verify` / defer / partial / silently-swallow it? A bypass that
   makes the symptom disappear without removing the cause is a HIGH.

Spawn independent adversarial reviewers (e.g. `codex-adversarial-review`)
against the PR diff with these lenses. **Only a finding the reviewer can
REPRODUCE blocks.** A speculative "this might…" without a reproduction is
NOT a block — it is at most a review comment. On a reproducible HIGH,
`request-changes` with the reproduction in the 繁中 comment, then
continue. No reproducible HIGH → the PR is **mergeable**, proceed to
Step 2.9.

> **why_not_bucket_a (the judgment residual):** whether a regex is
> "general" or "tuned to one example", whether a widened guard "masks a
> real defect", and whether a diff "fixes the cause or hides the symptom"
> all require reading the change's INTENT against the spec — open-ended
> reading no regex settles. The *programmable* half (the known
> deny-list, the version invariants, the full-suite gate) is already in
> the machine gates; Step-2.7 is the single LLM residue.

### Step 2.9 — serialized merge queue (the lock + rebase + re-run)

A green PR does **not** merge immediately. It **enqueues** to a
**serialized merge queue**: at most one PR merges at a time, repo-wide,
so two green PRs can't both rebase-and-merge against the same base and
land a **semantic conflict** that neither one's checks saw. Serialise
with a repo-level `.merge.lock` reusing the `_runner_lock.py` PID-lock
pattern (the same single-driver mechanism the one-shot runners use):

```python
import sys
sys.path.insert(0, "plugins/vibe-ic/programs")
import _runner_lock

# repo root is the "project" the lock keys on; runner_name names the queue.
lock = _runner_lock.acquire(repo_root, runner_name="gatekeeper-merge-queue")
if lock is None:
    # Another gatekeeper instance holds the queue (CONCURRENT_RUN_REFUSED
    # was printed, naming the live holder pid). There must only ever be
    # ONE gatekeeper, so this means a previous tick is still mid-merge —
    # back off and retry this PR next tick. NEVER force the lock.
    sys.exit(0)
try:
    #   1. git fetch origin
    #   2. rebase the PR branch onto CURRENT origin/main (not the base it
    #      was opened against — the queue may have moved main since)
    #   3. RE-RUN the required checks on the REBASED tree with
    #      --version-by-gatekeeper (the PR is VERSION-LESS — the version gate
    #      DEFERS): gatekeeper_review.py --base origin/main --head <branch>
    #      --role <author-role> --version-by-gatekeeper. A 3-way merge can be
    #      clean yet the rebased code semantically conflict (e.g. a function
    #      this PR calls was renamed by a PR that merged five minutes ago);
    #      only a re-run on the rebased tree catches it.
    #   3.05 STALE-BRANCH / phantom-revert (gatekeeper_stale_branch_check — now
    #      a gatekeeper_review required gate): a PR forked from an OLDER base
    #      than the current origin/main tip that ALSO touches a file which
    #      LANDED since the fork (verdict STALE_OVERLAP, rc 1) has a phantom-
    #      revert trap — a naive `origin/main..HEAD` diff shows a REVERT of that
    #      landed work, so NEVER land it by a blind `git checkout HEAD -- <f>`
    #      (or "just take the PR's file versions"). The rebase in step 2 is
    #      safe because it REPLAYS the PR's commits; when you instead apply a
    #      delta by hand, cherry-pick the PR's OWN delta
    #      (`git diff <merge-base>..HEAD`), then grep the intervening fix's
    #      symbols to prove no false revert. STALE_ADVISORY (rc 0, no shared
    #      file — the #247 orthogonal shape) cannot phantom-revert; cherry-pick
    #      of the true delta is still the drift-free default. (Learned #246/#247.)
    #   3.5 GREEN -> ASSIGN THE VERSION (this is the gatekeeper's sole right):
    #      gatekeeper_assign_version.py --write reads the CURRENT origin/main
    #      version and writes the next strictly-monotonic version (patch 0..99;
    #      x.y.99 -> x.(y+1).0) into plugin.json + marketplace.json on the
    #      rebased branch; commit it ("vX.Y.Z — assign version for #<n>").
    #      Because the queue is serialized and rebased onto the latest main,
    #      this version cannot collide with a sibling PR's.
    #   3.6 RE-RUN gatekeeper_review.py WITHOUT the flag on the now-versioned
    #      tree: the monotonic+equality bump is now fully ENFORCED, and the
    #      cadence-correct suite is required (FULL on an x.y.0 milestone the
    #      gatekeeper just assigned, TARGETED on a patch). This is the
    #      gatekeeper OWNING the milestone-cadence decision the author could
    #      not know.
    #   4a. both runs GREEN -> squash-merge (one squash commit = the one
    #      gatekeeper-assigned version bump).
    #   4b. any run RED     -> EJECT: request-changes with the failure, do NOT
    #       merge. The PR goes back to the author (version assignment is
    #       reverted with the branch — it lands only on a clean merge).
finally:
    lock.release()   # ALWAYS release — even on eject/exception
```

The **squash-merge** is load-bearing: **one PR = one squash commit = one
gatekeeper-assigned version bump**, honoring the **one-version-per-push**
rule. **The gatekeeper assigns ALL versions** (owner directive 2026-06-17:
*"all versions are given by gatekeeper"*) — the authoring PR is VERSION-LESS
(it does NOT touch `plugin.json` / `marketplace.json`), because two PRs in
flight that each self-bumped would COLLIDE (both pick `x.y.(z+1)`). Only the
SERIALIZED queue, landing PRs one at a time onto an advancing `origin/main`,
can assign a strictly-monotonic version: at Step 3.5 above
`gatekeeper_assign_version.py --write` writes the next version into both
files on the rebased branch, then the enforced re-run
(`version_bump_monotonic_check.py` + `marketplace_version_sync_check.py`,
flag OFF) validates it. The squash collapses the PR's internal commits +
that version-assignment commit into the single landing commit that carries
the one bump. Never merge-commit or rebase-merge a multi-commit PR (that
would land several commits).

### Step 3.7 — RUN THE MERGE-PATH GATE. `gh pr merge` runs no gate at all.

```bash
tools/gatekeeper-verify-merge.sh <num> --json /tmp/verify-<num>.json   # MUST exit 0
gh pr merge <num> --squash --delete-branch
tools/gatekeeper-verify-merge.sh --reassert /tmp/verify-<num>.json     # if time passed
```

**This is not a reminder, it is the only gate on this path.** Measured
2026-08-12 (vibe-ic#1019):

| what was assumed | what is true |
|---|---|
| required status checks gate the merge | Actions is disabled at the **account** level — `actions/permissions` → `{"enabled": false}`; the appeal was rejected. `gh workflow run` → `HTTP 422`. A self-hosted runner does not help: *scheduling* is the blocked layer. |
| branch protection backs it up | `gh api repos/vibeic/vibe-ic/branches/main/protection` → **`404 Branch not protected`**. No required check exists. |
| `gatekeeper-land.sh` runs at the merge | It runs on **`git push`**, via the stamp `tools/git-hooks/pre-push` demands. **`gh pr merge --squash` creates the commit SERVER-SIDE — nothing is pushed from a local clone, so `pre-push` never fires and `gatekeeper-land.sh` never runs.** |

Consequence, measured rather than feared: `test_matrix_d2_falsifiable.py` was
RED on `main` across five merges (#1006 #1007 #1008 #1009 #1013) and the
targeted selector had picked that exact file for **all seven** merges examined.
The suite was right, the selection was right, and the thing that runs them was
never invoked. In the same window the **version assignment of Step 3.5 also
stopped happening** — the last twelve first-parent landings all carry the same
plugin version, because Step 3.5 commits it on the *rebased local branch* and a
server-side squash of the PR's *remote head* never sees it.

`gatekeeper-verify-merge.sh` fetches the PR head, rebases it onto the current
base **in a throwaway worktree**, proves that tree is the tree the merge would
produce (`git merge-tree --write-tree`, cross-checked against the forge's own
`refs/pull/<n>/merge`), and runs `gatekeeper-land.sh` on it. It refuses — loudly,
non-zero — on a rebase conflict, on any non-test gate failure, on a stamp naming
another commit, and on a tree that is not the one that would land. **Land only
on rc 0.**

It judges the suite DIFFERENTIALLY (the base's failed set vs the candidate's)
rather than demanding green, because `main` carries pre-existing red and a gate
that refuses every landing is a ban that teaches the operator to bypass it. A
test going **failed → skipped/absent is a refusal, never an improvement**.

Two things it does NOT do, on purpose: it does not push, and it does not merge.
The version assignment of Step 3.5 still has to reach the PR branch before
`gh pr merge` can carry it — the verdict says so in its notes rather than
letting the deferral pass for a bump.

#### Read the TIER on the verdict. This host is probably running the weaker one.

`git merge-tree --write-tree` needs **git >= 2.38**, and four of the six hosts
in this fleet run 2.34.1 — **including `.102`, the orchestrator, where every
`gh pr merge` is actually run.** On those the strong path cannot start, so the
script probes the capability and declares a tier:

| `verification_tier` | tree under test | squash-vs-rebase cross-check |
|---|---|---|
| `merge-tree` | the 3-way merge | **performed** — the rebase replay is an independent second opinion and a disagreement is a refusal |
| `rebase-replay` | the rebase replay | **NOT performed** — there is only one answer, so nothing is left to disagree with it |

Everything else is identical in both tiers: the same squash commit, the same
`gatekeeper-land.sh`, the same test and gate differentials, and the same
fail-closed refusal when the replay conflicts. **A `rebase-replay` pass is a
real pass, not a waiver** — the negative control (an innocuous diff that leaves
a test red) is asserted under the fallback precisely so it cannot become one.

Read it off the record rather than off the prose — it is machine-readable:

```bash
jq -r '.verification_tier, .tier_degraded, .squash_vs_rebase_cross_check' /tmp/verify-<num>.json
#   rebase-replay
#   true
#   NOT_PERFORMED
```

The printed verdict carries the same codes as `  DISCLOSE  ` lines. If a PR is
one whose risk is exactly the replay-vs-merge divergence (a revert of something
that also moved on `main` — the phantom-revert shape), verify it on `.112` or
`.114`, which have the capability, or wait for the forge's own
`refs/pull/<n>/merge` to exist: when the forge merged this same base it
cross-checks the replayed tree even under the fallback.

```bash
gh pr merge <num> --squash --delete-branch
```

The merge uses `--squash` and NEVER `--admin` / `--force` (see §Hard
rules). After release, the loop moves to the next PR; the next PR rebases
onto the **now-advanced** `origin/main`, so each landing is serialized and
re-validated against the latest tree — and `--reassert` refuses a verdict whose
base moved while it waited, because other agents land while a verify runs.

> **why re-run on the rebased tree is not optional:** the PR's own CI ran
> against the base it was opened on. Between then and now, the queue has
> merged other PRs. A clean 3-way merge proves the *text* doesn't
> conflict; it does NOT prove the *behaviour* still holds. Re-running the
> required checks on the rebased tree is the only thing that catches a
> semantic conflict — this is exactly the class of bug a serialized merge
> queue exists to prevent.

## Hard rules (non-negotiable)

> **The gatekeeper MAY self-merge.** A single identity may both author and
> merge its own PRs — there is NO author≠approver requirement. The gates
> (machine required checks + Step-2.7 + the serialized re-test-on-rebase
> queue), not identity separation, are what make a merge trustworthy.
> Nothing lands without surviving every gate on the rebased tree, whoever
> authored it.

| # | Rule | Reason | Enforced by |
|---|------|--------|-------------|
| 1 | NEVER `gh pr merge --admin` / `--force` / bypass branch protection | Bypasses the required status checks (the machine gates) | `git_prohibition_guard.py` |
| 2 | NEVER `git push --force` / `git commit --no-verify` / `git reset --hard` on `main` | Loss of history; bypasses pre-commit gates | `git_prohibition_guard.py` |
| 3 | NEVER merge a multi-commit PR with merge-commit / rebase-merge — squash only | one PR = one squash commit = one version bump (one-version-per-push) | `--squash` only; version gates |
| 4 | NEVER use chip/vendor/SKU string literals as detection logic in any gate | gates must be general | `source_chip_agnostic_check.py` |
| 5 | ALWAYS release `.merge.lock` (even on eject / exception) and NEVER force-steal a live lock | a stuck lock must heal via the dead-PID path, not a steal | `_runner_lock.py` (atexit/signal release + dead-pid cleanup) |

### Self-merge is allowed (no author≠approver requirement)

There is **no** identity-separation rule: the gatekeeper MAY merge a PR it
authored itself. The PR author login is irrelevant to the merge decision —
a PR lands iff it survives every gate (machine required checks + Step-2.7 +
the serialized re-test-on-rebase queue), regardless of who wrote it. This
keeps a single-maintainer / single-agent project self-sufficient: the same
identity can author a fix, open a PR, and — once the gates are green — merge
it through the queue. The quality guarantee is the GATE, not a second
person.

### Break-glass override (so a wedged gate can't deadlock the queue)

A failure mode the loop MUST survive: **a required gate is itself broken**
(e.g. `gatekeeper_review.py` crashes, or a machine gate has a bug that
red-flags every PR). If the *only* fix is a PR that repairs that gate, the
queue deadlocks — the broken gate blocks the very PR that would fix it.

**Break-glass protocol** (documented, auditable, narrow):

1. **Eligibility.** Break-glass applies ONLY to a PR whose diff is scoped
   to **fixing the wedged gate itself** (the gate program + its tests) —
   never to a feature/IC PR. The gatekeeper confirms the PR touches only
   the gate machinery and carries a `break-glass: <gate>` declaration in
   its body naming the wedged gate and a reproduction of the wedge.
2. **Explicit recorded approval.** Break-glass is never silent: the
   gatekeeper records an explicit `break-glass: <gate>` approval on the PR
   (a `gh pr review --approve` + a comment naming the wedged gate and the
   reproduction of the wedge) BEFORE merging. Skipping a safety gate is the
   one high-risk action the loop can take, so it must always leave an
   auditable trail — even though self-merge of an ordinary gated PR is
   allowed, a gate-SKIP must be declared, not hidden.
3. **Reduced gate set, never zero gates.** The wedged gate is the ONLY
   check skipped; **every other** required check still runs on the rebased
   tree. The merge still uses `--squash`, never `--admin`/`--force`. (We
   bypass the BROKEN gate, not branch protection.)
4. **Self-healing follow-up.** Immediately after the gate-fix lands, the
   gatekeeper re-runs the full machine gates (now including the repaired
   gate) on `origin/main` to confirm the wedge is gone, and the normal
   loop resumes — the next tick re-validates every still-open PR against
   the repaired gate. The break-glass event is recorded in the PR (the
   declaration + the human co-sign + the post-merge re-run output) so it
   is fully auditable.

Break-glass is deliberately painful (scoped diff + human co-sign +
reduced-not-zero gates + post-merge re-validation) so it can only ever be
used for its one legitimate purpose: un-wedging a broken gate. It can
never be used to fast-path a normal PR.

## Cadence (machine-gate test cost)

The machine gates honor the SAME test cadence as the rest of the plugin so
gatekeeping a routine patch-bump PR doesn't pay the full-suite cost:

- **PATCH-bump PR** (`x.y.Z`, Z>0) → `gatekeeper_review.py` runs the
  TARGETED regression (the PR's new `test_v*` + the touched module's
  tests + an affected-family `-k` sweep + `source_chip_agnostic_check.py`).
- **MINOR-milestone PR** (`x.y.0`) → the FULL both-tree suite the CI way,
  green required before merge — the periodic cross-module safety net.

The patch rollover (`x.y.99 → x.(y+1).0`) makes the milestone full-test
land automatically. The **rebased-tree re-run** in Step 2.9 uses the same
cadence (targeted for a patch, full for a milestone).

## Comment shape (繁體中文, 5 sections)

Every `request-changes` (machine-red or reproducible-HIGH) posts a
繁體中文 comment in this exact 5-section shape:

```
Gatekeeper 已 request-changes：PR #<num>（head=<branch>）

**問題**：<重述 PR 的目標 + 觸發 request-changes 的 gate / 發現>
**根因**：<machine gate 的失敗類別，或 Step-2.7 對抗發現的根因>
**證據**：
    <失敗 gate 的逐字輸出，或可重現的 HIGH 對抗重現步驟與輸出>
**要求**：<請作者修正什麼，才能重新進入 gate>
**機制說明**：本 PR 由單一 gatekeeper 把關 main；通過 machine gates（required checks）+ Step-2.7 對抗審查（唯一 agent 判斷關卡）後，才會進入序列化合併佇列、rebase 到最新 origin/main、在 rebase 樹上重跑 required checks，並以 squash 合併（一 PR＝一 squash commit＝一次版本 bump）。品質由 gate 保證（非作者≠審核者之身分分離）；本機從不 --admin / --force / --no-verify / 繞過 branch protection。
```

A successful merge is recorded by the squash-merge itself (and the deleted
branch); no comment is required on the happy path, though the gatekeeper
MAY post a 繁中 `已 squash-merge：<sha>` note.

## Compliance gate (mandatory)

After producing the 繁體中文 request-changes comment text (before posting),
save it to a file and run the deterministic publish-layer gate:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/gatekeeper-loop/compliance.yaml \
    <comment_file.md>
```

Exit 0 = PASS (post the comment), exit 1 = FAIL with the missing sections
listed. The gate enforces the canonical 5-section shape (`問題` / `根因` /
`證據` / `要求` / `機制說明`), the `Gatekeeper 已 request-changes：PR #`
header, the squash one-version-per-push mention, and a chip-AGNOSTIC
publish-layer scan. Patch and re-run until PASS, THEN post the comment.

## STOP CONDITION

The cron continues **indefinitely**. The gatekeeper does **not**
self-terminate — it stays available to gate any future PR. A tick that
produces `(no actionable PRs)` is a **healthy idle** state, not a stop
signal. There is no "done": the gatekeeper is the standing owner of
`main`. (This is the PR-loop analogue of the core-agent's "no actionable
issues" healthy idle.)

## State

The gatekeeper is **stateless across cron ticks**. All state lives in:

- **git** — `main`'s commit history, each PR branch's state.
- **GitHub** — PR open/merged/closed, review state (`request-changes` /
  `approved`), the required-check statuses.
- **the filesystem** — the `.merge.lock` file (held only WHILE a single
  merge is in flight, released on exit/signal/atexit per `_runner_lock.py`;
  a crashed holder's lock is cleaned via the dead-PID path on the next
  acquire).

Every tick is independent — no `state.json`. This matches the core-agent's
stateless design and for the same reason: the gatekeeper reacts to one PR
at a time and the response is fully captured by the PR's review/merge
transition + the transient lock.

## Cron-invocation template

```
Run /gatekeeper-loop against <owner/repo> (base=main).

Each tick must:
1. python3 plugins/vibe-ic/skills/gatekeeper-loop/programs/poll_prs.py --repo <owner/repo> --base main
2. If rc=0 → output "(no actionable PRs)" and exit (healthy idle).
3. If rc=2 → log + exit. Retry next tick.
4. If rc=1 → for each PR in `actionable[]` (newest-first). The PR author is
   irrelevant — the gatekeeper MAY merge its OWN authored PR; the gates are
   the quality guarantee, not identity separation:
     a. git fetch origin; run gatekeeper_review.py --version-by-gatekeeper
        (machine gates; the PR is VERSION-LESS so the version gate DEFERS)
        on base=origin/main head=<headRef>.
        - RED → gh pr review --request-changes with the verbatim failing
          output in the 繁中 5-section comment; continue.
     b. GREEN → Step-2.7 adversarial review on the PR diff
        (General-not-overfit / §4.05 no-leak / root-cause-not-bypass).
        Only a REPRODUCIBLE HIGH blocks → request-changes with the
        reproduction; continue.
     c. GREEN + no reproducible HIGH → enqueue to the SERIALIZED merge
        queue: acquire .merge.lock (_runner_lock.py); rebase onto current
        origin/main; RE-RUN required checks (--version-by-gatekeeper) on the
        rebased tree;
        - rebased GREEN → ASSIGN THE VERSION:
          gatekeeper_assign_version.py --write (next monotonic version →
          plugin.json + marketplace.json), commit it, then RE-RUN
          gatekeeper_review.py WITHOUT the flag (version bump now ENFORCED,
          cadence-correct suite — FULL on the x.y.0 milestone you assigned).
          - enforced run GREEN → gh pr merge <num> --squash --delete-branch
            (one PR = one squash commit = one gatekeeper-assigned version bump).
          - enforced run RED → eject: request-changes; do NOT merge.
        - rebased RED → eject: request-changes with the post-rebase
          failure; do NOT merge.
        Release the lock (always, even on eject/exception); next PR.
Hard rules: never --admin/--force/--no-verify, squash-only, always release
the lock. Self-merge of an ordinary gated PR is ALLOWED. A PR that fixes a
wedged gate uses the documented BREAK-GLASS path (scoped diff + recorded
break-glass approval + reduced-not-zero gates + post-merge re-validation).
See SKILL.md §Hard rules and §Break-glass override.
End of tick. The cron runs indefinitely — never self-terminate.
```

Save as the CronCreate `prompt` field; pick a short interval (e.g. 3-4
minutes) so freshly-pushed PRs are gated promptly.

## Reference

Deterministic gates + programs backing this skill (the loop SCAFFOLD is
fully programmable; only Step 2.7 is genuine LLM judgment):

- Poll / actionability (every open, non-draft PR against `main`,
  newest-first): `skills/gatekeeper-loop/programs/poll_prs.py`
- Machine-gate aggregator (required status checks, cadence-aware):
  `gatekeeper_review.py` (the required-check runner this loop invokes)
- Serialized merge-queue lock (one merge in flight, dead-PID self-heal):
  `programs/_runner_lock.py`
- Forbidden git/gh ops (rules 1-2): `programs/git_prohibition_guard.py`
- Chip-AGNOSTIC source scan (rule 4): `programs/source_chip_agnostic_check.py`
- Version equality (one-version-per-push): `programs/marketplace_version_sync_check.py`
- Version strict-monotonic bump: `programs/version_bump_monotonic_check.py`
- Gatekeeper version ASSIGNMENT at merge (the gatekeeper's sole right —
  next monotonic version → plugin.json + marketplace.json):
  `programs/gatekeeper_assign_version.py`
- PR machine gate — `--version-by-gatekeeper` DEFERS the version gate for
  the version-less authoring PR; the post-assignment re-run (flag OFF)
  enforces the bump: `programs/gatekeeper_review.py`
- Full-suite (not subset) pytest run: `programs/full_suite_run_check.py`
- Issue-fix counterpart (the other half of the contribution model):
  `vibe-ic:core-agent-loop`
- Adversarial-review skill used at Step 2.7: `vibe-ic:codex-adversarial-review`

### Which PR owns a non-atomic write

`atomic_artifact_write_check` answers "does THIS TREE contain a new offender".
It cannot answer "WHOSE PR put it there", and a batch of open PRs needs the
second question — each site has to be converted on the branch that carries it,
because none is on main yet.

    programs/atomic_write_pr_attribution.py --owner-repo <org/repo> --pr <n> [--pr <n> ...]

Not a gate and it cannot become one: `--pr` names live GitHub state, so no flow
clause and no `run` line can supply it. It is a triage tool for the person
holding the batch, which is this loop.
