# LAND — step 23 PARTIALLY-VACUOUS voids three downstream steps: four preconditions, measured

STATUS: **MEASUREMENT ONLY. NOT LANDED. NO PRODUCT CODE CHANGED.**
This branch adds three measurement rigs and this document. It changes no program,
no flow yaml, no test under `programs/tests/`. The candidate rung is described and
measured; it is not applied.

## REF
`measure/step23-drv-promotion-vacuity`

## BASE
`origin/main` @ `fafb823d90` [v1.14.37], fetched 2026-08-31. Measured in a clean
detached worktree, not in a stale checkout. (Stated because my own session checkout
was `issue1263-sigkill-cleanup-flake` @ `03b74d95bb`, which does not contain the
`PARTIALLY-VACUOUS` tier at all and would have produced a wrong answer.)

## WHAT THIS IS
spm@1.14.30 posted step-level FAIL=0, PASS=24, PASS_VOIDED_BY_DEPENDENCY=6.
Three of the six (36, 37.5ip, 38) chain to INCOMPLETE steps 31 and 37, owned by
another agent. The other three — **32, 34, 35** — chain to an INDEPENDENT voider:
**step 23 "Post-route STA (multi-corner multi-mode sign-off)" at PARTIALLY-VACUOUS**,
named by its own observed line as
`drv_promotion_corroboration_check . --json reports/phase3/sta/drv_promotion_corroboration.json`.
This document measures the four preconditions that were open on that voider.

## THE DEFECT
`drv_promotion_corroboration_check` (#293) corroborates a route promoted by
`signoff_spef_repair` against the sign-off STA report. Its own verdict table makes
the inapplicable case its NORMAL outcome — "no promotion happened this run". The
marker it keys on is written at exactly one site
(`phase3_one_shot_runner.py:26220`) and only when a promotion actually occurred;
the repo's own corpus test (`tests/test_issue306_register_paydown.py:278`) measures
**0 of 15** runs carrying it. It is nonetheless wired as a mandatory blocking
`program_exit_zero` clause on a CERTIFYING step, so its correct "nothing to
corroborate" outcome demotes step 23 below PASS and voids 32, 34 and 35 —
independent of design quality. Chip-AGNOSTIC.

## THE CANDIDATE RUNG (described, measured, NOT applied)
Rewire that one clause to the shape the flow already has for exactly this case
(W4, `flow_compliance_check.py:3739-3770`), which clause 5 of this same step
already uses:

    optional_program_exit_zero:
      command: "drv_promotion_corroboration_check . --json reports/phase3/sta/drv_promotion_corroboration.json"
      condition_files_exist: ["pnr/routed_base_prerepair.def",
                              "phase3/stage3/pnr/routed_base_prerepair.def"]
      absent_condition_reason: "no route promotion occurred this run, so there is
        no promoted route whose claimed improvement the sign-off could corroborate"

## THE FOUR PRECONDITIONS — one measured number each

### (a) Does an UNMET declared optional condition move the tier? — MET
Rig `.measure/m_ab.py`. Two-step synthetic flow: step 23s certifying (name matches
`_SIGNOFF_RE`) with 5 clauses, 4 substantive + 1 drv-shaped; step 32s downstream,
`blocks_on: [23]`.

| arm | 5th clause wiring | step 23 | step 32 | rc |
|---|---|---|---|---|
| A status quo | mandatory `program_exit_zero` | PARTIALLY-VACUOUS | PASS_VOIDED_BY_DEPENDENCY | 1 |
| B rewired | optional + declared reason | PASS | PASS | 0 |

**Number: 1 of 5 unmet clauses moves the tier in A and does not in B.**
Arm A emits verbatim `"PARTIALLY-VACUOUS (1 of 5 gate clause(s) examined nothing)"`
and `"PASS voided: dependency [23] Post-route STA ... = PARTIALLY-VACUOUS"` — the
same sentence pair the spm audit carries, so the rig reproduces the shipped defect
rather than a lookalike. Arm B emits `"NOT-APPLICABLE (declared, 1 of 5 ...)"` and
keeps PASS. Mechanism: an unmet declared optional returns before the `__RAN_HINT__`
append (`:8215-8218`) so it enters neither `ran_hints` nor `all_vacuous_cmds`;
`__NA_HINT__` is disclosed and deliberately does not move the tier (`:10352-10356`).
The rung is the right one.

### (b) Bidirectional negative control — MET
The assertion "step 32 is PASS" scores **FAIL against the pre-fix wiring** (arm A:
PASS_VOIDED_BY_DEPENDENCY) and **PASS against the post-fix wiring** (arm B).
**Number: 2 of 2 arms behave as the control requires.** A test that cannot fail
against the pre-fix code proves nothing; this one fails against it.

### (c) Does the promotion-vs-signoff refusal survive? — MET
Rig `.measure/m_c.py`, driving the **real shipped program** through the full
`flow_compliance_check`, 4 cases × 2 wirings = 8 measurements.

| case | arm A mandatory (23/32) | arm B rewired (23/32) |
|---|---|---|
| c1 promoted + signoff contradicts | FAIL / PASS_VOIDED | FAIL / PASS_VOIDED |
| c2 promoted + no signoff report | FAIL / PASS_VOIDED | FAIL / PASS_VOIDED |
| c3 promoted + corroborated | PASS / PASS | PASS / PASS |
| c4 no promotion | **PARTIALLY-VACUOUS / PASS_VOIDED** | **PASS / PASS** |

**Numbers: 2 of 2 refusal cases preserved; 1 of 4 truth-table rows moved.**
The rewiring changes exactly one row, and it is c4 — the inapplicable case that
should never have cost anything. The two rows carrying #293's entire purpose are
byte-identical under both wirings. The refusal is not silenced.

### (d) Is this a one-off or a pattern? — MEASURED, and it is a pattern
Rig `.measure/m_d.py` (static) plus a sweep of `benchmark-data/`.

STATIC exposure on the shipped flow:
  certifying steps **19**; mandatory `program_exit_zero` clauses on them **37**;
  of those, vacuity-capable **19**, spread over **12** certifying steps
  (A6, 23×3, 24, 28, 31×5, 36×2, 37×2, 38, M3, 40, 42).

REALIZED damage in `benchmark-data/`:
  files with a per-step `steps[]` **56**; using the flow-compliance vocabulary
  **19** (the valid denominator — the other **37** are STEP_INDEX-schema and were
  excluded; my first sweep mixed the two and its histogram was invalid);
  PASS_VOIDED instances **0**; PARTIALLY-VACUOUS instances **0**.

**That zero is not evidence of safety.** Of the 19 compliance-schema reports, **3**
carry a parseable version, ranging **v1.5.58 .. v1.10.18**, and **0** are at or
after v1.14.0 — the corpus predates the tier and could not have recorded it. The
first measured firing is spm@1.14.30 itself: 1 clause → 3 voided steps.
**A per-clause rewiring closes 1 of 19.** Recorded as the open question this rung
does not answer.

## INCIDENTAL DEFECT FOUND WHILE MEASURING (c) — named, not fixed
`drv_promotion_corroboration_check.py:194-195` writes its `--json` report with
`Path(a.json).write_text(...)` and no `mkdir(parents=True, exist_ok=True)`. With
the report directory absent the gate crashes:
`__CRASH_HINT__: FileNotFoundError ... 'reports/phase3/sta/drv_promotion_corroboration.json'`.
MEASURED CONSEQUENCE: my first (c) run scored c1/c2/c3 as step23=FAIL under both
arms — c3 should have been PASS. That FAIL was the crash, not the refusal, and had
I not checked I would have reported "refusal preserved" while measuring a crash.
All **3** of step 23's other report-writing clauses do mkdir first
(`sta_corner_record_completeness_check.py:1666`, `hold_corner_coverage_check.py:986`,
`post_route_signoff_corner_check.py:466`); this gate is the odd one out among its
own step-mates. Rough repo census: **246** programs write a json report, **68**
contain no `mkdir(parents=True` anywhere — an UPPER BOUND on the shape, not a count
of confirmed defects. LATENCY: step 23's clauses 2 and 4 both write into
`reports/phase3/sta/` and both mkdir, and both run before clause 7, so the dir
exists by then. This crash is latent and is NOT what happened on spm@1.14.30.

## CORRECTIONS TO MY OWN EARLIER RECORD
1. **Schema.** I wrote that `phase23_completion_audit.json` carries only
   `step_counts` and can never name a voider. FALSE for the 1.14.x schema.
   `_blocker_classification.py:515-524` emits a per-step object with `step_id`,
   `status`, `derived_from` and `observed`, reaching the report as top-level
   `blockers[]` (`flow_compliance_check.py:13274`, `:13332`, `:13600`). `observed`
   is bounded at **400** characters (`_observed(step, limit=400)`; the gate-level
   variant is **240**, `:426`), which is exactly why 3 of the 6 spm voided steps
   carried the "PASS voided:" sentence and 3 did not. I generalised from
   `caravel_user_project/v1.9.43`, whose audit predates the field.
2. **Exit code.** The gate exits **0** with a line-start `VACUOUS_PASS:` token
   (#1115), not rc=2. Both channels yield the same vacuity hint, so no measurement
   moves.
3. **Sweep denominator.** First (d) sweep counted 56 files across two schemas. The
   valid denominator is 19.
4. Two earlier hypotheses were falsified and withdrawn: the promotion is not dead
   code (rare at 0/15, not impossible), and #1115's tier split did not cause the
   voiding (the pre-split branch set VACUOUS_PASS unconditionally, which is equally
   `is_qualified_done`, so a certifying step voided its descendants under the old
   word too).

## WHAT IS STILL OPEN
- A per-clause rewiring closes 1 of the 19 mandatory vacuity-capable clauses on
  certifying steps. Whether the other 18 want the same treatment, or whether the
  tier itself should distinguish "inapplicable by construction" from "applicable
  and unexamined", is a flow-POLICY question and is the owner's to settle.
- The missing-mkdir defect above is separable and is not fixed here.

chip-AGNOSTIC: every fixture is synthetic artefact text; no design, PDK, foundry,
vendor, SKU or process appears anywhere in the rigs or in this document.
English only.

## (e) RESOLVED — repairing step 23 is necessary AND sufficient for step 31

The peer session owning 9/21/31/37 measured 31 voided by `derived_from ['23','29','30']`
after its own fix, and could not resolve whether 29/30 would still hold 31, because
both of its arms had 23 red. Rig `.measure/m_e.py` answers it by driving
`flow_step_execution_coverage_check.analyze()` — the voiding engine itself, not a
stand-in — against the real shipped graph. 242 combinations.

Real edges and classification, read from the flow:
  29 Post-Layout GLS      `blocks_on [22]`                        NOT certifying
  30 Post-Layout SPICE    `blocks_on [22, 23]`                    CERTIFYING
  31 Physical Verification `blocks_on [23,24,25,26,27,29,30]`

| varying | words that let 31 PASS | words that void 31 |
|---|---|---|
| step 30 (certifying) | **4 of 11** — PASS, SKIPPED-CONDITION, WAIVED, DEFERRED-BY-UPSTREAM | **7 of 11** — every disclosure tier (VACUOUS-PASS, PARTIALLY-VACUOUS, STRUCTURE-ONLY, INCOMPLETE) plus MISSING, FAIL, SKIPPED-SETUP-REQUIRED |
| step 29 (not certifying) | **8 of 11** — including every disclosure tier | **3 of 11** — MISSING, FAIL, SKIPPED-SETUP-REQUIRED only |

MEASURED WORDS on the 1.14.30 trees, supplied by the peer from
`reports/phase3/gates/stage3_compliance.json` (the step rows, not the bounded
`blockers[].observed` snippet), on BOTH its control and its fixed arm, and agreeing
across both the short `{step_id,status}` and long `{id,name,status}` rows:
    step 29 = SKIPPED-CONDITION
    step 30 = SKIPPED-CONDITION

Both are EXCUSED. **So step 30 is not a third voider, nobody needs to own it, and
repairing step 23 is necessary AND sufficient to take step 31 to PASS** — and with
it the 32/34/35/36/37/37.5ip/38 subtree, once the peer's 31/37 work lands.

### VERSION-DRIFT CAVEAT — RAISED BY THE PEER, RESOLVED BY MEASUREMENT
The peer correctly flagged that its words come from v1.14.30 trees while my sweep
ran the engine at v1.14.37, and that the vocabulary or `_SIGNOFF_RE` might have
moved in between. Checked by blob hash, `551560ba1` [v1.14.30] vs `fafb823d90`
[v1.14.37]:
    programs/_flow_verdict_tiers.py               4fcea108fa61... == 4fcea108fa61...
    programs/flow_step_execution_coverage_check.py c6e7bd79ca44... == c6e7bd79ca44...
    flow/phase1_phase2_phase3.yaml                0e3fe5f1ca7f... == 0e3fe5f1ca7f...
All three are **byte-identical** across those seven versions. The tier vocabulary,
the voiding engine and the graph did not move, so the v1.14.37 sweep applies to the
v1.14.30 trees verbatim. The caveat is discharged, not carried.

### WHAT THIS IS NOT — stated because it is a prediction, not an observation
No tree with step 23 repaired has been run. This conclusion is the sweep's table
combined with the peer's measured words; it is not an observation of step 31 at
PASS. The observation requires a run with the rewiring applied, which this branch
deliberately does not do. If the rung is applied and 31 does NOT go PASS, the
disagreement is either in the table or in a dependency neither of us enumerated,
and the thing to read at that point is `derived_from` on 31 — which on both of the
peer's trees reads exactly `['23', '29', '30']`.

### CORRECTION TO MY OWN RECORD (5)
I cited `steps/STEP_INDEX.json` as where the per-step word lives. That file does not
exist on the 1.14.30 trees at all — their `steps/` holds `index.json` plus per-phase
directories, and the word lives in `reports/phase3/gates/stage3_compliance.json`.
My v1.10.18 datum came from a tree with a different layout AND a different
vocabulary ("skipped" vs "SKIPPED-CONDITION"), which is exactly why I recorded it as
suggestive only and did not answer from it. Recording the layout difference so the
next reader looks in the right artefact.

---

# APPLICATION PASS — the rung was applied, step 31 was observed, and the result is **NOT GREEN**

The rung is applied in this branch (`flow/phase1_phase2_phase3.yaml`, step 23 clause
7) together with an acceptance test and five rigs. **It must not land**, and not only
because the brief says so: a BLOCKING flow gate refuses it, and the reason it refuses
is correct.

## WHAT WAS OBSERVED — step 31 does reach PASS
Rig `.measure/m_obs.py`. No reachable tree is converged at v1.14.x (see the honest
limit below), so the observation drives the real `flow_compliance_check` over a
flow-def carrying the **real ids, names, stages and `blocks_on` of the 22..38
subgraph** — so the ordering graph and the certifying classification are the shipped
ones — with step 23's clause 7 being the **real** `drv_promotion_corroboration_check`.

| case | arm A (stock, mandatory) | arm B (rung, declared optional) |
|---|---|---|
| **no promotion** (the 0-of-15 normal case) | 23=PARTIALLY-VACUOUS, **31=PASS_VOIDED**, 32/34/35=PASS_VOIDED, rc=1 | 23=PASS, **31=PASS**, 32/34/35=PASS, rc=0 |
| **promotion + sign-off contradicts it** | 23=FAIL, downstream voided, rc=1 | 23=FAIL, downstream voided, rc=1 |

Normal case: **10 steps move, every one of them PASS_VOIDED -> PASS** — 23, 30, 31,
32, 33, 34, 35, 36, 37, 38 — and the run goes rc 1 -> 0.
Contradiction case: **0 steps move.** Criterion 3 (prove-by-run) is satisfied in the
direction that matters: the refusal still FAILs the step and still stops the run.
So step 31 at PASS is now an **observation**, not the earlier prediction.

## AND THEN THE FLOW REFUSED IT
`flow_condition_reachability_check`, BLOCKING, from the plugin root:

    clean main fafb823d90   rc=0   PASS: all 66 flow conditions reachable
    this branch             rc=1   FAIL: 1 NEW self-disabling condition
      step 23 predicate drv_promotion_corroboration_check:
      condition ['phase3/stage3/pnr/routed_base_prerepair.def',
                 'pnr/routed_base_prerepair.def']
      ANY-of: no trigger survives — none is a declaration (T1), a not-run
      disclosure (T2), a backstopped required_output (T3/T5), or a hard
      files_exist (T4/T7).

**The gate is right.** `routed_base_prerepair.def` is a RESULT the flow produces, not
a declaration, so T1 fails; the promotion writes no `*_not_run.json`, so T2 fails; it
is no step's sole `required_outputs` (T3/T5) and no hard `files_exist` names it
(T4/T7). My rung makes the gate skip on exactly the condition it exists to police.

## THE OBVIOUS REPAIR DOES NOT WORK — this is a DOCTRINE COLLISION
The check's own prescribed shape is T2: have the producer always leave either a
result or a `*_not_run.json`, and condition `any_of: [marker, record]`. Trace it —
with no promotion the record EXISTS, so the condition is true, so the clause RUNS,
so it returns VACUOUS_PASS, so step 23 is PARTIALLY-VACUOUS again and 32/34/35 are
voided again. **T2 restores reachability by reinstating the exact defect the rung
was for.**

Two landed flow doctrines sit on opposite sides of this one clause:

- **reachability (#210/#219)** — never silently skip; run, and report BLOCKED.
- **vacuity tier (#901/#1115)** — a clause that RAN and examined nothing demotes a
  certifying step, and `_blocks_when_vacuous` then voids its descendants.

Together they leave **no wiring in which a rarely-applicable clause on a CERTIFYING
step is neutral**: every option either skips silently (fails reachability) or runs
and discloses nothing (fails the tier and voids the back end). That is the finding,
and it is larger and more durable than the rung. It is a flow-POLICY question — does
the vacuity tier distinguish "inapplicable by a declared condition" from "applicable
and unexamined", or does reachability grow a fifth trigger class for a subject that
is an optional EVENT? — and it is the owner's to settle, not mine.

## WHAT I DECLINED TO DO
`flow_condition_reachability_check` carries a visible, reviewable `ALLOWLIST`, whose
`ppa_head_to_head_check` entry reads "the subject is a CLAIM, not a result". Mine
would read "the subject is an OPTIONAL EVENT, not a result" — a plausible fifth
class. **I did not add it, and I did not touch the baseline.** Adding my own change
to the list that refuses it is self-serving; it is a doctrine judgement that belongs
to the owner; and the baseline's own docstring warns against a list rotting into a
permanent excuse. Named as the candidate, not taken.

## ACCEPTANCE STATUS against `flow-change-acceptance`
| criterion | status | evidence |
|---|---|---|
| 1 bidirectional negative control | **MET** | 2 fail pre-fix / 6 pass post-fix; `control_substance_check` grades **2 of 2 reported failures observed a VALUE**, 0 presence-only, 0 undecided |
| 2 corpus sweep, zero false positives | **MET** | 2 real trees, 2 different designs (spm `_spmfinal`, a converged sha256 tree): **0 steps moved** on each; neither reaches the path, stated not dressed up |
| 3 prove-by-run that BLOCKING blocks | **MET** | contradiction and uncorroborated cases: step 23 FAIL, rc!=0, **0 steps move** between arms |
| 4 no design/PDK/vendor literals | **MET** | `source_chip_agnostic_check` rc=0; fixtures synthesized; one control reads the checked-in flow yaml via `_hostpaths.require_repo` (#400) |
| 5 BLOCKING/ADVISORY declared | **MET** | declared in the clause comment: "ENFORCEMENT: BLOCKING, and still blocking after the rewiring below" |
| 6 degrade loudly | **MET** | `absent_condition_reason` is the named record; surfaces as "NOT-APPLICABLE (declared, N of M gate clause(s) here examined nothing)" |
| skill compliance gate | **MET** | 2 passed, 1 skipped |
| **`flow_condition_reachability_check`** | **FAILED** | rc=1 on this branch, rc=0 on clean main |

Six criteria and the compliance gate are met. **One blocking flow gate is not, so the
change is NOT GREEN and is not offered for landing.** Reporting it that way is the
point: a flow change that trades one defect for another a gate catches is exactly
what this doctrine exists to stop, and it stopped mine.

## HONEST LIMIT ON THE REAL-TREE ARMS
Neither reachable real tree exercises the path — on `_spmfinal` step 23 is MISSING,
on the sha256 tree it is FAIL, both because a pre-v1.14 tree cannot satisfy
v1.14.37's step-23 clauses. A tree converged AT v1.14.x is needed and the only one is
`spm_manual_1.14.30` on .121, which refuses ssh from this host. Both arms are
therefore reported as corpus-sweep data, not as the observation; the observation is
the real-graph run above.

## REGRESSION — failure NAME SETS, not counts (58 modules, both arms)
Same 58-module set run on this branch and on clean main `fafb823d90`, compared by
name because equal counts mean nothing:

    branch: 9 failed, 1822 passed, 6 skipped, 8 xfailed   (742s)
    main:   7 failed, 1824 passed, 6 skipped, 8 xfailed   (783s)

**PRE-EXISTING on main, not mine (5):**
`test_a_gate_that_cannot_judge_must_not_retier_the_step::test_POSITIVE_CONTROL_the_blocking_slot_deletes_the_voided_line`,
`test_issue306_advisory_gate_slot` (x2),
`test_ppa_runner_extraction_ledger::test_no_new_ppa_logic_may_be_added_to_the_runner`,
`test_signoff_required_outputs_completeness::test_the_matrix_does_not_hold_the_step31_json_entry`.

**FIXED by the branch (2)** — my two controls, failing on main by construction.

**NEW, introduced by my change (4):**
1. `test_flow_condition_reachability_check::test_canonical_flow_has_no_unbaselined_holes`
   — the blocking gate above.
2. `test_matrix_d6_skip_discipline[step23]` — "L4 SELF-DISABLING CONDITION
   (undisclosed)"; it wraps the same classifier, so this is the SAME objection
   reported by a second guard, not a second problem.
3. `test_matrix_d2_falsifiable::test_d2_gate_has_a_reachable_fail[step23]` — a
   DIFFERENT and more interesting one: "1 clause(s) in UNREDDENED now reach a real
   FAIL — the gap closed, so the entry is a lie and must be deleted". The clause is
   registered as one that cannot reach a real FAIL, and after the rewiring it can.
   That is bookkeeping made stale by an improvement, and the repair is to delete the
   registry entry — NOT done here, because it is only correct if the rung itself is.
4. `test_issue306_register_paydown::test_306_drv_blast_radius_is_stated_where_the_wiring_is`
   — **mine, and sloppiness, not doctrine**: my rewritten comment dropped the
   sentence recording that the clause blocks 0 of 15 published run-roots. That
   measurement is the very thing that motivates the rewiring, so deleting it while
   rewiring on its strength was exactly backwards. RESTORED; the module is now
   16 passed.

So after the restore, the outstanding failures are **1 doctrinal objection reported
by 2 guards, plus 1 stale registry entry that the change itself invalidates.** None
of them is noise, and the first one is disqualifying on its own.

### CONFIRMED OUTSTANDING SET (after the #306 restore)
Re-run of the four affected modules plus the new test file:
`3 failed, 18 passed in 172.83s`
    FAILED test_flow_condition_reachability_check::test_canonical_flow_has_no_unbaselined_holes
    FAILED test_matrix_d2_falsifiable::test_d2_gate_has_a_reachable_fail[step23]
    FAILED test_matrix_d6_skip_discipline::test_d6_skip_discipline[step23]
All six of the new acceptance tests pass. #306 is back to 16 passed.

## VERDICT ON THIS BRANCH
**NOT GREEN. Do not land, and do not land it later without settling the collision.**
The rung does what it was measured to do — step 31 and nine other steps observed
moving PASS_VOIDED -> PASS, with the #293 refusal intact — and the flow's own guards
still refuse it, on grounds that are correct. The honest summary is that the defect
is real, the rung is the right shape for the vacuity doctrine and the wrong shape for
the reachability doctrine, and no wiring satisfies both today. That is the thing to
carry forward, not the diff.
