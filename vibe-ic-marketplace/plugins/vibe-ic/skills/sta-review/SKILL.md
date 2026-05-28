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

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
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


## Captured by benchmark-enhancement-capture — 2026-05-28 (RTLLM Shape B + benchmark_clean + CVDP cross-step capture)

### Skill: PnR must run set_wire_rc + repair_design + repair_timing -setup, not just hold-fix

**Pattern**: After yosys synth, OpenROAD PnR with ONLY `repair_timing -hold` leaves high-fanout control nets (reset_n, FSM state-decode, enable nets driving hundreds of flops) on zero-strength gates with no buffer tree. Result: post-route critical path can show single-gate delays of TENS-to-HUNDREDS of ns from interconnect-RC alone — even when synth was fine. Worse, without `set_wire_rc`, STA also ignores wire delay, so the violation may not surface until silicon.

**When to apply**: Authoring or reviewing any PnR script that targets OpenROAD on sky130 / gf180 (or any PDK without commercial-DC sign-off). Whenever a runner template only has `repair_timing -hold`.

**What to do**: After `read_liberty` + `read_verilog` + `link_design` + `read_sdc`, ALWAYS run, in this order:
  - `set_wire_rc -signal -layer met1` (with fallback to bare `set_wire_rc -layer met1` if `-signal` unsupported; NONFATAL guard)
  - `set_wire_rc -clock -layer met5` (NONFATAL guard)
  - `estimate_parasitics -placement`
  - `repair_design`
  - `repair_timing -setup`
  - `detailed_placement` (legalize after repair)
Then post-CTS run `repair_timing -hold` as usual. After global_route, re-run `estimate_parasitics -global_routing` + `repair_design` + `repair_timing -setup` + `repair_timing -hold`.

**Worked example** (from sha256): benchmark_clean/sha256 v0.1.25: post-route WNS = -102.76 ns (VIOLATED) attributed (wrongly) to single-cycle SHA round. Real root cause: PnR template had no `set_wire_rc` (STA optimistic, repair_timing -setup aborted with RSZ-0089) and no `repair_design`/`repair_timing -setup` at all. After adding the chain above (v0.1.26), WNS = +10.95 ns MET on the SAME RTL.

**Why this is GENERAL**: Universal across OpenROAD-driven PnR. Every IC class (digital primitive, SoC, DSP, FSM-heavy) suffers from unbuffered high-fanout nets when only hold-repair runs. The fix is template-level, not chip-specific.

_Captured by benchmark-enhancement-capture 2026-05-28._
