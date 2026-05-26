---
name: drc-fix
description: Diagnose and fix Design Rule Check (DRC) violations in a layout or GDS. Use when the user says "fix DRC", "DRC clean", "resolve spacing errors", "my layout fails DRC", or shares a DRC report from Calibre, Klayout, or Magic.
---

# DRC Fix

Take a DRC report and a layout, and produce a targeted fix plan — which rules are violated, where, why, and the minimal edits to clean them. Handles common rule families: spacing, width, density, via enclosure, antenna, and metal fill.

## When to use

Trigger when the user:
- Has a DRC report with non-zero violations
- Is near sign-off and needs layout clean
- Asks which violations are real vs waiver candidates
- Needs help interpreting cryptic rule names

## Inputs to gather

1. The DRC report (Calibre, KLayout, Magic, or equivalent)
2. The layout file (GDS/OAS) or at least the affected cells
3. The PDK DRC manual or rule deck name
4. Sign-off target: zero violations or rule-by-rule exceptions allowed

## Fix workflow

1. **Group by rule** — 1000 violations are usually 5 root causes
2. **Classify severity** — hard (will fail fab) vs soft (waiverable)
3. **Map rule to fix pattern** — spacing → move or add jog; width → widen or replace; density → add fill; antenna → add diode or jumper
4. **Propose minimal edit** — smallest layout change that clears the rule
5. **Check for collateral damage** — does the fix create a new violation or break LVS?
6. **Emit fix script** — KLayout Python, SKILL, or TCL snippet when applicable

## Output format

```
# DRC Fix Plan — <block>

Total violations: N → grouped into M root causes

## Root causes
| # | Rule | Count | Root cause | Fix strategy |
|---|------|-------|------------|--------------|
| 1 | M2.S.1 | 47 | std-cell row abutment on narrow pitch | add 1-track jog on M2 egress |
| 2 | ANT.1  | 12 | long M3 antenna to gate | insert diode at sink |
| ... |

## Fix order (apply in sequence)
1. ...
2. ...

## Expected residual
After applying the plan, residual violations: ~<n> (list each with waiver rationale or further fix)

## Verification
Re-run DRC on <list of affected cells>.
```

## Technical basis

Grounded in DRC-Coder and LLM-assisted layout repair research. Key insight: DRC reports are structured logs, and the mapping from rule violation → fix pattern is largely a classification problem that LLMs handle well when given the rule deck.

## Do not

- Do not propose fixes that break LVS (especially for antenna diodes — maintain connectivity)
- Do not waive hard rules without explicit user approval
- Do not touch cells outside the block boundary without flagging it

## ⛔ ECO spare-cell preservation (mandatory)

> ⛔ **ECO spare-cell preservation:** cells/gates/pads carrying the `dont_touch` /
> `keep` attribute (or otherwise tagged spare/ECO) are RESERVED for a future
> metal-only ECO. NEVER delete, resize, re-purpose, or optimize them away while
> clearing DRC. In particular: a density/metal-fill fix must stay **ECO-aware**
> — do NOT delete spare cells/pads to clear spacing, and do NOT lock metal fill
> over the tracks above spares/reserved pads (use slottable/removable fill there
> so a future metal-only ECO can still route to them). No `opt_clean` /
> `clean -purge` / `remove_buffers` on keep-marked instances to "clean up"
> geometry. After your DRC fix, `spare_cell_preservation_check.py` MUST still
> PASS (spare set + keep attrs intact, 0 removed); a dropped spare is a
> regression — restore it and re-run the checker. See the `design-for-eco` skill.

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/drc-fix/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
