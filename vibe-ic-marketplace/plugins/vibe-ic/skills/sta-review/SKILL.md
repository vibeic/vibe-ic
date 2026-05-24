---
name: sta-review
description: Read Static Timing Analysis reports, triage setup/hold/recovery/removal violations, and propose fixes (RTL pipelining, sizing, useful skew, buffer insertion). Use when the user says "STA", "timing report", "timing violation", "setup fail", "hold fail", "close timing", "WNS", "TNS".
---

# STA Review

STA signoff runs in a commercial tool (PrimeTime, Tempus, OpenSTA). This skill reads the report, classifies violations, and proposes the minimum-churn fix — keeping senior engineers focused on hard paths.

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
