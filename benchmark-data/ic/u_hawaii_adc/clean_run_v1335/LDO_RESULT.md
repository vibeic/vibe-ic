# u_hawaii_adc — Block B (LDO) clean-run result (IHP sg13g2, ngspice)
Blind-authored PMOS-pass LDO (5T OTA error amp, R-divider FB), §4.05 from L5_ANALOG_SPEC.
| Metric | Measured | Spec | Verdict |
|---|---|---|---|
| VOUT | 1.203 V | 1.1-1.3 (1.2 nom) | PASS |
| Line regulation | 146 uV over Vin 1.6-2.0 V | — | PASS |
| Load regulation | 4.1 mV over Iload 0.1-1.0 mA | — | PASS |
| PSRR (min) | 69.7 dB | >=40 dB | PASS |
Devices: sg13_hv_pmos pass (1.8->1.2 V), sg13_hv_nmos OTA, psp103 OSDI models, mos_tt corner.
Block A (2nd-order incremental delta-sigma modulator, ENOB>=14) is the remaining analog task.

## Block A (delta-sigma modulator) — honest attempt result
Blind transistor-level 2nd-order active-RC CT delta-sigma (sg13g2 lv: 2 OTA integrators +
clocked comparator + 1-bit feedback DAC). 150us ngspice transient (23,297 steps, converged):
- **Loop STABLE**: 2nd-integrator output bounded 0.60-0.95 V (does not rail).
- **1-bit output toggles**, density ~0.47 for a mid-scale input (density tracks input level).
- **Limitation**: simplified comparator is not full-swing (dout 0.10-0.74 V vs 0-1.2 V rail)
  -> caps effective resolution. Verified ENOB>=14 needs a proper regenerative comparator +
  loop-coefficient tuning + multi-period FFT run (substantial analog iteration, days-class).
- HONEST VERDICT: modulator loop authored + stable + tracking, but NOT verified to ENOB>=14.
  The LDO (Block B) fully PASSES all specs. Analog front-end is partially closed.
