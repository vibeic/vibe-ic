---
name: sta-review
description: Read Static Timing Analysis reports, triage setup/hold/recovery/removal violations, and propose fixes (RTL pipelining, sizing, useful skew, buffer insertion). Use when the user says "STA", "timing report", "timing violation", "setup fail", "hold fail", "close timing", "WNS", "TNS".
---

# STA Review

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt。
> Mandatory program preflight first; AI is the backstop, not the lead.

STA signoff runs in a commercial tool (PrimeTime, Tempus, OpenSTA). The
deterministic triage (5 endpoint categories → fix strategies) is now in
`programs/sta_triage_classify.py`; this skill is the wrapper that runs
it, narrates residual interpretation, and refuses to override the
program's category counts.

## Mandatory Deterministic Preflight

Before any narrative:

```bash
# 1. STA report audit (presence, WNS/TNS extraction, basic structure):
python3 plugins/vibe-ic/programs/sta_report_check.py \
    --rpt <sta.rpt> --json /tmp/sta_check.json

# 2. Endpoint categorisation (5 categories + fix strategy per category):
python3 plugins/vibe-ic/programs/sta_triage_classify.py \
    --endpoints-json <endpoints.json> \
    --wns <wns_ns> --tns <tns_ns> \
    --out-md /tmp/sta_triage.md --out-json /tmp/sta_triage.json
```

The program returns counts per category (cell_delay_limited /
net_delay_limited / logic_depth_limited / clock_skew_limited /
hold_violation) plus the fix strategy per category. **Do not author
these counts by reading the report.**

```bash
# 3. (when reviewing a PnR Tcl script) confirm the mandatory
#    setup-timing-repair sequence is present, not hold-fix-only:
python3 plugins/vibe-ic/programs/pnr_timing_repair_completeness_check.py \
    <pnr.tcl> --json /tmp/pnr_repair.json
```

`pnr_timing_repair_completeness_check.py` FAILs any OpenROAD PnR script
that runs only `repair_timing -hold` without `set_wire_rc` +
`repair_design` + `repair_timing -setup` (the sha256 silicon-DOA
anti-pattern). The phase3 runner already emits the full chain; this
gate is the static backstop when reviewing a hand-authored script.

## When to use

- After synthesis, after CTS, after routing, after ECO
- Any time WNS (Worst Negative Slack) or TNS (Total Negative Slack) goes positive
- When hold violations appear after routing
- Multi-corner sign-off (ss/tt/ff × low/high temp × low/high Vdd)

## Inputs

1. STA report(s) — setup + hold + recovery/removal + min-pulse-width
2. SDC constraints
3. Top violating paths (usually `-max_paths 100`)
4. Corner/mode matrix
5. Optional: RTL source for the violating module

## Workflow

1. **Categorize** every violating endpoint:
   - Cell delay limited → upsize driver, Vt swap
   - Net delay limited → insert buffer, reroute, shorten wire
   - Logic depth limited → pipeline / restructure RTL
   - Clock skew limited → useful skew, CTS re-balance
   - Hold → buffer insertion on min paths
2. **Propose fix per endpoint** with an estimated slack gain
3. **Flag paths that cannot be fixed by ECO** — require RTL change
4. **Cross-corner view**: if a path fails only at one corner, adjust margin first
5. **Summarize**: WNS/TNS before → after, number of endpoints touched

## Output format

- `sta/sta_review.md`:
  - Summary (WNS, TNS, #failing endpoints, corner)
  - Top 20 paths with classification + fix + slack delta
  - RTL change recommendations (handoff to `/rtl-repair`)
  - ECO fix list (handoff to `/eco-plan`)

## Technical basis

Static timing analysis is governed by setup/hold relationships around launch/capture flops. Standard references: Bhasker & Chadha "Static Timing Analysis for Nanometer Designs". OpenSTA is the open-source signoff-class engine (https://github.com/The-OpenROAD-Project/OpenSTA).

## Handoff

- RTL change → `/rtl-repair`
- Metal-only fix → `/eco-plan`
- Power impact of sizing → `/ir-drop-triage`

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/sta-review/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.


## Captured rule — PnR must run set_wire_rc + repair_design + repair_timing -setup (not hold-fix-only)

**Enforced by two programs — no longer prose judgment:**
- The full deterministic command sequence (`set_wire_rc -signal/-clock` with
  NONFATAL fallbacks → `estimate_parasitics` → `repair_design` →
  `repair_timing -setup` → `detailed_placement`; then post-CTS `repair_timing -hold`;
  then post-global-route re-estimate + repair) is **emitted by
  `programs/phase3_one_shot_runner.py`** (phase3 PnR template).
- **`programs/pnr_timing_repair_completeness_check.py`** is the static gate that
  FAILs any PnR script missing that chain (the hold-only silicon-DOA shape).

Worked example (kept for context): benchmark_clean/sha256 v0.1.25 post-route
WNS = -102.76 ns, mis-blamed on the SHA round; real cause was the missing
`set_wire_rc` / `repair_design` / `repair_timing -setup` (STA optimistic,
RSZ-0089). After adding the chain (v0.1.26): WNS = +10.95 ns MET on the same RTL.
General across all OpenROAD-driven PnR — template-level, not chip-specific.

_Captured by benchmark-enhancement-capture 2026-05-28; extracted to programs in M4._
