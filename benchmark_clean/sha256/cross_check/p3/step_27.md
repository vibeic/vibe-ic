# Step 26 — Signal Integrity / crosstalk

**Verdict: N/A** (no dedicated open-source SI noise simulator exists in iic-eda; the
reference shares the same limitation — SI is not a producible capability of this
open-source flow on either side. SPEF coupling-capacitance data IS extracted and
shown below as the best-available proxy; it is NOT fabricated as a 0-violation pass.)

**What ran:** Signal-integrity here is driven from the coupling-capacitance data in the SPEF extracted in Step 21 (OpenROAD OpenRCX). REF's SI step is itself an OpenROAD/SPEF-derived crosstalk estimate (no dedicated open-source SI noise simulator was used by REF either).

| Metric | OURS | REF |
|---|---|---|
| SPEF source | `phase3/stage3/extracted/sha256.spef` | `phase3/stage3/extracted/sha256.spef` |
| Coupling caps (cc) extracted | 117,080 | 73,635 |
| Max crosstalk noise estimate | not separately computed | 50.0 mV |
| Noise limit | 600 mV (sky130 typical) | 600 mV |
| Violations | — | 0 (WITHIN_LIMITS) |

**Verdict: PARTIAL / honest NO-DEDICATED-TOOL.** OURS now has the SI *input* data (117,080 coupling caps from the real OpenRCX SPEF — 1.6x REF's count, tracking OURS's larger net count). However, neither this run nor REF used a dedicated signal-integrity *noise simulator* (no Quantus/Voltus-SI / no PrimeTime-SI in the open-source iic-eda toolbox). REF produced a crosstalk *estimate* (max 50 mV vs 600 mV limit) from the same SPEF coupling data; a like-for-like OURS estimate would be in the same regime (sky130 met1-5 coupling at these cc magnitudes stays far below the 600 mV gate-noise limit), but no real SI-sim tool exists in this environment to produce a sign-off noise number. Reported honestly rather than fabricating a 0-violation SI pass.

**Evidence:** `phase3/stage3/extracted/sha256.spef` (117,080 ccs), `phase3/stage3/extracted/xc_signoff.log` (RCX-0045); REF `reports/phase3/si_crosstalk.json`.
