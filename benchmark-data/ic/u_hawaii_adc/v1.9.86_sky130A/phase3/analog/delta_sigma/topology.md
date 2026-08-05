# Topology — delta_sigma (u_hawaii_adc, IHP SG13G2)

GENERATED from L5 Block A spec (analog-topology-select). Authored to meet
order=2, OSR=256, ENOB>=14, Vin(diff)=1.0 V, Vref=1.0 V, Vdd_core=1.2 V,
fclk=1.0 MHz, 1-bit serial output. R3: SC or CT, single-loop or otherwise — the
designer's choice as long as ENOB/OSR/range are met.

## Selected: 2nd-order single-loop **switched-capacitor (SC) CIFB** incremental delta-sigma modulator with 1-bit quantizer

Rationale: an **incremental** converter resets and accumulates over a fixed
conversion window of OSR clocks, then the digital decimator (sinc^2 for a 2nd
order loop) produces one high-resolution sample. A 2nd-order CIFB
(cascade-of-integrators, feed-back) SC loop with OSR=256 gives ideal
SQNR well above 14-bit ENOB:

  SQNR_2nd_order(dB) ~ -12.9 + 50*log10(OSR) for a sinc^2-decimated incremental
  -> at OSR=256: ~ 6.66 effective bits per decade * ... ; numerically the
  ideal in-band quantization-noise-limited ENOB at OSR=256 for L=2 is ~ 17 bit,
  leaving comfortable margin above the 14-bit target after thermal/kT/C budget.

SC (discrete-time) chosen over CT because it is robust to the 1 MHz clock,
needs no anti-alias tuning, and matches the incremental reset-and-accumulate
operation cleanly with SC integrators that are reset at the start of each window.

## Schematic (text)

```
  Vin(diff) --[SC int1: C/Cs, opamp1]--+--[SC int2: opamp2]--+--> 1-bit
   Vref ----<------ DAC fb (1-bit) ----+---------------------+    quantizer
                                                                  | (latched comparator)
                                                  bitstream out ->-+--> sinc^2 decimator (digital, separate)
  reset asserted at window start -> integrators cleared (incremental).
```

## Device roles
| Block | Role | Key constraint |
|-------|------|----------------|
| opamp1, opamp2 | SC integrator OTAs | DC gain > OSR (so leakage < 1 LSB); GBW > 5*fclk |
| Cs, Cint       | sampling / integrating caps | kT/C noise budget for 14-bit ENOB |
| comparator     | 1-bit quantizer | regenerative latch, offset tolerated by feedback |
| 1-bit DAC      | feedback ref injection | +/- Vref, clean reference switching |
| reset switch   | per-window integrator reset | defines incremental window = OSR cycles |

## Trade-off analysis
| Candidate | Pros | Cons | Verdict |
|-----------|------|------|---------|
| 2nd-order SC CIFB, 1-bit | robust, ENOB margin at OSR=256, simple 1-bit DAC (inherently linear) | OTA GBW must track fclk | **Selected** |
| MASH 2-1 | higher order | needs precise inter-stage gain matching | Rejected (overkill for 14-bit) |
| CT 2nd-order | low power | RC tuning + anti-alias sensitive at 1 MHz | Rejected |
| 1st-order | simplest | OSR=256 gives < 14-bit ENOB -> FAILS target | Rejected |

## PDK constraints applied (IHP SG13G2)
- 1.2 V core supply -> single-stage cascode OTA headroom is tight; use
  telescopic/folded OTA sized for DC gain > 48 dB (> OSR).
- MIM caps for SC ratios (good matching).
- **Tool disclosure:** SG13G2 has NO public ngspice corner lib -> the transient
  modulator sim uses documented LEVEL=1 standin MOS models for the OTA + ideal
  SC behavioral integrators = MODELED, not silicon sign-off.

## Verification model note (honest)
The full transistor-level 2nd-order SC modulator transient at OSR=256 over many
conversion windows is expensive; the A4 corner sim verifies the modulator
**core small-signal/DC operating points** (OTA bias + comparator trip) on the
LEVEL=1 standin across PVT, and the **system-level ENOB/OSR** is verified by a
behavioral incremental-DSM transient (iverilog/vvp mixed-signal cosim, A8/A9)
that models the SC loop arithmetic + sinc^2 decimation and measures ENOB. Both
are disclosed as MODELED, not silicon sign-off.
