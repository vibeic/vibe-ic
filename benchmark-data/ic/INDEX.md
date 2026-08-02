# `benchmark-data/ic/` — what each published cell IS

<!-- GENERATED FILE — do not hand-edit.
     Regenerate:  python3 vibe-ic-marketplace/plugins/vibe-ic/programs/benchmark_evidence_index.py --write
     Verify:      python3 vibe-ic-marketplace/plugins/vibe-ic/programs/benchmark_evidence_index.py --check
     The only hand-maintained input is `retention.json` beside this file. -->

This tree holds converged evidence AND runs that did not converge, and the folder name deliberately does not say which (`benchmark-data/PUBLISHING.md`: the verdict lives in `RESULT.md`, and a `clean_run_*`/`pass_*` prefix would strip the committed phase folders). This index is the answer that costs no JSON to read.

**Nothing here is deleted for failing.** Removing a failed run would make "we never ran this" and "we ran it, it failed, and we kept the record" the same state. Cells marked `corpus: yes` are also the population two BLOCKING gates walk (`cross_layer_reference_check --corpus`, `l4_systemrdl_export audit-corpus`).

| classification | cells |
|---|---|
| CONVERGED EVIDENCE | 3 |
| RETAINED FAILURE | 13 |
| UNAUDITED RECORD | 13 |
| **total** | **29** |

## CONVERGED EVIDENCE — 3

The cell's own audit artefact reads PASS or PASS_WITH_WAIVERS. This is what the project means when it says a cell converged.

| cell | audit verdict | steps | orchestrator | RESULT.md says | corpus | retained for |
|---|---|---|---|---|---|---|
| `spm/v1.5.58_ihp-sg13g2` | PASS_WITH_WAIVERS | P35 F0 M0 W3 | vibe_ic=PASS_WITH_WAIVERS; phase3=PASS_WITH_WAIVERS; phase2=PASS_WITH_WAIVERS | UNSTATED | yes | converged; the real-GDS source for #287/#291 and the formal-evidence-chain repro for #412/#417/#418/#420 |
| `spm/v1.5.65_sky130A` | PASS_WITH_WAIVERS | P35 F0 M0 W3 | vibe_ic=PASS_WITH_WAIVERS; phase3=PASS_WITH_WAIVERS; phase2=PASS_WITH_WAIVERS | UNSTATED | yes | converged; the byte-identical witness run the #235 fix landed against, and the corpus #421/#441 measured gate coverage on |
| `spm/v1.5.66_gf180mcuD` | PASS_WITH_WAIVERS | P33 F0 M0 W4 | vibe_ic=PASS_WITH_WAIVERS; phase3=PASS_WITH_WAIVERS; phase2=PASS_WITH_WAIVERS | UNSTATED | yes | converged; repro for #363 (EM coordinates outside the die) and second site of the #366/#381 formal false-PASS |

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
| `u_hawaii_adc` | FAIL | P0 F0 M9 W1 | vibe_ic=PASS_WITH_WAIVERS; phase2=PASS_WITH_WAIVERS | UNSTATED | yes | read directly by tests under programs/tests/ (published-cell layer gates); the one cell whose audit and orchestrator verdicts contradict each other |
| `u_hawaii_adc/clean_run_v1422_20260715` | FAIL | P3 F2 M8 W8 | vibe_ic=FAIL; phase2=FAIL | UNSTATED | yes | reproduction for #141/#142/#143 — their repro commands name this path verbatim |
| `u_hawaii_adc/clean_run_v1427_20260715` | FAIL | P2 F1 M6 W1 | vibe_ic=FAIL; phase2=FAIL | UNSTATED | yes | corpus member — walked by both blocking corpus gates |

## UNAUDITED RECORD — 13

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
| `u_hawaii_adc/clean_run_v1432_commercial` | — | — | — | UNSTATED | no | record only |
| `u_hawaii_adc/clean_run_v1432int_commercial` | — | — | — | UNSTATED | no | record only |

## Reading the columns

- **audit verdict** — `verdict` in the cell's `reports/audit/phase23_completion_audit.json`. `—` means the artefact does not exist: no machine verdict was ever recorded, which is neither a pass nor a failure.
- **steps** — `step_counts` from the same file: PASS / FAIL / MISSING / WAIVED. This is the magnitude behind the verdict. `F1` and `M27` both read FAIL and are not the same result.
- **orchestrator** — the `verdict` each `reports/orchestrator/*_one_shot.json` recorded. Where it disagrees with the audit column, the disagreement is real and is shown rather than resolved.
- **RESULT.md says** — the verdict the human-facing document DECLARES on an `OVERALL:` / `VERDICT:` / `STATUS:` line. `UNSTATED` means it states its outcome in prose only, so no verdict was extracted; `—` means there is no RESULT.md. Where this column disagrees with **audit verdict**, the cell contradicts itself — that is the condition this index was built to make visible.
- **corpus** — the cell carries tracked `phase1/generated_docs/`, so it is inside the population both blocking corpus gates count. Changing that population changes their recorded counts.
- **retained for** — from `retention.json` where a maintainer has recorded one; otherwise derived. Absence is not evidence a cell is unused: several with no recorded reason are read directly by tests under `programs/tests/`.

## Notes

- **The `#235` attribution is weaker than this repo repeats.** PR #421 and issue #440 both state that `sha256/clean_run_v1422_20260715` IS the #235 reproduction. Checked: #235's own body and comments name no `benchmark-data/` path at all, and the run its landing comment cites as byte-identical evidence is `spm/v1.5.65_sky130A`. The cell is still load-bearing — #140/#145/#146/#147 itemise its files as evidence — but not for the reason most often given for keeping it. A citation repeated three times is not a citation checked once.
- **No cell here is loaded as a test fixture merely by being cited in an issue.** Deleting a cited-but-unread cell would break no test and would still destroy the record an issue points at. That is the argument for labelling rather than deleting, and it is also why `retained for` is prose a maintainer writes rather than something derived from a grep.

