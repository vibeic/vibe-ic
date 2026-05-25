---
name: phase1-coverage-loop
description: Closed-loop field-agent for Phase 1 coverage. Rotates through a benchmark IC folder (e.g. 2nd_banchmark/) running /vibe-ic-phase1 on each IC's README/prompt, measures input→L1-L13 token completeness with phase1_input_vs_generated_completeness_check, and files chip-AGNOSTIC plugin backlog issues for systematic ingester gaps. Same 4-step pattern as field-agent-loop (review → file → monitor → verify) but targets Phase 1 (Path A) instead of Phase 2a/2b/3. Invoke as a cron prompt; loop self-advances until STOP CONDITION (full rotation passes + no open ORGANIC-phase1 issue).
---

# Phase 1 Coverage Loop — Closed-Loop Phase 1 Ingester Improvement

## Purpose

`field-agent-loop` covers Phase 2a / 2b / 3 — it drives plugin
quality on the **existing-design-documents** entry path. This
sibling skill closes the same loop for the **prompt/dialogue
entry path** (Phase 1).

The loop treats benchmark IC README files as realistic Phase 1
prompts: an experienced user briefing the platform would mention
the same facts the README documents (clock rate, supply voltage,
register addresses, pin names, opcodes, timing). After running
`/vibe-ic-phase1` on each IC, the completeness gate harvests
chip-AGNOSTIC design tokens from the prompt and verifies each
token survived into `generated_docs/L*.json`, `human_docs/L*.md`,
`facts.yaml`, or `PROVENANCE.md`. Missing tokens are systematic
ingester gaps — they become backlog issues.

The loop is **chip-AGNOSTIC**: filed issues describe general
ingester gaps (e.g. "NL ingester drops `<pattern>` register-table
rows"), never project-specific bugs. Every YAML passes
`backlog_sanitize_check` before filing.

## State

```
<target>/_field_agent_phase1_state.json
```

Schema:

```json
{
  "step": 1 | 2 | 3 | 4 | "STOPPED",
  "iter": <int>,
  "started_at": "<YYYY-MM-DD>",
  "target_folder": "<absolute path to benchmark folder>",
  "ic_rotation": ["<ic_name>", "<ic_name>", ...],
  "current_ic_index": <int>,
  "rotation_passes_completed": <int>,
  "last_plugin_version": "<semver>",
  "agent_task_id": "<id or null>",
  "agent_status": "<short status string>",
  "issue_number": <int or null>,
  "tracking_secondary": [<int>, ...],
  "per_ic_last_verdict": {"<ic_name>": "PASS|WARN|FAIL|SKIP", ...},
  "last_summary": "<one paragraph>"
}
```

`ic_rotation` is the sorted list of immediate subdirectories of
`<target>` that contain a `README.md` (or `input/prompt.md`).
`current_ic_index` is the next IC to run. Rotation advances
deterministically; `rotation_passes_completed` increments every
time `current_ic_index` wraps back to 0.

## The four-step loop

### Step 0 — verify-debt check (mandatory, before Step 1)

```bash
plugins/vibe-ic/skills/field-agent-loop/programs/check_wait_for_verification.sh
```

(Same script as field-agent-loop — reused unchanged.)

For every OPEN ORGANIC issue with `wait-for-verification` whose
title contains `phase1` or `Phase 1` or `ORGANIC-phase1`:

1. Dispatch a verify agent scoped to that issue.
2. On VERIFIED → close + remove label.
3. On NOT VERIFIED → comment counter-evidence + remove label.

Non-negotiable. Unattended `wait-for-verification` = stalled
core-agent slice.

### Step 1 — review

Run when `agent_task_id` is null OR the prior agent task is
completed/failed.

```bash
cd /home/<user>/AI_IC_design/vibe-ic-marketplace && git pull --ff-only
cd /home/<user>/AI_IC_design/mcp-eda-server         && git pull --ff-only
```

Check `plugins/vibe-ic/.claude-plugin/plugin.json` version. Update
`state.last_plugin_version` if it advanced.

Pick the next IC from `state.ic_rotation[state.current_ic_index]`.

Dispatch a **fresh general-purpose Agent** with a prompt that:

- Names the target IC: `<target>/<current_ic>`
- Locates the Phase 1 prompt: prefer `input/prompt.md`, else
  fall back to `README.md`
- Runs `/vibe-ic-phase1` on the prompt (NL mode) — produces
  `<ic>/generated_docs/L*.json` + `<ic>/human_docs/L*.md` +
  `<ic>/facts.yaml`
- Runs the deterministic coverage gate:
  ```bash
  python3 plugins/vibe-ic/programs/phase1_input_vs_generated_completeness_check.py <ic>
  ```
- Inspects the FAIL/WARN missing-token sample and asks: *are these
  systematic NL-ingester gaps the plugin should learn to handle?*
- Caps response length (≤800 words)
- Explicitly lists already-closed gap IDs the agent must NOT
  re-report (read `community/backlogs/` for `ORGANIC-phase1-*`)

Save the dispatched agent's task id; set `agent_status=running`.

When the agent returns, advance `current_ic_index = (current_ic_index + 1) % len(ic_rotation)`.
If it wrapped to 0, increment `rotation_passes_completed`.

### Step 2 — file

When the review agent reports concrete systematic gaps:

1. For the top gap, write
   `<plugin_root>/community/backlogs/ORGANIC-phase1-<YYYYMMDD>-<slug>.yaml`
   using the schema in the `community-backlog-submit` skill. Set
   `severity: HIGH` if the missing tokens are in an L3/L4/L8/L9
   layer (structural-RTL-affecting), `MEDIUM` otherwise.
2. Sanitize:
   ```bash
   python3 <plugin_root>/programs/backlog_sanitize_check.py \
       --file <yaml>
   ```
   If `pass: false` → fix the flagged literal, re-sanitize.
3. File the GitHub issue (NO confirmation prompt):
   ```bash
   gh issue create --repo reyerchu/AI_IC_design \
       --title "ORGANIC-phase1: <title>" \
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

If plugin version bumps for an unrelated track, update
`state.last_plugin_version` and stay in step 3.

### Step 4 — verify

**Re-dispatch a fresh general-purpose Agent** with a verify prompt
that:
- names the specific issue + the v1.6.x test file shipping the fix
- clean-wipes `<ic>/generated_docs/` `<ic>/human_docs/` `<ic>/facts.yaml`
  `<ic>/reports/` for the affected IC(s)
- re-runs `/vibe-ic-phase1` + `phase1_input_vs_generated_completeness_check`
- inspects the load-bearing fields the fix touches
- reports PASS criteria objectively (exact captured_pct before vs after)
- spot-checks one OTHER IC in the rotation for regression
  (re-run the gate; verdict must not have got worse)

Two outcomes:

- **VERIFIED** → post verify comment, `gh issue close`, remove
  `wait-for-verification` label, `state.step = 1`,
  `state.agent_task_id = null`.
- **NOT VERIFIED** → post counter-evidence comment with the exact
  failing token AND a concrete suggested-fix line, remove
  `wait-for-verification` label, keep issue OPEN, `state.step = 3`.

### STOP CONDITION

At Step 1, before dispatching: if BOTH
- `state.rotation_passes_completed >= 2` (every IC has been
  audited at least twice — first pass to find gaps, second pass
  to confirm fixes landed), AND
- no OPEN `ORGANIC-phase1-*` issue exists
  (`gh issue list --search "ORGANIC-phase1 in:title" --state open`
  returns empty), AND
- last full rotation's per-IC verdict was PASS or SKIP for every IC

then:

```bash
CronList     # find this cron's id
CronDelete <id>
echo "STOP cron — Phase 1 coverage closed on rotation pass <N>."
```

Set `state.step = "STOPPED"` and exit.

## Constraints (non-negotiable)

- **NO RTL ORACLE**: never inspect `<ic>/rtl/` when scoring Phase 1
  coverage. The Phase 1 ingester must derive structure from the
  prompt alone.
- **Chip-AGNOSTIC backlog**: every YAML must pass
  `backlog_sanitize_check`. No `picorv32`, `ibex`, `cv32e40p`,
  `neorv32`, `darkriscv`, `serv`, `VexRiscv`, `EE628`,
  `DeltaSigma`, vendor IC names, or project paths in the
  title/pattern/suggested_fix. Cite the missing token *pattern*
  (e.g. "register-table row of form `<addr> | <name> | <desc>`"),
  not the specific token (`0x40 | PWR_CTRL | ...`).
- **File GENERAL ingester gaps**, never chip-specific bugs. The
  user owns chip-specific fixes; the field-agent owns Phase 1
  ingester generality.
- **No y/n confirmation**: file issues directly. Do not ask.
- **Sanitize before file**: every YAML, every time.
- **Honour reference-doc skip**: if the gate returns
  `SKIP_REFERENCE` (DE10-Lite / vendor PDK manual), the IC is
  recorded as SKIP for the rotation; do not file an issue.
- **Honour low-tokens skip**: if a README has <10 design tokens
  (e.g. the `U_Hawaii_EE628_DeltaSigma_ADC/README.md` is 7 lines),
  treat as SKIP; do not file an issue blaming the ingester for
  insufficient input.

## Coverage gate thresholds

The deterministic gate
(`phase1_input_vs_generated_completeness_check.py`) uses:

- FAIL if captured_pct < 50% AND distinct_tokens >= 10
- WARN if 50% <= captured_pct < 80%
- PASS if captured_pct >= 80%

These are looser than phase1's 100% (Phase 1 is interpretation,
not extraction — see program file header for rationale). The
loop files ORGANIC backlog only when:

- Verdict is FAIL (clearly broken), OR
- Verdict is WARN AND missing tokens cluster around a recognisable
  pattern (e.g. all the missing tokens are register addresses
  from a Markdown table — that's a single ingester gap worth
  fixing).

## Cron-invocation template

```
phase1-coverage-field-agent

You are the Phase 1 coverage field-agent loop for
/home/<user>/AI_IC_design/2nd_banchmark/. State at
2nd_banchmark/_field_agent_phase1_state.json.

[paste the four-step loop above]

LLM-review prompt body (Step 1):
"Run /vibe-ic-phase1 on the IC at <path>. Use README.md as the
prompt (it is the closest stand-in for what an experienced user
would describe to the PM Agent). After Phase 1 emits, run
`python3 vibe-ic-marketplace/plugins/vibe-ic/programs/phase1_input_vs_generated_completeness_check.py <path>`.
Read the per-layer hits, the missing-token sample, and the
verdict. Then report:

  1. Coverage verdict + captured_pct (one line)
  2. Up to 5 systematic ingester gaps. For each: the token pattern,
     which L layer should have caught it, and a one-sentence
     hypothesis for which ingester step missed it. NO chip-specific
     bug reports — describe the pattern, not the value.
  3. STOP_RECOMMENDATION: YES if pct >= 95% AND no systematic
     pattern in missing tokens; NO otherwise.

Cap at 800 words. Already-closed gap IDs you must NOT re-report:
<list current ORGANIC-phase1-* slugs>."
```

Save the prompt as the CronCreate `prompt` field; pick a 5–7
minute interval (Phase 1 NL ingest + render takes longer than
phase1 — give the dispatched agent room to finish).

## Reference

- Reused helper: `field-agent-loop/programs/check_wait_for_verification.sh`
- Paired deterministic gate: `programs/phase1_input_vs_generated_completeness_check.py`
- Backlog YAML schema + sanitize: `vibe-ic:community-backlog-submit`
- Sibling skill (Phase 2a / 2b / 3): `vibe-ic:field-agent-loop`
- Phase 1 entry point: `vibe-ic:phase1`

## Compliance gate (mandatory)

After producing your verify comment or backlog YAML, save to a
file and run:

```bash
python3 <plugin_root>/_shared/skill_compliance_check.py \
    --requirements ./compliance.yaml <output_file>
```

Exit 0 = PASS, exit 1 = FAIL with missing elements listed. Patch
and re-run until PASS.
