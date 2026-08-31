# LAND — u_hawaii_adc convergence, fixes 2+3 (continuation of #1940; fix-1 landed as v1.14.40)

## Fix 2 — A4 follows A3's recorded model-set election (flavour-aware)
`analog_real_corner_sweep.py` run_block (design-deck path): when the delivered
netlist's RECORDED model lib (netlist_provenance.json -> pdk.model_lib, A3's #903
flavour election) differs from A4's context-resolved lib but lives in the SAME
model tree (same directory) and is reachable, A4 follows the record
(design_deck_info.model_lib_followed_declared records the overridden resolution)
and keeps only the corner choice. Cross-tree binding still refuses naming both
sides; absent/unreadable record changes nothing. Helper `_a3_declared_model_lib`.
WHY (measured, .108 round-2 + REPRODUCED on main v1.14.43 round-3, u_hawaii_adc
ldo): A3 elects the elevated-voltage MOS lib for the 1.8V pass path and records
it; A4 re-elected the plain-voltage flavour -> own-card election 0 -> false
model-set refusal. Flavour-aligned blocks pass, flavour-split dead-end.
Two-tree: pre c0867ee16 follow-case RED (exact refusal text) + 2 refusal pins
GREEN; post 3/3 new + 123/123 A4 suites. Independent re-verification (second
session): post 9/9 + 160/160; pre red/green as stated. E2E: ldo 9/9 real corners,
vout PASS vs L5 target, on both 8HD-8 and .108 real runs.

## Fix 3 — A2 quotes the DECLARED target's constants, not a static sky130 default
`analog_a2_topology_emit.py`: --pdk default None -> explicit CLI > project's own
L19-declared pdk_target (same field A3 reads; helper `_declared_pdk_target`) >
'sky130' fallback; winning selector + source recorded. `pdk_device_params` gains
a containment rung (bare `sg13g2` resolves vendor-prefixed `ihp-sg13g2`; prefix
matching alone returned None for exactly the declared-target case).
WHY (measured, .108 round-2 ldo topology.json): runner invokes A2 with no --pdk
-> static sky130 default -> an IHP project's topology quoted family=sky130A
(vth 0.45 / rail 1.8) while the registry's ihp-sg13g2 entry (0.42 / 1.2) sat
unread — its own note says the carried-over values mis-bias sizing.
Two-tree (base c0867ee16): pre 2 RED (bare-token match; L19-follow) + 2 GREEN
(fallback + explicit-flag pins); post 4/4 new + 29/29 A2 suites. Independent
re-verification: 4/4 + 142/142. Degrades loudly: unknown L19 target still yields
the honest "no analog_device_params resolves" text, never silent sky130.

## Doctrine
Both chip-AGNOSTIC (recorded election + directory identity; declaration + registry
read; no PDK literal in code). Do not land from here — gatekeeper review; see
PR #1940's review comments for the second session's VERIFIED records.
