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

1. **Hotspot map + budget pass/fail** — DETERMINISTIC, enforced by
   `programs/ir_drop_budget_check.py`. It computes `budget_mV = pct·Vdd·1000`
   (the 5–10%-of-Vdd budget; 10% permissive default) and FAILs iff the
   worst-case measured drop ≥ budget. Do NOT re-derive the budget by hand —
   call the program.
2. **Classify cause** — DETERMINISTIC, enforced by
   `programs/ir_drop_triage_classify.py`. It runs the fixed 4-cause table with
   the threshold ladder (via_count<4 → weak_via; strap_pitch_um>100 →
   strap_sparse; activity_density>0.7 → switching_cluster; metal_width_um<0.4 →
   narrow_metal; else strap_sparse). Do NOT classify hotspots by hand.
3. **Fix options** — DETERMINISTIC 1:1 cause→fix map, enforced by the same
   `programs/ir_drop_triage_classify.py` (`CAUSE_TO_FIX`): strap_sparse→add_straps,
   switching_cluster→add_decap, narrow_metal→widen_metal, weak_via→add_via_array.
   The program emits both the JSON triage and the markdown fix table; use them
   directly rather than reproducing the mapping in prose.
4. **EM-specific judgment**: beyond the deterministic widen_metal fix, weigh the
   trade-off between widening metal vs shortening run length vs upsizing via
   arrays for the specific EM-limited net (a JUDGMENT call — depends on routing
   resources, congestion, and which net is most critical).
5. **Re-run guidance**: minimum P&R steps needed to re-evaluate (JUDGMENT —
   depends on whether the fix touched PDN only vs placement/routing).

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

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/ir-drop-triage/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
