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

---

# LAND — fix 2: A4 follows A3's model-set election (flavour-aware)

## What
`run_block` (design-deck path): when the delivered netlist's RECORDED model lib
(`netlist_provenance.json` → pdk.model_lib, A3's #903 flavour election) differs from
A4's context-resolved lib but lives in the SAME model tree (same directory) and is
reachable, A4 follows the record (`design_deck_info.model_lib_followed_declared`
records the overridden resolution) and keeps only the corner choice. Cross-tree
bindings still refuse naming both sides; absent/unreadable record changes nothing.
New helper `_a3_declared_model_lib`.

## Why (measured — .108 round-2, u_hawaii_adc ldo)
A3 correctly elects the elevated-voltage MOS lib for the 1.8V LDO pass path and
records it; A4's own resolution elected the plain-voltage flavour in the same
directory → own-card election found 0 cards → model-set refusal. Flavour-aligned
blocks (delta_sigma, LV) passed; flavour-split blocks dead-ended. Flavour-blind.

## Falsification (two-tree, 2026-08-31)
- pre-fix c0867ee16 + test file: test_same_tree_flavour_election_is_followed RED
  (exact flavour-blind refusal in stderr), both refusal pins GREEN.
- post-fix: 3/3 new + 123/123 across all 8 A4/corner suites GREEN.

## Doctrine
Chip-AGNOSTIC (directory identity + recorded election; no PDK literal). The rule is
A4's own stated doctrine made true: "re-stamping the MODEL SET is not this step's
job" — now it also does not RE-ELECT it. Do not land from here — gatekeeper review.
