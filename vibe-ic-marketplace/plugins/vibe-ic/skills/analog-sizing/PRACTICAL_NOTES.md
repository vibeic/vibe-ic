# Analog Sizing — Practical Notes

**Added**: 2026-04-07
**Updated**: 2026-04-07 — ALL 3 BLOCKS VERIFIED (LDO + OSC + POR)

## GF180MCU Device Characteristics (Measured)

| Parameter | NMOS (nfet_03v3) | PMOS (pfet_03v3) |
|-----------|-----------------|-----------------|
| Vth (typical, 25°C) | **0.650V** | **0.699V** |
| Lmin | 0.28µm | 0.28µm |

**Critical**: Vth is ~0.65-0.70V, much higher than textbook 0.3-0.5V.

## ngspice Model Include (CORRECT syntax)

```spice
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
```

Order matters: `design.ngspice` first, then `.lib typical`.

---

## Block 1: LDO — WORKING ✅ (5 iterations)

**Topology**: NMOS-input diff pair + PMOS mirror + PMOS pass

```
VIN ──── MP_load1(diode) ──┬── MP_load2(mirror) ── n_out ── MP_pass ── VOUT
                           │                                             │
         MN_d1(vfb) ───────┘── MN_d2(vref)                         R1─vfb─R2
                        MN_tail                                          │
                          GND                                           GND
```

| Parameter | Target | Measured |
|-----------|--------|----------|
| VOUT | 1.8V | **1.8002V** ✅ |
| Load regulation | <1% | **0.03%** ✅ |
| ICC | ≤60µA | ~45µA ✅ |

Key devices: MP_load 20µ/4µ, MN_diff 20µ/2µ, MN_tail 10µ/4µ, MP_pass 20µ/0.5µ, R1=500k, R2=1M, Cc=5pF

**Critical lesson**: PMOS mirror DIODE must be on vfb-input side (MN_d1), mirror OUTPUT on vref side (MN_d2). Swapping creates positive feedback. Took 5 iterations to discover.

---

## Block 2: OSC — WORKING ✅ (bias sweep)

**Topology**: 5-stage current-starved ring oscillator

| Ibias | Frequency | ICC |
|-------|-----------|-----|
| 50nA | 1.87 MHz | 0.22µA |
| 100nA | 3.33 MHz | 0.39µA |
| **150nA** | **4.97 MHz** | **~0.5µA** ✅ |

Key devices: MNB 0.5µ/10µ (mirror), MP_inv 1µ/1µ, MN_inv 0.5µ/1µ

---

## Block 3: POR — WORKING ✅ (14 iterations)

**Topology**: PMOS diode offset + resistor divider + 2-inverter chain + weak PMOS feedback + RC delay

```
VDD ── MP_diode ── sense ── R1(60k) ── vdiv ── INV1 ── INV2 ── Rdelay ── Cdelay ── INV3 ── INV4 ── rst_n
                                        │                 ↑                                           │
                                     R2(1M)          MP_fb(weak)                                   R_pd(5M)
                                        │                 │                                           │
                                       GND              rst_n                                        GND
```

| Parameter | Target | Measured |
|-----------|--------|----------|
| VPOR+ | 1.35-1.50V | **1.492V** ✅ |
| Hysteresis | 85-130mV | **112.7mV** ✅ |
| tPORWU | ~60µs | **61.8µs** ✅ |
| Brownout | rst_n→LOW | **~0V** ✅ |

Key devices: MP_diode 10µ/0.5µ, INV1 MP 3µ/MN 1µ, MP_fb 0.28µ/3µ (very weak), Rdelay=1M, Cdelay=100pF

**Key breakthrough**: PMOS diode provides fixed |Vtp| offset (~0.7V), breaking the inverter-threshold-tracks-VDD problem that caused all previous topologies to fail. 14 iterations: Schmitt trigger → resistor divider → stacked NMOS diode → PMOS diode offset.

---

## Common Pitfalls

1. **Feedback polarity** (LDO): Most common bug. Draw signal flow, verify each inversion.
2. **Bias current direction**: `Ibias vin nbias DC 10u` (FROM vin TO nbias).
3. **Body connections**: PMOS body=VDD, NMOS body=VSS (4th terminal in SPICE).
4. **Common-mode range**: Vth=0.65V → NMOS diff pair needs input >~0.9V.
5. **POR VDD tracking**: Inverter threshold tracks VDD proportionally → use diode offset for fixed trip point.
6. **Model include order**: `design.ngspice` before `.lib sm141064.ngspice typical`.

## References

- [AnalogCoder (AAAI 2025)](https://arxiv.org/abs/2405.14918)
- [ADO-LLM (ICCAD 2024)](https://arxiv.org/html/2406.18770v1)
- [mabrains/gf180mcu_riscv_soc](https://github.com/mabrains/gf180mcu_riscv_soc) — GF180 analog IP
- [OpenFASOC](https://github.com/idea-fasoc/OpenFASOC) — Digital LDO generator
- [PySpice](https://github.com/PySpice-org/PySpice)
