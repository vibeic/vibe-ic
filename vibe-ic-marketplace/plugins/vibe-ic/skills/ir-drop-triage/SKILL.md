---
name: ir-drop-triage
description: Triage static and dynamic IR-drop and electromigration (EM) reports from power signoff tools (Voltus, RedHawk, PrimePower). Use when the user says "IR drop", "power grid", "dynamic voltage drop", "electromigration", "EM violation", "hotspot", "power signoff".
---

# IR-Drop / EM Triage

Power integrity failures can turn a timing-clean chip into a field failure. This skill reads native IR-drop and EM reports, pinpoints hot regions, and proposes power-grid fixes. The native tool result against its original limit determines signoff.

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
2. **Classify the measured cause.** Inspect the native voltage/current map,
   grid connectivity, via arrays, strap pitch, metal width and switching
   activity at each hotspot. Separate sparse straps, narrow metal, weak via
   connections and local switching demand using the tool's actual data.
3. **Choose a physical fix.** Add straps or vias, widen metal, add decoupling,
   or reduce local switching demand when the measured cause supports it.
   Rerun native IR and EM analysis against the same original budgets.

## Native PDN implementation choices

Read the failing segment's layer, coordinates, current, cross-section and
original limit from the native EM report. Distinguish a metal-width violation
from a per-cut via violation before choosing a repair. A width-scaled utilization
is only a prediction; rebuilding the grid can redistribute current.

For the native flow, use `programs/flow_config.py --project <project> --route ic
--set KEY=JSON` to record the selected `PDN_*` setting. The program preserves
other choices in the existing `plugin_output/declaration.json` and emits the
configuration that consumes the move. This is an implementation choice, not a
new specification limit or a required declaration contract. Do not change the
user's prompt or generated L documents to express it.

Keep the original report and the rollback value. Resume through the public
entry from PDN generation, then remeasure EM, IR, timing and physical verification
with their original limits. A changed declaration alone does not invalidate a
retained result or establish that the candidate ran.

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
