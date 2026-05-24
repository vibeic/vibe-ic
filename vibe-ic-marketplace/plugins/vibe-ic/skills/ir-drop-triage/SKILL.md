---
name: ir-drop-triage
description: Triage static and dynamic IR-drop and electromigration (EM) reports from power signoff tools (Voltus, RedHawk, PrimePower). Use when the user says "IR drop", "power grid", "dynamic voltage drop", "electromigration", "EM violation", "hotspot", "power signoff".
---

# IR-Drop / EM Triage

Power integrity failures can turn a timing-clean chip into a field failure. This skill reads IR-drop and EM reports, pinpoints hot regions, and proposes power-grid fixes. Sign-off stays in commercial tools; this is the triage / copilot layer.

## When to use

- After initial power grid insertion
- After placement (static IR)
- After routing + SDF back-annotation (dynamic IR)
- Whenever tapeout checklist flags an EM-density violation

## Inputs

1. IR-drop report (static + dynamic)
2. EM report (current density per metal layer)
3. Power grid definition
4. Switching activity file (VCD, SAIF, or propagation from simulation)
5. Floorplan with macro/standard-cell placement

## Workflow

1. **Hotspot map**: list cells exceeding IR-drop budget (typical: 5–10% of nominal Vdd)
2. **Classify cause**:
   - Too few power straps in the region
   - High-switching block clustered without decap
   - Narrow metal width for current density
   - Via-array too small / high resistance
3. **Fix options**:
   - Add power straps / widen existing
   - Insert decap cells near aggressors
   - Spread high-activity flops
   - Add via arrays on hotspot straps
4. **EM-specific fixes**: wider metal, shorter runs, bigger via arrays
5. **Re-run guidance**: minimum P&R steps needed to re-evaluate

## Output format

- `power/ir_triage.md`:
  - Hotspot table with coordinates, cell, drop %, fix
  - EM violation table with metal layer, current density, fix
  - P&R script snippets (strap insertion, decap placement)
  - Estimated impact on routing congestion

## Technical basis

Power integrity references: Tan & Roy "On-Chip Power Delivery and Management". Commercial signoff: Ansys RedHawk, Cadence Voltus, Synopsys PrimePower. Open-source: OpenROAD `psm` (PDN analysis).

## Handoff

- PDN changes → `/flow-orchestrate` to re-run PDN + route
- Timing impact of sizing changes → `/sta-review`
- Decap placement → `/placement-optimize`

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/ir-drop-triage/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
