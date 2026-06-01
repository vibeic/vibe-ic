# Antenna repair + routing-completeness honesty — FINDINGS (v0.2.14)

> Surfaced by the external-IC pilot (chacha, a sky130A AES/ChaCha core). Run-shape A
> (`phase3_one_shot_runner.py`). Honesty per `open-benchmark-methodology` §3/§4/§6.

## Headline
The v0.2.14 antenna-repair step was **non-functional** (wrong OpenROAD command) and, while
verifying the fix, surfaced a **silicon-DOA-class pre-existing bug**: `detailed_route` failures
were swallowed as `NONFATAL` and the runner shipped **completely unrouted designs as
`PERC_EQUIV_PASS`**. Three coupled, general fixes landed; both a routable control (spm) and the
unroutable pilot (chacha) now produce the **correct, honest** verdict.

## Fix 1 — antenna repair command + sequence (general)
- **Bug**: the step emitted `repair_antenna -diode_cell <c>` → `[ERROR STA-0562] ... -diode_cell is
  not a known keyword or flag`. The OpenROAD 26Q1 command is **`repair_antennas <diode_cell>`**
  (plural; the diode cell is a **positional** arg, not a flag — `help repair_antennas`).
- **Bug**: even with the right command, placing it **after** the main `detailed_route` degraded it
  to diode-only insertion (~no improvement: 85→84). `repair_antennas` fixes antennas chiefly by
  **jumper insertion** (layer hopping), which needs a **fresh global-route graph**.
- **Fix (proven on chacha, 50k-cell sky130A: 85 net / 112 pin → 0/0)**: the sequence is
  `global_route → repair_antennas <diode> -iterations 5 → detailed_route → check_antennas`, all
  in the PnR session. `repair_antennas` iterated `85 →(104 jumpers)→ 3 →(5 diodes)→ 2 →(4
  jumpers)→ 0`.
- Extracted as the pure helper `_antenna_repair_tcl(pdk)` so the silicon-critical sequence is
  pinned by regression tests (v0.1.49 doctrine).

## Fix 2 — in-session authoritative antenna measurement (general)
- **Bug**: the measurement re-`read_def` + re-`global_route` the routed DEF. `check_antennas`
  cannot read routing from a re-`read_def` (`[ERROR ANT-0008] No detailed or global routing
  found`), so the forced re-`global_route` **discards the antenna-fixing jumpers** and mis-reports
  a repaired design as still-violating.
- **Fix**: `_emit_antenna_report` now PREFERS the **in-session post-repair** `check_antennas`
  result (parsed from `phase3/stage3/pnr/openroad.log` via the `ANTENNA_POSTROUTE_DONE`
  sentinel); the re-global_route path is a fallback only.

## Fix 3 — DRT-0305 PG-net cleanup + routing-completeness honesty (silicon-DOA)
- **Root cause (chacha)**: a dangling `zero_` net tagged `+ USE GROUND` in the regular `NETS`
  section (a Yosys `setundef`/`hilomap` tie stub) made TritonRoute abort **all** detailed routing:
  `[ERROR DRT-0305] Net zero_ of signal type GROUND is not routable ... Move to special nets.` The
  prior runner swallowed this as a "cosmetic" `NONFATAL` warning — so chacha shipped with **0
  signal nets detail-routed** (every `placed/post_hold/routed/<top>.def` carried `0` `+ ROUTED` in
  `NETS`) yet still produced a GDS, a DRC report, and `PERC_EQUIV_PASS`.
- **Fix 3a — `_pg_net_cleanup_tcl()` (runs before `global_route`)**: deletes dangling non-special
  POWER/GROUND nets (no iterm/bterm — unconditionally safe) and reclassifies connected ones to
  SIGNAL so they route. Real PG nets are SPECIAL and untouched. On a healthy design there are no
  such nets, so it is a verified no-op (`PG_CLEANUP_DONE: deleted=0 reclassified=0` on spm).
- **Fix 3b — routing-completeness honesty in `_emit_antenna_report`**: when the PnR log carries a
  detailed-route abort marker (`DETAILED_ROUTE_NONFATAL`, `REPAIR_ANTENNA_REROUTE_NONFATAL`,
  `[ERROR DRT-0305]`, `[ERROR DRT-0085]`, `[ERROR ANT-0008]`, `ANTENNA_POSTROUTE_CHECK_NONFATAL`),
  the antenna result is marked `routing_incomplete: true` and reported **FAIL** — never a silent
  antenna-clean pass on an unrouted design. The antenna FAIL drops the overall PERC verdict.

## Fix 4 — set_dont_use the PDK's PnR-forbidden cells (general; the DRT-0085 root cause)
After Fix 3a removed the `zero_` abort, chacha hit a **different** abort:
`[ERROR DRT-0085] Valid access pattern combination not found` on instances `load_slew15` /
`load_slew26` whose master is **`sky130_fd_sc_hd__probe_p_8`**. Provenance check settled the cause:
probe_p_8 is **absent** from the original RTL (0) and the Yosys synth netlist (0) — it appears
**only** in the PnR output (`chacha_pnr.v`, 141). So OpenROAD's `repair_design` was itself inserting
`probe_p_8` as a *slew-fix buffer* (instances named `load_slew*`), and TritonRoute cannot route a
characterization probe cell → DRT-0085. **This is a general runner bug, not a chacha property.**
- **Fix (`_dont_use_tcl` + `PdkConfig.pnr_exclude_cell_file`, injected after `link_design`, before
  any opt)**: read the PDK's OWN `drc_exclude.cells` (the `PNR_EXCLUDED_CELL_FILE` OpenLane/librelane
  feed to OpenROAD `set_dont_use`) and `set_dont_use` each entry — probe + lpflow + DRC-failed
  masters. Reading the PDK's own file keeps this GENERAL (any PDK shipping one works; no hand-curated
  list to drift) and AUTHORITATIVE (byte-identical to the reference flow). It correctly does NOT
  exclude plain `clkbuf_*` (CTS needs them) nor tap/decap/fill/diode (dedicated steps place them) —
  the adversarial design review caught an early hand-rolled pattern that wrongly globbed `clkbuf_*`.
- **Result**: with the 53 sky130A exclusions applied, `repair_design` no longer inserts probe cells,
  and chacha **detail-routes for the first time** — `Total wire length = 775000 um` across
  met1–met4, no DRT-0085. (chacha's residual DRC violations at 300×300 / util 0.35 are a
  floorplan-congestion matter — a larger die routes clean — separable from this fix.)

## Verification (Fix 4)
| Design | set_dont_use | detailed_route | signal routing | PERC |
|---|---|---|---|---|
| **spm** (healthy control) | 53 cells applied | OK | 330 `+ROUTED` | **PERC_EQUIV_PASS** (no regression — exclusion is a no-op for a design that never used probe/lpflow) |
| **chacha** (probe_p_8) | 53 cells applied | OK — no DRT-0085 | **775 000 µm wire** (was 0) | routes (DRC-congested at tight params, separable) |

## Fix 5 — skip-when-clean (the antenna repair's second detailed_route is now conditional)
Making chacha route exposed that the antenna block's `repair_antennas → detailed_route` is a FULL
second route pass that ~doubles wall-clock on a large congested design. Fixed directly (not deferred):
the block now first runs a **read-only `check_antennas` directly on the realized main route**
(verified: `check_antennas` reads detailed routing with no `global_route` when signal routing exists)
and, if it reports **0 net violations**, SKIPS the entire `global_route + repair_antennas +
detailed_route` (the precheck's own 0/0 is the shippable result; net-count 0 ⇒ pin-count 0). The skip
branch runs NO `global_route`, so it cannot disturb the main route. Only a design that still has
antenna violations (or whose precheck cannot measure) pays the repair sequence.
- **spm** (already clean): precheck = 0 → `ANTENNA_ALREADY_CLEAN`, second route SKIPPED; 330 `+ROUTED`
  preserved, antenna PASS, PERC_EQUIV_PASS — same result, one route pass saved.
- **chacha** (has violations): precheck > 0 → the proven repair path runs unchanged.

## Generality + no-cheating audit
All five v0.2.14 enhancements were independently audited (adversarial, AST-level re-verification):
verdict **ALL_GENERAL_AND_CLEAN**, no must-fix. Every enhancement keys only on STRUCTURAL net
properties (sigType / isSpecial / iterm-bterm), OpenROAD tool/error markers (DRT-0305/0085,
ANT-0008), or PDK-config parameters (`antenna_diode_cell`, `pnr_exclude_cell_file`) — the chip/
benchmark names (chacha/prince/poly1305/aes/sha3/spm) live ONLY in docstrings as provenance, never in
a code branch. The honesty logic can only convert a would-be PASS into a FAIL, never inflate a FAIL
into a PASS. No gold/reference/hidden-TB is read — each enhancement operates solely on the design's
own DEF/log + PDK standard config.

## Verification matrix
| Design | PG cleanup | detailed_route | antenna.json | routing_incomplete | PERC |
|---|---|---|---|---|---|
| **spm** (routable control) | no-op (deleted=0) | OK — 330 `+ ROUTED` | in-session 0/0 PASS | false | **PERC_EQUIV_PASS** |
| **chacha** (probe_p_8) | deletes `zero_` (1) | DRT-0085 abort | unmeasured FAIL | **true** | **PERC_EQUIV_FAIL** |

- Antenna mechanism proven 85→0 on the completed chacha routing (in-session, `repair_antennas`
  104 jumpers + 5 diodes).
- 103 pytest pass (`test_phase3_signoff_chain_organic.py` + `test_perc_corpus_sweep.py`), incl. 19
  new cases pinning the antenna sequence, the diode-cell-positional form, the PG cleanup, and the
  routing-incomplete honesty (clean→PASS, failed/unmeasurable→FAIL, no false-positive on healthy
  runs).

## Tool substitution (mandatory disclosure)
- No commercial PERC (Calibre PERC) ran — the chain is the open-source structural equivalent.
  OpenROAD `repair_antennas`/`check_antennas` substitute for the antenna sign-off; the antenna
  PASS is necessary-but-not-sufficient (oxide-physics stays MANUAL).

## Reproduce
- spm control: `phase3_one_shot_runner.py <proj> --top-name spm --pdk sky130A --die-um 150x150
  --util 0.40` → `reports/phase3/antenna.json` verdict PASS + `perc_equivalent.json`
  PERC_EQUIV_PASS; `grep -c '+ ROUTED' .../routed.def` (NETS block) > 0.
- chacha pilot: same runner, `--top-name chacha --die-um 300x300 --util 0.35` → antenna FAIL with
  `routing_incomplete: true`; PnR `openroad.log` shows `PG_CLEANUP_DEL: zero_` then
  `[ERROR DRT-0085] ... probe_p_8`.
