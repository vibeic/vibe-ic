---
name: field-agent-loop
description: Closed-loop field-agent that drives plugin quality improvements by running phase1/phase2/phase3 on benchmark IC projects, filing ORGANIC backlog issues for systematic plugin gaps, and AUDITING the fixes the core-agent self-verifies and CLOSES. Invoke as a cron prompt with a target benchmark folder and an LLM-review prompt; every tick the loop first audits CLOSED `core-closed` issues against the real benchmark (VERIFIED → add `field-verified`, NOT adequate → `gh issue reopen` + remove `core-closed`), then self-advances through review → file → monitor → audit until STOP CONDITION (no new gaps + no open primary/secondary issue + no un-audited closed issue).
---


<!-- WAVE_76_CHIP_AGNOSTIC_BANNER -->

> **Case-study notation.** This skill cites the IC-A / USB-HID tester /
> MDV-A1101 BENCH-A reference project as concrete evidence for the
> rules below. The rules themselves are chip-AGNOSTIC and apply to
> any IC of the matching `ic_class` (see
> `vibe-ic-marketplace/plugins/vibe-ic-d/programs/ic_class_profile.py`).
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
  "last_summary": "<one paragraph>"
}
```

## The four-step loop

### Step 1 — review

Run when `agent_task_id` is null OR the prior agent task is
completed/failed.

```bash
cd /home/user/AI_IC_design/vibe-ic-marketplace && git pull --ff-only
cd /home/user/AI_IC_design/mcp-eda-server         && git pull --ff-only
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

### Step 2 — file

When the dispatched agent reports concrete quality gaps:

1. For the top gap, write
   `<plugin_root>/community/backlogs/ORGANIC-<YYYYMMDD>-<slug>.yaml`
   using the schema in the `community-backlog-submit` skill.
2. Sanitize:
   ```bash
   python3 <plugin_root>/programs/backlog_sanitize_check.py \
       --file <yaml>
   ```
   If `pass: false` → fix the flagged literal, re-sanitize.
3. File the GitHub issue (NO confirmation prompt):
   ```bash
   gh issue create --repo reyerchu/AI_IC_design \
       --title "ORGANIC: <title>" \
       --body "$(cat <yaml>)"
   ```
4. Save `state.issue_number = <primary>`,
   `tracking_secondary = [<others>]`, `state.step = 3`.

For multiple gaps in one review: file each as a separate issue.
First filed becomes primary; rest go into `tracking_secondary`.

### Step 3 — monitor (until core closes)

`gh issue view <issue_number>` and watch for any of:
- the issue transitions to **CLOSED** with label `core-closed`
  (the core-agent self-verified + closed it)
- plugin version advances past `state.last_plugin_version`
- maintainer comment

The issue going CLOSED+`core-closed` is the primary trigger →
`state.step = 4` (the audit step). The closed-audit rule below
will pick the issue up regardless, but advancing the tracked
issue's step keeps the state file honest.

If plugin version bumps for an unrelated track (e.g. PnR fixes
on a phase1 issue), just update `state.last_plugin_version` to
the new version and stay in step 3.

### Step 4 — audit (verify the closed fix, reopen if inadequate)

**Re-dispatch a fresh general-purpose Agent** (not the original
task — must be a clean context) with an audit prompt that:
- names the specific issue + the v1.6.x test file that ships the
  fix
- clean-wipes the affected benchmark IC(s) and re-runs phase1/
  phase2/phase3 as needed against the **real benchmark**
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
The field-agent no longer waits for any `wait-for-verification`
label — that label is **RETIRED**; the field audits CLOSED issues
instead.

## Constraints (non-negotiable)

- **NO RTL ORACLE**: never inspect `input/rtl/` or any generated
  RTL when assessing input-doc-only extractors. The plugin must
  derive structure from input docs.
- **Chip-AGNOSTIC backlog**: every YAML must pass
  `backlog_sanitize_check`. No `ic-a`, `bench-a`, `vendor`,
  `usb_hid_tester`, `aid`, vendor IC names, or project paths in the
  title/pattern/suggested_fix. The authoritative deny-list lives
  in `tests/chip_deny_list.txt`.
- **Field-agent files GENERAL plugin gaps**, never chip-specific
  bugs. The user owns chip-specific fixes; the field-agent owns
  plugin generality.
- **No y/n confirmation**: file issues directly. Do not ask.
- **Sanitize before file**: every YAML, every time, even when
  you're sure it's clean.

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
  retry.

- **Never abandon a background runner that still holds a project.**
  Before handing a project to a successor agent (or before STOP), the
  driving agent MUST either `wait` for its background runner to finish
  or `kill` it. An abandoned, still-alive background runner keeps its
  lock and will (correctly) refuse the successor — and worse, if the
  lock is force-removed, both runners co-write and the run record is
  silently corrupted.

- **The double-driver incident (generic).** In a real campaign an
  orphaned background runner was left driving a project while the cron
  advanced and a successor agent launched a fresh runner on the SAME
  project; both wrote logs / manifests / provenance concurrently. There
  was no refusal mechanism, so the corruption went unnoticed until the
  artifacts were audited. The single-driver lock above is the
  deterministic fix; the operational rule is: account for every
  background runner you spawn — wait or kill — before relinquishing a
  project.

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

## Reference

- Helper script: `programs/check_closed_for_field_audit.sh`
- Backlog YAML schema + sanitize: `vibe-ic:community-backlog-submit`
- Phase2a deep review: `vibe-ic:phase1-completeness-deep-review`
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
