# `benchmark-data/ic/` — what each published cell IS

<!-- GENERATED FILE — do not hand-edit.
     Regenerate:  python3 vibe-ic-marketplace/plugins/vibe-ic/programs/benchmark_evidence_index.py --write
     Verify:      python3 vibe-ic-marketplace/plugins/vibe-ic/programs/benchmark_evidence_index.py --check
     The only hand-maintained input is `retention.json` beside this file. -->

This tree holds converged evidence AND runs that did not converge, and the folder name deliberately does not say which (`benchmark-data/PUBLISHING.md`: the verdict lives in `RESULT.md`, and a `clean_run_*`/`pass_*` prefix would strip the committed phase folders). This index is the answer that costs no JSON to read.

**Nothing here is deleted for failing.** Removing a failed run would make "we never ran this" and "we ran it, it failed, and we kept the record" the same state. Cells marked `corpus: yes` are also the population two BLOCKING gates walk (`cross_layer_reference_check --corpus`, `l4_systemrdl_export audit-corpus`).

| classification | cells |
|---|---|
| CONVERGED EVIDENCE | 4 |
| RETAINED FAILURE | 13 |
| UNAUDITED RECORD | 11 |
| **total** | **28** |

## CONVERGED EVIDENCE — 4

The cell's own audit artefact reads PASS or PASS_WITH_WAIVERS. This is what the project means when it says a cell converged.

| cell | audit verdict | steps | orchestrator | RESULT.md says | corpus | retained for |
|---|---|---|---|---|---|---|
| `spm/retired/v1.5.58_ihp-sg13g2` | PASS_WITH_WAIVERS | P35 F0 M0 W3 | vibe_ic=PASS_WITH_WAIVERS; phase3=PASS_WITH_WAIVERS; phase2=PASS_WITH_WAIVERS | UNSTATED | yes | RETIRED 2026-08-09 as a published NON-CELL — spm declares sky130A primary + gf180mcuD secondary and this run's own L19 says `pdk_target: sky130`, so `spm × ihp-sg13g2` was never a declared cell (CELL_MATRIX.md). MOVED, not deleted; see its RETIRED.md. Retained as history and as the artefact behind #287/#291 (real GDS) and the formal-evidence-chain repro for #412/#417/#418/#420, and as the 2026-08-07 fixture source for #235's own test — but it MUST NOT be cited as a result for spm on IHP-SG13G2 |
| `spm/v1.10.18_sky130A` | PASS_WITH_WAIVERS | P36 F0 M0 W3 | vibe_ic=PASS_WITH_WAIVERS; phase3=PASS_WITH_WAIVERS; phase2=PASS_WITH_WAIVERS | PASS_WITH_WAIVERS | yes | converged (plugin v1.10.18, published 2026-08-09); a FRESH clean-room run whose PRODUCING and MEASURING plugin version are the same, so its orchestrator record agrees with its completion audit instead of carrying a stale derived verdict; real-GDS witness superseding v1.9.94_sky130A — see notes below for what that supersession does and does not carry forward |
| `spm/v1.9.96_gf180mcuD` | PASS_WITH_WAIVERS | P34 F0 M0 W4 | vibe_ic=FAIL; phase3=FAIL; phase2=PASS_WITH_WAIVERS | UNSTATED | yes | converged (plugin v1.9.96, re-published 2026-08-07 after the v1.9.96 ciel-content-addressed-hash DFT/ATPG fix and the earlier v1.9.94 metal-fill fixes); real-GDS witness superseding v1.5.66_gf180mcuD — see notes below for what that supersession does and does not carry forward |
| `u_hawaii_adc/retired/v1.9.86_sky130A` | PASS | P8 F0 M0 W0 | — | UNSTATED | yes | RETIRED 2026-08-09 as a published NON-CELL — u_hawaii_adc declares ihp-sg13g2 (L19 `pdk_target: sg13g2`; L1 'Target PDK **IHP SG13G2**') and sky130 appears 0 times in its input docs, so `u_hawaii_adc × sky130A` was never a declared cell (CELL_MATRIX.md). MOVED, not deleted; see its RETIRED.md. It MUST NOT be cited as a result. Retained as history — what it recorded: the analog A-track run re-verified on plugin 1.9.86 (PASS=8 FAIL=0 MISSING=0, gate exit 0). No phase2/ because it runs the A-track, not the digital RTL->synth stage; the structure gate records that as a disclosed note rather than a silent pass. Its phase3/analog/ tree (hardmacro layouts, per-block specs) is published here rather than left in a pre-canonical run tree at the IC level — the publisher used to drop it, so the folder that IS the evidence did not contain it. |

## RETAINED FAILURE — 13

An audit ran and did NOT converge. These are retained on purpose: deleting them would make "we never ran this" and "we ran it, it failed, and we kept the record" the same state. Read the step counts — they separate one failed gate from a flow that never reached the steps at all.

| cell | audit verdict | steps | orchestrator | RESULT.md says | corpus | retained for |
|---|---|---|---|---|---|---|
| `caravel_user_project` | FAIL | P28 F2 M0 W3 | vibe_ic=FAIL; phase3=FAIL; phase2=PASS_WITH_WAIVERS | UNSTATED | yes | provenance-defect row in #413; inventory member of the #419/#426 layout-artefact audits |
| `caravel_user_project/v1.9.43_sky130A` | FAIL | P5 F10 M10 W2 | vibe_ic=PASS_WITH_WAIVERS; phase3=PASS_WITH_WAIVERS; phase2=PASS_WITH_WAIVERS | PASS_WITH_WAIVERS | yes | corpus member — walked by both blocking corpus gates |
| `edge_llm_accel` | FAIL | P22 F8 M4 W3 | vibe_ic=FAIL; phase3=FAIL; phase2=PASS_WITH_WAIVERS | COMPLETE | yes | read directly by tests under programs/tests/ (its input/docs/ and its published-cell layer gates); provenance-defect row in #413 |
| `edge_llm_matmul_accel` | FAIL | P5 F3 M28 W2 | phase2=FAIL | UNSTATED | yes | corpus member — walked by both blocking corpus gates |
| `ibex` | FAIL | P2 F7 M27 W0 | vibe_ic=FAIL; phase2=FAIL | — | yes | the richest L4 in the repo (48 registers / 84 fields); the cell #377 (OPEN) tested its SystemRDL export hypothesis against, via phase1/systemrdl/ |
| `opentitan_aes` | FAIL | P3 F6 M25 W1 | vibe_ic=FAIL; phase2=FAIL | — | yes | reproduction for #405 — its input/docs/ drives the real walker that returned null for everything; also read directly by tests under programs/tests/ |
| `sha256` | FAIL | P5 F5 M25 W0 | vibe_ic=FAIL; phase2=FAIL | UNSTATED | yes | reproduction for #186 (OPEN) part 1 — the 9th top-level port reproduces on this cell |
| `sha256/clean_run_v1422_20260715` | FAIL | P29 F3 M3 W1 | vibe_ic=FAIL; phase3=FAIL; phase2=FAIL | UNSTATED | yes | evidence artefact itemised by #140/#145/#146/#147 (closed) and #413; NOT named by #235 itself — see note below the tables |
| `sha256/clean_run_v1427_20260715` | FAIL | P33 F3 M0 W3 | vibe_ic=FAIL; phase3=FAIL; phase2=PASS_WITH_WAIVERS | UNSTATED | yes | corpus member — walked by both blocking corpus gates |
| `subservient` | FAIL | P24 F9 M0 W1 | vibe_ic=FAIL; phase3=FAIL; phase2=FAIL | PRODUCTION-READY | yes | reproduction for #414 (5 near-fabricated HASH_MISMATCHes) and #417 (a shipped formal PASS citing a log that does not exist); also read directly by tests under programs/tests/ |
| `u_hawaii_adc` | FAIL | P0 F0 M9 W1 | vibe_ic=PASS_WITH_WAIVERS; phase2=PASS_WITH_WAIVERS | — | yes | corpus member — walked by both blocking corpus gates |
| `u_hawaii_adc/clean_run_v1422_20260715` | FAIL | P3 F2 M8 W8 | vibe_ic=FAIL; phase2=FAIL | UNSTATED | yes | reproduction for #141/#142/#143 — their repro commands name this path verbatim |
| `u_hawaii_adc/retired/v1.9.86_sky130A/reports` | FAIL | P0 F0 M40 W0 | — | — | no | record only |

## UNAUDITED RECORD — 11

No `reports/audit/phase23_completion_audit.json` exists for this cell, so there is NO machine verdict either way. A claim made in its RESULT.md is unbacked by an audit artefact; that is not the same as a failure, and it is not a pass.

| cell | audit verdict | steps | orchestrator | RESULT.md says | corpus | retained for |
|---|---|---|---|---|---|---|
| `caravel_user_project/clean_run_v1432_commercial` | — | — | — | UNSTATED | no | record only |
| `caravel_user_project/clean_run_v1432int_commercial` | — | — | — | UNSTATED | no | record only |
| `ibex/clean_run_v1432int_commercial` | — | — | — | UNSTATED | no | record only |
| `ibex/rerun_v1346` | — | — | — | UNSTATED | no | the only CRYPTOGRAPHIC MATCH in the #426 layout-artefact recovery audit |
| `opentitan_aes/clean_run_v1432int_commercial` | — | — | — | UNSTATED | no | record only |
| `sha256/clean_run_v1335` | — | — | — | UNSTATED | no | record only |
| `sha256/clean_run_v1431_commercial_pdk` | — | — | — | UNSTATED | no | record only |
| `sha256/clean_run_v1432int_commercial` | — | — | — | UNSTATED | no | record only |
| `sha256/clean_run_v1461_0223` | — | — | — | UNSTATED | no | reproduction for #210 (sign-off corner declared with no record) and the #316 UNTYPED_STEPS discovery |
| `subservient/clean_run_v1335` | — | — | — | UNSTATED | no | record only |
| `subservient/clean_run_v1432int_commercial` | — | — | — | UNSTATED | no | record only |

## Reading the columns

- **audit verdict** — `verdict` in the cell's `reports/audit/phase23_completion_audit.json`. `—` means the artefact does not exist: no machine verdict was ever recorded, which is neither a pass nor a failure.
- **steps** — `step_counts` from the same file: PASS / FAIL / MISSING / WAIVED. This is the magnitude behind the verdict. `F1` and `M27` both read FAIL and are not the same result.
- **orchestrator** — the `verdict` each `reports/orchestrator/*_one_shot.json` recorded. Where it disagrees with the audit column, the disagreement is real and is shown rather than resolved.
- **RESULT.md says** — the verdict the human-facing document DECLARES on an `OVERALL:` / `VERDICT:` / `STATUS:` line. `UNSTATED` means it states its outcome in prose only, so no verdict was extracted; `—` means there is no RESULT.md. Where this column disagrees with **audit verdict**, the cell contradicts itself — that is the condition this index was built to make visible.
- **corpus** — the cell carries tracked `phase1/generated_docs/`, so it is inside the population both blocking corpus gates count. Changing that population changes their recorded counts.
- **retained for** — from `retention.json` where a maintainer has recorded one; otherwise derived. Absence is not evidence a cell is unused: several with no recorded reason are read directly by tests under `programs/tests/`.

## Notes

- **The `#235` attribution is weaker than this repo repeats.** PR #421 and issue #440 both state that `sha256/clean_run_v1422_20260715` IS the #235 reproduction. Checked: #235's own body and comments name no `benchmark-data/` path at all, and the run its landing comment cites as byte-identical evidence was `spm/v1.5.65_sky130A` (retired 2026-08-07, see below) — #140/#145/#146/#147 itemise its files as evidence, but not for the reason most often given for keeping it. A citation repeated three times is not a citation checked once.
- **No cell here is loaded as a test fixture merely by being cited in an issue.** Deleting a cited-but-unread cell would break no test and would still destroy the record an issue points at. That is the argument for labelling rather than deleting, and it is also why `retained for` is prose a maintainer writes rather than something derived from a grep.
- **`spm/v1.5.65_sky130A` was retired 2026-08-07**, replaced by `spm/v1.9.94_sky130A` — an owner-directed re-publish after this session's plugin fixed the STA_CORNER_BASIS_MISMATCH false-positive (v1.9.93) and the density metal-fill engine's container-reachability gap (v1.9.94), both of which the v1.5.65 run predates. What supersedes and what does not: the GDS/DRC/LVS/STA/DFT-scan-coverage evidence is a fresh, independently-verified run on the current plugin (see the new cell's RESULT.md). What does NOT carry forward byte-identically: the retired cell's specific role as `#235`'s cited witness (that citation now points at a file that no longer exists — this note is the record of where it went), and its `path_delay_coverage.json`/`sdd_coverage.json` DT2/DT3 blobs, which on the new run report NOT_APPLICABLE for this design rather than the old run's graded PASS — `test_a_real_grade_is_never_downgraded_by_a_stale_record` (#235's own regression test) now sources that fixture from `spm/v1.5.58_ihp-sg13g2` instead, which still carries it.
- **`spm/v1.9.94_sky130A` was retired 2026-08-09**, replaced by `spm/v1.10.18_sky130A`. Two reasons, and the second is the load-bearing one. (1) A newer plugin: v1.10.18 withdrew the v1.10.14/#901 completion-audit vacuity hook, which had over-reached — it marked a whole step VACUOUS_PASS when a single one of its gates was legitimately inapplicable, cascading into PASS_VOIDED_BY_DEPENDENCY and an overall FAIL whose `failed_gate_count` was 0. (2) The retired cell's own `reports/orchestrator/*.json` and its RESULT.md were produced by DIFFERENT plugin versions, so the cell carried a derived verdict its own audit no longer agreed with. The replacement is a fresh clean-room run produced AND measured by v1.10.18 (`vibe_ic_one_shot_runner`, 226 s from the L1-L9 documents), so `vibe_ic=PASS_WITH_WAIVERS; phase3=PASS_WITH_WAIVERS; phase2=PASS_WITH_WAIVERS` is what the run itself recorded, not what a later re-audit asserted over it. What does NOT carry forward: the retired cell's role as the path cited by `spm/v1.9.96_gf180mcuD`'s RESULT.md and by `caravel_user_project/v1.9.43_sky130A`'s RESULT.md — both are HISTORICAL statements about a measurement made on 2026-08-07 and are deliberately left unedited (re-stamping a historical claim against a run it was not made on would be the fabrication this file exists to prevent); this note is the record of where that path went. The three tests that read the cell by path (`test_issue448_citation_routing`, `test_organic404_r4_shipped_netlist_refutes_a_resolution`, `test_provenance_matches_by_digest_after_publish_move`) were MIGRATED to the new cell in a separate commit, not left to fail.
- **`spm/v1.5.66_gf180mcuD` was retired 2026-08-07**, replaced by `spm/v1.9.96_gf180mcuD` — landed after this session's plugin fixed a stale ciel content-addressed PDK version hash that had been misread as a DFT/ATPG capability gap (v1.9.96, commit 3d7c5a095), on top of the same v1.9.94 metal-fill container-reachability fix that also carried the sky130A cell above. The new run independently re-derives GDS/DRC(0 real violations)/LVS(match)/STA/DFT-ATPG(100.00% stuck-at) from its own artifacts — see the new cell's RESULT.md. What does NOT carry forward unverified: the retired cell's specific citations as the repro site for `#363` (EM coordinates outside the die) and the `#366`/`#381` formal false-PASS — those were properties of the OLD (pre-fix) run's artifacts, and this note does not re-assert them against the new run without re-checking; a maintainer who needs those specific repros should re-verify against the new cell or fall back to `spm/v1.5.58_ihp-sg13g2`, which is unaffected by this retirement.
- **Two published NON-CELLS were retired 2026-08-09 by the repo gatekeeper — by MOVING, not deleting.** `spm/v1.5.58_ihp-sg13g2` -> `spm/retired/v1.5.58_ihp-sg13g2` (211 files) and `u_hawaii_adc/v1.9.86_sky130A` -> `u_hawaii_adc/retired/v1.9.86_sky130A` (188 files). This is a DIFFERENT kind of retirement from the three supersessions above: those replaced a cell with a newer run of the SAME (IC x PDK); these two have no replacement because the combination was never a cell. `CELL_MATRIX.md` derives each cell from the design's own `L19_CONSTRAINTS_PDK.json` / `L1`, and lists both combinations under 'Combinations that are NOT cells' — spm declares sky130A primary + gf180mcuD secondary (and the ihp-sg13g2 run's OWN L19 says `pdk_target: sky130`); u_hawaii_adc declares ihp-sg13g2 (L19 `sg13g2`, L1 'Target PDK **IHP SG13G2**') with sky130 appearing 0 times in its input docs. Moving resolves the standing conflict between the layout contract (an IC dir holds `input/` and `v*_<PDK>/`) and this file's never-delete rule: nothing is lost and the `v*_<PDK>/` level becomes conformant. Each moved folder carries a `RETIRED.md` stating why it is not a cell, that it is history and MUST NOT be cited as a result, and who decided it when. What does NOT carry forward: their status as cells, and any claim derived from them — including `spm x IHP-SG13G2` as one of the campaign's converged results and `u_hawaii_adc x sky130A converged / PASS` as published on the site's IC-matrix. The preceding note's advice to 'fall back to `spm/v1.5.58_ihp-sg13g2`' is superseded: that path moved, and a non-cell is not a fallback for a cell — re-verify against a declared cell instead. Dependents that READ these paths live outside `benchmark-data/` and are migrated in a SEPARATE commit; a plugin change and a benchmark result never share one.

