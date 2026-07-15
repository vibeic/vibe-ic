---
layer: L5
ic: u_hawaii_adc
status: draft
written_at: 2026-05-26
sources:
  - github.com/bmurmann/EE628 5_Design/1_System (system-level idsm2 model) + 2_Idealized_circuits
  - EE628 chip top pins (IN/OUT/CK/VHI/VLO/IOVDD/CORE/VLDO/VREF)
r1_r2_r3_compliance:
  r1_schema_only: "PASS — target electrical specs only; no circuit implementation"
  r2_blackbox: "PASS — externally-observable analog behavior (resolution, range, supply, regulation)"
  r3_multiple_correct: "PASS — any topology meeting the specs is acceptable"
confidence_note: >-
  Values marked (est) are course-typical estimates anchored to the EE628 system docs +
  visible top pins (the upstream publishes the numeric spec mostly as figures). They are
  the DESIGN TARGET; the analog track must SIZE a circuit to meet them. The fabricated chip
  is the golden oracle for the verify stage only.
---

# L5 — Analog / Mixed-Signal Design Spec

This chip has **two analog block types** to design (the digital decimation/serial
read-out, if any, is generated separately and is out of scope for this analog spec):

## Block A — `delta_sigma` : incremental delta-sigma modulator (×6 copies)
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| converter_type | incremental delta-sigma | — | — | resets/accumulates per conversion window |
| Order | 2 | 1–3 | — | loop-filter order (est) |
| OSR | 256 | 64–512 | — | oversampling ratio (est) |
| ENOB | ≥ 14 | ≥ 10 | bit | target effective resolution (est) |
| Vin (diff) | 1.0 | 0–1.2 | V | input range vs VHI/VLO |
| Vref | 1.0 | 0.8–1.2 | V | reference (VHI−VLO) |
| Vdd (core) | 1.2 | 1.1–1.3 | V | core supply (one copy from the LDO) |
| fclk | 1.0 | 0.1–10 | MHz | modulator clock (CK4/5/6) (est) |
| output | 1-bit serial (OUTn / dout) | — | — | digital bitstream per channel |

R3: SC or CT, single-loop or otherwise — designer's choice, as long as ENOB/OSR/range met.

## Block B — `ldo` : low-dropout regulator (×1, supplies one modulator core)
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| Vout | 1.2 | 1.1–1.3 | V | regulated CORE for the LDO-fed modulator copy |
| Iout | 0.5 | 0.1–1.0 | mA | modulator quiescent + dynamic budget (est) |
| Vin | 1.8 | 1.6–2.0 | V | IOVDD (confirmed top pin) |
| Dropout | ≤ 0.5 | — | V | headroom (1.8 IOVDD − 1.2 CORE = 0.6 V available) |
| PSRR | ≥ 40 | ≥ 40 | dB | supply rejection target (est, not silicon-measured) |
| Iq | ≤ 50 | — | µA | quiescent current target (est) |
| Load/line reg | best-effort | — | — | report achieved |

R3: NMOS or PMOS pass device, error-amp topology — designer's choice.

## Verification intent (drives L7 / Pillar 5)
- DC operating point + line/load regulation (LDO); SNDR/ENOB transient + input sweep (modulator).
- Multi-corner: TT/SS/FF × −40/27/125 °C.
- **Tool disclosure:** IHP SG13G2 has no public ngspice corner library; corner sims use
  documented LEVEL=1 standin models — modeled, NOT silicon sign-off (disclosed in every result).
- Golden cross-check (verify stage only): the fabricated UHEE628_S2024 GDS + KLayout-extracted
  SG13G2 netlist (chip-level; per-block sub-netlist is NOT published upstream → cross-check is
  spec-level + chip-GDS-DRC level, not per-block device-LVS).
