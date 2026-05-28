# Phase 3 — Real Tape-out Scoping (v0.1.44 baseline)

Status snapshot (2026-05-28). Scoping document only — drives the next chunk of work
beyond v0.1.43 (which closed the audit loop on `enhancement_emit.py`).

## What's already shipped under `benchmark_clean/` (v0.1.25 fresh runs)

Per `benchmark_clean/RESULT_v0125_fresh.md`:

| IC | Phase 3 status | Closure detail |
|---|---|---|
| spm | **PASS_WITH_WAIVERS** | WNS +11.50 ns MET (wire-RC honest), GDS 446 KB; hold MET; cross-check 200/200 bit-exact |
| subservient | **PASS_WITH_WAIVERS** | WNS +4.90 ns MET (wire-RC), GDS 1.12 MB; reused SERV (tagged), generated WB-bridge + GPIO |
| sha256 | **PASS_WITH_WAIVERS** | WNS +10.95 ns MET at L9 25.9 ns, GDS 1.70 MB; KAT bit-exact vs secworks oracle |
| u_hawaii_adc | **analog PASS 24/24** | Real ngspice 9-corner; ENOB/SNDR deferred to cosim |

Verdict: all 4 pass under the "research-grade tape-out" bar (yosys + OpenROAD + KLayout DRC + netgen LVS,
SKY130 PDK, single chip-top wrapper). None are MPW-submitted.

## What's missing for a real MPW (Multi-Project Wafer) submission

These are the gaps between PASS_WITH_WAIVERS and "send GDS to a foundry shuttle". Each
is a real, defensible work-item:

### Tier 1 — Foundry sign-off rules
Today's flow uses the open-PDK rule decks (`sky130_fd_pr_drc_full.lyrd`). Real submissions
need:
1. **Full DRC** (not `_drc_basic`): all density rules, antenna ratios, fill rules,
   per-layer min-area, well-tie spacing. Many open-PDK decks omit these.
2. **Latch-up rule check**: well-tap density + tap-to-active spacing.
3. **Antenna check** with charge accumulation per-layer.
4. **ESD diode insertion at every IO pad**.
5. **DRC waiver documentation** — every waiver needs a written justification reviewed by
   the foundry rep.

### Tier 2 — Power integrity sign-off
1. **IR-drop static + dynamic** (the v0.1.32 ir-drop-triage skill scopes this but no
   real run yet — needs `irsim` or commercial equivalent).
2. **EM (electro-migration) check** on power straps.
3. **Decap insertion** to hit dI/dt target.

### Tier 3 — Manufacturing artifacts
1. **GDS + LEF + lib + cdl + DEF** bundle (today only GDS is emitted).
2. **Extracted timing model** (ETM lib for the chip block).
3. **Mask-shop deck**: GDS-stream with reticle-frame, fill, dummy patterns added.
4. **Pad-ring**: today the designs are core-only; MPW needs a pad-ring with bond-pads
   matching the shuttle template (e.g. eFabless/OpenMPW pad-ring spec).

### Tier 4 — Verification trail
1. **Full coverage report** (line / toggle / FSM / branch — today we emit functional only).
2. **Formal property check** (today: spec_conformance_check is syntactic; real sign-off
   needs SymbiYosys for assertions or SVA).
3. **Post-PnR gate-level sim** under SDF (today: bit-exact KAT but not under SDF delays).
4. **Cross-tool LVS** (currently netgen-only; foundry usually wants Calibre LVS too — or
   open-PDK alternative).

### Tier 5 — Submission flow
1. **eFabless/OpenMPW PR template** — automated PR scaffolding for chipignite shuttles.
2. **PDK version pinning + reproducibility** (open_pdks SHA, tool versions, container
   hash).
3. **Manifest signing** for foundry receipt.

## Recommended order of work (for v0.1.44+ tape-out track)

The lowest-cost / highest-value next step is **Tier 1 + a one-IC MPW dry-run**:
1. Pick **spm** as the smallest pilot (GDS 446 KB, fits comfortably in any pad-ring template).
2. Run full SKY130 DRC + antenna + latch-up — surface real waivers.
3. Add a pad-ring (use the openMPW chipignite/caravel user-project template).
4. Run IR-drop with `irsim` (open-source) or document the gap honestly.
5. Bundle GDS + LEF + lib + cdl + DEF; write a foundry-receipt manifest.

Total expected effort: 1–2 weeks for a real-spm dry-run. Output: a directory bundle that
could be submitted to a real shuttle (chipignite, ICDP, MPW @ TSMC academic, IMEC) **if**
the user wanted to spend the submission fee.

## Honest gaps (NOT silently waived)

- **No real silicon yet.** Every IC under `benchmark_clean/` is sim+PnR-clean; none has been
  fabbed. Hardware-pass attestation (the L13 `evidence` block) is empty everywhere.
- **No commercial-tool cross-check.** A foundry will typically want a Calibre or PVS DRC
  pass alongside KLayout's open-PDK deck. The plugin currently has neither.
- **No real STA under SDF.** Post-PnR gate-level sim uses zero-delay vectors.
- **u_hawaii_adc digital wrapper not closed.** Only the analog block sims pass — the digital
  decimation filter / SPI register file are scoped but not run end-to-end. (Tracked in
  `community/backlogs/ORGANIC-20260528-fullstack-tb-placeholder-false-functional-pass.yaml`
  for the closure track.)

## What v0.1.44 actually delivers under this track

This document is the v0.1.44 scoping output. Concrete code work starts in v0.1.45+ once
a target shuttle is picked. The work is non-trivial (each Tier 1 item is multiple days);
this scoping doc lets a user understand the gap before committing time.
