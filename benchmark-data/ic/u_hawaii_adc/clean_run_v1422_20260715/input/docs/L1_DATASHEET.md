---
layer: L1
ic: u_hawaii_adc
class: mixed_signal_adc
status: draft
written_at: 2026-05-26
sources:
  - github.com/bmurmann/EE628  (handwritten datasheet + 5_Design/1_System system spec, public)
  - EE628 incremental delta-sigma course context (public)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — product intent + tapeout target; no transistor-level implementation"
  r2_blackbox: "PASS — only externally-observable specs (channels, supplies, PDK, die, converter type)"
  r3_multiple_correct: "PASS — modulator architecture / LDO topology chosen by the designer"
confidence_note: >-
  The upstream EE628 dataset publishes the system spec mostly as figures / Simulink models
  and ships only a flat top-cell GDS (no per-block schematic/netlist). Numeric targets below
  marked (est) are course-typical, evidence-anchored estimates; they are the DESIGN TARGET
  to meet, not measured silicon values. This is disclosed, not hidden.
---

# L1 — Datasheet / Product & Tapeout Metadata

## Product
| Field | Value |
|---|---|
| product_name | `u_hawaii_adc` (UHEE628) |
| product_family | mixed-signal incremental delta-sigma ADC front-end |
| one-line | An array of 6 incremental delta-sigma modulator channels; one channel's core is supplied by an on-chip LDO. Analog inputs + digital (serial) outputs. |
| application | sensor/instrumentation incremental-ADC front-end; teaching/tapeout reference (UH Mānoa EE628, IHP SG13G2, fabricated May 2024) |
| design origin | github.com/bmurmann/EE628 — **fabricated reference; used as the golden oracle for cross-check ONLY (not as a Phase-1/2 input)** |

## Tapeout target
| Field | Value |
|---|---|
| Target PDK | **IHP SG13G2** (130nm BiCMOS, open PDK) |
| Supplies | IO/analog **1.8 V** (IOVDD) · core **1.2 V** (one channel core from the LDO) |
| Channels | **6** identical incremental delta-sigma modulator copies |
| On-chip regulator | 1 LDO supplying one modulator copy's core |
| Die (core, no seal ring) | **1300 × 1300 µm** |
| Sign-off | DRC clean, LVS, multi-corner analog corner coverage (TT/SS/FF × −40/27/125 °C) |

## Externally-observable interface (per the fabricated chip's top pins)
- Analog inputs `IN1..IN6` (PAD), differential referenced to `VHI`/`VLO`.
- Digital serial outputs `OUT1..OUT6` (+ `dout` serial), modulator clocks `CK4/CK5/CK6`.
- Reference pins `VHI`/`VLO`; supplies `IOVDD` (1.8 V), `CORE` (1.2 V), `VLDO`/`VREF` for the LDO channel.

## NOT constrained at L1 (R3 design freedom)
- ❌ modulator internal architecture (single-loop vs MASH, SC vs CT) — designer's choice
- ❌ LDO topology (NMOS vs PMOS pass, error-amp type) — designer's choice
- ❌ transistor sizes, bias scheme, layout — chosen downstream to meet the spec

