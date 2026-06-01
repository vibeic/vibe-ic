# PERC-equivalent coverage — end-to-end validation on a padded multi-domain chip

**Plugin v0.2.10.** The open-source PERC-equivalent sign-off (Step 32) was built incrementally
(v0.2.7 aggregate → v0.2.8 ESD presence → v0.2.9 ESD discharge topology → v0.2.10 latch-up well-tap),
each validated on the real Caravel `chip_io.def` / real routed DEFs in isolation. This doc records
the **first end-to-end run with every category composed on one padded chip**.

## Why this run

The unit tests each exercise ONE category. The integration path — all categories composed, on a
**multi-supply** padded chip — was never run together. The specific risk: the cross-voltage-domain
check (`single_supply` detection) had only ever seen single-supply core macros (→ auto-N/A); a real
padded chip has ≥3 supply domains and must flip to MANUAL.

## Fixture

A faithful Caravel-chip_io-shaped DEF (host-side, structure extracted from the real in-container
`/foss/designs/.../caravel/def/chip_io.def`):
- **3 supply domains** via SPECIALNETS — vddio/vssio, vccd/vssd, vdda/vssa.
- A **gpiov2 + clamped pad ring** (gpiov2_pad + vddio/vssio/vccd/vssd/vdda/vssa hvc/lvc clamped
  pads), every pad tied to both a power and a ground net.
- A core std cell + a `tapvpwrvgnd_1` well tap.

## Result — every category composes correctly

| Category | Status | Result |
|---|---|---|
| Antenna / IR drop / EM / Floating-nets | AUTOMATED | PASS |
| EM current-density / via-array | GUARDBAND | — |
| ESD protection presence | MANUAL_REVIEW | (clamp HBM/CDM sizing) |
| **ESD discharge-path topology** | **AUTOMATED** | **PASS (TOPOLOGY_OK)** |
| **Latch-up well-tap presence** | **AUTOMATED** | **PASS (WELLTAP_PRESENT)** |
| Latch-up / well-tap (spacing + device-physics) | MANUAL_REVIEW | — |
| **Cross-voltage-domain** | **MANUAL_REVIEW** | ✅ multi-domain correctly **NOT** auto-N/A |

→ **overall `PERC_EQUIV_PASS`** (no AUTOMATED category failed; manual items listed pending).

## What this proves (and the honest residual)

- The four new AUTOMATED/structural checks (ESD presence + topology, latch-up presence, plus the
  xdomain detector) **compose without interference** on a realistic padded chip.
- The multi-domain `single_supply=False` path — never unit-tested — **correctly** routes
  cross-voltage-domain to MANUAL_REVIEW instead of a false N/A.
- A conclusive automated FAIL still dominates: dropping the vssa return clamp from the same chip
  flips ESD topology → GAP → **`PERC_EQUIV_FAIL`** even with a full ring + taps.
- HONEST residual unchanged: device-physics (ESD HBM/CDM sizing, latch-up Vhold/SCR-β/guard-ring
  efficacy, tap spacing via the DRC deck, cross-domain level-shifter sizing) stays MANUAL — an
  adversarial panel proved those cannot be auto-passed from DEF.

Pinned as a permanent regression: `tests/test_phase3_signoff_chain_organic.py::
TestPercPaddedChipEndToEnd` (composed PASS + the open-loop → PERC_EQUIV_FAIL case).
