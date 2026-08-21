---
name: field-agent-loop
description: Closed-loop field-agent that drives plugin quality improvements by running phase1/phase2/phase3 on benchmark IC projects, DRILLING each systematic gap to a fully-converged all-layers-resolved state in its OWN sandbox worktree, then handing the gatekeeper ONE complete verified bundle (candidate.patch + per-layer regression tests + 2-round clean-room proof) to REVIEW + land — not re-discover. Still files ORGANIC backlog issues and AUDITS the fixes the core-agent self-verifies and CLOSES. Invoke as a cron prompt with a target benchmark folder and an LLM-review prompt; every tick the loop first audits CLOSED `core-closed` issues against the real benchmark (VERIFIED → add `field-verified`, NOT adequate → `gh issue reopen` + remove `core-closed`), then self-advances through review → deep-resolve → file-bundle → monitor → audit until STOP CONDITION (no new gaps + no open primary/secondary issue + no un-audited closed issue).
---


<!-- WAVE_76_CHIP_AGNOSTIC_BANNER -->

> **Case-study notation.** This skill cites the IC-A / USB-HID tester /
> MDV-A1101 BENCH-A reference project as concrete evidence for the
> rules below. The rules themselves are chip-AGNOSTIC and apply to
> any IC of the matching `ic_class` (see
> `vibe-ic-marketplace/plugins/vibe-ic/programs/ic_class_profile.py`).
> When you adopt this skill on a different IC, swap `IC-A` →
> `<your IC name>` and `USB-HID tester` → `<your host-tester name>`; the
> structural gates and rule bodies do not depend on those SKUs.
> See `docs/design/CASE_STUDIES/IC-A_*.md` for the full BENCH-A
> regression history.

# Field-Agent Loop — Closed-Loop Plugin Quality Improvement

## Purpose

The field-agent is the **organic improvement engine** for the
vibe-ic plugin. It treats real IC benchmark projects as a test
harness: re-run the plugin at HEAD, ask a fresh LLM to compare
source docs against generated output, and convert every
systematic gap it finds into a structured backlog issue.

> **Contribution-layer note.** The field-agent is a **Layer-1** intake role: it
> **files a backlog** (a report — or hands the gatekeeper a candidate-patch
> bundle) and audits landed fixes. It never edits the plugin/MCP and never pushes
> to `main`. Direct-push is the maintainer-internal (**Layer-2**) landing method
> for the gatekeeper's own fixes — not the field-agent's path. The maintainer
> resolves every backlog into the next plugin version.

The core-agent now **self-verifies and CLOSES** each issue it
fixes (adding the `core-closed` label). The default terminal
state is therefore **CLOSED**. The field-agent is the
**audit/reopen safety net**: at every cron tick it re-checks the
core-agent's closed issues on the actual benchmark — not on the
unit test fixtures. If the fix holds on real silicon it stamps
`field-verified` (terminal); if it does not, the field-agent
**reopens** the issue (`gh issue reopen`), posts counter-evidence,
and removes `core-closed` so the core-agent re-engages. This
audit/reopen model is what kills the old wait-for-verification
limbo where a fixed issue sat un-confirmed forever.

The loop is **chip-AGNOSTIC**: filed issues describe general
plugin gaps (e.g. "extractor X doesn't match canonical pattern Y"),
never project-specific bugs. Every YAML passes
`backlog_sanitize_check` before filing.

### Why discovery alone is not enough — the deeper-layer disease

For most of its history the field-agent reported only the **surface
layer it could see**: it ran the benchmark, observed the topmost
failing layer, filed one backlog, and handed it off. The core-agent
fixed exactly that surface — and then, on the next round, a **deeper
layer surfaced** that had been hidden behind the one just fixed. The
record is full of this multi-round drilling done the slow way, one
layer per round-trip:

- **#770 r2..r6** — five reopen rounds, each peeling one provenance
  layer the prior fix had unmasked.
- **#518 r1..r4** — the instantiation-graph / reset-skip family,
  four rounds because each guard exposed the next wrapper shape.
- **#780 r1..r2** — two rounds for what was, in hindsight, one
  convergent defect.

Each round costs a full file → core-fix → push → re-audit cycle just
to **re-discover** the next layer that was always going to be there.
The cure is structural: the field-agent must **DRILL to a
fully-converged, all-layers-resolved state in its OWN sandbox
worktree FIRST**, then hand the gatekeeper **ONE complete verified
bundle** to **REVIEW + land** — not a surface symptom for the
gatekeeper to re-discover layer by layer. This is the
**deep-resolution contract** in the section of the same name below.

## State

Every field-agent cron has a state file at the target folder root:

```
<target>/_field_agent_state.json
```

Schema:

```json
{
  "step": 1 | 2 | 3 | 4 | "STOPPED",
  "iter": <int>,
  "started_at": "<YYYY-MM-DD>",
  "target_folder": "<absolute path>",
  "last_plugin_version": "<semver>",
  "agent_task_id": "<id or null>",
  "agent_status": "<short status string>",
  "issue_number": <int or null>,       // primary tracked issue
  "tracking_secondary": [<int>, ...],  // secondary issues
  "sandbox_worktree": "<path or null>", // deep-resolution prototype sandbox
  "bundle_path": "<path or null>",      // handoff bundle dir for the primary
  "residual_rounds_clean": <int>,       // consecutive clean-room rounds at 0 residual
  "last_summary": "<one paragraph>"
}
```

## The loop

The loop is **review → deep-resolve → file-bundle → monitor →
audit**. Step 2 is no longer "file a one-line symptom"; it is "drill
the gap to convergence in a sandbox, then file a complete verified
**bundle**". Steps 1, 3, 4 are unchanged in shape.

### Step 1 — review

Run when `agent_task_id` is null OR the prior agent task is
completed/failed.

```bash
cd /home/<your-user>/AI_IC_design/vibe-ic-marketplace && git pull --ff-only
cd /home/<your-user>/AI_IC_design/mcp-eda         && git pull --ff-only
```

Check `plugins/vibe-ic/.claude-plugin/plugin.json` version.

Dispatch a fresh **general-purpose Agent** with a prompt that:
- names the target benchmark folder
- runs phase1 (or phase2+3 / phase2+3+analog depending on cron
  intent)
- asks the agent to read input docs + generated_docs and report
  systematic (chip-AGNOSTIC) gaps
- caps response length (≤800 words is a good default)
- explicitly lists already-closed gap IDs the agent must NOT
  re-report

Save the dispatched agent's task id, set `agent_status=running`.

### Step 2 — deep-resolve, then file the bundle

When the dispatched agent reports concrete quality gaps, do **not**
file a surface symptom and hand off. First **drill the gap to a
fully-converged, all-layers-resolved state in a throwaway sandbox
worktree** (the full procedure is in **Deep-resolution before
handoff** below), THEN file a complete verified bundle:

1. **Drill to convergence in a sandbox** — run the inner close-loop
   (run benchmark IC → observe the TOP failing layer → prototype a
   chip-AGNOSTIC fix → re-run → the next deeper layer surfaces →
   prototype it too → repeat until **0 residual**). See the
   deep-resolution section for the exact aggregate/audit probes and
   the convergence criterion.
2. **Admit the bundle** through the new admission gate before filing
   anything:
   ```bash
   python3 <plugin_root>/programs/handoff_bundle_check.py <bundle_dir>
   #   the bundle dir is POSITIONAL — there is no --bundle flag
   #   exit 0  → ADMIT: bundle is admissible (0 residual × 2 rounds,
   #             chip-AGNOSTIC candidate, per-LAYER tests, Step-2.7 run)
   #   exit 1  → INCOMPLETE; the printed reason names the missing
   #             criterion — fix it in the sandbox and re-run
   #   exit 2  → the bundle / manifest could not be read at all (this is
   #             a usage or I/O error, NOT a verdict about the bundle)
   ```
   A bundle that does not pass this gate is NOT filed — it is still
   a surface symptom, not a converged resolution.
3. For the gap, write the backlog YAML
   `<repo_root>/vibe-ic-marketplace/community/backlogs/ORGANIC-<YYYYMMDD>-<slug>.yaml`
   (ORGANIC #794 — this used to read `<plugin_root>/community/backlogs/`,
   which resolves to `plugins/vibe-ic/community/backlogs/` and does not
   exist. That is the ONE directory `agent_checkin_scope_guard.ZONE_BACKLOG`
   and the `--audit tracked` hygiene gate watch; a file written anywhere else
   is watched by nothing.)
   using the schema in the `community-backlog-submit` skill, and
   describe **all** layers the bundle resolves (not just the surface
   one), so the gatekeeper reviews the converged whole.
4. Sanitize:
   ```bash
   python3 <plugin_root>/programs/backlog_sanitize_check.py \
       --file <yaml>
   ```
   If `pass: false` → fix the flagged literal, re-sanitize. The
   `candidate.patch` inside the bundle is sanitized the same way —
   no `ic-a`, `bench-a`, vendor names, or project paths as logic.
5. File the GitHub issue (NO confirmation prompt), attaching the
   bundle as the candidate **PROPOSAL** (never as a self-merged
   change):
   ```bash
   gh issue create --repo vibeic/vibe-ic \
       --title "ORGANIC: <title>" \
       --body "$(cat <yaml>)"
   ```
   The issue body links the bundle (`candidate.patch`, the per-layer
   regression tests, the 2-round clean-room residual proof, the
   Step-2.7 record). The patch rides as an **untrusted proposal** the
   gatekeeper reviews and independently reproduces — see the
   guardrails in the deep-resolution section.
6. Save `state.issue_number = <primary>`,
   `tracking_secondary = [<others>]`, `state.bundle_path = <dir>`,
   `state.step = 3`.

**One bundle per independent root cause.** If the drill reveals that
the "deep" problem is actually **several independent root causes**
(not one convergent chain of layers), SPLIT into multiple
bundles / issues — first filed becomes primary, the rest go into
`tracking_secondary`. Do NOT ship one un-bisectable mega-bundle. (A
single convergent chain of layers — like #770's provenance peel —
IS one bundle; independent defects are NOT.)

### Step 3 — monitor (until core/gatekeeper lands the bundle)

`gh issue view <issue_number>` and watch for any of:
- the issue transitions to **CLOSED** with label `core-closed`
  (the gatekeeper independently reproduced + Step-2.7'd the bundle,
  landed it, self-verified + closed it)
- plugin version advances past `state.last_plugin_version`
- maintainer comment

The issue going CLOSED+`core-closed` is the primary trigger →
`state.step = 4` (the audit step). The closed-audit rule below
will pick the issue up regardless, but advancing the tracked
issue's step keeps the state file honest.

If plugin version bumps for an unrelated track (e.g. PnR fixes
on a phase1 issue), just update `state.last_plugin_version` to
the new version and stay in step 3.

> **The bundle is a PROPOSAL, not a merge.** Even a 0-residual
> bundle is landed by the **gatekeeper only**. The field-agent
> never pushes the prototype and never self-merges it. "Only
> Core/gatekeeper edits the plugin" means only the gatekeeper
> **LANDS** — it does not forbid the field-agent from prototyping
> the fix. See the deep-resolution guardrails.

### Step 4 — audit (verify the landed fix, reopen if inadequate)

#### Verify discipline — ARTIFACT-FIRST (mandatory, chip-AGNOSTIC default)

**Before launching ANY phase re-run, classify the closed fix's diff.**
A full phase3 re-run is ~40 minutes (route ~21 min + DRC + LVS); most
closed fixes do NOT need it. The asymmetry: the core-agent fixes
autonomously via a persistent loop, so the field agent must NOT
reintroduce 40-minute synchronous babysitting where a seconds-long
artifact check is the faithful real-surface verification.

1. **Classify the fix by what its diff TOUCHES — the deterministic
   answer is the program `fix_surface_classify.py` (#602), do NOT
   eyeball it:**
   ```bash
   python3 plugins/vibe-ic/programs/fix_surface_classify.py <issue|sha>
   #   exit 0  CONSUMER_ONLY → artifact-first verify (step 2)   [deterministic]
   #   exit 10 PRODUCER      → justified re-run (step 3)         [deterministic]
   #   exit 11 MIXED         → AI-adjudicate the residual (step 2.5)  [uncertain]
   ```
   It maps each diff hunk → its enclosing function/file → a maintained
   PRODUCER set (route/floorplan/streamout/geometry emitters: `step_pnr`,
   `make_tracks`, `_gds_grid_snap`, `_magic_def_to_gds`,
   `_klayout_merge_layers`, the `_GDS_*_PY` emitters, …) vs a CONSUMER
   set (checkers / classifiers / verdict-message strings). **Three-tier
   dispatch — the deterministic ends are decided by the program; only the
   uncertain middle goes to an AI agent:**
   - **CONSUMER_ONLY** (deterministic) — a checker / classifier /
     verdict-message / cache-decision / disclosure-line change (e.g. a DRC
     off-grid classifier, an LVS cross-reference string, a pin-count
     disclosure, a cache-validity line). The route, geometry, netlist,
     DEF, GDS and report files are UNCHANGED by such a fix.
   - **PRODUCER** (deterministic) — a change to the route/geometry
     producers: PnR Tcl, floorplan, CTS, streamout, or a verdict that
     depends on the actual run (e.g. a measure-only SPEF repair that
     prevents a segfault, a route-convergence verdict keyed on the real
     DRT count).
   - **MIXED** (uncertain) — touches both sets, OR an unknown/ambiguous
     surface the rules could not PROVE consumer-only. **This is the
     genuine judgment residual** (why_not_bucket_a) — and instead of
     defaulting straight to a ~40-min re-run, it goes to an AI agent
     (step 2.5). The program does NOT guess; it hands the agent the
     minimal material.
2. **CONSUMER_ONLY → drive the NEW program version against the
   project's ALREADY-PERSISTED artifacts** (`reports/phase3/*.rpt`,
   `lvs_verdict.json`, the netlist / DEF / GDS) and read the verdict.
   This is the faithful real-surface check and it takes SECONDS — feed
   the prior run's artifacts to the new program, do not regenerate them.
2.5. **MIXED → AI-adjudicate the ambiguous hunks BEFORE deciding to
   re-run.** Get the minimal agent material — the ambiguous hunks only,
   not the whole diff — from the program:
   ```bash
   python3 plugins/vibe-ic/programs/fix_surface_classify.py <issue|sha> \
       --adjudication-bundle
   ```
   The bundle carries each ambiguous hunk's file + enclosing symbol +
   changed lines + why it was ambiguous, plus what the engine already
   decided (producers/consumers) as context, plus the decision question.
   READ those hunks and decide per the bundle's rule: **ALL ambiguous
   hunks are consumer → treat the commit as CONSUMER_ONLY and do step 2
   (artifact-first, NO re-run); ANY is producer, or you cannot tell →
   step 3 (re-run).** This is the program-first / agent-on-uncertain
   split: the rules settle the certain hunks; the agent reads only the
   residual the rules could not. Do NOT auto-re-run a MIXED without
   reading the bundle — that throws away the whole point of the
   classifier.
3. **PRODUCER (or a MIXED the agent ruled producer/unsure) → a full
   phase3 re-run is justified** (clean-wipe + re-run the affected
   phase(s) below). Only here.
4. **A "check status" request is READ-ONLY**: report the persisted
   artifact state; do NOT launch a run. The canonical answer is the
   universal watchdog `run_status.py <project> [--phase auto]` (#599):
   a bounded one-shot probe that returns DONE / DIED / STUCK /
   RUNNING_ON_TIME in seconds from existing artifacts (the phase's
   `reports/orchestrator/<phase>_one_shot.json` verdict, the live log
   mtime as heartbeat, and the `.runner.lock` holder PID). Use it as
   the field-agent heartbeat too: launch a producer re-run async, then
   each status check is this one probe — never block on a wait-for-exit
   watcher, which cannot tell a hung step from progress.

This is **non-negotiable**: re-running phase3 to confirm a
checker/message-only fix wastes ~40 min per issue for a verification an
artifact check does faithfully in seconds.

#### Audit execution

**Re-dispatch a fresh general-purpose Agent** (not the original
task — must be a clean context) with an audit prompt that:
- names the specific issue + the v1.6.x test file that ships the
  fix
- **consumer-only fix**: drives the new program/gate against the
  affected IC's already-persisted artifacts and reads the verdict
  (seconds) — NO phase re-run
- **producer fix only**: clean-wipes the affected benchmark IC(s) and
  re-runs phase1/phase2/phase3 as needed against the **real benchmark**
- inspects the load-bearing fields the fix touches
- reports PASS criteria objectively
- spot-checks the unaffected ICs for regression

Two outcomes:

- **VERIFIED ok** → post a verify comment, add label
  `field-verified` (the issue STAYS CLOSED — this is the terminal
  do-not-re-audit marker), `state.step = 1`,
  `state.agent_task_id = null`.
  ```bash
  gh issue edit <num> --repo "$REPO" --add-label field-verified
  ```
- **NOT adequate** → `gh issue reopen` + post a counter-evidence
  comment (see the FIELD reopen-comment shape below) with the
  exact failing field/value on the real benchmark AND a concrete
  suggested-fix line, then remove `core-closed` so the core-agent
  treats it as actionable again. The issue is now OPEN; track it
  as the primary and go to `state.step = 3`.
  ```bash
  gh issue reopen <num> --repo "$REPO"
  gh issue comment <num> --repo "$REPO" --body-file reopen_comment.md
  gh issue edit <num> --repo "$REPO" --remove-label core-closed
  ```

**FIELD reopen-comment shape** (post on NOT-adequate):

```
Field agent 複查未通過，已 reopen：
**複查對象**：#<num> <title>
**實機證據**：<failing field/value on the real benchmark>
**建議修法**：<concrete suggested-fix line>
（已移除 core-closed 標籤；等待 core agent 重新處理。）
```

### STOP CONDITION

The real convergence test (per the fix-all-into-the-plugin principle in
`benchmark-enhancement-capture` / `community-backlog-submit`) is that a **fresh
clean-room re-run on the newest plugin produces 0 residual that needs a plugin
fix**, confirmed across two consecutive rounds — every recoverable residual is
captured and fixed into the plugin (program > skill, never discarded as
"variance" / "design-side" / "not a plugin gap"). In loop terms:

At Step 1: if the fresh review agent reports **STOP_RECOMMENDATION: YES**
(no new gaps AND no open primary/secondary issue AND the closed-audit
rule below returns an empty list — i.e. no un-audited `core-closed`
issue remains), then:

```bash
CronList  # find this cron's id
CronDelete <id>
echo "STOP cron."
```

Exit.

## Deep-resolution before handoff

This is the core of the field-agent's job: **converge the whole stack
of layers in your own sandbox, then hand the gatekeeper one complete
verified bundle to review + land** — never a surface symptom for the
gatekeeper to re-discover one layer per round-trip (#770 r2..r6,
#518 r1..r4, #780 r1..r2). The field-agent is the layer-driller; the
gatekeeper is the independent reviewer + lander.

### Prototyping is allowed — in a throwaway sandbox only

The field-agent **MAY prototype plugin fixes in a throwaway sandbox
worktree.** Inside that sandbox it may run `rtl_hygiene_lint --fix`,
re-synth, re-PnR, re-DRC, and edit programs or skills — whatever it
takes to reach a converged fix. This is **not** a violation of "only
Core/gatekeeper edits the plugin": that rule governs who **LANDS** a
change, not whether the field may **prototype** one. Concretely:

- The prototype lives in a **sandbox worktree** off the project, e.g.
  `git worktree add <target>/_deep_resolve_sandbox <base-sha>`; record
  it in `state.sandbox_worktree`.
- The prototype is **NEVER pushed** and **NEVER self-merged**. It is
  not committed to any shared branch the gatekeeper would treat as
  authoritative.
- The prototype rides into the handoff bundle as
  **`candidate.patch`** — an **untrusted PROPOSAL**. The gatekeeper
  independently reproduces it and decides whether to land it (often
  re-deriving the fix rather than applying the patch verbatim).
- Tear the sandbox down after the bundle is filed
  (`git worktree remove`), but keep `candidate.patch` and the test
  files inside the filed bundle.

### The inner close-loop (drill to 0 residual)

Run the failing benchmark IC through the runner and **peel layers
until none remain**:

1. **Run** the failing benchmark IC through the one-shot runner
   (phase1 / phase2 / phase3 as the gap demands), in the sandbox.
2. **Observe the TOP failing layer.** To answer "is there a *deeper*
   layer hiding behind the one I'm looking at?", use the aggregate /
   audit probes — they roll up every per-layer verdict so a fixed
   surface layer cannot hide the next one:
   - `python3 plugins/vibe-ic/programs/phase1_verify_aggregate.py <proj>`
   - `python3 plugins/vibe-ic/programs/phase2_verify_aggregate.py <proj>`
   - `python3 plugins/vibe-ic/programs/phase3_verify_aggregate.py <proj>`
   - `python3 plugins/vibe-ic/programs/signoff_audit.py <proj>`
     (sign-off layer roll-up: DRC / LVS / STA / IR-drop / antenna …)
3. **Prototype a chip-AGNOSTIC fix** for the top layer in the sandbox
   (program > skill; the fix must generalize — no chip/vendor/SKU
   literal as logic, no keyword overfit, root cause not bypass).
4. **Re-run.** The next deeper layer surfaces (this is exactly the
   per-round peeling that #770 / #518 did across reopen rounds — now
   collapsed into one sandbox session).
5. **Prototype it too**, and **repeat from step 1** until the
   aggregate/audit probes report **0 residual**.

Capture a **per-LAYER regression test** for every layer you peel —
both the surface layer and each deeper one — so a future run cannot
silently re-open the chain. (A bundle that fixes 4 layers ships
≥4 layer-pinned tests, each built from a clean independent reference
fixture, never a fixture seeded from the very output under test.)

### Convergence criterion (the bundle's admission gate)

A bundle is **admissible for handoff** — and `handoff_bundle_check.py`
(the NEW program the core-agent is adding) is the gate that enforces
it — only when ALL of:

- **0 residual across 2 INDEPENDENT clean-room rounds.** A fresh
  clean-room re-run on the candidate plugin produces 0 residual that
  needs a plugin fix, reproduced across **two** consecutive
  independent rounds (not the same run inspected twice). Track the
  count in `state.residual_rounds_clean`; it must reach 2.
- **Candidate is chip-AGNOSTIC.** `candidate.patch` carries no
  chip/vendor/SKU literal as logic; it passes `backlog_sanitize_check`
  and the chip-AGNOSTIC source guard.
- **Per-LAYER regression tests** — one for the surface layer and one
  for each deeper layer the bundle resolves; each built from a clean
  independent reference fixture.
- **Field ran Step-2.7 on its OWN prototype** before handoff (the
  adversarial multi-lens self-review on the candidate diff, recorded
  in the bundle). The field does not hand off a prototype it has not
  itself adversarially reviewed.
- **NO version bump in the bundle** (owner directive 2026-06-17:
  *"field dont need to have version to issue pr. all versions are given
  by gatekeeper"*). `candidate.patch` must NOT touch `plugin.json` /
  `marketplace.json` — the gatekeeper assigns the next strictly-monotonic
  version at merge (`gatekeeper_assign_version.py`), because two in-flight
  bundles that each self-bumped would collide. The field's job is the
  converged fix + tests + clean-room proof, not the version.

Run the gate before filing (see Step 2):

```bash
python3 <plugin_root>/programs/handoff_bundle_check.py <bundle_dir>
#   the bundle dir is POSITIONAL — there is no --bundle flag
#   exit 0  → ADMIT; file the bundle
#   exit 1  → INCOMPLETE; the printed reason names the missing
#             criterion (residual not 0×2 / not chip-agnostic /
#             missing layer test / no Step-2.7 record) — fix in the
#             sandbox and re-run
#   exit 2  → the bundle / manifest could not be read (usage / I/O
#             error, NOT a verdict about the bundle)
```

> **Known limitation, measured — read this before treating an INCOMPLETE on
> `root_cause_not_surface` as your bug.** That item admits only a
> `fix_surface_classify` verdict of `PRODUCER`. Over the 200 most recent
> `origin/main` commits fed in as candidate bodies the classifier returned
> `PRODUCER` **0** times (`CONSUMER_ONLY` 85, `MIXED` 115). If that item is
> the ONLY red one, the bundle is very likely fine and the PRODUCER registry
> is what needs widening — say so in the handoff instead of reshaping the fix
> to satisfy the classifier.

### CRITICAL guardrails — do NOT over-rotate

Deep-resolution makes the field-agent stronger, not autonomous. The
following are **non-negotiable** and bound the new power:

1. **The gatekeeper still independently reproduces + Step-2.7s the
   bundle.** The field's own 0-residual proof is a *proposal*, not a
   verdict. **Never trust a force-overwrite-to-0 or a subagent-built
   fixture blindly** — a `candidate.patch` that drives some residual
   counter to 0 may have done so by *masking* a real defect rather
   than fixing it (the documented force-overwrite-to-0 masking risk:
   a detector that over-fires to 0 looks converged but is hiding a
   mis-fire). The gatekeeper re-derives the fix and re-runs Step-2.7
   on the bundle from a clean context; a 0 it cannot independently
   reproduce is rejected.
2. **KEEP the post-merge real-benchmark re-audit.** Even after the
   gatekeeper lands the bundle, the field-agent's closed-audit safety
   net (below) still re-checks the landed fix on the **real
   benchmark**. A bundle/PR gives **role-independence, not
   judgment-independence**: the deepest spec-interpretation layers
   (does the generated design actually *mean* what the spec says?) are
   blind to any local self-check — only a fresh agent re-reading the
   spec against the real generated output catches them. The
   deep-resolution drill does NOT retire the audit/reopen loop.
3. **SPLIT independent root causes.** When the "deep" problem is
   actually several **independent** root causes — not one convergent
   chain of layers — file **multiple bundles / PRs**, never one
   un-bisectable mega-PR. A mega-PR that bundles unrelated fixes
   cannot be bisected when one of them regresses, and forces an
   all-or-nothing review. (One convergent chain of layers, like #770's
   provenance peel where each layer was hidden behind the previous, IS
   a single bundle; genuinely independent defects are NOT.)

## The deterministic closed-audit rule

The core-agent now self-verifies, CLOSES, and stamps `core-closed`
on every issue it fixes. The cron MAY have filed issues across
multiple field-agent sessions (e.g. one cron's audit shipped the
slice for a neighbouring cron's umbrella issue). Without an
explicit cross-check, the loop drifts: it tracks only its own
primary issue and never re-checks the core-agent's other closed
fixes on real silicon.

**Therefore: at every cron tick, BEFORE Step 1, run:**

```bash
plugins/vibe-ic/skills/field-agent-loop/programs/check_closed_for_field_audit.sh
```

(The script is bundled with this skill.)

It returns the list of all **CLOSED** ORGANIC issues authored by
you that carry `core-closed` and **LACK** `field-verified`. For
each, dispatch a fresh verify agent against the **real benchmark**:

1. Dispatch a verify agent scoped to that issue (clean context).
2. On **VERIFIED ok** → add label `field-verified`; the issue
   **stays CLOSED** (terminal do-not-re-audit marker).
   ```bash
   gh issue edit <num> --repo "$REPO" --add-label field-verified
   ```
3. On **NOT adequate** → `gh issue reopen` + post the FIELD
   reopen-comment (counter-evidence) + remove `core-closed` so the
   issue returns to OPEN and the core-agent treats it as
   actionable again.
   ```bash
   gh issue reopen <num> --repo "$REPO"
   gh issue comment <num> --repo "$REPO" --body-file reopen_comment.md
   gh issue edit <num> --repo "$REPO" --remove-label core-closed
   ```

This is **non-negotiable**: an un-audited `core-closed` issue
means a core-agent fix has never been confirmed on real silicon.
A field-driven deep-resolution bundle does **not** exempt the issue
from this audit — even a 0-residual bundle is re-checked on the real
benchmark after it lands, because the bundle proves role-independence,
not judgment-independence (see guardrail 2). The field-agent no
longer waits for any `wait-for-verification` label — that label is
**RETIRED**; the field audits CLOSED issues instead.

## Constraints (non-negotiable)

- **NO RTL ORACLE**: never inspect `input/rtl/` or any generated
  RTL when assessing input-doc-only extractors. The plugin must
  derive structure from input docs. (This holds inside the
  deep-resolution sandbox too — prototyping a fix never licenses
  reading the RTL oracle to "converge".)
- **Chip-AGNOSTIC backlog AND candidate.patch**: every YAML and every
  bundled `candidate.patch` must pass `backlog_sanitize_check`. No
  `ic-a`, `bench-a`, `vendor`, `usb_hid_tester`, `aid`, vendor IC
  names, or project paths in the title/pattern/suggested_fix or in the
  patch logic. The authoritative deny-list lives in
  `tests/chip_deny_list.txt`.
- **Field-agent files GENERAL plugin gaps**, never chip-specific
  bugs. The user owns chip-specific fixes; the field-agent owns
  plugin generality.
- **Prototype, never land.** The field-agent may prototype a fix in a
  throwaway sandbox and ship it as `candidate.patch`, but it NEVER
  pushes the prototype and NEVER self-merges. Only the gatekeeper
  LANDS plugin changes.
- **No y/n confirmation**: file issues directly. Do not ask.
- **Sanitize before file**: every YAML and every `candidate.patch`,
  every time, even when you're sure it's clean.

## Campaign orchestration — single-driver principle

A multi-tick field campaign drives the one-shot runners against a
project directory over and over, often handing the project from a
background agent to a successor agent across cron ticks. These are the
host lessons for keeping that hand-off clean:

- **One runner per project dir at a time.** A project directory is a
  single-writer resource: the run logs, manifests, and provenance under
  its `reports/` tree are written by exactly one driving runner. Two
  runners pointed at the same project will co-write that tree and
  corrupt the run record. The runner now enforces this with a
  `<proj>/.runner.lock` (pid + ISO timestamp + runner name): a second
  concurrent invocation against a live-held project is refused by name
  (`CONCURRENT_RUN_REFUSED`, naming the holder pid) and exits non-zero;
  a lock left behind by a dead runner is cleaned as stale and the new
  runner proceeds. Treat a `CONCURRENT_RUN_REFUSED` as a signal to find
  and resolve the other driver — never to delete the lock by hand and
  retry. **The deep-resolution sandbox is a SEPARATE project dir**
  (its own worktree): never run the inner close-loop against the live
  audited project — clone/worktree it so the sandbox runner holds its
  own lock and never collides with the audit driver.

- **Never abandon a background runner that still holds a project.**
  Before handing a project to a successor agent (or before STOP), the
  driving agent MUST either `wait` for its background runner to finish
  or `kill` it. An abandoned, still-alive background runner keeps its
  lock and will (correctly) refuse the successor — and worse, if the
  lock is force-removed, both runners co-write and the run record is
  silently corrupted. This applies to sandbox runners too — account
  for every sandbox runner you spawn and tear the sandbox worktree
  down after the bundle is filed.

- **The double-driver incident (generic).** In a real campaign an
  orphaned background runner was left driving a project while the cron
  advanced and a successor agent launched a fresh runner on the SAME
  project; both wrote logs / manifests / provenance concurrently. There
  was no refusal mechanism, so the corruption went unnoticed until the
  artifacts were audited. The single-driver lock above is the
  deterministic fix; the operational rule is: account for every
  background runner you spawn — wait or kill — before relinquishing a
  project.

- **Keep your turn ALIVE to completion — never detach-and-idle (v1.3.51,
  the launch-and-idle abandon bug).** The failure that motivated this
  rule: an agent that delegates a multi-hour run launches the runner as a
  DETACHED background process, then its turn ENDS (idle); when the
  detached process later finishes, NOTHING re-invokes the agent, so its
  "then write RESULT.md" step never runs. The runner's OWN outputs
  (`reports/final_summary.md` / orchestrator `*_one_shot.json` verdict /
  GDS/SPEF artifacts) exist, but the synthesis deliverable is never
  written. All three beliefs that make yielding feel safe are impossible
  (vibe-ic#558): the harness does not **re-invoke** a finished turn; a
  background waiter can only wake a turn that is **still alive**; and a monitor
  **notifies the DISPATCHER**, not the agent, so it cannot resume you.
  written — observed 3× in one session (two idled pre-write; one flow
  finished but RESULT.md had to be hand-authored from artifacts). Rules:
  1. **Run the long tool through the BLOCKING `_watchdog.run_supervised`**
     (returns ONLY on process exit or stall, killing only a
     non-progressing job — never a live one), NOT a raw detached host
     `timeout &`. That keeps your turn alive until the run genuinely
     completes, so your write step actually runs.
  2. **Your FINAL act before reporting done is to WRITE + SELF-VERIFY the
     deliverable**: author `RESULT.md`, then run
     `python3 programs/run_output_completeness_check.py <run_dir>` on your
     OWN run_dir. Exit 0 (COMPLETE) is the only "done"; exit 3
     (RUN_STILL_IN_PROGRESS) means the run isn't finished yet; any FAIL
     (`COMPUTE_DONE_DELIVERABLE_MISSING` / `DELIVERABLE_STUB` /
     `RUN_DIED_EARLY`) means you have not delivered.
  3. **NO RESULT / empty output = the run FAILED.** A run that produced no
     RESULT is not "mostly done" — it is a failed run; do not report it as
     complete. The gate emits a capture candidate on FAIL — feed it to
     `enhancement_emit.py` so the gap is absorbed, never silent.

## Cron-invocation template

```
<short-name>-field-agent

You are the field-agent loop for <target>. State at
<target>/_field_agent_state.json.

At EVERY tick, BEFORE Step 1, run the deterministic closed-audit
rule (programs/check_closed_for_field_audit.sh): for each CLOSED
`core-closed` issue lacking `field-verified`, dispatch a verify
agent against the real benchmark — VERIFIED → add `field-verified`
(stays closed); NOT adequate → `gh issue reopen` + counter-evidence
comment + remove `core-closed`.

In Step 2, do NOT file a surface symptom. DRILL the gap to 0 residual
in a throwaway sandbox worktree first (inner close-loop: run → observe
top layer via phase{1,2,3}_verify_aggregate / signoff_audit →
prototype a chip-AGNOSTIC fix → re-run → peel the next deeper layer →
repeat), gate the bundle with handoff_bundle_check.py (0 residual ×2
rounds + chip-AGNOSTIC candidate.patch + per-LAYER tests + your own
Step-2.7), then file ONE complete verified bundle as a PROPOSAL. Split
independent root causes into separate bundles. NEVER push or self-merge
the prototype — the gatekeeper independently reproduces + Step-2.7s +
lands it, and the post-merge real-benchmark re-audit still runs.

[paste the four-step loop above, adapted to the target intent]

LLM-review prompt body (Step 1):
"<paste the prompt that names the target ICs, the runner, the
 known-closed gap IDs, and the report cap>"
```

Save this prompt as the CronCreate `prompt` field; pick a 4–6
minute interval; field-agent self-paces from there.

## Verification traps (MANDATORY audit hygiene)

Traps that corrupted audit verdicts in real sessions (rules 1-2:
2026-06-06, ORGANIC #456; rule 3: 2026-06-07, ORGANIC #460/#466
verification round) — all are now standing rules for EVERY fix audit:

1. **Pipeline exit-code masking.** `prog … | tail; echo $?` reports
   `tail`'s exit code, not the gate's — a FAILing gate reads as exit 0.
   RULE: run the gate program BARE first and capture its exit code
   (`prog …; rc=$?`), THEN pretty-print output separately (or use
   `set -o pipefail`). Never derive a verdict from a piped invocation.

2. **Which-tree-runs resolution.** Verifying a fix against the repo
   tree proves nothing if the INSTALLED PLUGIN CACHE is what actually
   executes — the cache can lag the marketplace origin by several
   versions. RULE: before auditing a fix, resolve which tree will run
   (installed cache vs repo checkout vs marketplace origin); when the
   cache lags, check out / worktree the origin commit under audit,
   run against THAT, and STATE the tree+version in the verify comment.

3. **Acceptance-criterion audit, not unit-test trust.** A core-closed
   issue's fix comment will report the new tests green + full suite
   green — but those are the *intermediate products of the new code*,
   not proof the defect is gone. RULE: audit a core-closed issue by
   FIRST running the issue's own `## 驗收` (acceptance) command(s)
   end-to-end on the **real benchmark** — the actual program / gate
   invocation, observing its end-state output. The unit-test / suite
   evidence quoted in the fix comment is **secondary**; treat a fix
   whose acceptance command still fails as NOT adequate and reopen it,
   regardless of how green the suite is. This pattern recurred twice in
   one verification round (2026-06-07): one fix's tests asserted only
   that a generated bridge artifact existed and never exercised the
   `all_of` coverage sub-gate that actually decided the step verdict;
   another's rule landed in skill prose instead of the runner that
   executes it — both passed their own suites yet failed the moment the
   acceptance command was run end-to-end. Reproduce a defect-artifact
   fixture shaped like the issue's `現象`, run the acceptance command,
   and assert the END state — never the intermediate. (When an issue
   genuinely has no `## 驗收` section, fall back to reproducing the
   `現象` to an end-state; do not substitute unit-test trust.)

   **The same trap applies to your OWN deep-resolution bundle.** The
   bundle's 0-residual proof is *intermediate product of your
   candidate.patch*, not proof the defect class is gone. Build each
   per-layer regression test from a clean independent reference fixture
   (a known-good N-stage shift-reg → N, a comb block → 0), NEVER from a
   fixture seeded from the patch's own output — a subagent-built
   fixture seeded from the output under test is circular and its green
   test lies. This is also why the gatekeeper re-derives the fix rather
   than trusting your patch's green tests (guardrail 1).

   **Filing convention (flow #485):** every `## 驗收` section you FILE
   must contain **at least one concrete executable command in fenced
   code** — narrative-only bullets leave the deterministic
   `acceptance_evidence_in_fix_comment_check` gate unable to bite (it
   then emits a named `ACCEPTANCE_NARRATIVE_ONLY` warning instead of
   biting, and the trace has to be audited manually). The intake check
   (`regression_issue_intake_check`) warns at filing time on
   zero-command acceptance sections.

   **Filing-time lint (flow #489):** ORGANIC-form issues never pass
   through the (network-only, template-gated) intake check — so the
   filing step is draft → lint → create:
   `python3 programs/organic_issue_body_lint.py <draft.md>` (or stdin
   `-`). Fix any `MISSING_ACCEPTANCE` / `ACCEPTANCE_NARRATIVE_ONLY` /
   `NO_DEFECT_ARTIFACT` warning (the last one points at the flow #487
   snapshot helper) BEFORE `gh issue create`.

4. **A published L document is the output of a PAST run — ask it which
   one.** (2026-07-28, #522.) On one day three issues were filed against
   `benchmark-data/**/generated_docs/L*.json` produced ~70 releases
   earlier and read as the current state of the flow; one was written by
   someone holding this exact rule in the brief they had just handed out.
   Discipline was not enough because the documents said nothing about
   their own vintage. They do now. RULE: before quoting a count from a
   published L document, calling a gate on it a blocker, or filing an
   issue whose premise is what it contains, run

   ```bash
   python3 programs/l_doc_generator_stamp.py <design-or-corpus-dir>
   ```

   `CURRENT` — same release and same L-doc taxonomy as your checkout;
   read it as current. `STALE` / `NEWER` — the report gives the version
   distance. `UNSTAMPED` — produced before the stamp existed, vintage
   unknown: **re-derive through the canonical entry before concluding
   anything**, and if you file anyway, say which version you measured.
   The same applies to your own audit of a `core-closed` fix: a
   `## 驗收` command run against a stale artefact reproduces the past,
   not the fix.

## Reference

- Handoff bundle admission gate: `programs/handoff_bundle_check.py`
- Layer roll-up probes (inner close-loop):
  `programs/phase1_verify_aggregate.py`,
  `programs/phase2_verify_aggregate.py`,
  `programs/phase3_verify_aggregate.py`, `programs/signoff_audit.py`
- Helper script: `programs/check_closed_for_field_audit.sh`
- Backlog YAML schema + sanitize: `vibe-ic:community-backlog-submit`
- Phase 1 deep review: `vibe-ic:phase1-completeness-deep-review`
- Compliance gate: `compliance.yaml` (run after producing
  state-file updates / verify comments)

## Compliance gate (mandatory)

After producing your verify comment or backlog YAML, save to a
file and run:

```bash
python3 <plugin_root>/_shared/skill_compliance_check.py \
    --requirements ./compliance.yaml <output_file>
```

Exit 0 = PASS, exit 1 = FAIL with missing elements listed. Patch
and re-run until PASS.
