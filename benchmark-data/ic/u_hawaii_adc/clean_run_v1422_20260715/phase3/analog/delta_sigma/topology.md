# delta_sigma — Topology Selection (analog-topology-select)

**Block:** `delta_sigma` (incremental delta-sigma modulator, ×6 identical copies)
**Spec source:** L5_ANALOG_SPEC.md Block A — order 2, OSR 256, ENOB ≥ 14 bit, Vin_diff 1.0 V,
Vref 1.0 V, Vdd_core 1.2 V, fclk 1.0 MHz, 1-bit serial output.
**Target PDK:** IHP SG13G2; SPICE sizing/corners in sky130 substitute (disclosed).

## Topology selected: 2nd-order single-loop switched-capacitor incremental modulator

Rationale (R3 design freedom):
- **Switched-capacitor (SC) loop filter** chosen over continuous-time: SC integrators give
  ratio-defined, temperature-stable gains (cap ratios) — well matched to an incremental converter
  that resets/accumulates over the OSR = 256 conversion window and targets ENOB ≥ 14.
- **2nd-order** (order = 2 from spec): a cascade of two SC integrators around a 1-bit quantizer +
  1-bit DAC feedback. The critical analog cell is the **integrator operational transconductance
  amplifier (OTA)**.
- **Integrator OTA — two-stage Miller-compensated, NMOS-input**
  (`xm1`/`xm2` NMOS differential input pair, `xm3`/`xm4` PMOS current-mirror load first stage,
  `xm6` PMOS common-source second stage, `xm7` NMOS second-stage current-source load), with an
  **NMOS tail current source** (`xm5`) biased by an **NMOS current-mirror** leg (`xmb` + `r_ib`),
  **Miller compensation** `cc`.
- **SC integrator network**: sampling capacitor `cs` into the OTA virtual-ground summing node,
  integrating capacitor `ci` in feedback (cs/ci ratio sets the integrator gain).

## Primitives (device-level)
- amplifier: two-stage Miller OTA (operational transconductance amplifier)
- differential pair: NMOS input transistors
- active load: PMOS current mirror
- output stage: PMOS common-source with NMOS current-source load
- tail bias: NMOS current source (current mirror)
- compensation: Miller capacitor (pole split)
- SC network: sampling capacitor + integrating capacitor (switched-capacitor integrator)
- quantizer: 1-bit comparator + 1-bit DAC feedback (loop, out of the transistor-level OTA scope)

## Closure evidence
Sized point (from analog sizing loop): Cs = 0.25–0.5 pF, Ci = 1 pF; OTA integrates the input step
within T/2 = 500 ns. Real ngspice transient + AC open-loop UGBW across TT/SS/FF × −40/27/125 °C
(see corner_results.json — `real_ngspice_partial`; the settle metric is the OTA-sufficiency proxy).
