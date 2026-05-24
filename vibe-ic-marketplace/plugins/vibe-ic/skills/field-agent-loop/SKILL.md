---
name: field-agent-loop
description: Closed-loop field-agent that drives plugin quality improvements by running phase1/phase2/phase3 on benchmark IC projects, filing ORGANIC backlog issues for systematic plugin gaps, and verifying fixes the core-agent ships back. Invoke as a cron prompt with a target benchmark folder and an LLM-review prompt; the loop self-advances through review → file → monitor → verify until STOP CONDITION (no new gaps + no open primary/secondary issue).
---

# Field-Agent Loop — Closed-Loop Plugin Quality Improvement

## Purpose

The field-agent is the **organic improvement engine** for the
vibe-ic plugin. It treats real IC benchmark projects as a test
harness: re-run the plugin at HEAD, ask a fresh LLM to compare
source docs against generated output, and convert every
systematic gap it finds into a structured backlog issue. When the
core-agent ships a fix, the field-agent verifies it on the actual
benchmark — not on the unit test fixtures — and closes the loop.

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

### Step 3 — monitor

`gh issue view <issue_number>` and watch for any of:
- label `wait-for-verification` appears
- plugin version advances past `state.last_plugin_version`
- maintainer comment

Either trigger → `state.step = 4`.

If plugin version bumps for an unrelated track (e.g. PnR fixes
on a phase1 issue), just update `state.last_plugin_version` to
the new version and stay in step 3.

### Step 4 — verify

**Re-dispatch a fresh general-purpose Agent** (not the original
task — must be a clean context) with a verify prompt that:
- names the specific issue + the v1.6.x test file that ships the
  fix
- clean-wipes the affected benchmark IC(s) and re-runs phase1/
  phase2/phase3 as needed
- inspects the load-bearing fields the fix touches
- reports PASS criteria objectively
- spot-checks the unaffected ICs for regression

Two outcomes:

- **VERIFIED** → post a verify comment, `gh issue close`, remove
  `wait-for-verification` label, `state.step = 1`,
  `state.agent_task_id = null`.
- **NOT VERIFIED** → post a counter-evidence comment with the
  exact failing field/value AND a concrete suggested-fix line,
  remove `wait-for-verification` label (so core-agent re-engages
  on a fresh slice), keep issue OPEN, `state.step = 3`.

### STOP CONDITION

At Step 1: if the fresh review agent reports **STOP_RECOMMENDATION: YES**
(no new gaps AND no open primary/secondary issue), then:

```bash
CronList  # find this cron's id
CronDelete <id>
echo "STOP cron."
```

Exit.

## The deterministic wait-for-verification rule

The cron MAY have filed issues across multiple field-agent
sessions (e.g. one cron's verify shipped the slice for a
neighbouring cron's umbrella issue). Without an explicit cross-
check, the loop drifts: it monitors only its own primary issue
and misses `wait-for-verification` on others.

**Therefore: at every cron tick, BEFORE Step 1, run:**

```bash
plugins/vibe-ic/skills/field-agent-loop/programs/check_wait_for_verification.sh
```

(The script is bundled with this skill.)

It returns the list of all OPEN ORGANIC issues authored by you
that currently carry `wait-for-verification`. For each:

1. Dispatch a verify agent scoped to that issue.
2. On VERIFIED → close + remove label.
3. On NOT VERIFIED → comment counter-evidence + remove label.

This is **non-negotiable**: an unattended `wait-for-verification`
label means a core-agent slice is stalled waiting for your gate.

## Constraints (non-negotiable)

- **NO RTL ORACLE**: never inspect `input/rtl/` or any generated
  RTL when assessing input-doc-only extractors. The plugin must
  derive structure from input docs.
- **Chip-AGNOSTIC backlog**: every YAML must pass
  `backlog_sanitize_check`. No `example_chip`, `benchmark_a`, `example_vendor`,
  `example_tester`, `aid`, vendor IC names, or project paths in the
  title/pattern/suggested_fix.
- **Field-agent files GENERAL plugin gaps**, never chip-specific
  bugs. The user owns chip-specific fixes; the field-agent owns
  plugin generality.
- **No y/n confirmation**: file issues directly. Do not ask.
- **Sanitize before file**: every YAML, every time, even when
  you're sure it's clean.

## Cron-invocation template

```
<short-name>-field-agent

You are the field-agent loop for <target>. State at
<target>/_field_agent_state.json.

[paste the four-step loop above, adapted to the target intent]

LLM-review prompt body (Step 1):
"<paste the prompt that names the target ICs, the runner, the
 known-closed gap IDs, and the report cap>"
```

Save this prompt as the CronCreate `prompt` field; pick a 4–6
minute interval; field-agent self-paces from there.

## Reference

- Helper script: `programs/check_wait_for_verification.sh`
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
