# HANDOFF — fix/hardmacro-supply-p1p3-block

**Worktree:** `~/vibe-ic-wt-hmpg-supply-p1p3` (8HD-9 / 192.168.1.105)
**Branch:** `fix/hardmacro-supply-p1p3-block`
**Commit:** `2f26100b` (to be re-amended with this verified message — see note ★)
**Parent / clean baseline:** `0f13bdf9` (v1.5.81)
**Author:** repo-gatekeeper (core-agent), 8HD-9, 2026-07-25
**Version:** left at parent's — **gatekeeper assigns the monotonic version at land.**

> ⛔ NOT pushed. Land is the gatekeeper's. This doc records ONLY what was actually run.
> ★ The commit currently on the branch is an automated "rescue" snapshot of the staged tree
> with an *un-verified* template message. Its SOURCE is my final code (verified — it contains
> the `have_rails` env-safety guard and `_macro_supply_preroute_decision`). Before land, amend
> it to fold in the regenerated `programs/INDEX.md` + this handoff and replace the message with
> the verified one below.

---

## The defect (measured, chip-AGNOSTIC — described neutrally)

A hard macro types a supply pin `USE POWER`/`USE GROUND` in its **own LEF**. When the RTL
constant-ties that pin, synthesis drives it with a TIEHI/TIELO cell → a **SIGNAL net lands on
a POWER/GROUND terminal**. TritonRoute does not skip that one net — it **aborts the entire
detailed route** (opaque `DRT-0307`), so the whole design ships with 0 signal nets routed and
LVS/STA are unreachable. The information needed to prevent this exists at Phase 1 (the macro's
LEF says `USE POWER`) but never flowed into the layer the backend reads (`L21_POWER_INTENT`),
so the gap surfaced 5 steps later as an inscrutable router crash.

## The fix (two halves, one shared decision module)

- **`programs/hardmacro_supply_intent.py` (NEW, ~223 lines)** — the ONE chip-agnostic place
  that decides, for a macro's LEF-typed PG pin, whether the design's L21 power-intent ACCOUNTS
  for it: `declared_rail` / `declared_gap` / `rail_name_match` (accounted) vs `rail_undeclared`
  (a mapping to a rail the design does not declare — anti-cheat) vs `undeclared` (the gap).
  Imported by BOTH phases so **Phase-1 verifies exactly what Phase-3 honors.** Pure functions,
  no PDK/design/pin literal.
- **`programs/ip_integration_check.py` (Phase-1 half)** — for every macro PG pin from its own
  LEF, emits `IP_MACRO_SUPPLY_UNDECLARED` / `IP_MACRO_SUPPLY_RAIL_UNDECLARED` as
  **WARNING (named, surfaced, `rc` stays 0)** so the requirement flows into L21 now rather than
  aborting routing later. (Task Phase-1 says "named finding, not silently passed" — NOT
  "blocking"; so this is a non-regressing review-level surfacing.)
- **`programs/phase3_one_shot_runner.py` (Phase-3 half)** — `_macro_supply_preroute_decision`
  (pure) binds the bindable pins (name-match OR design-declared L21 mapping, even when names
  differ — "the design says so") and, for a signal-tied PG pin **no rail can bind**, returns it
  in a `blocking` set. `step_pnr` then **`return StepResult("pnr","FAIL",…)` BEFORE the pnr.tcl
  is built/run** — a named block (macro/pin/net) at the right place and scale instead of a
  mid-route DRT-0307. (Task Phase-3 says "named, BLOCKING finding" — this is the hard block.)
- **Design-declared mapping mechanism:** `L21.fields.hard_macro_supplies` =
  `[{master,pin,rail}]` (explicit bind, honored even when names differ) or
  `[{master,pin,integration_gap:true,reason}]` (acknowledged "this design provides no such
  supply"). Read by Phase-1 (coverage) and Phase-3 (binding).

---

## Verification — ONLY what was actually run on 8HD-9, 2026-07-25

### 1. Chip-agnostic — PASS
`python3 programs/source_chip_agnostic_check.py .` → **PASS** (no forbidden chip/vendor/SKU
tokens). New code carries no design/PDK/pin literal; the only `VDD/VSS` is a comment, and
`VPWR/VGND` appears only in the **pre-existing** `_design_supply_nets` the fix reuses. A design
with no macro PG pins → empty plan → byte-identical flow.

### 2. Negative control — bidirectional, confirmed by actually running pre- vs post-impl
Each test file was run against the code BEFORE its implementation existed, then after:

| test file | pre-impl (observed) | post-impl |
|---|---|---|
| `test_hardmacro_supply_intent.py` (20) | **collection ERROR** `ModuleNotFoundError` (module absent) | **20 pass** |
| `test_ip_integration_check.py` (6) | **2 FAIL / 4 pass** — the two `*_fires`/`*_flagged` named-finding controls fail (rules absent) | **6 pass** |
| `test_hardmacro_supply_route_block.py` (11) | **8 FAIL / 1 pass** — every `_macro_supply_preroute_decision` blocking control + `master`-key + declared-map fail; the 1 pass is `test_backward_compatible_without_map` (a correct pre-existing-behavior guard) | **11 pass** |

Load-bearing controls that FAIL pre-fix and PASS post-fix:
`test_undeclared_pin_fires_named_finding`, `test_phantom_rail_binding_is_flagged`,
`test_unbindable_signal_tie_blocks`, `test_declaring_a_real_rail_clears_the_block`,
`test_empty_rail_set_never_blocks_env_safety`.

> **Honest caveat:** the paired `*_clears_the_finding` / `*_clears_the_block` assertions pass
> *vacuously* pre-fix (the finding/block never fires when the logic is absent). They are
> meaningful only PAIRED with their `*_fires`/`*_blocks` sibling (which does fail pre-fix). The
> suite as a whole is a valid bidirectional control — every behavior has a direction that fails
> pre-fix — but no single "clears" test is a standalone negative control.

All fixtures are synthetic + neutral (`NEUTRAL_MACRO`, pins `P_CORE`/`G_CORE`/`P_PROG`); no
real design/PDK/pin file is copied.

### 3. Corpus / false-positive check — on the real macro-bearing benchmark available
- `ip_integration_check` on the real **`benchmark-data/ic/edge_llm_accel`** (instantiates the
  `fakeram45` hard macro, pins `VDD`/`VSS`; its `L21` has empty `power_domains`): my check adds
  **two `IP_MACRO_SUPPLY_UNDECLARED` WARNINGs (VDD, VSS)**. The gate `rc` is **UNCHANGED** — it
  is `1` **solely** from the *pre-existing* `IP_FILESET_INCOMPLETE` ERROR (the macro ships no
  `.gds`), not from my WARNINGs. `rc = 1 iff errors`; my findings are WARNINGs, so for any design
  that PASSed the gate (`rc=0`) it **stays `rc=0`** → the `optional_program_exit_zero` flow gate
  is not regressed; verdict may go `PASS → PASS_WITH_REVIEW` (a named review, the intended
  surfacing).
- Macro-free designs → the gate `SKIP`s (rc=2), covered by `test_empty_project_skips`.
- **Env-safety guard** (`have_rails`): if the PDK rail set is empty (e.g. cell LEF unreadable in
  this env), the Phase-3 block does NOT fire (we cannot tell "no rail" from "could not read
  rails") — falls back to the passive unconnected report; pinned by
  `test_empty_rail_set_never_blocks_env_safety` + `test_ground_blindness_does_not_block_ground…`.

> Scope note: `edge_llm_accel` is the only real project on 8HD-9 with a hard macro that declares
> PG pins; other local benchmark designs are macro-free (SKIP path). I did NOT survey a 30-project
> corpus and make no such claim.

### 4. Full test suite — name-set diff vs clean baseline (authoritative)
`python3 -m pytest programs/tests/` (18,997 tests) run on BOTH trees:

- **HEAD (my fix):** `18527 passed, 11 failed, 457 skipped, 2 xfailed` (38m28s).
  *(Before I regenerated `INDEX.md` for my new program it was 13 failed; regenerating turned the
  2 `test_programs_index_freshness` tests green — see below.)*
- **Baseline `0f13bdf9`:** the exact 13 files that failed on HEAD's first run were re-run on the
  baseline tree — **all 13 fail on baseline too** (`test_cvdp_gate`×3, `test_formal_env_…`,
  `test_lec_include_hub_aggregator`×2, `test_programs_index_freshness`×2,
  `test_protocol_detector_no_misfire`, `test_v1_0_80_…real_yosys`×2, `test_v1_5_24_…phantom`×2).
- **Result: my failing name-set ⊆ baseline failing name-set — ZERO new failures.** Net I also
  **fixed 2 pre-existing** failures (`test_programs_index_freshness`) by regenerating
  `programs/INDEX.md` (which was already stale on origin/main, missing
  `drv_promotion_corroboration_check`; regenerating adds both it and my `hardmacro_supply_intent`).

### 5. The Phase-3 block placement — verified by structure, NOT by a live PnR run
I did **not** execute a real `step_pnr`/OpenROAD run (no claim of one). The load-bearing logic
is the PURE `_macro_supply_preroute_decision`, fully unit-pinned (§2). Its wiring in `step_pnr`
is `if _hm_block: … return StepResult("pnr","FAIL",…)` positioned in the pre-route setup, BEFORE
`_build_pnr_tcl_text`/the container run — the same region whose ordering the landed
`test_block_appears_before_routing_and_full_tcl_parses` already pins (`… < full.index("detailed_route")`).

---

## Reproduce
```
cd ~/vibe-ic-wt-hmpg-supply-p1p3/vibe-ic-marketplace/plugins/vibe-ic
python3 programs/source_chip_agnostic_check.py .                      # PASS
python3 -m pytest programs/tests/test_hardmacro_supply_intent.py \
        programs/tests/test_ip_integration_check.py \
        programs/tests/test_hardmacro_supply_route_block.py \
        programs/tests/test_hardmacro_supply_globalconnect.py -q       # 55 passed (37 new + 18 landed)
python3 tools/gen_programs_index.py --check                           # clean (INDEX fresh)
python3 programs/ip_integration_check.py ../../../benchmark-data/ic/edge_llm_accel   # 2 WARNINGs, rc unchanged
```

## Files changed
```
programs/hardmacro_supply_intent.py                      | +223 (new)
programs/ip_integration_check.py                         |  +73
programs/phase3_one_shot_runner.py                       | +155
programs/tests/test_hardmacro_supply_intent.py           | +177 (new, 20 tests)
programs/tests/test_ip_integration_check.py              | +145 (new, 6 tests; also fills a pre-existing D1 gap — ip_integration_check had no test)
programs/tests/test_hardmacro_supply_route_block.py      | +170 (new, 11 tests)
programs/INDEX.md                                        | regenerated (adds hardmacro_supply_intent + pre-existing drv_promotion_corroboration_check)
```

## Notes for the gatekeeper (non-blocking)
- **Related in-flight subsystem branch:** `fix/hardmacro-supply-globalconnect`
  (`~/vibe-ic-wt-macro-globalconnect`, `291e7ed0`) authored the Phase-3 **matched-rail
  add_global_connection** half — which is ALREADY in `origin/main` (v1.5.81; the cherry-pick
  came up empty). This change builds ON that landed half and adds (a) the Phase-1 coverage gate,
  (b) the design-declared L21 mapping, (c) the pre-route BLOCK for the unbindable case. De-conflict
  at land if that branch is still open.
- `parse_macro_supply_pins` recognizes `USE`/`PIN` at the start of a stripped line
  (one-statement-per-line LEF, which real tool output and the fixtures satisfy). A LEF cramming
  `DIRECTION …; USE POWER;` onto one physical line would be missed. Not chip-specific, not a
  correctness bug for real inputs — noted for robustness only.
```
