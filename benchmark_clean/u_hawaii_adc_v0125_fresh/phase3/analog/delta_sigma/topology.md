# Topology — delta_sigma (2nd-order incremental ΔΣ modulator)

_AI-authored from L5_ANALOG_SPEC.md Block A via `analog-topology-select`. sky130A PDK
(nfet_01v8 Vth≈0.45 V, pfet_01v8 Vth≈0.47 V); core 1.2 V from the LDO. R3 design
freedom: SC single-loop CIFB chosen._

## Selected: 2nd-order switched-capacitor (SC) CIFB single-loop incremental modulator

A 2nd-order **CIFB** (cascade-of-integrators, feedback) loop is the standard incremental-ΔΣ
core: it gives one extra order of noise shaping over a 1st-order loop (so a given ENOB is
reached at a much lower OSR), it is unconditionally stable for a 1-bit quantizer with the
classic a1=a2=0.5 / b1=b2=1 coefficients, and every coefficient is just a capacitor *ratio*
— ideal for matched-cap layout in sky130.

```
            ┌────────── 1-bit feedback DAC (±Vref via SC) ──────────┐
            │                                                       │
  Vin ─►[ SC sampler Cs1 ]─►(+)─►[ INTEGRATOR 1 ]─►(+)─►[ INTEGRATOR 2 ]─►[ COMPARATOR ]─► dout
        φ1/φ2 switches      a1=0.5  OTA1 + Ci1     a2=0.5  OTA2 + Ci2     (1-bit quantizer)
                                                                              │
            └──────────────── feedback DAC also sums into stage-1 ────────────┘
        (clocks φ1, φ2 = non-overlapping two-phase from fclk = 1 MHz; OSR 256)
```

Each **SC integrator** = a single-ended-modelled OTA with an input sampling cap (Cs) that
transfers charge onto an integrating cap (Ci) on φ2; the cap ratio Cs/Ci sets the integrator
gain coefficient. The **quantizer** is a 1-bit clocked comparator. The **feedback DAC** is a
pair of switches that inject +Vref or −Vref charge back into the stage-1 summing node
according to the previous comparator decision (`dout`).

## Device roles (transistor / primitive level)

### OTA1 / OTA2 — integrator amplifier (two-stage Miller op-amp, NMOS-input)
| Device | Role | Key constraint |
|--------|------|----------------|
| M1,M2  (nfet_01v8) | **NMOS input differential pair** | Vgs > Vth+Vdsat; NMOS input → wide CM near mid-rail at 1.2 V core |
| M3,M4  (pfet_01v8) | **PMOS active current-mirror load** | sets diff-pair gain; matched W/L |
| M5     (nfet_01v8) | **tail current source** (bias) | Vds > Vdsat to stay in saturation |
| M6     (pfet_01v8) | **common-source output stage** (2nd gain stage) | provides loop DC gain ≥ 60 dB target |
| M7     (nfet_01v8) | output-stage current sink / load | |
| Cc     | **Miller compensation capacitor** (pole-splitting) | sets dominant pole → phase margin / closed-loop stability |
| Mb0,Mb1 (nfet/pfet) | bias **current mirror** generating tail + output bias | mirror ratio sets quiescent current |

### Quantizer — 1-bit clocked comparator (preamp + regenerative latch)
| Device | Role | Key constraint |
|--------|------|----------------|
| Mc1,Mc2 (nfet_01v8) | comparator **input differential pair** (preamp) | resolves sign of integrator-2 output |
| Mc3,Mc4 (pfet_01v8) | preamp mirror load | |
| Mlat1,Mlat2 (cross-coupled) | **regenerative latch** | positive feedback → rail-to-rail digital decision |
| Mclk (nfet_01v8) | latch clock / tail switch | strobes on φ2 (decision instant) |

### SC sampling network + feedback DAC (switches + capacitors)
| Device | Role | Key constraint |
|--------|------|----------------|
| Cs1,Cs2 | **sampling capacitors** (stage 1 / stage 2) | ratio Cs/Ci = integrator coefficient a1,a2=0.5 |
| Ci1,Ci2 | **integrating (feedback) capacitors** | hold accumulated charge across the conversion window |
| Sφ1,Sφ2 (nfet/pfet **switches**) | **two-phase non-overlap switches** | low Ron; charge injection minimised by dummy switches |
| Sdac± (nfet/pfet **switches**) | **1-bit feedback DAC** select +Vref / −Vref | injects reference charge → closes the ΔΣ loop |

## Trade-off analysis
| Candidate | Pros | Cons | Verdict |
|-----------|------|------|---------|
| 2nd-order SC CIFB single-loop | unconditionally stable 1-bit loop; coefficients = cap ratios (matchable); standard incremental core | needs OTA settling < T/2 | **Selected** |
| 1st-order SC | simplest | needs OSR ≫ 256 for ENOB 14 → impractical | Rejected |
| 2nd-order CT (RC/Gm-C) | low power, no kT/C from sampling | absolute RC tolerance → coefficient error; harder in incremental reset | Rejected (R3 allows, but SC matches incremental-reset use) |
| MASH 2-1 | high order | needs multi-bit / digital cancellation logic + matched stages | Rejected (over-complex for OSR 256 / ENOB 14) |

## PDK constraints applied (sky130)
- nfet_01v8 Vth≈0.45 V, pfet_01v8 Vth≈0.47 V → NMOS-input OTA gives the widest input
  common-mode at the 1.2 V core (PMOS-input pair would crowd headroom).
- 1.8 V devices used at the 1.2 V core → comfortable Vds margin, all transistors in saturation.
- Caps realised as MiM / MOM (ratios, not absolute values) → coefficient accuracy from matching.
- No inductors required (none in the loop).

## Verifiable-in-container vs system-level
- **Verifiable now (real ngspice, A4):** OTA DC operating point + open-loop gain (AC),
  SC-integrator step settling within T/2 @ 1 MHz, comparator resolves a ±sign decision.
- **System-level (NOT closed in a single container transient):** ENOB ≥ 14 / SNDR over a
  full OSR-256 conversion window + decimation FFT. Documented as unverified — see
  corner_results.json `unverified_metrics`.
