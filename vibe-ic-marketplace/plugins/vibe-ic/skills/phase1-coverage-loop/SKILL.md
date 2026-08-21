---
name: phase1-coverage-loop
description: Closed-loop field-agent for Phase 1 coverage. Rotates through a benchmark IC folder (e.g. 2nd_banchmark/) running /vibe-ic-phase1 on each IC's README/prompt, measures input→L1-L27 token completeness with phase1_input_vs_generated_completeness_check, and files chip-AGNOSTIC plugin backlog issues for systematic ingester gaps. Same 4-step pattern as field-agent-loop (review → file → monitor → verify) but targets Phase 1 (Path A) instead of Phase 1/2/3. Invoke as a cron prompt; loop self-advances until STOP CONDITION (full rotation passes + no open ORGANIC-phase1 issue).
---

# Phase 1 Coverage Loop — Closed-Loop Phase 1 Ingester Improvement

## Purpose

`field-agent-loop` covers Phase 1 / 2 / 3 — it drives plugin
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

`ic_rotation` construction and advance/wrap are **enforced by
`programs/phase1_rotation_state_advance.py`** (no longer hand-rolled):

```bash
# build the rotation (sorted immediate subdirs with README.md or input/prompt.md)
python3 programs/phase1_rotation_state_advance.py build --target <target> --json rot.json
# advance the index by one; wrap → rotation_passes_completed += 1
python3 programs/phase1_rotation_state_advance.py advance \
    --current-index <i> --count <len> --passes <p> --json adv.json
```

`current_ic_index` is the next IC to run.

## The four-step loop

### Step 0 — field-audit of core-closed issues (mandatory, before Step 1)

The core-agent now SELF-VERIFIES and CLOSES issues, tagging them
`core-closed`. The field-agent's job is to audit those closed issues
against the REAL benchmark and reopen any that do not hold up. Run
this BEFORE Step 1 every tick.

List CLOSED ORGANIC issues authored by me that carry `core-closed`
and LACK `field-verified` (these are the audit targets):

```bash
# Title matched LOCALLY, not via --search (vibe-ic#554): the search index
# returns 0 for this repository regardless of content, and here that reads as
# "no audit targets" — the same substitution as the STOP clause below, with a
# quieter consequence. `--label` and `--state` are server-side FILTERS rather
# than index queries and are fine.
gh issue list --repo vibeic/vibe-ic --state closed \
    --author "@me" --label core-closed --limit 1000 \
    --json number,title,labels \
  | python3 -c 'import sys,json; \
print("\n".join(str(i["number"]) for i in json.load(sys.stdin) \
  if "ORGANIC-phase1" in i["title"] \
  and "field-verified" not in [l["name"] for l in i["labels"]]))'
```

For each such issue, dispatch a fresh verify agent scoped to it,
run against the REAL benchmark, then:

1. **VERIFIED ok** → add label `field-verified` (issue stays CLOSED).
   Terminal — do not re-audit on later ticks.
2. **NOT adequate** → `gh issue reopen` + post the counter-evidence
   comment + remove the `core-closed` label. The issue is now OPEN
   and the core-agent is actionable on it again.

Non-negotiable. An un-audited `core-closed` issue is the only thing
standing between a claimed fix and a verified one.

### Step 1 — review

Run when `agent_task_id` is null OR the prior agent task is
completed/failed.

```bash
cd /home/<user>/AI_IC_design/vibe-ic-marketplace && git pull --ff-only
cd /home/<user>/AI_IC_design/mcp-eda         && git pull --ff-only
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
   `<repo_root>/vibe-ic-marketplace/community/backlogs/ORGANIC-phase1-<YYYYMMDD>-<slug>.yaml`
   (ORGANIC #794 — this used to read `<plugin_root>/community/backlogs/`,
   which resolves to `plugins/vibe-ic/community/backlogs/` and does not
   exist. That is the ONE directory `agent_checkin_scope_guard.ZONE_BACKLOG`
   and the `--audit tracked` hygiene gate watch.)
   using the schema in the `community-backlog-submit` skill. The
   `severity` field is **enforced by
   `programs/backlog_severity_classify.py`** (HIGH iff any affected
   layer is L3/L4/L8/L9 structural-RTL, MEDIUM otherwise):
   ```bash
   python3 programs/backlog_severity_classify.py --layers <L4,L2,...>
   ```
   (the *which layer should have caught this token* call is the Step 1
   review's job; the HIGH/MEDIUM verdict is mechanical).
2. Sanitize:
   ```bash
   python3 <plugin_root>/programs/backlog_sanitize_check.py \
       --file <yaml>
   ```
   If `pass: false` → fix the flagged literal, re-sanitize.
3. File the GitHub issue (NO confirmation prompt):
   ```bash
   gh issue create --repo vibeic/vibe-ic \
       --title "ORGANIC-phase1: <title>" \
       --body "$(cat <yaml>)"
   ```
4. Save `state.issue_number = <primary>`,
   `tracking_secondary = [<others>]`, `state.step = 3`.

For multiple gaps in one review: file each as a separate issue.
First filed becomes primary; rest go into `tracking_secondary`.

### Step 3 — monitor

`gh issue view <issue_number>` and watch for any of:
- the issue becomes CLOSED with label `core-closed` (the core-agent
  self-verified and closed it)
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

The core-agent has already self-verified and CLOSED the issue with
`core-closed`. This step is the field-audit of that closed issue.
Two outcomes:

- **VERIFIED** → post a verify comment ending with the line
  `Adding `field-verified`.`, add label `field-verified` (issue stays
  CLOSED — terminal), `state.step = 1`, `state.agent_task_id = null`.
- **NOT VERIFIED** → `gh issue reopen`, post a counter-evidence
  comment with the exact failing token AND a concrete suggested-fix
  line, ending with `Reopening; removing `core-closed`.`, remove the
  `core-closed` label, keep issue OPEN, `state.step = 3`.

### STOP CONDITION

The three-clause STOP boolean (`rotation_passes_completed >= 2` AND
zero OPEN `ORGANIC-phase1-*` issues AND last rotation all-PASS/SKIP) is
**enforced by `programs/phase1_loop_stop_condition_check.py`**. Run the
`gh` query to get the open-issue count, then let the program decide:

```bash
# NOT `gh issue list --search` (vibe-ic#554). `--search` routes through
# GitHub's search INDEX, which returns 0 for this repository regardless of
# content. Positive control, measured:
#     --search "Actions in:title" --state open  ->  0    WRONG (#550 is open
#                                                          and has it in the title)
#     list + filter locally                     ->  1    correct
# A broken query and a finished job then produce the same number, and that
# number IS the STOP decision.
#
# `|| exit 1` is load bearing: the counter exits 2 when it could not count,
# and passing an empty or zero N on a FAILED measurement satisfies clause (2)
# — the exact substitution this is about. CONTINUE is the safe direction; a
# loop that runs one extra round costs a round, a loop that stops early
# reports the work as finished.
N=$(python3 programs/open_organic_issue_count.py "ORGANIC-phase1") || exit 1
python3 programs/phase1_loop_stop_condition_check.py \
    --state <state.json> --open-organic-issues "$N"
# exit 0 = STOP, exit 1 = CONTINUE, exit 2 = bad state
```

On STOP (exit 0):

```bash
CronList     # find this cron's id
CronDelete <id>
echo "STOP cron — Phase 1 coverage closed on rotation pass <N>."
```

Set `state.step = "STOPPED"` and exit.

## Constraints (non-negotiable)

- **KEEP YOUR TURN ALIVE TO COMPLETION.** Run any long tool through the
  BLOCKING call (e.g. `_watchdog.run_supervised`, which returns only on exit or
  stall), never a detached `timeout … &` fire-and-forget followed by yielding.

  This skill had neither this rule nor the fact below, and it is a LOOP skill —
  the shape most likely to invite "I'll yield and pick it up next round"
  (vibe-ic#558). An agent did exactly that on a still-running Phase-3 flow,
  saying it would "yield until the harness re-invokes me". Nothing did.
  `claude -p` is one-shot, so all three of its justifications are impossible:

  * *"the harness will re-invoke me when the background job exits"* — nothing
    re-invokes a finished turn. There is no such mechanism.
  * *"a background waiter is armed to fire"* — a waiter can only wake a turn
    that is STILL ALIVE. It cannot start a new one.
  * *"the monitor will fire"* — a monitor notifies the DISPATCHER, not you. It
    cannot resume you. Step 3 of this loop arms exactly such a monitor, which
    is precisely why the belief is available here.

  Yielding does not pause your turn; it ENDS it, and your "then write the
  result" step never runs.

- **NO RTL ORACLE**: never inspect `<ic>/rtl/` when scoring Phase 1
  coverage. The Phase 1 ingester must derive structure from the
  prompt alone.
- **Chip-AGNOSTIC backlog**: the literal-ban deny-list is **enforced
  by `programs/backlog_sanitize_check.py`** — every YAML must pass it
  before filing. Cite the missing token *pattern* (e.g. "register-table
  row of form `<addr> | <name> | <desc>`"), not the specific token
  (`0x40 | PWR_CTRL | ...`). (Backlog note: the sanitizer's deny-list
  does not yet include the open-source RISC-V core codenames
  picorv32 / ibex / cv32e40p / neorv32 / darkriscv / serv / VexRiscv
  nor EE628 / DeltaSigma — these are still caught only by author
  discipline until that augment lands.)
- **File GENERAL ingester gaps**, never chip-specific bugs. The
  user owns chip-specific fixes; the field-agent owns Phase 1
  ingester generality.
- **No y/n confirmation**: file issues directly. Do not ask.
- **Sanitize before file**: every YAML, every time.
- **Honour the gate's SKIP verdicts**: the `SKIP_REFERENCE`
  (reference / vendor PDK manual) and `SKIP_LOW_TOKENS`
  (<10 design tokens) verdicts are **emitted by
  `phase1_input_vs_generated_completeness_check.py`**. When the gate
  returns either, record the IC as SKIP for the rotation and do NOT
  file an issue — the loop consumes the gate's verdict, it does not
  re-derive the skip rule.

## Coverage gate thresholds

The verdict thresholds (FAIL < 50% with >=10 tokens, WARN 50–80%,
PASS >= 80%, plus the SKIP family) are **enforced by
`programs/phase1_input_vs_generated_completeness_check.py`** — the loop
consumes its JSON `verdict`/`captured_pct` rather than re-stating the
numeric bounds. (Looser than phase1's 100% because Phase 1 is
interpretation, not extraction — see that program's file header for the
rationale.) The loop files ORGANIC backlog only when:

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
would describe to the IC Expert Agent). After Phase 1 emits, run
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

## Deterministic programs this loop drives

The orchestration mechanics are deterministic and live in programs —
the prose above defers to them, it does not re-implement them:

- `programs/phase1_rotation_state_advance.py` — rotation build +
  index advance/wrap.
- `programs/phase1_loop_stop_condition_check.py` — three-clause STOP
  boolean.
- `programs/backlog_severity_classify.py` — HIGH/MEDIUM layer lookup.
- `programs/phase1_input_vs_generated_completeness_check.py` — coverage
  verdict + thresholds + SKIP_REFERENCE / SKIP_LOW_TOKENS.
- `programs/backlog_sanitize_check.py` — chip-AGNOSTIC literal-ban.

Step 0's audit-target list (CLOSED ORGANIC issues carrying
`core-closed` but lacking `field-verified`) is a plain `gh issue list`
query — see the Step 0 snippet above; there is no dedicated program for
it.

## Reference

- Backlog YAML schema + sanitize: `vibe-ic:community-backlog-submit`
- Sibling skill (Phase 1 / 2 / 3): `vibe-ic:field-agent-loop`
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
