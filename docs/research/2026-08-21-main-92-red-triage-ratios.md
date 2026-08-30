### the 57 non-1.6x IDs — red ratio per lane, pass 1 + interleaved repeats

### VERDICT: IMAGE-ONLY = 0 and HOST-ONLY = 0, so **main is genuinely red here — these are NOT environment artefacts of one lane**. Of these 57 IDs, 55 reproduce in BOTH the pinned CI image and on this host, on every observation taken; the only exceptions are the 2 named FLAKY below, whose red ratios are stated. Nothing on this list can be closed by blaming the developer host. **These ratios were taken against `867de4289` (v1.11.18) and are historical; a row leaves the BOTH bucket only when it has been RE-MEASURED green in both lanes at a named later sha, and moves to CLEARED below rather than disappearing. A row may also leave BOTH for NOT_MEASURED below, which is neither of those two and is not a closure: it records that the predicate declined to look and names what it could not look at.**

### bucket needs BOTH lanes to have >=1 observation; NOT_MEASURED is never a default
  BOTH          0
  CLEARED       48
  FLAKY         2
  NOT_MEASURED  7

bucket        image    host     id
FLAKY         4/13     13/13    test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged
FLAKY         1/10     0/10     test_matrix_63x8_coverage.py::test_live_collection_relays_finite_semantic_progress_past_old_bound

### NOT_MEASURED — the predicate declined to look, re-measured at a named sha

**These seven left BOTH by an OWNER RULING ON 2026-08-28**, and the ruling is
that a deliberate design decision must not be reported as a defect.
`benchmark-data` was MOVED OUT of this repository on purpose, and large raw
geometry — `*.def`, `*.gds`, `*.spef`, `*.oas` above the ceiling — is NOT
COMMITTED on purpose. A check that goes red because this repository followed
its own published rules is measuring the policy and calling it a defect.

NEITHER OF THE OTHER TWO BUCKETS IS TRUE OF THESE ROWS. BOTH means (red) in
both lanes and CLEARED means re-measured GREEN at a named sha; a cell that was
honestly not looked at is neither, and this table's own header has always said
so — *"NOT_MEASURED is never a default"*. It is now a bucket rather than only
a warning, and the repository's first principle applies unchanged in both
directions: a gate that could not run has not passed, and it has not failed
either.

**NOT A WAIVER, AND IT CLOSES NOTHING — the state SELF-INVALIDATES.** The
moment the evidence becomes obtainable — the artefact is published, or the
manifest record is re-pointed at a run root the dimension actually searches —
the predicate returns a verdict and the cell RE-ENTERS THE DENOMINATOR, in
whichever colour it earns. Nothing here is excluded from any enumeration and
nothing here is counted as coverage: `programs/tests/matrix_63x8/README.md`
already prints all 47 of the coverage row's cells in its NOT MEASURED column
and already says "NOT MEASURED is not a pass and not a defect".

The `was` ratios are the original BOTH observations at `867de4289`, kept so the
history is not erased. Re-measured whole-module, serial, no `-k`, corpus
pointer UNSET, on the host lane at the sha named in the first column.

MAIN MOVED WHILE THIS WAS MEASURED, and the measurement still carries. The
re-measurements below were taken at `75c71a47a1` (v1.12.18); this landing sits
on `bff27f202` (v1.12.22), one commit later. `git diff` between the two over the
three files this landing touches — the census reader, its README and this table —
is EMPTY, so nothing the measurement depended on changed underneath it. The sha
in the first column is the sha each row was measured at, not the sha it landed
on, because those are different facts.

WHICH TREE EACH ROW WAS RE-MEASURED ON, because they are not the same and the
difference matters. **The six `d3` rows were re-measured on CLEAN main** at that
sha: `test_matrix_d3_outputs_produced.py` runs rc=0, **54 passed / 66 skipped in
50.71 s**, and each of the six skips prints the citation quoted above. Their
skip is already main's behaviour and owes nothing to any branch. **The seventh
is measured at that sha with the refusal applied**; on clean main it still
FAILS — 1 failed / 37 passed in 356.80 s across both 63x8 modules — and that
failure, over 0 measured red and 47 not measured, is exactly what the ruling
names.

not_measured_at  was(image/host)  id / what it could not look at / why not obtainable
75c71a47a1   5/5 5/5 RED   test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step15]
             could not look at   `phase3/stage3/pnr/floorplan.def` from run root `campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721`
             why not obtainable  the record cites a campaign run root this dimension searches on NO host, so the corpus pointer cannot settle it; and `programs/benchmark_evidence_publish.py` names `floorplan.def` VERBATIM as still `NOT_PUBLISHED` — "widening the SUBTREE remains an evidence-policy call left alone here" — so publishing the corpus would not settle it either

75c71a47a1   5/5 5/5 RED   test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step17]
             could not look at   `phase3/stage3/pnr/placed.def` from run root `campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721`
             why not obtainable  the record cites a campaign run root this dimension searches on NO host, so the corpus pointer cannot settle it; and `programs/benchmark_evidence_publish.py` names `placed.def` VERBATIM as still `NOT_PUBLISHED` — "widening the SUBTREE remains an evidence-policy call left alone here" — so publishing the corpus would not settle it either

75c71a47a1   5/5 5/5 RED   test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step19]
             could not look at   `phase3/stage3/pnr/post_cts.def` from run root `campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721`
             why not obtainable  the record cites a campaign run root this dimension searches on NO host, so the corpus pointer cannot settle it; and `programs/benchmark_evidence_publish.py` names `post_cts.def` VERBATIM as still `NOT_PUBLISHED` — "widening the SUBTREE remains an evidence-policy call left alone here" — so publishing the corpus would not settle it either

75c71a47a1   5/5 5/5 RED   test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step20]
             could not look at   `phase3/stage3/pnr/post_hold.def` from run root `campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721`
             why not obtainable  the record cites a campaign run root this dimension searches on NO host, so the corpus pointer cannot settle it; and it is the same subtree and the same clause — raw PnR scratch under `phase3/stage3` is not staged, which is why the corpus at `88621a5ac` carries ZERO `*.def` of any name

75c71a47a1   5/5 5/5 RED   test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step30]
             could not look at   `phase3/stage3/spice/*.sp OR phase3/stage3/spice/*.spice OR sim_spice/*.sp` from run root `AI_IC_design/4th_benchmark/cv32e40p_e2e`, and `phase3/stage3/spice/correlation.json OR reports/phase3/spice_correlation.json` from run root `AI_IC_design/4th_benchmark/ibex_e2e`
             why not obtainable  both records cite benchmark run roots this dimension searches on NO host; and `phase3/stage3` scratch is not staged by the same evidence-policy clause, so the corpus carries 0 `*.sp` and its only three `*.spice` files are LVS netlists under `phase3/stage3/lvs/`, which is not the declared path

75c71a47a1   5/5 5/5 RED   test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step32]
             could not look at   `phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json` from run root `campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721`
             why not obtainable  the record cites a campaign run root this dimension searches on NO host; and the corpus carries no `postroute_timing_repair` path at all, so the pointer has nothing behind it for this cell to read

75c71a47a1   2/2 2/2 RED   test_matrix_63x8_coverage.py::test_no_cell_is_counted_enforced_while_its_predicate_is_red
             could not look at   the 47 disagreeing cells its own live run reports — 45 `ENFORCED-SKIPPED` + 2 `WAIVED-SKIPPED`, every one of them a `d3 (outputs_produced)` coordinate, and **0 MEASURED RED**
             why not obtainable  the six artefacts above plus the rest of dimension 3's corpus-bound declarations. The check now REFUSES rather than fails when MEASURED RED is empty and NOT MEASURED is not, carrying the same 47-cell enumeration; ONE measured red still FAILS it

The absence was checked against the corpus itself, not assumed: the public
`vibeic/benchmark-data` tree at `88621a5ac` lists **8897 paths, untruncated,
with ZERO `*.def`, ZERO `*.sp` and ZERO `postroute_timing_repair` paths**. So
these are not rows waiting on someone to set `VIBE_IC_BENCHMARK_DATA` — there
is nothing behind that pointer for them to read.

### CLEARED — re-measured GREEN in both lanes at a named later sha

Not a re-bucketing of the old observation: a new measurement, stated with the sha it
was taken at. The original ratio is kept in the row so the history is not erased.

The `now` ratios are the pooled observations of TWO independent sessions on two
different fleet hosts, each with its own fresh `--no-local` clone, its own control
clone and its own constructed violations: 2+2 image runs and 3+3 host runs, whole
modules, no `-k` selection, `VIBEIC_CORPUS_ROOT` unset. Neither pass reused an
artefact of the other and both reached the same verdict.

THAT TWO-SESSION PARAGRAPH DESCRIBES THE EIGHT `ae5cc4dbf` ROWS ONLY. Each
clearance states how its own `now` ratio was taken, in its own block below, and
they are not all the same shape. Two different slices cleared at `628ca251f`:
the eleven rows reading `0/2 0/2` are the extraction / structured-vacuity / w4
slice, and the seven reading `0/3 0/3` are the inventory / step-metrics /
manifest-parity slice — one session, image 0/3 and host 0/3 interleaved, with a
both-lane control at `867de4289`. Read a row's ratio with its own block, never
with this paragraph.

cleared_at   was(image/host)  now(image/host)  id
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_77_lvs_reachable.py::test_lvs_fails_on_real_mismatch
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_77_lvs_reachable.py::test_lvs_runs_and_passes_on_match
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_97_issue477_lvs_incomplete.py::test_clean_complete_lvs_still_passes
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_97_issue477_lvs_incomplete.py::test_real_mismatch_still_fails_as_conclusive
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_97_issue477_lvs_incomplete.py::test_small_ext2spice_error_count_is_warning_not_fail
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_97_issue477_lvs_incomplete.py::test_truncated_verdict_less_report_is_incomplete_fail
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_3_24_issue524_lvs_pin_matching_verdict.py::test_runner_pin_fail_is_conclusive_mismatch_not_incomplete
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_3_24_issue524_lvs_pin_matching_verdict.py::test_runner_truncated_still_incomplete
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_extraction_input_blocked_verdict.py::test_complete_generic_tech_still_passes_end_to_end
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_extraction_input_blocked_verdict.py::test_complete_tech_passes_with_real_tech_lef_layer_crosscheck
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_extraction_input_blocked_verdict.py::test_complete_tech_with_matching_design_still_passes
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_extraction_input_blocked_verdict.py::test_unreadable_tech_does_not_block
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_GUARD_the_shipped_step_is_not_vacuous_when_its_sim_actually_ran
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_the_other_self_aware_shipped_gate_also_reaches_the_tier
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_the_shipped_step_names_the_one_clause_that_examined_nothing
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_organic900_901_ratchet_and_json_vacuity.py::test_a_shrink_is_still_allowed
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_passed_the_empty_predicate_lists
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_passes_the_same_empty_corpus_silently
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_was_silent_on_the_advisory_slot
628ca251f    5/5 5/5 RED     0/3 0/3 GREEN  test_flow_manifest_declaration_parity.py::test_every_declared_path_has_a_manifest_entry
628ca251f    5/5 5/5 RED     0/3 0/3 GREEN  test_flow_manifest_declaration_parity.py::test_the_population_is_the_whole_flow_and_is_not_empty
628ca251f    5/5 5/5 RED     0/3 0/3 GREEN  test_program_inventory_no_drift.py::test_check_mode_exits_zero_on_the_committed_tree
628ca251f    5/5 5/5 RED     0/3 0/3 GREEN  test_program_inventory_no_drift.py::test_clean_tree_reports_no_failure
628ca251f    5/5 5/5 RED     0/3 0/3 GREEN  test_program_inventory_no_drift.py::test_declared_non_counts_are_still_present[and all 56 EDA/device tools]
628ca251f    5/5 5/5 RED     0/3 0/3 GREEN  test_program_inventory_no_drift.py::test_stated_counts_in_the_documents_match_the_tree
628ca251f    5/5 5/5 RED     0/3 0/3 GREEN  test_step_metrics_coverage.py::test_declared_coverage_matches_the_tree
5d1b82988    5/5 5/5 RED     0/1 0/1 GREEN  test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step31]
5d1b82988    5/5 5/5 RED     0/1 0/1 GREEN  test_matrix_mutation_ledger.py::test_every_enforced_cell_carries_a_named_mutation[step0.5ic]
51c0db4b7    5/5 5/5 RED     0/1 0/1 GREEN  test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships
51c0db4b7    5/5 5/5 RED     0/1 0/1 GREEN  test_flow_compliance_check_gate.py::test_a_real_verdict_is_not_mistaken_for_a_crash
984f30df7    5/5 5/5 RED     0/2 0/3 GREEN  test_issue306_register_paydown.py::test_306_shipped_tree_is_green_against_its_register
984f30df7    5/5 5/5 RED     0/2 0/3 GREEN  test_issue490_drc_report_check_argv.py::test_the_docstring_does_not_claim_an_enforcement_tier_it_lacks
984f30df7    5/5 5/5 RED     0/2 0/3 GREEN  test_medlow_synth_dft_backlog.py::test_step11_declaration_is_satisfiable_by_a_successful_run
984f30df7    5/5 5/5 RED     0/2 0/3 GREEN  test_v0_2_96_issue460_coverage_bridge.py::test_e2e_oracle_pass_is_deferred_not_counted_without_coverage
984f30df7    5/5 5/5 RED     0/2 0/3 GREEN  test_v0_2_96_issue460_coverage_bridge.py::test_e2e_oracle_pass_lifts_step4_out_of_skipped_condition
984f30df7    5/5 5/5 RED     0/2 0/3 GREEN  test_v0_3_5_issue502_503_cascade_attribution.py::test_ordering_ancestry_is_two_orders_of_magnitude_wider
462b66838    5/5 5/5 RED     0/1 0/1 GREEN  test_issue1082_open_w_category_closed.py::test_no_declared_report_is_written_through_open_w
462b66838    5/5 5/5 RED     0/1 0/1 GREEN  test_issue1082_open_w_category_closed.py::test_no_new_offender_and_the_ratchet_holds
462b66838    5/5 5/5 RED     0/1 0/1 GREEN  test_issue1470_atomic_declared_report.py::test_the_gate_is_green_and_the_ratchet_holds
72a558fdb    2/2 2/2 RED     0/3 0/4 GREEN  test_matrix_63x8_coverage.py::test_every_na_cell_asserts_a_live_precondition
72a558fdb    5/5 5/5 RED     0/3 0/4 GREEN  test_matrix_63x8_ledger.py::test_absent_from_audit_is_surfaced_not_swallowed
72a558fdb    5/5 5/5 RED     0/3 0/4 GREEN  test_matrix_63x8_ledger.py::test_accessors_track_a_removed_field
72a558fdb    5/5 5/5 RED     0/3 0/4 GREEN  test_matrix_63x8_ledger.py::test_every_coordinate_appears_exactly_once
72a558fdb    5/5 5/5 RED     0/3 0/4 GREEN  test_matrix_63x8_ledger.py::test_output_entries_classify_into_the_four_kinds
f8781ed4d    2/2 2/2 RED     0/2 0/2 GREEN  test_matrix_63x8_census_freshness.py::test_the_census_block_is_fresh
f8781ed4d    2/2 2/2 RED     0/2 0/2 GREEN  test_matrix_63x8_census_freshness.py::test_the_published_total_equals_the_live_census
f8781ed4d    2/2 2/2 RED     0/2 0/2 GREEN  test_matrix_63x8_coverage.py::test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved
f8781ed4d    2/2 2/2 RED     0/2 0/2 GREEN  test_matrix_63x8_coverage.py::test_the_enforcement_census_is_reported_for_humans

All eight are one cause and one fix. The three modules' shared `_fake_docker` stub
modelled a Magic `ext2spice` that wrote the extracted netlist but never wrote
`FEEDBACK_OUT` — an extraction whose error channel was never dumped, which real Magic
always dumps (0 bytes when `feedback count` is 0). `step_lvs`'s pre-netgen gate
`magic_illegal_overlap_check` refused it, correctly, as `EXTRACTION_FEEDBACK_ABSENT`:
an absent file is not a measured zero. Every one of the eight died at that abort
before netgen was ever reached. `d3dce649b` (v1.11.43) repaired the stub in all three
modules; no assertion was weakened, no case deleted, no skipif added, no tolerance
widened. Both directions are shown in
`docs/research/2026-08-27-lvs-family-remeasured-at-v1-11-96.md`: removing that same
`FEEDBACK_OUT` write again at `ae5cc4dbf` sends the two `test_v0_2_77` IDs straight
back to RED with the same finding, and leaves the module's three non-extraction tests
green.

The independent second pass is in
`docs/research/2026-08-28-lvs-family-independent-reverification.md`, and it closes
the two holes a single-direction proof leaves. Its CONTROL run at the ratios
table's own subject `867de4289` fails exactly these eight IDs and no others, in
BOTH lanes — so the harness demonstrably can produce this red, and the original
`5/5 5/5` was a true measurement of its own subject. Its constructed violation V1
(remove the `FEEDBACK_OUT` write at head, all three modules) also fails exactly
these eight in BOTH lanes; its constructed violation V2 feeds the gate a feedback
dump that IS written and carries two real `Illegal overlap` records while netgen
reports `Circuits match uniquely`, and `step_lvs` still returns FAIL /
`LVS_EXTRACTION_ILLEGAL_OVERLAP` in both lanes. The gate therefore refuses an
unmeasured channel AND a dirty one, and is not a check that refuses everything.

The four `test_matrix_63x8_{census_freshness,coverage}` IDs above are ONE cause and it is
the LAST non-cell red in the dimension modules. `_cell_outcomes_from_reports` refuses to let
the nested outcome run's rc=1 be represented by anything outside the step x dimension cell
join, so ONE red SUPPORTING test in any `test_matrix_d*` module declares the whole 612-cell
census NORECORD — and every id that reads that census goes red with it, five files away from
the cause. The one red item was
`test_matrix_d7_outputs_list_complete.py::test_the_dropped_edge_RETURNS_when_the_step_stops_supplying_the_flag`.

Its premise had never been true on a corpus-free checkout. W2 is produced AND consumed AND
undeclared; the control is about the CONSUMER leg, and its first two assertions prove that
leg and passed before and after. The third asks the whole pipeline for a finding, which also
needs a PRODUCER, and for `reports/final_summary.md` neither oracle can answer here: the AST
does not follow `_pl.report_path(project, "final_summary.md")` through an `IfExp`
(`writers_of` is `()`), and every root carrying a `reports/write_ledger.json` is a published
cell that moved to vibeic/benchmark-data (`record_roots()` is `()`). MEASURED at
`a974ed55c~1` — the tree from before the rule the control was written for —
`findings_for("37")` is ALREADY `()`. It was landed green where a record was readable and
was red everywhere else. Fixed at `f8781ed4d` [v1.12.18] by PLANTING the producer with the
module's own `_plant_record` (the real `step_write_ledger` emitter over a committed probe
run), which also makes the REVERSE direction live for the first time — it previously
compared an empty set against an empty set and would have passed against a rule that had
blinded the oracle completely. Falsified in both directions against
`_gate_consumers`: drop the edge regardless of the step's own flags -> the forward assertion
reddens; never drop it -> the reverse assertion reddens.

Two derived-artefact repairs landed with it, each a legitimate flow change whose figures
were left behind: seven ANCHORED figures (v1.12.3's advisory PERC clause moved four,
v1.12.10's step-31 declaration moved three), the `required_outputs` entry pin 165 -> 166
(FILE 123 -> 124, GLOB and ANY_OF untouched, measured by diffing the (step, entry) SET), and
the generated census block (531 -> 532 ENFORCED, 3 -> 2 WAIVED-SKIPPED, CONTRADICTED 0).

    host   2 runs   1 failed, 89 passed   (402.2 / 401.7 s)
    image  2 runs   1 failed, 89 passed   (454.0 / 464.0 s)
           ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2... via tools/ci/run_suite_in_eda_image.sh

whole modules, never a `-k` selection, at `f8781ed4d`. The single remaining failure in both
lanes is the fifth ID of this slice, `test_no_cell_is_counted_enforced_while_its_predicate_
is_red`, which STAYS IN BOTH and is not this change's to move.

WHY THAT ONE IS STILL RED, measured rather than guessed. It now reports **0 measured red and
47 NOT MEASURED**, identically in both lanes — the one MEASURED red it used to carry (31/d7,
`reports/phase3/perc_sweep.json`) was closed by v1.12.10. The 47 are dimension-3 cells whose
predicate SKIPS because the published corpus is not in this checkout. The test's own failure
message calls them "a HOST problem, not a repo defect" and the census publishes them in its
own NOT MEASURED column as "not a pass and not a defect... read them as UNKNOWN" — and the
test fails on them anyway, which is the very conflation `_join_axes` introduced the
`-SKIPPED` label to remove one level down. Whether it should fail on an UNMEASURABLE
predicate is a gate-semantics decision on a check that is itself part of the criterion, so it
is named here for its owner and not changed unilaterally.

ADJACENT, NOW MOVED — the four `test_extraction_input_blocked_verdict.py` IDs carry
the same `FEEDBACK_OUT` stub repair from the same commit. They were measured green at
`ae5cc4dbf` and left in BOTH because they were another slice's to move; that slice has
now moved them, on its own measurement at `628ca251f`, together with seven more. See
the section below.


### the extraction / structured-vacuity / w4 slice — 11 IDs, cleared at `628ca251f`

```
subject   628ca251f  (v1.12.8)   TREE_SHA 7a7f8cb0ca9667aded2669c78ba4e00a5c28f9d1
control   867de4289  (v1.11.18)  — the sha this table's own ratios were taken at
host      8HD-9 (192.168.1.105)
image     ghcr.io/vibeic/vibeic-eda:latest  (entrypoint bypassed)
env       PYTHONDONTWRITEBYTECODE=1 · TMPDIR outside the account home ·
          VIBEIC_TRUSTED_PYTEST_SITE=auto · PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ·
          VIBEIC_CORPUS_ROOT unset · one `python3 -m pytest` per lane, serial, no xdist
```

Whole modules, never a `-k` selection. At `628ca251f`: **119 passed, 2 skipped** on every
run — host 2/2, image 2/2. (The same four modules at `88809e6bf` also gave 119 passed /
2 skipped, host 3/3 and image 2/2.) The two skips are
`test_extraction_input_blocked_verdict.py` lines 1143 and 1162, both gated on real PDK
technology files, and neither is one of these eleven. All 11 named IDs collect and PASS
explicitly — 11 collected, 0 skipped — so the green is not a collection hole.

**The control.** At `867de4289`, the same command in the same two lanes fails
**11 of 120**, and the failing set is these eleven exactly — not a superset, not a
subset — in BOTH lanes (`host 11 failed, 107 passed, 2 skipped`; image identical). The
harness demonstrably still produces this red, and the original `BOTH 5/5 5/5` was a true
measurement of its own subject.

**Three causes, not eleven.**

1. *The four extraction IDs* — the shared `_fake_docker` stub modelled a Magic
   `ext2spice` that wrote the netlist but never wrote `FEEDBACK_OUT`. Repaired by
   `d3dce649b` (v1.11.43); same cause and same commit as the eight LVS IDs above.
2. *The three w4 negative controls* — the control asserted that the reference evaluator
   still exhibits the bug, but aimed at `origin/main`, a MOVING ref. It died the moment
   the fix landed there, reporting "the control no longer discriminates". `d3dce649b`
   pinned `_BASE_REV = "397b3f25f"`. A control must be built from a state that stays
   legitimately vulnerable, and only an immutable revision is that.
3. *`test_a_shrink_is_still_allowed`* — the ratchet FAILED when it tightened. Paying a
   debt cost a red board, and the remedy the audit named was `--write-baseline`, the one
   write that would also record that run's NEW findings as accepted debt. A shrink is now
   reported as a TIGHTENING. (The three `issue901` IDs move with the tier work in the
   same span.)

No assertion was weakened, no case deleted, no `skipif` added, no tolerance widened, and
no baseline written: every repair is in a test fixture, in a pinned revision, or in the
direction of refusing more.

**Constructed violations — each family put back to red at head.**

| # | violation at `628ca251f` | effect |
|---|---|---|
| V1 | remove the `FEEDBACK_OUT` write from the stub | the 4 extraction IDs FAIL, `EXTRACTION_FEEDBACK_ABSENT` |
| V2 | point `_BASE_REV` back at `origin/main` | the 3 w4 controls FAIL, "control no longer discriminates" |
| V3 | make the write path refuse any change, not only growth | the shrink ID FAILS: "refusing to GROW ... (116 -> 115)" |
| V4 | silence BOTH partial-vacuity producers | 2 of the 3 issue901 IDs FAIL |
| V5 | withhold the unanimous `VACUOUS_PASS` tier grant | the 3rd issue901 ID FAILS, "consumed as PARTIALLY-VACUOUS" |

Two of these took a second attempt, and the reason is worth recording. The
partial-vacuity disclosure has **two independent producers** — the tier's own
`else` branch and the structured channel below it, printing the same sentence from the
same numerator and denominator by design. Silencing either one alone leaves every test
GREEN, which reads exactly like "this guard cannot detect the defect". Only V4, which
silences both, is a falsification. The same trap caught the shrink ID: `_run_audit`
passes `--write-baseline`, so a mutation on the read/compare path never executes, and
`_json_report_signals_vacuous` is documented as NOT WIRED INTO THE STEP TIER. A mutation
that lands in a dead arm is indistinguishable from a guard that does not work.


### the prose-polarity / evidence-snippet slice — 2 IDs, cleared at `51c0db4b7`

```
subject   51c0db4b7  (the candidate tip; the table edit and the version bump
                      are the commit that carries this section, and neither
                      touches code)
control   243f7e731  (v1.12.11) — live main immediately before this landing
host      8HD-8 (192.168.1.114)
image     ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2 — the digest BOTH
          tools/ci/protected_landing_transition.json and
          tools/ci/run_suite_in_eda_image.sh pin, entrypoint bypassed
env       PYTHONDONTWRITEBYTECODE=1 · TMPDIR=/var/tmp/jl, outside the account
          home and on the repository's own filesystem ·
          PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 in the image lane ·
          VIBEIC_CORPUS_ROOT unset · one `python3 -m pytest` per lane, both
          modules in one invocation, serial, no xdist
```

Whole modules, never a `-k` selection. ONE observation per lane per tree, and
the `now` ratios say `0/1` rather than borrowing a repeat count these runs do
not have.

```
                        host              image
control 243f7e731       1 failed, 70 p    1 failed, 70 p
subject 51c0db4b7       71 passed         71 passed
```

**The control is exact.** At `243f7e731` the failing set is
`test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships`
and nothing else — not a superset, not a subset — in BOTH lanes. The harness
demonstrably still produces this red, so the original `5/5 5/5` was a true
measurement of its own subject, and the green is not a collection hole: 71
collected and 0 skipped in all four runs.

**`test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships`
— cleared BY this landing.** `prose_polarity_consulted_check` named two
functions in `programs/_l_doc_pad_placement.py`. Each takes a value out of a
design's own ENGLISH document and writes it into a declared field, and neither
asked whether the document was DENYING what it read — the shape vibe-ic#712
opened on (`pdk_target` "This block is NOT targeted at <PDK>",
`die_area_budget_um` "REMOVED, not translated"), both read out of exactly this
kind of file. The repair IMPORTS `_prose_polarity`'s `is_denied` and
`sentence_scope` rather than re-spelling them — that module's own header records
that "three private copies of it is how the divergence happened" — and both
names are CALLED, not merely imported, because an import whose only consumer is
the test asserting the import is a green light rather than a check. The reach is
the record the value sits in: a markdown table ROW for the row predicates, and
the house `sentence_scope` with `extra_breaks=("\n",)` for the one genuinely
prose value, because this document wraps a line at a time and a bare newline is
a record break in a table. No assertion was weakened, no case deleted, no
`skipif` added, no tolerance widened.

**`test_flow_compliance_check_gate.py::test_a_real_verdict_is_not_mistaken_for_a_crash`
— cleared EARLIER, and recorded here rather than left saying something false.**
This row was NOT cleared by this landing and the entry says so: at the control
`243f7e731`, before any commit of this branch, it is already among the 70
passing in both lanes. It was repaired by `a4db289d9` (v1.12.4), which
CONSTRUCTS the shallow arm's project instead of hoping the host's temp root is
short enough. The red was `2 * len(project) + 156 <= 300` failing — a statement
about `TMPDIR`, not about the crash detector the test owns — and that commit
asserts the premise so it cannot rot back into a confusing red. Nobody moved the
row when the repair landed. A row that is green in both lanes and still sits in
BOTH overstates the criterion in the direction that makes the board look worse,
which is no better than understating it.

What this branch carries for that module is adjacent and is NOT the clearance:
`output_snippet` now grows its cut BACKWARD to a line boundary, so a verdict is
not served as a fragment (`AIL` where `verdict: FAIL` was cut). It GROWS and
never shrinks — dropping the partial first line was the shorter fix and would
have taken a truncated traceback FRAME line with it, which is a crash's only
evidence — and over 4000 random stdout/stderr pairs every line the old snippet
carried is still carried, with crash detection never downgrading. The width
stays bounded: a line wider than the budget falls back to the plain tail.

### the six-singles slice — 6 IDs, measured at `984f30df7`, landed doc-only

```
subject   984f30df7               TREE_SHA 1b97203f4055143c29c8d03d9a1e2dd36f867ec7
          (branch next/pad-ring-prose-polarity, one commit on 5a9bc15fd / v1.12.8)
control   867de4289  (v1.11.18)   TREE_SHA 7840974874537d10d0952057f06857f4b699ec38
          — the sha this table's own ratios were taken at
host      8hd-3 (192.168.1.121)
image     ghcr.io/vibeic/vibeic-eda@sha256:9f8676be8f7b8d99f5b0013fecad6b3532193146bf9599a7a846df23219db0d9
          (entrypoint bypassed; USER=designer; /work WRITABLE, /work/.git read-only)
env       PYTHONDONTWRITEBYTECODE=1 · TMPDIR=/tmp/s6/{tmp,itmp}, outside the account home ·
          VIBEIC_TRUSTED_PYTEST_SITE=auto · PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ·
          VIBEIC_CORPUS_ROOT unset · one `python3 -m pytest` per lane, serial, no xdist ·
          independent `--no-local` clone, `git clean -xdfq`, own control clone
```

Whole modules, never a `-k` selection. At the subject: **host 202 passed / 12 skipped**
on 3 of 3 runs, **image 203 passed / 11 skipped** on 2 of 2. All named IDs collect and
PASS explicitly in both lanes, so the green is not a collection hole. **Red ratio for
each: image 0/2, host 0/3.**

**The control.** At `867de4289` the same command in the same two lanes fails **8 of 192**,
and the failing set is those eight exactly — not a superset, not a subset — in BOTH lanes
(`host 8 failed, 184 passed`; image identical). The harness demonstrably still produces
this red, and the original `BOTH 5/5 5/5` was a true measurement of its own subject.

**EIGHT WERE MEASURED; SIX MOVE HERE, AND THE OTHER TWO ALREADY LEFT.** Stated so the
count is checkable against the rows rather than against the slice's own headline.
`test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships` and
`test_flow_compliance_check_gate.py::test_a_real_verdict_is_not_mistaken_for_a_crash`
were both moved to CLEARED at `51c0db4b7` by v1.12.12, which landed while this slice was
parked. Their rows are not written twice. `BOTH 32 -> 26` and `CLEARED 23 -> 29` are the
literal row counts of the two tables above, re-derived by counting them, and
`26 + 29 + 2 FLAKY = 57` closes against this document's own population.

**THIS LANDING IS DOCUMENTATION ONLY — the code half of `984f30df7` was already on main.**
That commit's repair of `_l_doc_pad_placement` (vibe-ic#712) landed independently as
v1.12.12, in a strictly more developed form: main imports `_prose_polarity` the same way,
scopes the minimum distance with `sentence_scope(extra_breaks=("\n",))`, and carries an
extra pinned test, `test_the_min_distance_denial_reach_is_the_sentence`, that this slice
did not have. All six of the slice's behaviour tests are present in main's
`test_pad_ring_derived_from_l3.py`. The commit was therefore SKIPPED as already-landed
rather than re-applied — re-applying it would have replaced main's version with the
earlier one. Nothing of this branch's code is lost and nothing of main's is reverted: the
diff this landing carries is one documentation file.

**CAUSE NOT ATTRIBUTED FOR THE SIX.** Every one of them was already green at `5a9bc15fd`
— an ancestor of main — before this branch existed, and is unchanged by it. What carried
each from red at `867de4289` to green at `5a9bc15fd` was NOT bisected. It is not needed
for the bucket, whose stated criterion for leaving BOTH is a both-lane re-measurement at a
named later sha, and that is what these rows carry; but it is missing, and the next reader
should know it is missing rather than infer a fix.

**CONFIRMED AGAIN AT THE LANDING PARENT.** Host lane at `a4f6b4f33` (v1.12.12), the five
modules run WHOLE with no `-k` selection, `VIBEIC_CORPUS_ROOT` unset,
`PYTHONDONTWRITEBYTECODE=1`: **121 passed, rc 0**, all six IDs collected and passing, and
`suite_write_guard` reported the session wrote nothing `git status --porcelain` would
show. This is a third host observation, not a second lane, and it is recorded as such.

**LANE CONFIGURATION, measured by the slice, because it produces five reds that are not
code.** Two flags the image lane needs, neither guessable from the failure text:

  * `-e USER=designer`. The image's own `$USER` is the two-line string `"1000\ndesigner"`
    (uid 1000 has no passwd entry), so `getpass.getuser()` returns it verbatim and pytest
    builds `<TMPDIR>/pytest-of-1000\ndesigner/...`. Every `tmp_path` then carries an
    embedded newline.
  * **`/work` must be mounted WRITABLE, with `/work/.git` mounted `:ro` separately.** Five
    IDs in `test_flow_compliance_check_gate.py` write a helper into `programs/` and delete
    it again. Under a whole-tree `:ro` mount they fail with `Read-only file system`, which
    reads as an IMAGE-ONLY red of the gate under test. The `.git` half of the split is not
    optional: a writable `.git` inside a container lets the hygiene gates prune every
    worktree's metadata on the host.

  With the tree mounted `:ro` the slice measured `image 5 failed, 198 passed, 11 skipped`,
  twice; with the split mount, `203 passed, 11 skipped`, twice, on the same image and the
  same commit. The tell is that the SAME FIVE IDs appear under `:ro` at the subject AND at
  the control, giving `12 failed` there against `8 failed` on the host and under the split
  mount. A lane artefact does not care which tree it is aimed at, which is what separates
  it from a finding.


### the inventory / step-metrics / manifest-parity slice — 7 IDs, cleared at `628ca251f`

THE SEVEN INVENTORY / STEP-METRICS / MANIFEST-PARITY IDS, cleared at `628ca251f`
(v1.12.8). One cause, stated once: **the tree grew and every declaration of its
size was left behind.** None of the seven is a defect in the code they guard;
each is a stated number or a declared set that stopped matching the population
it describes.

Control first, because a green whose harness cannot produce the red is not
evidence. At the ratios table's own subject `867de4289`, whole modules, both
lanes: **exactly these seven fail and nothing else does** — host 7 failed / 39
passed, image 7 failed / 39 passed. The original `5/5 5/5` was a true
measurement of its own subject, and this harness demonstrably reddens them.

What the control names, id by id:

| id | at `867de4289` |
|---|---|
| `parity::test_every_declared_path_has_a_manifest_entry` | step `37.5ic` declared `reports/phase3/docs/BRIEF_*.html` and `SIGNOFF_*.html`; neither was ever measured into the d3 manifest |
| `parity::test_the_population_is_the_whole_flow_and_is_not_empty` | 162 declared paths vs 160 manifest entries |
| `inventory::test_stated_counts_in_the_documents_match_the_tree` | 11 stale sites — 1208≠1211, 1135≠1138, 2644≠2648, 3885≠3894 — plus one claim site reworded to `VANISHED` |
| `inventory::test_clean_tree_reports_no_failure` | the same list |
| `inventory::test_check_mode_exits_zero_on_the_committed_tree` | `gen_program_inventory.py --check` exit 1, the same list |
| `inventory::test_declared_non_counts_are_still_present[and all 56 EDA/device tools]` | that sentence did not exist in the docs yet |
| `step_metrics::test_declared_coverage_matches_the_tree` | tree 68 gate-carrying steps, literal `GATE_CARRYING_STEPS = 62` |

At `628ca251f` every one of those declarations has been re-measured by the
landings in between: manifest parity is a strict 165 == 165 bijection over 68
steps, all 22 bound claim sites agree, `GATE_CARRYING_STEPS` is 67 and equals
the tree, and the not-a-count sentence is present at `README.md:365`.

**Now: image 0/3, host 0/3 GREEN at `628ca251f`**, taken interleaved, whole
modules, no `-k`, serial, no xdist, `VIBEIC_CORPUS_ROOT` unset — image lane in
the ratios table's own `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…d01ff` with
`--skip` first, host lane python 3.10.12 / pytest 9.1.1, each from a fresh
standalone clone. No assertion weakened, no case deleted, no skipif added, no
tolerance widened, no exemption added or re-dated.

Constructed violations, one per guard, all still red at head: adding a single
`required_outputs` entry to the flow yaml without re-measuring the manifest
fails both parity IDs (`166 declared paths vs 165 manifest entries`); drifting
one bound count by one fails all three inventory IDs, each naming `README.md:17`
and both numbers; rewording the declared not-a-count sentence fails the
parametrized ID; and un-declaring emitting step 34, or restoring the stale
`GATE_CARRYING_STEPS = 62`, fails the step-metrics ID in the two directions it
has.

⚠️ **THIS FAMILY IS TIP-SENSITIVE AND WILL RE-RED. It is cleared, not immune.**
Every one of these seven compares a written-down number or set against a
population that changes whenever a file is added. That is not hypothetical: it
happened one commit before this clearance. `5ecd04595b` (v1.12.7) added
`programs/tests/test_checkout_write_attribution_needs_an_exclusive_window.py`,
correctly re-ran the generator so `PROGRAM_INVENTORY.json` read `test_files
2878` / `programs_tree_all_py 4243`, and touched all three READMEs — **but only
for the version badge**, leaving the six prose sites that state those same two
populations at 2877 / 4242. Three of these seven IDs were genuinely red on live
main for the length of that commit, and `628ca251f` (v1.12.8) is the repair. A
BOTH row for this family therefore means "someone added a file and did not
re-measure", never "the guard is broken" — and the fix is always to re-run
`python3 programs/gen_program_inventory.py` and then correct the prose sites the
gate names by `file:line`.

ONE UNBOUND SITE FOUND WHILE CLEARING THESE, and closed in the same change.
`vibe-ic-marketplace/README.md:561` reads `← 4243 *.py at any depth (1260 top
level)`. The `4243` is bound to `programs_tree_all_py`; the `1260` was bound to
nothing, waived by nothing, and stale by 38 — the tree has 1298. It survived
because `_sweep`'s unregistered-claim detector needs a population word within 34
characters of the number and finds none in either direction (`" top level)"`
ahead, `"*.py at any depth ("` behind), so the one gate that exists to catch a
hand-typed count could not see this one. It was written on 2026-08-22 by a
commit whose subject is `chore(inventory): re-derive after folding the
two_input_selectors repair` — a re-derivation that updated the bound sites and
left the unbound one behind, which is exactly the failure mode `_CLAIMS` exists
to prevent. A wide probe over both bound documents for every uncovered 3-4 digit
number found this and nothing else (the other hits are process nodes and years).
It is now bound in `_CLAIMS` as a 23rd site, and `test_a_drifted_stated_count_is_caught`
— which asserts EVERY bound site reddens under a deliberately wrong inventory —
covers it: 23 sites, 23 drift lines. Restoring `1260` puts the three inventory
IDs back to red.


### the atomic-declared-report slice — 3 IDs, cleared at `462b66838`

```
subject   462b66838  (the candidate tip; the table edit and the version bump
                      are the commit that carries this section, and neither
                      touches code)
control   8e5ce1629  (v1.12.15) — live main immediately before this landing
host      8HD-a
image     ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2 — the digest BOTH
          tools/ci/protected_landing_transition.json and
          tools/ci/run_suite_in_eda_image.sh pin, entrypoint bypassed
env       PYTHONDONTWRITEBYTECODE=1 · TMPDIR outside the account home ·
          PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 in the image lane ·
          VIBEIC_CORPUS_ROOT unset · one `python3 -m pytest` per lane, all
          four modules in one invocation, serial, no xdist
```

Whole modules, never a `-k` selection. ONE observation per lane per tree, and
the `now` ratios say `0/1` rather than borrowing a repeat count these runs do
not have. The image lane ran in a fresh `--no-local` clone checked out at the
named sha, not in a worktree.

The control/subject pair below was measured at `dd3883f85`/`21dd3edb9` — the
immediately preceding main and the same two-file change cherry-picked onto it.
Main then moved twice under this landing (v1.12.14, v1.12.15); neither touched
either file this commit changes, and the three rows were still in BOTH at
`8e5ce1629`, so the measurement is carried forward rather than re-run and
re-stated at a sha it was not taken at.

```
                        host              image
control dd3883f85       2 failed, 42 p    2 failed, 42 p
subject 21dd3edb9       44 passed         44 passed
```

**The control is exact.** At `dd3883f85` the failing set is
`test_issue1082_open_w_category_closed.py::test_no_new_offender_and_the_ratchet_holds`
and `test_issue1470_atomic_declared_report.py::test_the_gate_is_green_and_the_ratchet_holds`
and nothing else — not a superset, not a subset — in BOTH lanes, and the
failure text names the two files this branch changes, at the two line numbers
it changes. The harness demonstrably still produces this red, so the original
`5/5 5/5` was a true measurement of its own subject, and the green is not a
collection hole: 44 collected and 0 skipped in all four runs.

**Two rows cleared BY this landing.** `extraction_credited_by_prose_only_check`
and `flow_output_substance` each wrote their declared `--json` destination with
a raw `Path.write_text`, so a reader could resolve the declared name while the
document was half written — the shape vibe-ic#1082 opened on. Both now write
through `_atomic_artefact.write_text`, the helper the ratchet's own remedy line
names, so the destination appears under its final name only once complete. The
directory `mkdir` and the payload are unchanged; only the write is atomic. No
assertion was weakened, no case deleted, no `skipif` added, no tolerance
widened, no exemption re-dated, and no baseline written — the residual baseline
of 514 is untouched and the ratchet closes on the two new offenders rather than
being moved to admit them.

**`test_issue1082_open_w_category_closed.py::test_no_declared_report_is_written_through_open_w`
— NOT cleared by this landing, and the entry says so.** At the control
`dd3883f85`, before any commit of this branch, it is already among the 42
passing in both lanes. I did not attribute which earlier commit repaired it and
I am not guessing one; what is measured here is that it is green in both lanes
at both trees. It is moved because a row that is green in both lanes and still
sits in BOTH overstates the criterion in the direction that makes the board
look worse, which is no better than understating it.

DROPPED WHOLE from this branch — `38f55456ed`, "#712: `_l_doc_pad_placement`
reads a pad ring out of prose without its polarity". Main repaired that same
defect a different way at `a4f6b4f335` (v1.12.12), which imports
`_prose_polarity`'s `is_denied` and `sentence_scope` rather than re-spelling
them, and `test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships`
has been CLEARED at `51c0db4b7` since. The branch's alternative is not worth
overwriting a landed, reviewed fix to obtain, so it is dropped whole rather
than merged over it, and its companion test file is dropped with it.

### the 63x8 matrix slice — 5 IDs, cleared at `72a558fdb`

```
subject   72a558fdb  (v1.12.9)   — the sha the five were re-measured green at
control   867de4289  (v1.11.18)  — the sha this table's own ratios were taken at
landing   re-measured again ON the rebase, at the tree this landing pushes
env       PYTHONDONTWRITEBYTECODE=1 · TMPDIR outside the account home ·
          VIBEIC_CORPUS_ROOT unset · one `python3 -m pytest` per lane, serial, no xdist
```

**The five moved rows are ONE finding and it is not a fix: they were already
green on main and the rows were stale.** Measured on a fresh `--no-local` clone
of pristine `72a558fdb` with NOTHING applied — no branch, no patch — the whole
`test_matrix_63x8_ledger.py` module plus the one named coverage node, never a
`-k` selection:

    host   4 runs   53 passed  (15.3 / 16.6 / 16.6 s; ledger alone 52 passed / 6.3 s)
    image  3 runs   53 passed  (the digest-pinned CI image, not a tag)

Seven observations, both lanes, no failure in any. The four ledger predicates are
functions of the flow yaml and the waiver registry only, and every tripwire they
pin was re-derived by RUNNING the accessor rather than re-typing the pin —
`EXPECTED_STEPS` 68, `EXPECTED_CELLS` 612, `CENSUS_GATE_PRESENT` 67,
`CENSUS_REQUIRED_OUTPUTS_PRESENT` 66, `CENSUS_BLOCKS_ON_PRESENT` 68,
`CENSUS_BLOCKS_ON_NON_EMPTY` 66, `CENSUS_GATE_PROGRAMS_NON_EMPTY` 66. Nothing
about them is host-dependent. Their `5/5 5/5` was a true measurement of
`867de4289` and had stopped being true some landings ago. No commit of this lane
is claimed for them.

ONE OF THE FIVE IS DIFFERENT, AND THE BRANCH SAID SO AGAINST ITSELF.
`test_output_entries_classify_into_the_four_kinds` was measured green at
`72a558fdb`, and then v1.12.10 declared `reports/phase3/perc_sweep.json` on step
31 WITHOUT carrying its pinned entry census — taking the pin red again between
the measurement and the table edit. It is green here because this landing also
carries the pin repair (165 → 166 entries, FILE 123 → 124, GLOB and ANY_OF
untouched), not because the old measurement was re-read charitably.

RE-MEASURED ON THE REBASE, not before it, at the tree this landing pushes: the
five affected modules run WHOLE, no `-k`, serial, no xdist — **202 passed, 1
failed, 1 skipped, 4 xfailed in 416 s**. All five moved IDs PASSED by exact node
name. The one failure is `test_matrix_63x8_coverage.py::test_no_cell_is_counted
_enforced_while_its_predicate_is_red`, which is ITSELF a BOTH row of this table
and stays one — see below. It is PRE-EXISTING, carried onto main unchanged, and
NOT attributed to this branch.

The anchored figures were re-derived rather than trusted:
`tools/gen_matrix_63x8_census.py --check-figures` reports 57 anchored figures
fresh across 36 corpus files, rc 0 — and the gate was FALSIFIED at this tree by
putting one digit back (`required_outputs_file` 124 → 123), which reddens it
naming `flowref.py:76` and both numbers, rc 1. A freshness PASS whose checker
cannot fail is not evidence.

STILL BOTH, AND WHAT IS NOW KNOWN, so the next reader does not re-derive it. The
other five IDs of this slice all depend on the live 612-cell nested outcome run.
Two causes were stacked on one another and BOTH are addressed by this landing:
the d7 forward control that took the whole nested run to NORECORD is repaired
here by planting the producer with the module's own `_plant_record`, and the
README's generated census block is re-derived here (531 → 532 ENFORCED, 3 → 2
WAIVED-SKIPPED, undeclared 397 → 398, NOT MEASURED 54 → 53, CONTRADICTED still
0, 612/612 accounted for). The landing run corroborates the block independently:
the failing assertion above prints a live TWO-AXIS census of `ENFORCED 532,
WAIVED 8, NA 19, ENFORCED-SKIPPED 45, WAIVED-SKIPPED 2, NOT_MEASURED 6` — 612,
and identical to the block.

**Four of those five were GREEN on the HOST lane at this landing tree** —
`census_freshness::test_the_census_block_is_fresh`,
`::test_the_published_total_equals_the_live_census`,
`coverage::test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved`
and `::test_the_enforcement_census_is_reported_for_humans`. **They are NOT moved,
and the reason is a limit of this landing host, not a property of the code:** the
pinned-image lane could not be run here, and this document's own rule is that a
row leaves BOTH only when re-measured green in BOTH lanes. One lane is an
observation, not a clearance. Whoever has an image lane: re-run those four whole
modules against this sha and move them — the host half is already done.

The fifth, `::test_no_cell_is_counted_enforced_while_its_predicate_is_red`,
remains RED here and is a different question from the census block. Every cell it
names is a `d3 (outputs_produced)` coordinate reported ENFORCED while the live
run skipped it, because `VIBEIC_CORPUS_ROOT` was unset and the d3 predicates
need the published corpus this checkout does not carry. That is the corpus-shaped
condition, not a defect this branch introduced or could close.
