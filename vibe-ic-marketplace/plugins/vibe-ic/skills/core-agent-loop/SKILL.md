---
name: core-agent-loop
description: Closed-loop core-agent that fixes plugin issues filed by the field-agent. Invoke as a cron prompt; the loop polls the repo for ANY OPEN non-PR issue (new OR reopened — no label gating, no comment classifier), reproduces and fixes the bug chip-AGNOSTIC-ally, SELF-VERIFIES (reproduce + run the cadence-correct plugin test suite the CI way), then SHIPS via the PR-METHOD — a VERSION-LESS verified bundle (candidate.patch + regression tests; the gatekeeper assigns ALL versions at merge) opened as ONE PR to vibeic/vibe-ic base main, gated by `gatekeeper_review.py --role core-agent --version-by-gatekeeper` (MERGE_OK) + Step-2.7, then gated squash self-merge — posts a 繁體中文 fix comment in the canonical 5-section shape (incl 本機驗證 evidence), then `gh issue close` + adds the `core-closed` label. CLOSED is the terminal state; the field-agent audits closed issues on the real benchmark and reopens any it finds inadequate.
---


<!-- WAVE_76_CHIP_AGNOSTIC_BANNER -->

> **Case-study notation.** This skill uses `IC-A / USB-HID tester /
> BENCH-A` as the canonical example chip — substitute your own IC
> name and host-tester name. The rules themselves are chip-AGNOSTIC
> and apply to any IC of the matching `ic_class` (see
> `vibe-ic-marketplace/plugins/vibe-ic/programs/ic_class_profile.py`).
> When you adopt this skill on a different IC, swap `IC-A` →
> `<your IC name>` and `USB-HID tester` → `<your host-tester name>`;
> the structural gates and rule bodies do not depend on those SKUs.

# Core-Agent Loop — Closed-Loop Plugin Issue Fixing

## Purpose

The core-agent is the **fix-verify-and-close** half of the Vibe-IC
quality loop. The field-agent (see `vibe-ic:field-agent-loop`) runs
the plugin against real benchmark IC projects, finds systematic
gaps, and files them as `ORGANIC:` GitHub issues. The core-agent
picks those up at every cron wake-up, ships a deterministic
chip-AGNOSTIC fix, **self-verifies** (reproduce + run the full
plugin test suite the CI way), then **closes** the issue and adds
the `core-closed` label. CLOSED is the terminal state. The
field-agent is the audit/reopen safety net: each cron tick it
re-checks closed `core-closed` issues on the REAL benchmark, marks
the good ones `field-verified` (stays closed), and `gh issue
reopen`s any it finds inadequate (which makes the issue actionable
to the core-agent again). This replaces the old
`wait-for-verification` limbo — that label is RETIRED.

The loop is **chip-AGNOSTIC**: fixes describe general plugin
behaviour (regex broadens, schema accepts more synonyms, gate
recognises canonical pattern); no fix references `IC-A`,
`BENCH-A`, `Vendor`, `usb_hid_tester`, `aid`, or any vendor IC name as
detection logic.

## Issue repo + per-tick scope (BINDING)

**ALL vibe-ic issues are filed to, polled from, and closed on
`vibeic/vibe-ic`** — the plugin's own GitHub repo. `AI_IC_design` is the
local **design-WORKSPACE directory** (the mounted RTL/GDS tree), NOT an
issue tracker; never poll or file issues against it. `poll.py` defaults to
`vibeic/vibe-ic`.

**Every tick performs TWO fresh checks (PRs FIRST, then issues):**
1. **Open PRs** — `gh pr list --repo vibeic/vibe-ic --state open`. Any
   non-draft open PR is auto-landed via the gatekeeper flow (cherry-pick onto
   current main → `gatekeeper_review.py --version-by-gatekeeper` → Step-2.7
   adversarial review → remediate every reproduced finding + pin a §4.05
   regression test → `gatekeeper_assign_version.py --write` → enforced
   re-gate → squash-merge). "Fix PR automatically" is a STANDING per-tick
   action, not one-shot.
2. **Open issues** — `poll.py` (below).

A tick may report idle ONLY after BOTH checks were actually run THIS tick —
never assert "no open PR" / "no issues" from memory or a prior tick.

## The four-step loop

### Step 1 — poll

Run **before** any other action, deterministically (polls `vibeic/vibe-ic`):

```bash
python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py
```

The program lists every open non-PR issue as `actionable`. Exit
codes are the cron driver's signal:

| rc | Meaning | Core-agent action |
|----|---------|-------------------|
| 0  | No actionable issues | Output `(no actionable issues)` and exit this tick |
| 1  | ≥1 actionable | Process each issue listed |
| 2  | I/O / auth error | Log + exit; retry next tick (do NOT treat as actionable) |

No LLM classification, no label gating, no comment classifier. One
rule: **actionable = ANY open non-PR issue (new OR reopened).** A
reopened issue is just an open issue again, so the field-agent's
reopen automatically puts the issue back in front of the
core-agent — no special-casing. (`waiting` is always empty; the
key is retained in the report shape for backwards compatibility.)

### Step 2 — reproduce + fix

For each actionable issue:

1. `gh issue view <num>` (or curl + jq) to read body + comments.
2. Reproduce locally when possible. Programs live under:
   - `vibe-ic-marketplace/plugins/vibe-ic/programs/` (gates)
   - `vibe-ic-marketplace/plugins/vibe-ic/programs/phase*_one_shot_runner.py` (runners)
   - `tools/` (one-off helpers)
3. Write a chip-AGNOSTIC fix. This is the **one genuinely
   LLM step** in the loop — open-ended root-cause analysis +
   code authoring that cannot reduce to a regex/threshold. The
   chip-AGNOSTIC discipline itself, however, IS a deterministic
   gate: the forbidden-token scan (`IC-A`, `BENCH-A`, `Vendor`,
   `usb_hid_tester`, `aid`, etc.) is **enforced by
   `programs/source_chip_agnostic_check.py`** (deny-list sourced
   from `tests/chip_deny_list.txt`). Heuristics must use deny-list
   / length-floor / structural checks, not chip-class string
   literals; the fix must work across **every** benchmark chip.
4. Add tests covering BOTH the new path AND a regression-guard for
   the prior behaviour. Convention: `tests/test_v1_<MAJOR>_<MINOR>_<PATCH>_<slug>.py`.
5. **Self-verify** before closing. New-tests-green +
   full-suite-green ALONE is **insufficient** to close — that only
   proves the *intermediate products of the new code*, never that the
   defect the issue described is actually gone. Self-verification MUST,
   in this order:
   - **(5a) Execute the issue's `## 驗收` commands VERBATIM** against
     the issue-named defect artifact (or a faithfully reproduced
     fixture shaped like the issue's `現象`). Run the issue's
     acceptance command(s) exactly as written — the real program /
     gate invocation, not a unit-test paraphrase — and capture the
     **end-state output** (the gate verdict / exit-code / final line,
     not an intermediate file's mere existence). If the issue has NO
     `## 驗收` / acceptance section, say so explicitly with the
     `無驗收區` disclosure wording (see Step 4) and fall back to a
     reproduce-the-`現象` end-state instead.
   - **(5b)** Reproduce the original failing scenario and confirm it
     now passes.
   - **(5c)** Run the FULL plugin test suite the CI way (see Step 3 —
     both test trees, not a `-k`/single-file subset).
   The `本機驗證` section of the Step-4 close comment MUST quote
   **(a) the acceptance command text** (verbatim, in a code block) and
   **(b) its end-state output**, in addition to the `N/N PASS` suite
   line. Before posting, run the two deterministic gates (#478):
   ```bash
   python3 plugins/vibe-ic/programs/acceptance_evidence_in_fix_comment_check.py \
       --issue-number <num> <comment_file.md>     # exit 0 required
   python3 plugins/vibe-ic/programs/defect_artifact_fixture_check.py \
       --issue-number <num> <new_test_file.py>    # exit 0 required
   ```
   For a **round-2+ close** (the issue was reopened), the first gate
   binds the LATEST reopen comment's fenced repro as acceptance (issue
   #499): in network mode it auto-fetches+selects that comment; offline,
   pass it via `--reopen-comment-file`. The `本機驗證` MUST then quote the
   reopen repro + its end-state, not only the original body acceptance.
   Closing is the core-agent's responsibility precisely because the
   core-agent self-verifies the acceptance criterion first; the
   field-agent is the downstream audit net.

   > **why_not_bucket_a (the judgment residual):** the *deterministic*
   > half — does the `本機驗證` section literally contain the issue's
   > acceptance command + an end-state line; does the regression test
   > load the named defect artifact and assert an end state — lives in
   > the two #478 programs above. The *reading-judgment* half stays
   > here: deciding whether a quoted command **truly IS** the
   > acceptance criterion (vs a superficially-similar command) and
   > whether its output has reached **end-state** (vs a misleading
   > intermediate) requires reading the issue for a novel defect, which
   > no regex can settle.

#### Step 2.6 — REOPENED doc-extraction issues: root-cause on the REAL artifact, fixture quotes the real line VERBATIM

This is round-2+ doctrine, triggered when a **doc-extraction**
ORGANIC issue is **reopened** with counter-evidence that names a
real input document. A round-2 fix can rebuild the extractor's
*structure* (dual-table / borderless / column-order walker) and
still ship a self-test whose fixture uses the wrong **axis** — the
synthetic-fixture-vs-real-input gap. Concrete recurrence: a #491
round-2 fix rebuilt the table SHAPE but its fixture used English
headers, while the real document's failure axis was **VOCABULARY**
(CJK + a multi-word group header like `Port group | 寬度 | 方向`).
The 8/8-green self-tests never exercised the real axis, so the
reopen repro survived the fix verbatim. (Second recurrence of this
gap.)

For a reopened doc-extraction issue, the round-2+ fix agent MUST,
in this order:

1. **FIRST run the extractor on the real named artifact** and
   locate the exact stage that returns empty — *which classifier
   returned `None`, which token missed*. Do not author a fix or a
   fixture before this.
2. **Fix that axis** (e.g. extend the vocabulary the classifier
   accepts), not a same-shape sibling.
3. The new fixture **embeds the real document's discriminating
   line VERBATIM** — e.g. the literal header row that the parser
   chokes on — **never a same-shape paraphrase**.

**General principle:** the failure axis — *vocabulary vs structure
vs encoding* — is a property of the **REAL INPUT**, not of the
issue text. Paraphrasing the input (even into a structurally
identical fixture) silently selects back the axis the fix author
already understood, so a green suite proves nothing about the axis
that actually failed. Where the issue names a discriminating line,
the fixture must quote it verbatim.

> **why_not_bucket_a (the judgment residual):** judging *which
> axis* a real document fails on requires reading the artifact
> **through the parser's own branch structure** (which branch
> returned empty on which token) — open-ended reading that no
> regex settles. The *programmable* residue — the reopen repro
> must pass before close — is **#499's Bucket-A rule**; cross-reference
> it. This Step-2.6 prose covers only the reading-judgment half:
> picking the right axis and quoting the real line verbatim.

#### Step 2.7 — pre-push hardening doctrine (guard-class diffs, live corpus, single-source tokens)

Three rules learned from real reopen loops; apply them BEFORE Step 3,
not after the field agent reopens.

1. **Adversarial-review a guard/transform-class fix BEFORE pushing.**
   When the fix ADDS a guard / SKIP condition / RTL-rewriting transform
   / verdict re-classification (anything that changes WHEN the plugin
   acts, not just HOW), spawn independent adversarial reviewers against
   the uncommitted diff with concrete attack lenses (false-fire on a
   legitimate shape, false-skip on the motivating shape, blast radius
   on downstream flow steps, raw-text edits hitting comments/strings).
   Only findings the reviewer can REPRODUCE count. History: a count
   guard that shipped review-less was reopened twice (an over-fire on
   wrapped tops, then an under-fire); the first reviewed round caught
   two reproduced HIGHs — a destructive rename that broke the runner's
   own L9-driven TBs, and a comment-line rename that emitted duplicate
   module declarations — before any field exposure.

   > **why_not_bucket_a:** whether a diff is "guard-class" and whether
   > a review finding is genuine both require reading the change's
   > intent; no regex separates a guard from a feature. The
   > programmable residue is already enforced elsewhere (full-suite
   > gate, chip-agnostic scan, post-transform sanity checks inside the
   > transforms themselves).

2. **The host benchmark corpus is LIVE — on-host evidence must be
   content-gated.** The field agent re-runs benchmarks continuously;
   any report/RTL under the benchmark work dirs can be OVERWRITTEN
   between your reproduction and your test run (a FAIL-shaped lvs.rpt
   became a PASS report mid-fix, mid-session). Therefore: a test that
   pins a SPECIFIC defect shape found in a real on-host artifact must
   (a) copy the shape into a synthetic fixture (the durable assertion),
   and (b) gate any optional on-host check on the CONTENT still being
   in that shape (`skip` unless the token/shape is present) — never on
   mere file existence. Deliberate exception: a *canary* test whose
   purpose IS to track the live corpus (e.g. "checker has no false
   fail on whatever the corpus holds today") legitimately binds to
   live state — but then a failure means EITHER a plugin gap OR
   corpus drift, and the fix must root-cause which.

   > **why_not_bucket_a:** whether a live-corpus test is an
   > intentional canary (must follow drift) or a pinned-shape repro
   > (must content-gate) is design intent not derivable from the code;
   > a blanket lint would mis-flag every canary.

3. **Never hand-copy a verdict/token list — extract it to one shared
   module and import it everywhere.** A token list duplicated across
   sites WILL drift (a terminal-verdict token added to one of four
   copies left the gate and the runner disagreeing on the same
   report). The same disease wears a second face: an EMITTER whose
   output format evolves while its CHECKER's parser does not
   (emitter↔checker drift) — when you change what a step writes, run
   the program that reads it against the new artifact in the same
   commit. Both are Bucket-A by construction: prefer
   `from <shared_tokens> import …` over re-typing a regex, and pin
   the emitter's current format in the checker's tests.

### Step 3 — ship via the PR-method (gatekeeper-gated)

**BINDING (2026-06-17, owner directive — supersedes the old direct-push):** the
core-agent does NOT `git push origin main` directly. It assembles ONE **verified
bundle**, applies it in a worktree off `origin/main`, opens ONE **PR** to
`vibeic/vibe-ic` base `main`, and lets the **gatekeeper machine** gate it. CLOSED
issues are still the terminal state, but the fix LANDS only through the PR gate.

A **verified bundle** is exactly two things — **NO version bump** (owner directive
2026-06-17: *"field dont need to have version to issue pr. all versions are given
by gatekeeper"* — and the same applies to the core-agent's authoring PR):
1. `candidate.patch` — the unified diff of the fix (chip-AGNOSTIC source change).
2. the regression test(s) — `test_v<M>_<m>_<p>_*.py` covering the new path AND a
   regression guard (≥1 per issue; multi-issue batches carry one per issue).
   The `<M>_<m>_<p>` filename slug is just a label for the version the gatekeeper
   is expected to assign next; it does NOT touch `plugin.json` /
   `marketplace.json` — leave both version files UNCHANGED in the bundle.

**Why version-less:** two PRs in flight that each self-bumped would COLLIDE (both
pick `x.y.(z+1)`). Only the SERIALIZED **gatekeeper**, landing PRs one at a time
onto an advancing `main`, can assign a strictly-monotonic version. The gatekeeper
assigns it at merge (`gatekeeper_assign_version.py --write`) and owns the
milestone-cadence decision (an `x.y.0` rollover → FULL suite).

```bash
# VERSION SCHEME (the gatekeeper applies it, not the author): patch段 0..99;
#   x.y.99 之後 = x.(y+1).0.  The author leaves plugin.json/marketplace.json AS-IS.
# TEST CADENCE for the AUTHORING PR (version-less): TARGETED regression — the
#   author cannot know the merge-time version, so runs the targeted floor; the
#   gatekeeper re-runs the cadence-correct suite (FULL on an x.y.0 it assigns).

# 1) Build the bundle in a worktree off origin/main (NEVER edit the live main
#    checkout — a concurrent session's pull can wipe uncommitted tracked edits).
git fetch origin
WT=/home/reyerchu/vibe-ic-pr/<slug>
git worktree add -b core-pr/<slug> "$WT" origin/main
#    …make the fix + tests IN $WT (do NOT touch plugin.json / marketplace.json)…
git -C "$WT" diff > "$WT/candidate.patch"     # the bundle artifact (record)

# 2) Run the MACHINE GATES locally with --version-by-gatekeeper so the version
#    gate DEFERS (the bundle is version-less; the gatekeeper assigns at merge):
( cd "$WT/vibe-ic-marketplace/plugins/vibe-ic" \
  && python3 programs/gatekeeper_review.py --base origin/main --head HEAD \
       --role core-agent --version-by-gatekeeper --json /tmp/gk.json )
#    -> MERGE_OK(0)/REQUEST_CHANGES(1)/REJECT(2). gatekeeper_review composes:
#     source_chip_agnostic_check, git_prohibition_guard, marketplace_version_sync_check,
#     version_bump_monotonic_check (DEFERRED — cur==prev under the flag),
#     agent_checkin_scope_guard --role core-agent, plugin_full_audit, the
#     cadence-correct pytest, blindness/full-suite asserts. Drive every red gate
#    to green (MERGE_OK) before opening the PR.

# 3) Commit ONLY the files you touched (NEVER -A/--force/--no-verify) + push the
#    BRANCH (not main). The commit subject carries NO version (gatekeeper assigns):
git -C "$WT" add <specific files>
git -C "$WT" commit -m "for #<num> — <one-line summary> (version by gatekeeper)"
git -C "$WT" push -u origin core-pr/<slug>

# 4) Open ONE PR to base main (gh fires the gatekeeper-ci pull_request workflow
#    where Actions is enabled; the loop's gatekeeper_review is the gate of
#    record regardless). NO version in the title:
gh pr create --repo vibeic/vibe-ic --base main --head core-pr/<slug> \
  --title "[core-agent] #<num> — <summary>" --body-file /tmp/pr_body.md
```

**Gatekeeper machine gates → ASSIGN version → merge.** The gatekeeper (single
identity, post-v1.1.1 may author AND self-merge — quality is the GATE, not
identity separation) (a) runs `gatekeeper_review.py --base origin/main --head
<branch> --role core-agent --version-by-gatekeeper` (version gate deferred); on
**MERGE_OK** + a clean **Step-2.7** adversarial pass it (b) **assigns the version**
on the PR branch — `python3 programs/gatekeeper_assign_version.py --write` writes
the next monotonic version into `plugin.json` + `marketplace.json`, commits it
(`vX.Y.Z — assign version for #<num>`) — (c) **re-runs `gatekeeper_review.py`
WITHOUT the flag** (now the monotonic+equality bump is fully ENFORCED, and the
cadence-correct suite is required), then (d) **squash-merges** (one PR = one
commit = one gatekeeper-assigned version bump): `gh pr merge <num> --squash
--delete-branch`. A red gate → `gh pr review <num> --request-changes` (繁中
5-section) and the bundle is re-worked. NEVER `--admin`/`--force`/`--no-verify`;
squash-only.

> **Environment note (vibeic/vibe-ic, private free plan):** GitHub branch
> protection is unavailable (Pro/public-only) and Actions may be disabled, so the
> gatekeeper-ci required-check cannot be ENFORCED by GitHub today. The
> `gatekeeper_review.py` verdict, run locally by the gatekeeper, is therefore the
> AUTHORITATIVE machine gate; the merge is the gatekeeper's gated self-merge. When
> the repo is made public / Pro, run `tools/setup_branch_protection.sh --confirm`
> (after the gatekeeper-loop is live) to make the gate GitHub-enforced — see
> `docs/GATEKEEPER_CUTOVER_RUNBOOK.md`.

(Added a program? -> `programs/INDEX.md` via `tools/gen_programs_index.py`. Added a
skill? -> `compliance.yaml` + `tests/test_compliance.py`. Touched the MCP server?
-> `python3 -m pytest -q mcp-eda/test`. Mirror with `bash tools/sync_opensource.sh
--no-test` inside the bundle when the opensource mirror is tracked.)

### Step 4 — self-verify + CLOSE

Post a 繁體中文 fix comment on the issue. **5 mandatory sections
in this exact shape** (the `本機驗證` section carries the Step-2.5
self-verify evidence; the trailing line is the field-audit anchor).
The `本機驗證` section MUST carry an **acceptance-execution trace** —
it quotes the issue's `## 驗收` command(s) verbatim AND their
end-state output — not just an `N/N PASS` suite line:

```
Core agent 已推送修復：<commit_sha_short>

**問題**：<重述 field-agent 的問題>
**根因**：<root cause analysis>
**修法**：<chip-AGNOSTIC fix description + files changed>
**本機驗證**：
- 驗收指令（逐字執行 issue 的 `## 驗收`）：
  ```
  <issue 的 ## 驗收 指令原文>
  ```
- 端態輸出：
  ```
  <該指令的端態輸出，例如 gate 的最終 verdict / exit-code>
  ```
- 全測試套件（CI 方式，雙樹）：N/N PASS

Core agent 已自行驗證並關閉此 issue（已加 core-closed 標籤）。field agent 複查若發現未完整，請 reopen 並補反證。
```

**No-acceptance-section case.** If the issue genuinely has no `##
驗收` / acceptance section, the `本機驗證` section MUST state
`無驗收區（issue 未提供 ## 驗收）` and instead quote the
reproduce-the-`現象` command + its end-state output. The
compliance gate accepts either the `驗收` trace OR the `無驗收區`
disclosure — but NOT a bare `N/N PASS` with neither.

Then **close** the issue and apply the `core-closed` label:

```bash
gh issue close <num>
gh issue edit <num> --add-label core-closed
# OR via curl:
curl -sH "Authorization: Bearer $TOKEN" \
     -H "Accept: application/vnd.github+json" \
     -X POST https://api.github.com/repos/<owner>/<repo>/issues/<num>/labels \
     -d '{"labels":["core-closed"]}'
```

**CLOSE the issue after self-verify.** CLOSED is the terminal
state. The `core-closed` label marks the issue as a field-audit
target. Do NOT apply `wait-for-verification` (RETIRED) and do NOT
apply `field-verified` (that is the field-agent's marker). If the
field-agent's audit finds the fix inadequate it removes
`core-closed`, reopens the issue, and posts counter-evidence —
which makes the issue actionable to the core-agent again.

### STOP CONDITION

The cron continues indefinitely. The core-agent does **not**
self-terminate — it stays available to react to any future
field-agent filing. A tick that produces `(no actionable issues)`
is a healthy idle state, not a stop signal.

**Convergence (not termination)** — per the fix-all-into-the-plugin
principle (see `benchmark-enhancement-capture` / `community-backlog-submit`),
the loop's real convergence test is that a **fresh clean-room re-run on the
newest plugin produces 0 residual that needs a plugin fix**, confirmed across
two consecutive rounds — NOT merely "no open issue right now". Every issue is
fixed into the next plugin version (program > skill, but never skipped); "clean-
room variance" / "design-side" / "not a plugin gap" are never discard reasons.

## Hard prohibitions (non-negotiable)

These are no longer prose-only — each is a DETERMINISTIC gate. Rules
1–4 are enforced by **`programs/git_prohibition_guard.py`** (feed it the
command strings before running them); rule 5 by
**`programs/source_chip_agnostic_check.py`**; rule 6 by
**`programs/field_agent_terminology_scan.py`** (feed it the comment /
external text before publishing).

| # | Rule | Reason | Enforced by |
|---|------|--------|-------------|
| 1 | NEVER `git push --force` (`--force-with-lease` is the safe sibling, allowed) | Loss of upstream history | `git_prohibition_guard.py` |
| 2 | NEVER `git reset --hard` on tracked branches | Loss of local work | `git_prohibition_guard.py` |
| 3 | NEVER `git commit --no-verify` | Bypasses pre-commit gates that catch chip-specific literals | `git_prohibition_guard.py` |
| 4 | NEVER `git checkout .` or similar discard | Loss of work-in-progress | `git_prohibition_guard.py` |
| 5 | NEVER use chip-specific string literals as detection logic | Fix must be general | `source_chip_agnostic_check.py` |
| 6 | Use term "field agent" (not "debug agent") in external text | Project terminology decided 2026-05-10 | `field_agent_terminology_scan.py` |

**Closing is REQUIRED, not forbidden.** The old "NEVER close a
GitHub issue" prohibition is REMOVED. Under the core<->field
backlog state machine the core-agent MUST `gh issue close` (and add
`core-closed`) after self-verifying its fix — CLOSED is the terminal
state. `gh issue close` / `gh issue reopen` are NOT flagged by
`git_prohibition_guard.py`. The field-agent's reopen, not a label
limbo, is the audit safety net.

## State

The core-agent is **stateless across cron ticks**. All state lives
in git (commit history, branch state) and GitHub (issue labels,
comments). Every tick is independent — no `state.json` file.

This is the inverse of the field-agent (which carries
`_field_agent_state.json`). The reason: core-agent reacts to one
issue at a time and the response is fully captured by the
open→closed transition (+ `core-closed` label). No multi-step LLM
dispatch to track.

## Cron-invocation template

```
Run /core-agent-loop against vibeic/vibe-ic.

Each tick must (FRESH-CHECK both; PRs FIRST):
0. gh pr list --repo vibeic/vibe-ic --state open  → for each non-draft open
   PR, auto-land via the gatekeeper flow (cherry-pick onto current main →
   gatekeeper_review.py --version-by-gatekeeper → Step-2.7 → remediate every
   reproduced finding + pin a §4.05 test → gatekeeper_assign_version.py --write
   → enforced re-gate → squash-merge). Never assert "no open PR" without
   running this THIS tick.
1. python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py  (issues on
   vibeic/vibe-ic)
2. If rc=0 (and step 0 found no PR) → output "(no actionable issues)" and exit.
3. If rc=1 → for each entry in `actionable[]`:
     a. Reproduce the bug from issue body + comments.
     b. Write a chip-AGNOSTIC fix + tests.
     c. SHIP via the PR-METHOD (see SKILL.md §Step 3 — supersedes direct
        push): assemble the VERSION-LESS verified bundle (candidate.patch +
        regression tests; do NOT touch plugin.json / marketplace.json — the
        gatekeeper assigns ALL versions), apply it in a worktree off
        origin/main, run `gatekeeper_review.py --base origin/main --head HEAD
        --role core-agent --version-by-gatekeeper` until MERGE_OK (the version
        gate DEFERS), commit (`for #<num> <summary> (version by gatekeeper)`,
        NO version in the subject, NO --force/--no-verify), push the BRANCH,
        open ONE PR to vibeic/vibe-ic base main. As gatekeeper: on MERGE_OK +
        clean Step-2.7, ASSIGN the version (`gatekeeper_assign_version.py
        --write` → patch 0..99 / x.y.99 → x.(y+1).0), commit it, re-run
        `gatekeeper_review.py` WITHOUT the flag (version bump now ENFORCED),
        then self-merge (squash).
     d. Self-verify: FIRST execute the issue's `## 驗收` commands
        VERBATIM on the named defect artifact / reproduced fixture
        and capture the END-STATE output, THEN confirm the original
        failure now passes, THEN run the test suite per the CADENCE
        POLICY — TARGETED regression on a PATCH bump, the FULL both-tree
        suite ONLY at an x.y.0 minor milestone; the `本機驗證` evidence
        MUST quote the acceptance command + its end-state output (not
        just `N/N PASS`). Run
        acceptance_evidence_in_fix_comment_check.py +
        defect_artifact_fixture_check.py (#478, exit 0 each) before
        posting.
     e. Post 繁體中文 fix comment in the canonical 5-section shape
        (see SKILL.md §Step 4), then `gh issue close` <num> and add
        label `core-closed`.
4. If rc=2 → log + exit. Retry next tick.

Hard prohibitions: see SKILL.md §Hard prohibitions.
End of tick.
```

Save as the CronCreate `prompt` field; pick a 4-minute interval.

## Compliance gate (mandatory)

After producing the 繁體中文 fix comment text (before posting),
save to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/core-agent-loop/compliance.yaml \
    <comment_file.md>
```

Exit 0 = PASS, exit 1 = FAIL with missing elements listed. Patch
and re-run until PASS, THEN post the comment.

## Reference

Deterministic gates backing this skill (the loop SCAFFOLD is fully
programmable; only Step 2 fix-authoring is genuine LLM judgment):

- Poll / actionability (every open non-PR issue): `programs/poll.py`
- Close-comment 5-section shape + acceptance-execution trace:
  `compliance.yaml` (+ `_shared/skill_compliance_check.py`)
- Acceptance-criterion executed + quoted in `本機驗證` (#478):
  `programs/acceptance_evidence_in_fix_comment_check.py`
- Regression test loads the named defect artifact + asserts end-state
  (#478): `programs/defect_artifact_fixture_check.py`
- Forbidden git/gh ops (prohibitions 1–4): `programs/git_prohibition_guard.py`
  (`gh issue close` / `gh issue reopen` are NOT flagged)
- Chip-AGNOSTIC source scan (prohibition 5): `programs/source_chip_agnostic_check.py`
- Terminology guard (prohibition 6): `programs/field_agent_terminology_scan.py`
- Version equality: `programs/marketplace_version_sync_check.py`
- Version strict-monotonic bump: `programs/version_bump_monotonic_check.py`
- PR machine gate (`--version-by-gatekeeper` DEFERS the version gate for a
  version-less authoring PR): `programs/gatekeeper_review.py`
- Gatekeeper version assignment at merge (next monotonic version →
  plugin.json + marketplace.json): `programs/gatekeeper_assign_version.py`
- Full-suite (not subset) pytest run: `programs/full_suite_run_check.py`
- Field-agent counterpart: `vibe-ic:field-agent-loop`
