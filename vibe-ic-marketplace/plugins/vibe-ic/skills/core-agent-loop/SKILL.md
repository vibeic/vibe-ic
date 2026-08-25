---
name: core-agent-loop
description: Closed-loop core-agent that fixes plugin issues filed by the field-agent. Invoke as a cron prompt; the loop polls the repo for ANY OPEN non-PR issue (new OR reopened — no label gating, no comment classifier), reproduces and fixes the bug chip-AGNOSTIC-ally, SELF-VERIFIES (reproduce + run the cadence-correct plugin test suite the CI way), then SHIPS by DIRECT PUSH (2026-06-26 owner directive — direct commit + `git push origin main`, no PR ceremony) gated by `gatekeeper_review.py --role core-agent` (MERGE_OK) + Step-2.7 + `gatekeeper_assign_version.py --write` (the pusher assigns the monotonic version pre-push) — posts a 繁體中文 fix comment in the canonical 5-section shape (incl 本機驗證 evidence), then `gh issue close` + adds the `core-closed` label. CLOSED is the terminal state; the field-agent audits closed issues on the real benchmark and reopens any it finds inadequate.
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

> **Contribution-layer framing (so Step 3 is not misread as the public model).**
> The DIRECT PUSH in §Step 3 is the **Layer-2** *maintainer-internal* landing
> method, used while the plugin is built out — it is NOT what external users do.
> The **Layer-1** public contribution model is unchanged and retained: an external
> contributor files a **backlog** (a report, no code) **or** a **PR** (a fix, with
> code). This loop serves both — it polls open **backlog** items (Step 1) AND
> auto-lands any externally-filed **PR** through the gatekeeper flow (§per-tick
> scope). You are the maintainer, so you ship your OWN fixes by direct push; a
> non-maintainer contributor never pushes to `main`.

## Issue repo + per-tick scope (BINDING)

**ALL vibe-ic issues are filed to, polled from, and closed on
`vibeic/vibe-ic`** — the plugin's own GitHub repo. `AI_IC_design` is the
local **design-WORKSPACE directory** (the mounted RTL/GDS tree), NOT an
issue tracker; never poll or file issues against it. `poll.py` defaults to
`vibeic/vibe-ic`.

**Every tick performs TWO fresh checks (PRs FIRST, then issues):**
1. **Open PRs** — `gh pr list --repo vibeic/vibe-ic --state open`. The
   core-agent itself ships by DIRECT PUSH (Step 3), so it normally opens NO
   PRs; but a PR filed from ELSEWHERE (an external contributor, or a legacy
   in-flight branch) is still auto-landed via the gatekeeper flow (rebase onto
   current main → `gatekeeper_review.py` MERGE_OK → Step-2.7 adversarial review
   → remediate every reproduced finding + pin a §4.05 regression test →
   `gatekeeper_assign_version.py --write` → enforced re-gate →
   squash-merge). "Land/fix any open PR" is a STANDING per-tick action, not
   one-shot.
2. **Open issues** — `poll.py` (below).

A tick may report idle ONLY after BOTH checks were actually run THIS tick —
never assert "no open PR" / "no issues" from memory or a prior tick.

> **BINDING (owner directive 2026-06-19): the repo-gatekeeper FIXES every
> open PR, it does not merely merge-or-bounce it.** When a PR carries a
> reproduced finding, the single-identity gatekeeper **AUTHORS the
> remediation itself** (a structural code/test fix committed onto the
> landing branch) and lands the corrected PR — it does NOT leave the PR
> bounced-and-waiting for some external author. "Fix all open PRs" means
> *no open PR is left un-actioned each tick*: either it lands clean, or the
> gatekeeper authors the fix and lands the corrected version. Bounce-via-
> `gh pr comment` (the single identity cannot `--request-changes` its own
> PR) is reserved for the rare case where the correct fix genuinely cannot
> be authored this tick (needs a design decision only the owner can make);
> even then the PR stays OPEN and the NEXT tick must attempt the fix again,
> not idle past it.
>
> **REPRODUCE ON THE REAL ARTIFACT BEFORE FIXING OR BOUNCING (the #40
> lesson).** A finding — and the fix it motivates — MUST be reproduced on
> the **REAL benchmark artifact** (the dataset's own prompt + its reference
> golden / official testbench), NEVER only on a hand-crafted or synthetic
> fixture. A synthetic fixture can silently encode the WRONG convention and
> invert the verdict: PR #40's wired test hand-crafted a *same-edge*
> circuit7 waveform, but the real VerilogEval TB drives inputs via NBA at
> the posedge (`@(posedge clk) a<=val`), so the real published table is
> *NBA-lead* (output lags the input by one edge, X at the first posedge).
> Reviewing on the hand-crafted table "reproduced" a false-block that does
> NOT exist on the real prompt — the shipped check was correct all along
> (it PASSes the real golden `q<=~a` and BLOCKs the real wrong sample, and
> a sweep over ALL real circuitN goldens false-blocked ZERO). The phantom
> nearly drove an inverted "fix" that would have broken the gate on real
> data. So: pull the real `*_prompt.txt` + `*_ref.sv` + `*_test.sv` from the
> dataset, reproduce there, and when in doubt sweep the whole real-golden
> family to prove no-leak — a green synthetic fixture proves nothing about
> the axis (here: the TB's input-drive convention) that actually decides the
> verdict.

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

Then, before picking one, ask which of them nobody has taken:

```bash
python3 plugins/vibe-ic/programs/open_issue_claim_scan.py --repo vibeic/vibe-ic
```

An issue is TAKEN when one of its comments starts with `CLAIMED:` —
that is how a session announces it is working the issue, and it is
the only signal another session has. This matters even though a
single identity serializes the pushes: the Step-3 checklist below
already warns that "another session's pull/edit shares this tree",
so two ticks CAN be live at once, and the second one re-taking the
first one's issue is the collision this scan prevents.

Read its exit code the same way as `poll.py`'s, and note that this
one has no rc 1: it either scanned or it did not.

| rc | Meaning | Core-agent action |
|----|---------|-------------------|
| 0  | Scanned | Work `unclaimed[]`; post a `CLAIMED:` comment on the one you take, FIRST |
| 2  | Could not scan | Log + exit this tick. **NOT "nothing is claimed"** |

The rc 2 distinction is the whole reason this is a program. The hand-written
form of this question — `gh issue view <n> --json comments` per issue, testing
an unquoted count against `0` — prints nothing at all when the budget is
exhausted, which is byte-identical to printing nothing because every issue is
claimed. It also prints a well-formed list after examining 30 of 117, because
`gh issue list` defaults to `--limit 30`. This program prints the DENOMINATOR
with every answer and refuses (rc 2, empty stdout) rather than reporting a
count it could not measure — including the case where the per-issue comment
page came back AT its 100-comment cap, where a `CLAIMED:` past the cap would
make the NEGATIVE answer "unclaimed" the one truncation fabricates.

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
   **GENERAL-CORE / THIN-ADAPTER (BINDING):** a fix found while
   converging a benchmark must land in a **benchmark-AGNOSTIC general
   core** (operates on plain prose + a supplied interface; named for
   what it does — `verilog_width_resolve`, `spec_complete_extract`),
   called by a **thin benchmark adapter** (the `cvdp_`/`rtllm_`/
   `verilogeval_` prefix is correct ONLY for the record-IO shell).
   Never fuse reusable logic into a benchmark-named file — that traps
   the value away from the Phase-1 general path. If you touch a
   `cvdp_…`/`rtllm_…` file whose logic is pure prose/param handling
   (no record literal), it is naming debt: extract it to a neutral
   name. Verify flow-back: a plain Phase-1 doc of the same spec shape
   gets the SAME verdict with no harness. Full doctrine:
   `benchmark-enhancement-capture` → THE GENERAL-CORE / THIN-ADAPTER
   PRINCIPLE.
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
   - **(5a-i) A CHECKER CHANGE IS NOT AN ARTEFACT FIX.** When the
     issue reports a defective **artefact** (a report asserting a
     verdict it cannot back, a ledger field that was never measured,
     a document citing evidence it does not ship), adding or fixing
     the gate that *detects* it does NOT satisfy 5a. The acceptance
     re-run must be against **the named artefact**, and the artefact
     must have CHANGED. Two closes in two days broke this
     (vibe-ic#381): #366 was closed by landing an evidence gate and
     #365 by fixing an emitter, while all three
     `formal_evidence.json` still asserted PASS citing a `.sby` with
     zero files at that path, and 71 provenance entries still carried
     an unmeasured `duration_ms: 0`. Both were still reproducible on
     `main` after the close. This is the repo's own core defect —
     a check that reports a problem while the flow ships anyway —
     turned on its issue hygiene. **A gate reading PASS because the
     instance is in its debt register is NOT the artefact being
     fixed**; that is precisely the state that reads as done and is
     not.

     This paragraph is prose, and prose is what failed here — it
     already said all of the above and the close happened anyway. The
     deterministic half is a program; run it before closing, with the
     range you are about to push:
     ```bash
     python3 plugins/vibe-ic/programs/artefact_defect_close_check.py \
         --issue-number <num> --range origin/main..HEAD
     ```
     `FAIL` (exit 1) when the issue carries the `artefact-defect`
     label and the range changed none of the artefacts its body names
     — clear it by repairing the artefact, or by writing
     `ARTEFACT-UNCHANGED: <reason, >=30 chars>` in the close comment
     so the residue is recorded instead of implied. `ADVISORY`
     (exit 0) on an unlabelled issue whose body names a shipped
     artefact the range never touched: read it, do not skim past it.
     A version-bump manifest and a gate's own `*_baseline.json` are
     both counted as *not* an artefact repair, because writing the
     defective instance into a debt register is the exact move that
     made the measured close read green.
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

4. **A Phase-1 doc-extraction fix must keep the ANTI-FABRICATION grounding
   gate green (§4.05, OUTPUT→INPUT).** The Phase-1 gates verify COMPLETENESS
   (`extraction_coverage_check`, INPUT→OUTPUT — did we drop an input fact) and
   PROVENANCE PRESENCE + SCHEMA, but the load-bearing anti-fabrication direction
   is `phase1_evidence_grounding_check.py`: every direct input-doc evidence
   `literal`'s NAME identifiers must appear in the input, so an
   LLM-/extractor-INVENTED fact (a hallucinated port / register / opcode) is
   caught. Any fix that touches doc extraction or L-doc emission MUST run it on
   the affected project (it is also composed into `phase1_verify_aggregate`), and
   MUST keep an emitted evidence `literal` a VERBATIM source quote — never a
   synthesised string whose token need not be in the spec (the `wake_pulse` leak).
   This is **program-first wired into the loop**: `test_v1_2_39_grounding_loop_smoke`
   runs the gate on the committed `synthetic_benchmark_phase1` fixtures (stay-clean)
   AND on a fabricated fixture (stay-effective) inside the suite that
   `gatekeeper_review.py` -> `full_suite_run_check` runs every iteration — so a
   change that makes the extractor fabricate, OR that weakens the gate, fails the
   loop's own gate before merge.

   > **why_not_bucket_a:** whether a literal is a faithful quote vs a
   > synthesised description is a reading judgment; the deterministic residue —
   > the gate's NAME-identifier grounding + the smoke-test's stay-clean /
   > stay-effective assertions — is what's pinned here.

#### Step 2.8 — keep your turn ALIVE to completion; self-verify the deliverable (v1.3.51)

When any step of this loop delegates LONG work (a multi-minute/hour
sub-process — the full test suite, a reproduce run, a benchmark/IC flow),
**never launch it as a detached fire-and-forget and let your turn end.**
The launch-and-idle abandon bug: a detached background process finishes,
NOTHING re-invokes you, and your "then write the result" step never runs —
the tool's own outputs exist but your deliverable is never written
The three beliefs that make this feel safe are each impossible, and an agent in
vibe-ic#558 gave all three at once as its justification for yielding:

* *"the harness will re-invoke me when the background job exits"* — nothing
  re-invokes a finished turn. There is no such mechanism.
* *"a background waiter is armed to fire"* — a waiter can only wake a turn that
  is STILL ALIVE. It cannot start a new one.
* *"the monitor will fire"* — a monitor notifies the DISPATCHER, not you. It
  cannot resume you.

Refuting only the first leaves the other two as routes to the same outcome.

(observed 3× in one session). Two binding rules:

- **Run it through the BLOCKING `_watchdog.run_supervised`** (returns ONLY
  on process exit or stall; kills only a non-progressing job, never a live
  one) — NOT a raw detached host `timeout &`. Your turn then stays alive
  until the work genuinely completes, so your write step actually runs.
- **Your FINAL act before reporting done is to WRITE + SELF-VERIFY the
  deliverable** by running `python3 programs/run_output_completeness_check.py
  <run_dir>` on your own run_dir. Exit 0 (`COMPLETE`) is the only "done";
  exit 3 (`RUN_STILL_IN_PROGRESS`) means it isn't finished; any FAIL
  (`COMPUTE_DONE_DELIVERABLE_MISSING` / `DELIVERABLE_STUB` /
  `RUN_DIED_EARLY`) means you have not delivered. **NO RESULT / empty
  output = the run FAILED** — never report an abandoned run as complete.
  (The self-verify is the program-first gate; this line is the discipline.)

### Step 3 — ship by DIRECT PUSH (gatekeeper-gated)

**BINDING (2026-06-26, owner directive — STANDING preference; supersedes the
2026-06-17 PR-method):** the core-agent ships by **direct commit + `git push
origin main`** — NO `gh pr create`, NO PR branch, NO worktree-PR. Only the PR
*ceremony* is dropped; **every quality GATE is retained.** Because ONE identity
serializes its direct pushes to `main`, there is no two-in-flight collision, so
the pusher assigns the monotonic version **pre-push** (no version-less bundle
needed). CLOSED issues are still the terminal state.

> **Doctrine history (so the flip-flop is legible):** direct-push through v1.1.5
> → PR-method 2026-06-17 (to serialize concurrent authors via a gatekeeper merge
> queue) → **direct-push again 2026-06-26 owner directive** — the gates are
> retained in every era; only the landing *ceremony* changed.

The gates that MUST be green before the push are unchanged from the PR era:
1. `gatekeeper_review.py` → **MERGE_OK** is the AUTHORITATIVE machine gate of
   record (run locally — it composes `source_chip_agnostic_check`,
   `git_prohibition_guard`, `marketplace_version_sync_check`,
   `version_bump_monotonic_check`, `agent_checkin_scope_guard --role core-agent`,
   `plugin_full_audit`, the cadence-correct pytest, blindness/full-suite asserts,
   **and — since #538 — the ENTIRE `tools/ci/repo_hygiene_gates.sh` set that CI
   runs**). Do NOT run that script by hand as a separate step: it is invoked by
   the review, and its verdict line states its own denominator
   (`N/M gate(s) ran`, plus any gate that refused). Before #538 the review
   overlapped CI's hygiene set in 5 of 34 gates, and MERGE_OK twice failed to
   mean "this will land green" — v1.7.89 landed RED, and v1.7.92 was caught
   only because a maintainer happened to run the script manually. The gate now
   costs minutes rather than seconds for exactly that reason; that cost is the
   coverage, not overhead.
2. **Step-2.7** adversarial review on any guard/transform/extractor diff.
3. `gatekeeper_assign_version.py --write` for the strictly-monotonic version bump
   (one push = one version bump — honors `one-version-per-push`).

A regression test (`test_v<M>_<m>_<p>_*.py`) covering the new path AND a
regression guard is REQUIRED (≥1 per issue; multi-issue batches carry one per
issue). The `<M>_<m>_<p>` slug should match the version you assign below.

```bash
# VERSION SCHEME: patch段 0..99; x.y.99 之後 = x.(y+1).0. The PUSHER assigns it
#   pre-push now (serialized single identity — no collision). An x.y.0 rollover
#   is a milestone → run the FULL suite (cadence-correct) before the push.

# 0) Work on the MAIN checkout, but commit ONLY your own touched files by explicit
#    path (concurrent-tree hazard: another session's pull/edit shares this tree).
#    Re-poll (gh pr list / gh issue list) IMMEDIATELY before the push; if main
#    moved, `git pull --rebase` (or --ff-only) FIRST. NEVER edit unrelated files.
git fetch origin && git pull --ff-only origin main
#    …make the fix + tests in the working tree…

# 1) Run the MACHINE GATES locally — version gate ENFORCED (this is a direct push,
#    so the bump is real here, not deferred to a gatekeeper merge):
( cd vibe-ic-marketplace/plugins/vibe-ic \
  && python3 programs/gatekeeper_assign_version.py --write \
  && python3 programs/gatekeeper_review.py --base origin/main --head HEAD \
       --role core-agent --json /tmp/gk.json )
#    -> MERGE_OK(0)/REQUEST_CHANGES(1)/REJECT(2). Drive every red gate to green
#    (MERGE_OK) BEFORE the push. + run Step-2.7 on any guard/transform/extractor
#    diff. (gatekeeper_assign_version.py --write bumps plugin.json + marketplace.json
#    so version_bump_monotonic_check + marketplace_version_sync_check PASS.)

# 2) Commit ONLY the files you touched (NEVER -A/--force/--no-verify) — the fix +
#    its tests + the two version files — then push DIRECTLY to main:
git add <specific source files> <test files> \
        vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json \
        vibe-ic-marketplace/.claude-plugin/marketplace.json
git commit -m "vX.Y.Z — for #<num> — <one-line summary>

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push origin main
```

**One identity authors, gates, and pushes** (post-v1.1.1 — quality is the GATE,
not identity separation). The order is fixed: drive `gatekeeper_review.py` to
**MERGE_OK** + a clean **Step-2.7** pass, assign the version
(`gatekeeper_assign_version.py --write`), then `git push origin main`. A red gate
is NOT pushed — fix it first. If the push is rejected because `main` advanced,
`git pull --rebase origin main`, RE-RUN `gatekeeper_review.py` on the rebased tree
(catches a semantic conflict a 3-way merge misses), and push again. NEVER
`--admin`/`--force`/`--no-verify`/`--no-ff` bypass of a gate.

> **Environment note (vibeic/vibe-ic, private free plan):** GitHub branch
> protection is unavailable (Pro/public-only) and Actions may be disabled, so the
> `gatekeeper_review.py` verdict, run locally by the pusher BEFORE the push, is
> the AUTHORITATIVE machine gate. The push to `main` is gated by that local
> verdict, not by a GitHub required check.

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
0. gh pr list --repo vibeic/vibe-ic --state open  → the core-agent ships by
   DIRECT PUSH so it opens no PRs of its own, but any PR filed from elsewhere
   (external / legacy in-flight) is auto-landed via the gatekeeper flow (rebase
   onto current main → gatekeeper_review.py MERGE_OK → Step-2.7 → remediate every
   reproduced finding + pin a §4.05 test → gatekeeper_assign_version.py --write
   → enforced re-gate → squash-merge). Never assert "no open PR" without
   running this THIS tick.
1. python3 plugins/vibe-ic/skills/core-agent-loop/programs/poll.py  (issues on
   vibeic/vibe-ic)
2. If rc=0 (and step 0 found no PR) → output "(no actionable issues)" and exit.
3. If rc=1 → for each entry in `actionable[]`:
     a. Reproduce the bug from issue body + comments.
     b. Write a chip-AGNOSTIC fix + tests.
     c. SHIP by DIRECT PUSH (see SKILL.md §Step 3 — 2026-06-26 owner
        directive, supersedes the PR-method): on the MAIN checkout (re-poll +
        `git pull --ff-only` first; commit ONLY your own touched files by
        explicit path), ASSIGN the version (`gatekeeper_assign_version.py
        --write` → patch 0..99 / x.y.99 → x.(y+1).0, bumps plugin.json +
        marketplace.json), run `gatekeeper_review.py --base origin/main --head
        HEAD --role core-agent` until MERGE_OK (version bump ENFORCED), run
        Step-2.7 on any guard/transform/extractor diff, commit (`vX.Y.Z — for
        #<num> <summary>`, NO --force/--no-verify), then `git push origin main`.
        If the push is rejected because main advanced: `git pull --rebase`,
        RE-RUN gatekeeper_review.py on the rebased tree, push again.
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
- Which open issues nobody has taken, with the un-readable ones NAMED and
  the denominator printed: `plugins/vibe-ic/programs/open_issue_claim_scan.py`
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
- Authoritative machine gate (run locally → MERGE_OK before the direct push;
  `--version-by-gatekeeper` is the legacy flag that DEFERS the version gate for
  an externally-filed version-less PR): `programs/gatekeeper_review.py`
- Version assignment (next monotonic version → plugin.json + marketplace.json;
  the pusher runs `--write` pre-push): `programs/gatekeeper_assign_version.py`
- Full-suite (not subset) pytest run: `programs/full_suite_run_check.py`

### The ADVISORY censuses — run them, do not gate on them

Six programs answer a repo-wide question and REFUSE to be gates, in their own
words: `explicit_argument_outranks_the_environment_pointer_census`,
`provenance_value_is_resolved_not_constant_census` and
`local_clone_does_not_borrow_objects_census` both say "THIS IS A CENSUS, NOT A
GATE", `wall_clock_bound_standing_in_for_a_verdict` declares "VERDICT CLASS:
ADVISORY (rc 0 with findings) unless `--strict`", and
`layer_membership_is_declared_not_inferred_from_a_filename_prefix` carries a
test literally named `test_the_shipped_tree_is_RED_and_that_is_the_point`.

They belong here rather than in `tools/ci/repo_hygiene_gates.sh` and the reason
is structural, not preference. That dispatcher has exactly two forms — `run`,
which BLOCKS, and `run_tolerating_uncheckable`, which tolerates rc 2 and not a
finding. Declared bare, each would exit 0 while naming real findings, which is a
gate that CANNOT FAIL; declared `--strict`, each reddens the landing lane over
findings that predate any change in flight. Neither is what their authors asked
for. A skill line is the weakest runner there is and it is the honest one: an
agent reads it and runs the census when investigating. `checker_execution_
wiring_audit` models exactly this as its disclosed "skill-only" class.

Run each with `--root <repo>`; add `--strict` only when you intend to act on
every finding it names:

- Environment pointer vs explicit argument, as a population:
  `programs/explicit_argument_outranks_the_environment_pointer_census.py --root .`
- Clone sites that borrow objects, as a population:
  `programs/local_clone_does_not_borrow_objects_census.py --root .`
- Short wall-clock deadlines standing in for a verdict:
  `programs/wall_clock_bound_standing_in_for_a_verdict.py --root .`
- Layer membership inferred from a filename prefix rather than declared:
  `programs/layer_membership_is_declared_not_inferred_from_a_filename_prefix.py --root .`
- An axis that takes ONE value across arms that provably differ:
  `programs/metric_constant_across_differing_arms_is_not_measured.py --root .`
  **This one BLOCKS (rc=1) and its own docstring says it is RED ON THE TREE IT
  SHIPPED WITH.** It is here rather than in the landing lane for that reason:
  wiring a gate that is red by construction stops every landing on a finding
  that predates it. Run it, read what it names, and fix the axis — do not
  silence it by declaring it somewhere that turns it green.
- Prose extractors that do not consult polarity, as a population:
  `programs/prose_polarity_census.py`
- Source-naming fields filled from a path typed into the emitter:
  `programs/provenance_value_is_resolved_not_constant_census.py --root .`

  These last two were briefly declared as advisory clauses on flow steps D1 and
  36, and the placement was wrong on both counts. Their SUBJECT is this repo's
  own source, so on a per-project run they measure nothing about the project,
  and they charge it anyway: `prose_polarity_census` alone measured **25.7 s of
  the 27.3 s** that step D1's whole 33-clause probe set cost, enough to push a
  single census test case past the driver's 60 s forward-progress watchdog and
  be killed as hung. A census of the repo belongs where an agent reads it, not
  on a step that runs once per chip.

- A project still on the pre-v2 directory layout:
  `programs/migrate_to_layout_p.py <project> --dry-run`

  Reports what a migration to the v2 Layout P tree would move — `phase2a/`,
  `phase2b/`, top-level `analog/` and `manufacturing/` — and exits 1 on pre-v2
  residue, 0 on a tree already migrated. Drop `--dry-run` to perform it.

  IT IS HERE AND NOT A FLOW CLAUSE, measured on 2026-08-26 after being wired to
  step D1 and withdrawn the same day. It is a ONE-TIME migration an operator
  runs on an old project, not a question to re-ask on every chip, and the flow
  cannot hold it even if you wanted it to: its `_PHASE3_ANCHORS` name
  `layout.mag`, `drc_clean.flag`, `lvs_match.flag`, `pre_vs_post.json` and
  `hw_measurements.json`, which are required_outputs of A5/A6/A7/A9, so
  dimension 5 derives five dependency edges the step does not declare.
  Declaring them is refused by the graph — all four analog steps already have D1
  in their ancestry, so every edge is circular — and re-homing is refused too:
  the `blocks_on` closure of all 68 steps covers NONE of {A5, A6, A7, A9},
  because A9 is a leaf nothing blocks on.

- Field-agent counterpart: `vibe-ic:field-agent-loop`
