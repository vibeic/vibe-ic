# Gatekeeper Cutover Runbook

Operational runbook for activating the **PR + single-gatekeeper** governance model
shipped in plugin **v1.1.0** (commit `b7eccb61`). It takes the repo from
*everyone direct-pushes `main`* to *only the gatekeeper bot lands `main`, via PR +
required checks + a serialized merge queue*.

> **Two-layer status (where this runbook fits).** This runbook is the **Layer-1**
> machinery — the *PR + single-gatekeeper merge queue* that lands **externally-filed
> PRs** (the public contribution model: a **backlog** report or a **PR** fix →
> maintainer lands). It is **documented but NOT currently activated**: under the
> 2026-06-26 owner directive the maintainer is in the **Layer-2** internal
> improvement phase and lands its **own** fixes by **direct push** to `main` with
> every gate retained (see `vibe-ic:core-agent-loop` §Step 3). Do **not** delete
> this machinery — it is the standing mechanism for external PRs and the target
> state for a future PR-only cutover; run the phases below only when the repo
> moves off the direct-push improvement phase. Until then, direct-push is the
> active landing method.

> ⚠️ **The cutover BREAKS the current direct-push loop.** Running
> `tools/setup_branch_protection.sh --confirm` before the gatekeeper-loop is live
> **freezes the repo** — no merges land. Follow the phases IN ORDER. Phase 4 (the
> protection flip) is the point of no easy return; everything before it is
> additive and reversible.

---

## 0. What v1.1.0 already shipped (no action needed)

All of this is already on `main`; the cutover only *activates* it.

| Artifact | Role |
|---|---|
| `vibe-ic-marketplace/plugins/vibe-ic/programs/gatekeeper_review.py` | Deterministic PR-gate aggregator → `MERGE_OK` / `REQUEST_CHANGES` / `REJECT` |
| `vibe-ic-marketplace/plugins/vibe-ic/skills/gatekeeper-loop/` | The infinite loop (SKILL + `poll_prs.py`) |
| `vibe-ic-marketplace/plugins/vibe-ic/programs/handoff_bundle_check.py` | Q3 Field deep-resolution completeness gate |
| `vibe-ic-marketplace/plugins/vibe-ic/agents/gatekeeper-agent.md` | The gatekeeper identity definition |
| `.github/workflows/gatekeeper-ci.yml` | Required status checks (fires on `pull_request` **and** `merge_group`) |
| `.github/CODEOWNERS` | Routes review to `@vibeic/gatekeeper` |
| `tools/setup_branch_protection.sh` | The cutover switch (idempotent `gh api`, `--confirm`-guarded) |

**The required status-check contexts** (must stay name-matched between the
workflow, the protection rule, and the queue):

1. `Gatekeeper required (aggregate)`
2. `Governance gates (chip-AGNOSTIC + version + scope + git)`
3. `Plugin audit + pytest (targeted)`

---

## 1. Preconditions checklist

Do not start until ALL are true:

- [ ] `origin/main` is at **v1.1.0 or later** and green (`gatekeeper-ci.yml` is on `main`).
- [ ] You have **GitHub admin** on `vibeic/vibe-ic` (branch protection + merge queue are admin-only).
- [ ] `gh` CLI is authenticated as an admin (`gh auth status`), and the plan supports branch protection + merge queue (GitHub Team/Enterprise, or public repo).
- [ ] You have decided the **gatekeeper identity** (see Phase 1) and can run an agent under it.
- [ ] **No long batch is mid-flight** on the current direct-push loops (let any open core-agent batch finish + push first — see Phase 5).

---

## 2. Phase 1 — Choose the gatekeeper identity

**There is NO author≠approver requirement** (the gatekeeper≠submitter rule was
removed). The gatekeeper MAY be the **same identity as the author** — quality is
guaranteed by the GATES (required status checks + the loop's Step-2.7 + the
serialized re-test-on-rebase merge queue), not by a second person. So for a
single-maintainer / single-agent project the simplest, fully-supported setup is:

**Option A (recommended) — the OWNER identity IS the gatekeeper (no new account).**
The owner (e.g. `reyerchu`) authors PRs, runs the gatekeeper-loop, and merges
their own gated PRs. Nothing to create.
```bash
export REPO="vibeic/vibe-ic"
export BRANCH="main"
export GATEKEEPER_ACTOR="reyerchu"     # the single owner/agent login
export GATEKEEPER_IS_APP="false"
export REQUIRED_APPROVALS="0"          # ← 0: rely on STATUS CHECKS, not PR approvals
```
> ⚠️ **Why `REQUIRED_APPROVALS=0` for single-identity.** GitHub will NOT let an
> author approve their OWN PR. So if you keep `require Code-Owner review` with the
> author as the only code owner, a self-authored PR can never satisfy the review
> and the queue deadlocks. Under single-identity self-merge you therefore drop the
> PR-review requirement and lean entirely on the **required status checks**
> (`gatekeeper-ci`) + the gatekeeper-loop's own **Step-2.7** gate. `main` is still
> protected (no direct push, required checks, squash, no force) — just without a
> human-approval step that a single identity cannot provide. `setup_branch_protection.sh`
> omits the `required_pull_request_reviews` block when `REQUIRED_APPROVALS=0`.

**Option B (optional) — a DISTINCT bot identity, only if you want actor/audit separation.**
Not required for correctness; choose it only if you want merges attributed to a
separate `…[bot]` actor for provenance. Then a real Code-Owner review IS possible
(the bot reviews the human's PR), so you may set `REQUIRED_APPROVALS=1` and keep
`@vibeic/gatekeeper` in CODEOWNERS.
- *Bot account*: create `vibeic-gatekeeper-bot`, add to repo with **write**, generate a fine-grained PAT (Contents R/W, Pull requests R/W, Checks R, Administration R). Put it in a `gatekeeper` team; keep `@vibeic/gatekeeper` in CODEOWNERS. Set `GATEKEEPER_ACTOR=vibeic-gatekeeper-bot`, `REQUIRED_APPROVALS=1`.
- *GitHub App*: a stricter alternative, but a GitHub App **cannot be a CODEOWNER**, so the required Code-Owner review must come from a user/team — keep `REQUIRED_APPROVALS=0` or add a human reviewer. Set `GATEKEEPER_IS_APP=true`.

---

## 3. Phase 2 — Dry-run the protection script (no-op, safe)

Confirm the script sees your config and prints the EXACT plan it would apply —
**without touching GitHub** (no `--confirm`):

```bash
cd /path/to/vibe-ic
REPO="$REPO" BRANCH="$BRANCH" GATEKEEPER_ACTOR="$GATEKEEPER_ACTOR" \
GATEKEEPER_IS_APP="$GATEKEEPER_IS_APP" REQUIRED_APPROVALS="$REQUIRED_APPROVALS" \
  bash tools/setup_branch_protection.sh
```

Verify in the printed plan:
- the three required-check contexts match the `gatekeeper-ci.yml` job names exactly;
- pushes restrict to **your** `GATEKEEPER_ACTOR`;
- `enforce_admins=true`, `linear_history=true`, `force_pushes=false`;
- it will enable the **native merge queue** with `merge_method=squash`.

If the plan is wrong, fix the env vars (or `REQUIRED_CHECKS`) and re-run the dry run. **Do not proceed until the dry-run plan is exactly what you want.**

---

## 4. Phase 3 — Bring the gatekeeper-loop online and PROVE it end-to-end

This is the load-bearing validation. **Do this while `main` is still direct-pushable**,
so a problem here costs nothing.

1. **Start the gatekeeper-loop** under the gatekeeper identity (cron-prompt skill,
   modeled on the core-agent loop). Each tick it runs:
   ```
   poll_prs.py --repo $REPO --base $BRANCH        # open non-draft PRs, newest-first
   → gatekeeper_review.py --base origin/main --head <pr-branch> --role <author-role>
   → (green) Step-2.7 adversarial review on the diff
   → request-changes  OR  enqueue → .merge.lock → rebase → re-run checks → squash-merge
   ```
   See `skills/gatekeeper-loop/SKILL.md` for the full tick contract.

2. **Open a trivial canary PR** from a non-gatekeeper identity (e.g. a one-line
   docs change on a branch) and watch the loop:
   - `gatekeeper-ci.yml` runs the three required checks on `pull_request` ✅
   - `gatekeeper_review.py` returns `MERGE_OK` ✅
   - Step-2.7 returns clean ✅
   - the loop enqueues it; the **merge queue re-runs the checks on `merge_group`** ✅
   - it **squash-merges** as the gatekeeper identity ✅

3. **Open a deliberately-bad canary PR** (e.g. add a forbidden chip token, or a
   non-monotonic version) and confirm the loop **`request-changes`** with the
   failing gate's output — it must NOT merge. This proves the gate bites.

4. **Confirm self-merge of a GATED PR works** (single-identity model): a PR
   authored BY the gatekeeper identity, once its required checks + Step-2.7 are
   green, merges through the queue. There is no author≠approver block. Separately
   confirm a GATE-WEAKENING PR (e.g. one that loosens a required check) is caught
   by Step-2.7 and held — the gate must not relax itself unobserved.

> If any of steps 1–4 misbehaves, STOP. Fix the loop/checks while `main` is still
> open. **Do not flip protection on a loop that can't merge a good PR or block a
> bad one** — that freezes the repo.

---

## 5. Phase 4 — Flip branch protection (the point of no easy return)

Only after Phase 3 fully passes.

1. **Quiesce the direct-push loops.** Let any in-flight core-agent/field-agent batch
   finish its `git push`, then pause those loops (stop their cron). Confirm
   `git fetch && git rev-parse origin/main` is stable (no session mid-push).

2. **Apply protection** (this calls the GitHub API):
   ```bash
   REPO="$REPO" BRANCH="$BRANCH" GATEKEEPER_ACTOR="$GATEKEEPER_ACTOR" \
   GATEKEEPER_IS_APP="$GATEKEEPER_IS_APP" REQUIRED_APPROVALS="$REQUIRED_APPROVALS" \
     bash tools/setup_branch_protection.sh --confirm
   ```
   It PUTs the protection payload and enables the merge queue. It is idempotent —
   safe to re-run.

3. **Immediately verify** the protection is live:
   ```bash
   gh api "/repos/$REPO/branches/$BRANCH/protection" \
     | python3 -c 'import json,sys;d=json.load(sys.stdin);print("checks:",[c["context"] for c in d["required_status_checks"]["checks"]]);print("restrict:",d.get("restrictions",{}));print("enforce_admins:",d["enforce_admins"]["enabled"])'
   ```
   - required checks list matches the three contexts;
   - push restriction names only the gatekeeper actor;
   - a direct `git push origin main` from a non-gatekeeper now **fails** (try it from a scratch clone — expect `protected branch hook declined`).

---

## 6. Phase 5 — Flip the producers (core/field) to PR mode

The loops that USED to direct-push must now open PRs.

1. **Core-agent loop**: change Step 3/f of `core-agent-loop` from
   `git push origin main` to: create a feature branch, push it, `gh pr create`
   targeting `main`. The gatekeeper-loop takes it from there. (The version-bump,
   tests, and 5-section comment all stay; only the *landing* changes.)
2. **Field-agent loop (Q3)**: Field now drills every layer in its sandbox, runs
   `handoff_bundle_check.py` on its bundle until it **ADMITs**, then opens ONE PR
   carrying the complete bundle (root-cause per layer + candidate patch + surface
   **and** deeper-layer tests + 2-round clean-room proof). The gatekeeper reviews +
   lands. See the rewritten `skills/field-agent-loop/SKILL.md`.
3. **Restart** the core/field loops in PR mode and the gatekeeper-loop together.

---

## 7. Post-cutover smoke (run once, end-to-end)

- [ ] A real core-agent fix flows: branch → PR → gatekeeper-ci green → Step-2.7 clean → queue → squash-merge. `origin/main` advances by exactly one squash commit / one version bump.
- [ ] A bad PR is held at `request-changes` and never reaches `main`.
- [ ] `main` is green after the merge (the queue re-ran checks post-rebase).
- [ ] A Field bundle PR that is INCOMPLETE (e.g. one clean-room round) is blocked by `handoff_bundle_check`.

---

## 8. Break-glass / rollback

**A wedged gate must never deadlock the queue.** A PR that *fixes the gate itself*
cannot be required to pass the broken gate. The break-glass path:

1. A repo admin (human) reviews the gate-fix PR directly.
2. Temporarily relax the specific failing required check for that one merge:
   - via repo Settings → Branches → edit rule → uncheck the broken context, merge the fix, re-check it; **or**
   - re-run `setup_branch_protection.sh` with a reduced `REQUIRED_CHECKS` env list, merge, then restore the full list.
3. Never disable `enforce_admins` or push restrictions as the break-glass — only the *failing check*, and only for the gate-fix.

**Full rollback to direct-push** (if the model must be abandoned):
```bash
gh api --method DELETE "/repos/$REPO/branches/$BRANCH/protection"
# then re-enable the direct-push core/field loops and stop the gatekeeper-loop.
```
This is fully reversible — protection is a setting, not history.

---

## 9. Day-2 operations

- **Flaky tests amplify in a queue** (a 5%-flaky required check fails the whole queue ~5% of the time). Keep the required-check surface minimal (the three contexts), quarantine known-flaky tests, and keep the FULL both-tree suite as a **milestone-only** (`x.y.0`) check per the cadence policy — patch PRs run the targeted subset only.
- **Cadence is automatic**: `gatekeeper_review.py` / `gatekeeper-ci.yml` read the version bump and select TARGETED (patch) vs FULL (x.y.0 milestone). The patch→`x.(y+1).0` rollover lands the full suite naturally.
- **Changing the gate itself**: the gatekeeper MAY self-merge a change to the gate machinery (`gatekeeper_review.py`, the loop, the CI), but a gate change is the highest-risk diff — its Step-2.7 MUST explicitly hunt for gate-weakening (a removed/loosened check, broadened allow-list, blocking→advisory downgrade) and hold any such finding as a reproducible HIGH. The adversarial review of the gate diff, not a second person, is the safeguard.
- **Provenance**: every landed change now carries the PR diff + the gate run logs + the gatekeeper's verdict + the issue link. Author≠approver is structural, not a convention.
- **Keep the post-merge real-benchmark re-audit** (field-agent). The PR rail gives role-independence, not judgment-independence; the deepest spec-interpretation layers are blind to a local self-check and only the real benchmark re-run catches them.

---

## 10. Quick reference

```bash
# dry run (safe, no-op)
bash tools/setup_branch_protection.sh
# apply (BREAKS direct push — only after Phase 3 passes)
bash tools/setup_branch_protection.sh --confirm
# poll open PRs (what the loop does each tick)
python3 vibe-ic-marketplace/plugins/vibe-ic/skills/gatekeeper-loop/programs/poll_prs.py --repo vibeic/vibe-ic --base main
# review one PR deterministically
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/gatekeeper_review.py --base origin/main --head <pr-branch> --role core-agent
# check a Field handoff bundle
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/handoff_bundle_check.py <bundle-dir>
# inspect live protection
gh api "/repos/vibeic/vibe-ic/branches/main/protection"
# full rollback
gh api --method DELETE "/repos/vibeic/vibe-ic/branches/main/protection"
```

**The cardinal rule:** gatekeeper-loop LIVE and PROVEN first (Phase 3) → protection flip second (Phase 4). Never the other way around.
