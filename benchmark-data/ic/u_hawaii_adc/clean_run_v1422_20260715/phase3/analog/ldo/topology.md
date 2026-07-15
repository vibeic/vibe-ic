# ldo — Topology Selection (analog-topology-select)

**Block:** `ldo` (low-dropout regulator, ×1, supplies one delta-sigma modulator core)
**Spec source:** L5_ANALOG_SPEC.md Block B — Vout 1.2 V, Vin 1.8 V (IOVDD), Iout 0.5 mA, dropout ≤ 0.5 V, PSRR ≥ 40 dB, Iq ≤ 50 µA.
**Target PDK:** IHP SG13G2; SPICE sizing/corners in sky130 substitute (disclosed — no public SG13G2 ngspice lib).

## Topology selected: PMOS-pass, NMOS-input two-stage error amplifier LDO

Rationale (R3 design freedom — any topology meeting the specs is acceptable):
- **PMOS series-pass device** (`xmp_pass`, common-source): only 0.6 V of headroom is available
  (1.8 IOVDD − 1.2 CORE), so a low-dropout **PMOS pass** transistor is chosen over an NMOS
  source-follower pass (which would need V_GS above the rail). Gate driven by the error-amp output.
- **Error amplifier — NMOS differential pair with PMOS current-mirror active load**
  (`xmn1`/`xmn2` input pair, `xmp1`/`xmp2` mirror load), **NMOS tail current source** (`xmn_tail`)
  set by an **NMOS current-mirror bias** leg (`xmn_b` + bias resistor `r_ibias`).
- **Resistive feedback divider** (`r1`/`r2`, 8 kΩ/8 kΩ) sets Vout = 2·Vref = 1.2 V from Vref = 0.6 V.
- **Miller compensation capacitor** `cc` across the pass-gate node provides the dominant-pole
  split for closed-loop stability with the 1 kΩ / (0.5 mA) load.

## Primitives (device-level)
- differential pair: NMOS input transistors
- active load: PMOS current mirror
- tail bias: NMOS current source (current mirror)
- pass device: PMOS common-source (sized by multiplier m_pass)
- feedback network: resistor divider (closed-loop, feedback)
- compensation: Miller capacitor (dominant pole / zero)

## Closure evidence
Sized point (from analog sizing loop): m_pass = 160 → Vout = 1.19913 V (target 1.2 V, err 0.09 %),
Vfb = 0.5996 V. Real ngspice op across TT/SS/FF × −40/27/125 °C (see corner_results.json).
