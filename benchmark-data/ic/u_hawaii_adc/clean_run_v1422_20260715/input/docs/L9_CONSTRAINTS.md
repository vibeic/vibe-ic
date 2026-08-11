---
layer: L9
ic: u_hawaii_adc
status: draft
written_at: 2026-05-26
sources:
  - EE628 handwritten datasheet (die size, PDK, supplies)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — physical/process constraint targets only"
  r2_blackbox: "PASS — PDK + die + supply targets, not placement results"
  r3_multiple_correct: "PASS — any floorplan/layout meeting the targets"
---

# L9 — Constraints / Floorplan / PDK

## Process
| Field | Value |
|---|---|
| PDK | **IHP SG13G2** (open 130nm BiCMOS) |
| Std-cell / device libs | `sg13g2_*` (IHP), HV devices (`sg13_hv_*`) for the 1.8 V LDO pass path |
| Analog device models | IHP SG13G2 transistor models |

## Supplies / levels
| Rail | Voltage |
|---|---|
| IOVDD (IO + analog input domain) | 1.8 V |
| CORE (modulator core; LDO-fed copy uses the LDO output) | 1.2 V |

## Floorplan
| Field | Value |
|---|---|
| Core die (no seal ring) | 1300 × 1300 µm |
| With seal ring | ~1480 × 1480 µm |
| Channel layout | 6 identical modulator copies (array); 1 with adjacent LDO |
| Pad ring | analog IN/OUT + supply pads (per top-pin list in L1) |

## Sign-off targets (drives Pillar 5 + the analog A1–A9 track)
- ✅ DRC clean (KLayout SG13G2 deck) — foundry-cell-internal / vendor-pad items waivable with evidence
- ✅ LVS (per-block where a schematic exists; chip-level cross-check vs the fabricated extracted netlist)
- ✅ Multi-corner analog corner coverage TT/SS/FF × −40/27/125 °C
- ✅ LDO regulates Vout=1.2 V across line/load; modulator meets ENOB/OSR target in transient

## Tool / data disclosures (honesty)
- IHP SG13G2 has **no public ngspice corner lib** → corner sims use documented LEVEL=1 standin
  models (modeled, not silicon sign-off). Must be stated in every corner result.
- The fabricated EE628 chip publishes only a flat top-cell GDS + chip-level extracted netlist
  (no per-block sub-netlist). It is the **golden oracle for the verify stage only**.
- A8 hardware-in-the-loop is WAIVED (no physical EE628 die on the bench) — substitute with a
  real mixed-signal cosim and state it.

## NOT constrained (R3)
- ❌ exact device placement / routing / guard-ring geometry
- ❌ which channel sits where in the array
