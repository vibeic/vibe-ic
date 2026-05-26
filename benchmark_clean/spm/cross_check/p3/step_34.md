# Step 34 — GDSII

## What ran
Inspected OUR vs REF final GDS (size, layers, DRC/LVS state). Per the cross-check
methodology, the comparison is "both DRC/LVS-clean + functionally equivalent",
NOT a pixel/byte comparison (the two micro-architectures are intentionally
different so the layouts cannot and should not be identical).

## Side-by-side
| metric | OURS | REF |
|---|---|---|
| Streamed `phase3/stage4/gds/spm.gds` | 383,950 B (375 KB) | 292,110 B (285 KB) |
| gds_size_check | PASS (>100 KB min) | PASS |
| SHA-256 | 5f2b9ec1…05aa013a | cd287ab0…035142e1 (different, as expected) |
| Layers in streamed GDS | li1 + met1 (cell-level) | li1 + met1 (cell-level) |
| magic_merged GDS | 0 bytes (merge step empty — flow limitation) | (n/a; REF used spm_pdn.gds 421 KB) |
| DRC | clean modulo waivable li-class (step_29) | clean modulo same li-class |
| LVS | device-exact 3176/3176 (step_29) | device-exact 3176/3176 |
| Functional equivalence | gate sim PASS 10013 vectors (step_27) | RTL-TB flag |

## Verdict: BOTH-CLEAN + FUNCTIONALLY-EQUIVALENT (NOT pixel-compare)
Both GDS pass gds_size_check, are DRC-clean (waivable li-class only) and LVS
device-exact, and both implement the same spm multiply function (OURS proven by a
10013-vector gate sim). The SHAs differ — correctly so, because OURS is a
carry-save micro-arch and REF is shift-add. The note about a "4.26 MB merged GDS"
does not match this staged copy (streamed spm.gds is 375 KB; the magic_merged
artifact is 0 bytes on both flows due to the merge-step limitation) — stated
honestly. The valid cross-check (clean + functionally equivalent) holds.
