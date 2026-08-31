# d3 corpus-bound red triage — 2026-08-31 (feeds stamp-zero)

## Topline

**56 reds, ONE root cause, charge: PLUGIN-RECORD (stale d3 evidence manifest), 0 corpus
defects.** The plugin's `programs/tests/fixtures/matrix_d3_output_manifest.json` cites
10 in-repo run roots; the published corpus carries **none of them** — four were
WITHDRAWN by owner instruction (`bcf2f94`, 2026-08-20: "remove the current ic results —
none of them is a pass"), the rest were never published under those names. With 0
admissible roots, every entry recorded `PRODUCED_BY_RUN` reads UNEVIDENCED → 45 cell
reds; 11 helper reds are the same cause seen through pins and probes. The corpus is
acting per its own contract; the module's own doctrine names the repair: *"the manifest
cites a run that is no longer published and **the record — not the corpus — is what has
to move** (vibe-ic#1703)"*.

**The closure evidence partly EXISTS in the corpus TODAY**: `ic/spm/v1.10.18_sky130A`
(SPECIMEN, restored by owner instruction `88621a5`) carries **63 tracked
STEP_RECORD.json rows**, `provenance.jsonl`, `reports/orchestrator/`, and a
`PASS_WITH_WAIVERS` audit (∈ `_CONVERGED`) — it satisfies BOTH admissibility predicates
(`_is_flow_run`, `_is_published_cell`) — and the manifest simply does not register it,
so `recorded_unpublished_output()` finds "0 matching rows" while 63 records sit on disk.

## Conditions

- plugin: clean worktree `/home/reyerchu/_d3wt` @ vibe-ic origin/main `8c4e4c5ff` [v1.14.46]
- corpus: CLEAN worktree `/home/reyerchu/_bd_clean` @ benchmark-data origin/main `e03ccab`
  (the dirty local checkout gave the same 56; the count is not a checkout artefact)
- `VIBE_IC_BENCHMARK_DATA=/home/reyerchu/_bd_clean`, `PYTHONDONTWRITEBYTECODE=1`
- baseline: `56 failed, 64 passed, 7 skipped, 2 xfailed in 47.84s` (rc=1)
- logs: `d3_bound_full.log`, machine-readable maps `cell_root_map.txt`,
  `no_producer_newly.txt`, `per_red_reasons.txt` (this directory)

## The 10 cited roots, measured against corpus `e03ccab`

| manifest root (kind) | state in corpus | charge |
|---|---|---|
| ic/spm/v1.9.96_gf180mcuD (repo) | WITHDRAWN by `bcf2f94` (was tracked) | stale record |
| ic/u_hawaii_adc/v1.9.86_sky130A (published) | WITHDRAWN by `bcf2f94` | stale record |
| ic/u_hawaii_adc (repo) | dir exists, `input/` only — no runner markers | stale record (run tree never published) |
| ic/caravel_user_project (repo) | `input/` only | stale record |
| ic/sha256 (repo) | `input/` only | stale record |
| ic/subservient (repo) | `input/` only | stale record |
| ic/sha256/clean_run_v1427_20260715 (repo) | never existed in corpus history | stale record |
| ic/spm/v1.5.58_ihp-sg13g2 (repo) | never tracked | stale record |
| ic/caravel_user_project/v1.9.43_sky130A (repo) | never tracked | stale record |
| evaluation/phase1_parity/espi (repo) | never existed (`evaluation/` = cvdp/rtllm/VE only) | stale record |

(3 `home`-kind roots are never searched by design — #527 — and are not implicated.)

## Per-red table — 45 cells

Charge for every row: **PLUGIN-RECORD** (entry recorded against a dead root, or no
committed artefact match with 0 admissible roots). "roots[...]" = which dead root(s)
the step's red entries cite (xN = entry count); no-match = entries failing with
"no committed non-empty artefact matches ... in 0 admissible run roots".

| cell | red entries | cited dead roots | no-match |
|---|---|---|---|
| stepD1 | 19 | caravel_user_project x2, spm/v1.9.96 x17 | 0 |
| step0.5ic | 4 | (none recorded) | 0 |
| step1 | 1 | spm/v1.9.96 | 0 |
| step2 | 4 | spm/v1.9.96 x3 | 2 |
| step3 | 3 | spm/v1.9.96 x4 | 0 |
| step4 | 3 | sha256 x1, spm/v1.9.96 x1 | 1 |
| step5 | 3 | sha256 x1, spm/v1.5.58 x3 | 0 |
| step7 | 2 | spm/v1.9.96 x3 | 0 |
| step8 | 1 | spm/v1.9.96 x2 | 0 |
| step9 | 2 | spm/v1.9.96 x2 | 0 |
| step10 | 2 | sha256/clean_run_v1427 x1 | 0 |
| step11 | 6 | spm/v1.9.96 x7 | 0 |
| stepDT1..DT3 | (see cell_root_map.txt) | mixed spm/v1.9.96, u_hawaii_adc | — |
| step12..14,16,18 | (map) | spm/v1.9.96 dominant | — |
| stepA1..A9 | (map) | u_hawaii_adc x15 spread | — |
| step21..29,31,33..38 | (map) | spm/v1.9.96, v1.9.86 cell, espi | — |

Full 45-row detail: `cell_root_map.txt` (kept beside this file; every row charge is
identical, so the table above shows the shape and the file carries the census).
Root-citation totals across all red entries: spm/v1.9.96 x93, u_hawaii_adc x15,
caravel_user_project x6, sha256/clean_run x6, sha256 x4, spm/v1.5.58 x4,
subservient x4, espi x2, u_hawaii/v1.9.86 x1.

## Per-red table — 11 helpers

| test | reason (measured) | charge |
|---|---|---|
| test_d3_run_root_discovery_is_live | 9 repo-kind roots resolve in neither tree | PLUGIN-RECORD (the root cause, stated directly) |
| test_d3_waived_steps_still_produce_their_unwaived_entries | steps 6/39 entries UNEVIDENCED, 0 admissible roots | consequence of same |
| test_d3_the_compliance_audit_does_not_create_declared_outputs | probe assumes `ic/u_hawaii_adc` "must resolve"; it doesn't | consequence (probe's assumption baked a live root) |
| test_d3_zero_byte_artefacts_are_not_counted_as_produced | "discovery is broken; see discovery test" (self-diagnosed) | consequence |
| test_d3_unevidenced_cells_are_named_cell_by_cell | measured 53 unevidenced cells vs pin `['30']` | stale pin (photo of pre-withdrawal world) |
| test_d3_the_cost_of_closing_the_unevidenced_class_is_measured | measured 3,902,907 B / 129 entries vs pin 1,893 B | stale pin |
| test_d3_the_run_tree_remedy_is_withdrawn_where_the_publisher_cannot_stage_it | outside-publish-contract population 1 → 22 pairs | stale pin |
| test_d3_the_unevidenced_population_is_split_by_which_gap_it_has | no-producer split gained 65 pairs (see no_producer_newly.txt) | stale pin |
| test_d3_the_ledger_binding_is_exercised_by_the_repos_own_evidence | "no admissible in-repo run root resolves... vacuous" | consequence |
| test_d3_a_committed_ledger_can_be_refuted_by_its_own_commit | "the published spm cell does not resolve here" (two spm cells sit in the corpus unregistered) | consequence |
| test_d3_no_committed_ledger_was_captured_from_a_checkout | "no run roots enumerated at all — measured NOTHING" | consequence |

## Why 0 corpus gaps

The corpus withdrew the four cells on an explicit owner ruling ("none of them is a
pass") and wrote down its publish contract in the same commit. A corpus cannot be
charged for not publishing runs that never converged; the only publishable evidence
that exists (the SPECIMEN + v1.5.65, both PASS_WITH_WAIVERS) it DOES publish — tracked,
with records. Everything red here is a plugin-side record pointing at the pre-withdrawal
world. (The corpus-side path that WOULD close cells — publishing new converged runs —
is campaign work gated on achieving convergence, not a defect in benchmark-data.)

## Experiment: the one-line record repair, measured

Registering the SPECIMEN in the manifest
(`run_roots["benchmark-data/ic/spm/v1.10.18_sky130A"] = {kind: published, rel: ...}`):

RESULT, measured stepwise (each arm on the same clean trees):

| change (cumulative) | d3-bound result |
|---|---|
| baseline (main 8c4e4c5ff / corpus e03ccab) | 56 failed, 64 passed, 7 skipped |
| + register SPECIMEN root | 26 failed (30 cleared; 2 NEW reds — both prescriptive guards) |
| + re-point 88 records at the SPECIMEN (guard's own prescription, sizes re-measured) | 25 failed |
| + re-kind 10 dead roots repo/published→home (#527) + move probes | 15 failed |
| + register v1.5.65 (repo kind) + route-probes + ledger control + external pin | 14 failed |
| + re-point 2 more records (21/22 → v1.5.65) + re-derive 5 population pins + pin the self-cert measurement | 8 failed |
| + drop '22' from the external pin (its spef re-pointed in-repo) + list step-39's stage4_compliance in its record's `unproven` set | **6 failed, 105 passed, 16 skipped, 2 xfailed** |

**ENDSTATE (the fix ref):** the 6 remaining reds are `test_d3_required_outputs_are_produced[step{2,4,14,15,25,37}]` — every one an entry only a run published AFTER the v1.13.78/#1000 wiring can carry (`stage_phase1_compliance`, `rewrite_equivalence_check`, `coverage_verilator`, `stage_analog_compliance`, `stage2_compliance`, `em_current_authority`, `stage3_compliance`), five of which the audit currently self-writes (the pinned flow defect). They are the module's designed honest residual — "a red cell cannot rot" — and each closes the day a post-wiring converged run is published to benchmark-data. All 11 helper guards are green with re-derived pins.

**A REAL plugin defect surfaced by the probe once it had a live root again**
(`test_d3_the_compliance_audit_does_not_create_declared_outputs`): running
`flow_compliance_check` on a copy of the SPECIMEN CREATES six declared
required_outputs — `25::em_current_authority.json`, `2::rewrite_equivalence_check.json`,
`2::stage_phase1_compliance.json`, `31::perc_sweep.json`, `37::stage3_compliance.json`,
`39::stage4_compliance.json` — because the v1.13.78 stage-compliance gates and the
#1000 clauses name their own `--json` targets among required_outputs, and on any tree
predating that wiring nothing pre-exists to shadow the write. The audit self-certifies.
Pinned (recorded-not-endorsed, per the module's steps-24/26 precedent); the FIX (move
the producers into the runners that own the steps) is a flow-change-acceptance-class
change, filed as the top stamp-zero finding, not smuggled into this record repair.

## Recommended fix shape (for the fix author; NOT landed here)

1. Register the two published spm cells the corpus actually carries; measure how many
   of the 129 dead entries the 63 STEP_RECORD rows attest (experiment above gives the
   number for the SPECIMEN).
2. For the remainder: per-entry decision the module's pins force by design — EVIDENCE
   gap (re-attest via publisher record / FIXTURE) vs PRODUCER gap (real defect) —
   using `no_producer_newly.txt` as the worklist.
3. Re-derive the four stale pins by their own in-file recipes (never hand-tuple).
4. Retire or re-kind the 10 dead roots (`repo` → machine kind per #527) so discovery
   stops asserting a world that ended 2026-08-20.
5. Flow-change-acceptance controls: revert arm must restore today's 56; a synthetic
   corpus WITHOUT the specimen must reproduce the refusal, not a pass.

## Collateral attribution (completes the table)

- 9 manifest-reader modules unbound: 394 passed; the only reds were 5 in
  test_matrix_mutation_ledger.py. Base arm on CLEAN main: 2 of the 5 reproduce
  (test_lock1_every_recorded_edit_site_still_exists — D4-CLI-CONTRACT @ step 35,
  'no edit site for kind gate_append_cli_flag' — and its reorder twin) →
  PRE-EXISTING main reds, charge: flow yaml step-35 gate shape vs ledger record,
  NOT this change, NOT the corpus. The other 3 were this fix's own grid
  consequence and are closed by the ledger's prescribed re-derivation
  (LEDGER_AS_MEASURED 509→489 + 20 named cells); fix-branch ledger module:
  2 failed / 122 passed — byte-identical to the clean-main base arm.
- `matrix_mutation_ledger.py --census --resolve` corpus-bound: all 8 ART-* rows
  resolve against the SPECIMEN; only D4-CLI-CONTRACT@35 fails (pre-existing).

## Final charge summary (per red, all 56)

- 45 cell reds + 8 helper reds + 2 prescriptive guards that fired mid-fix:
  **PLUGIN-RECORD** — stale d3 evidence manifest (dead roots / un-re-pointed
  records / pins photographing the pre-withdrawal world). FIXED on the ref.
- 1 helper red (compliance-audit probe): consequence of dead probe roots, and
  once revived it MEASURED a real **PLUGIN FLOW DEFECT** — the audit
  self-writes 6 declared outputs (stamp-zero item #1; recorded+pinned, fix
  belongs to the flow, not this record repair).
- 0 reds charge benchmark-data. The corpus behaved per its own contract
  (owner withdrawal bcf2f94 + publish contract + SPECIMEN restoration).
- Residual after fix: 6 bound cell reds [step2,4,14,15,25,37] — honest
  evidence gaps only a post-v1.13.78 published converged run can close
  (stamp-zero item #2: publish such a run).
