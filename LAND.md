# LAND — A4 sectioned-corner-lib deck acceptance (u_hawaii_adc convergence, fix 1)

## What
`programs/analog_real_corner_sweep.py`:
1. `build_design_deck` no longer refuses a deck whose total `.lib` card count != 1.
   The card A4 owns = the one bound to the RESOLVED model set (file-name identity,
   same identity the model-set refusal always used). Exactly one such card required;
   companion device-class cards (sectioned PDKs: cornerCAP/cornerRES/…) are kept
   VERBATIM and recorded in info (`companion_lib_cards`, `lib_cards_kept`) — never
   blanket-restamped with a process-corner section from another library's vocabulary.
2. `design_deck_required_roles` reads the naming convention (nmos/nfet vs pmos/pfet
   identifiers, comments excluded) instead of two sky130 literals that returned None
   for every other family.

## Why (measured)
u_hawaii_adc (IHP SG13G2) run1 @ v1.14.39: A3's own emitter writes 3 sectioned
corner cards (cornerMOShv mos_tt + cornerCAP cap_typ + cornerRES res_typ) — the
PDK-correct binding per L9/#904 — and A4 refused it: "the delivered deck carries
3 `.lib` corner card(s); exactly one is required". A3↔A4 self-contradiction; every
block on a sectioned-lib PDK dead-ends at A4.

## Falsification (two-tree, 2026-08-31)
- pre-fix 464813346: programs/tests/test_a4_sectioned_corner_libs.py → 3 FAIL
  (sectioned build / byte-identity info keys / roles) + 3 PASS (the refusal pins).
- post-fix (this branch): 6/6 PASS; existing pins test_a4_consumes_design_netlist.py
  + test_a4_netlist_provenance.py + test_a4_raw_sim_fail_not_masked.py → 35/35 PASS.
- Negative control: single-card known-family deck rendering byte-identical
  (test_single_card_known_family_deck_is_byte_identical asserts the .lib line set).

## Known residual (recorded, not hidden)
Companion cards stay at A3's sections across the process sweep (e.g. res_typ at
mos_ss). Mapping a passive class's own corner vocabulary onto the sweep axis
requires per-class section semantics (bcs/wcs) the context does not yet model —
recorded in info, candidate follow-up issue, NOT silently guessed.

## Doctrine
BLOCKING-vs-ADVISORY unchanged (A4 still refuses 0-card / ambiguous / wrong-model-set
decks). Chip-AGNOSTIC: no PDK literal added; keyed on file-name identity + naming
convention. Do not land from here — review via repo-gatekeeper.
