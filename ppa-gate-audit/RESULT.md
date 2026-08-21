# Six PPA gates that had never checked anything

Measured on `origin/main` a00f53f2094812041c8aa6094f27058bc1b14ddd (v1.11.66),
on a tree cleaned with `git clean -xdfq`, `PYTHONDONTWRITEBYTECODE=1`.

Six gates in `tools/ci/repo_hygiene_gates.sh` carry `uncheckable_until 2026-11-30`.
Each takes zero seconds, examines zero items, and exits 2. The exemption text says
of every one of them: *"no run in this repository has filed one yet"*.

That sentence is what this lane tested, and for four of the six it is **false**.
The records exist. They are committed. The gates were pointed somewhere else.

## The one-line cause

`benchmark-data` left this repository in v1.10.56. All six gates are wired at
`$ROOT/benchmark-data/ppa/...`, a directory that has not existed here since. The
reproduced refusals name that path, and nothing else:

    PPA head-to-head records   rc=2  no corpus at <ROOT>/benchmark-data
    PPA measurement contract   rc=2  <ROOT>/benchmark-data/ppa/contract.json: absent
    PPA measurement coverage   rc=2  INPUT_ABSENT: no such bundle: .../ppa/coverage.json
    PPA promotion feasibility  rc=2  candidates not found: .../ppa/candidates.json
    PPA frontier recomputes    rc=2  candidates not found: .../ppa/candidates.json
    PPA arms solved one problem rc=2 baseline .../ppa/baseline_contract.json: absent

Meanwhile the repository carries, committed and tracked:

    ppa-crosslayer/records/h2h_A..O.json          15 vibeic.ppa.comparison.v2 records
    ppa-e2e/records/head_to_head*.json             2 more, + 2 checker REPORTS
    ppa-*/records/**/contract.json                82 vibeic.ppa.contract documents
    ppa-crosslayer/records/trials/*/candidates.json 21 candidate sets
    ppa-*/records/**/records_flat.json            metric record sets
    ppa-crosslayer/equivalence/equiv_*.json       12 RTL-vs-RTL equivalence records

## Verdict per gate

| # | Gate | Verdict | Subject actually examined |
|---|------|---------|---------------------------|
| 1 | PPA head-to-head records | **RUNS-AND-FAILS** | 17 real records: 12 PASS, 1 REFUSED, 4 UNDETERMINED |
| 2 | PPA measurement contract | **RUNS-AND-PASSES** | 82 real contracts, 82 PASS |
| 3 | PPA measurement coverage | **STILL-CANNOT** | denominator does not exist — named below |
| 4 | PPA promotion feasibility | **RUNS-AND-FINDS** | 21 real candidate sets, 21 UNDETERMINED on two axes |
| 5 | PPA frontier recomputes | **STILL-CANNOT** | no `objectives` declaration exists — named below |
| 6 | PPA arms solved one problem | **RUNS-AND-PASSES** | 80 real contract pairs, 80 PASS |

---

## 1. PPA head-to-head records — RUNS-AND-FAILS

**Input it needs.** A directory of `vibeic.ppa.comparison.v2` records.
**Producer.** `ppa-crosslayer/tools/head_to_head.py`, `ppa-e2e/tools/head_to_head.py`.
**It exists.** 17 of them, committed.

Two separate defects kept the gate off them.

**1a. The corpus glob is a filename guess.** `_RECORD_GLOB = "**/*head_to_head*.json"`.
The 15 crosslayer records are named `h2h_A.json` … `h2h_O.json`. They declare
`"schema": "vibeic.ppa.comparison.v2"` and the checker validates them one at a time
without complaint — but the corpus walk never sees them. Pointed at `ppa-crosslayer`,
the gate printed `0 head-to-head record(s) found` and exited 2, which is the same
output it gives for a corpus that does not exist.

**1b. The same glob eats the checker's own reports.** Pointed at `ppa-e2e`, the walk
matched 4 files: 2 records and 2 `*_report.json` artefacts written by this very
checker. A report has no `arms` key, so the gate refused it with
`TOO_FEW_ARMS: a head-to-head needs at least two arms; got 0` — a refusal aimed at
its own output. 2 of the 4 "refusals" in that run were the gate reading its own
homework.

**What the gate says about the real 17** (each run individually, so neither defect
is in the way):

    12 PASS   h2h_C D E G H I J K L M N O
     1 FAIL   h2h_F   BASELINE_TUNED_BY_US
     4 UNDET  h2h_A   SCOPE_SENTINEL      (timing_wns_ns scope declares rc_corner with no value)
             h2h_B   SCOPE_INCOMPLETE    (power_mw scope does not declare `mode`)
             ppa-e2e/records/head_to_head.json                  SCOPE_SENTINEL
             ppa-e2e/records/head_to_head_diagnostic_power.json SCOPE_SENTINEL

### The finding: `h2h_F` is the headline comparison, and the gate refuses it

`h2h_F` is the record behind the sentence v1.11.66 calls *"the number this lane
exists to produce, and it is the one to quote"* — cross-layer ECO-preserving `z23`
(6106 um2, 0.000541 W, 10 spares) against the place-and-route-only winner `p04`
(6136 um2, 0.000559 W, 0 spares).

    baseline  vibe-ic-pnr-only-searched     tuned_by_this_project = true
    subject   vibe-ic-crosslayer-searched   tuned_by_this_project = true

    [FAIL] BASELINE_TUNED_BY_US
      baseline 'vibe-ic-pnr-only-searched' does not declare `tuned_by_this_project: false`.
      A baseline we tune is an oracle we wrote, and a favourable number measured
      against it says nothing about silicon.

The lane was honest: it *recorded* that its baseline is self-tuned. The gate's
ruling is that a comparison against a baseline this project tuned cannot carry the
claim printed on it. Both statements can stand at once, and they point at the same
repair: the quotable number is the one against `vibe-ic-phase3-defaults`, which is
what the 12 passing records measure. `h2h_F` is a *within-project* ranking and must
be labelled one, not a head-to-head.

**This is reported, not suppressed.** No assertion was relaxed and the record was
not edited.

---

## 2. PPA measurement contract — RUNS-AND-PASSES

**Input.** `vibeic.ppa.contract` document.
**Producer.** `ppa_contract_build.py` (via `ppa-*/tools/gen_declaration.py`).
**It exists.** 82, committed.

    82 contract(s) checked, 82 rc=0, 0 rc=1, 0 rc=2

Every one carries the same single `[NOTE] PPA-C-014`: the `vibeic-eda` image digest
pins bytes, but its `org.opencontainers.image.version` label could not be read, so
the human-readable version is `NOT_MEASURED`. That is a note, not a finding — the
digest is the reproduction key and it is intact.

Per contract the gate examines: 5/5 identities MEASURED, 16/16 declared artefacts
hashed, 16 in the evidence manifest, 1 image, 9 declared facts.

---

## 3. PPA measurement coverage — STILL-CANNOT

**Input it needs.** A bundle carrying BOTH a record set AND a declared denominator:
either `{"records": [...], "expected": [...]}` or a separate `--expect` file whose
`expected` list is non-empty.

**The record half exists.** `ppa-*/records/**/records_flat.json`,
`signoff_records.json`, `timing_records.json`, `drv_records.json` — all
`vibeic.ppa.metric.v1`, all committed, 148 rows in `trials/b000` alone.

**The denominator half does not exist anywhere in this repository.** Measured:
`grep -rl '"expected"' ppa-e2e ppa-crosslayer` → no match. All 82 contracts carry
`"metrics": []`.

Pointed at a real record set the gate exits 2, but for a **different and better**
reason than the one the exemption states:

    [CANNOT CHECK] NO_EXPECTATION_SET: neither --expect nor the bundle declares
    what should have been measured. Coverage computed from the records alone can
    only ever be 100%, because the rows it would report missing are exactly the
    rows that are not there to iterate over.

That is the gate refusing a vacuous 100%, which is correct.

**Exact missing artefact:** a document with a non-empty `expected` list — the set of
`(metric, scope)` pairs a PPA run is *required* to produce, declared before the run.

**Who would produce it:** nothing does today. The natural producer is
`ppa_contract_build.py`, which already writes the `metrics` key it leaves empty; the
denominator belongs beside `required_views_by_axis` in the contract, declared from
the L19 constraints document rather than inferred from what the run happened to emit.
Authoring one here would be writing the answer key after the exam, so it is named
rather than written.

---

## 4. PPA promotion feasibility — RUNS-AND-FINDS (content-earned UNDETERMINED)

**Input.** `vibeic.ppa.candidates.v1` — carries its own `required_views_by_axis`,
`required_views`, `limits`, `allow_waivers` and the candidate metric records.
**Producer.** `ppa-crosslayer/tools/build_arm.py`.
**It exists.** 21 sets, committed.

**A second wiring defect, separate from the missing directory.** The shipped line
passes `--contract $ROOT/benchmark-data/ppa/contract.json` *as well as* the
candidates. Two different documents in this codebase are called "contract":

  - `vibeic.ppa.contract` — identities, evidence manifest, declared facts. What
    `ppa_contract_check` validates. 82 in tree.
  - the feasibility/pareto contract — `required_views`, `limits`, `objectives`.
    **Zero in tree.**

Handing gate 4 the first shape wipes out the views the candidates already declare:

    with    --contract .../trials/b000/contract.json
      b000: UNDETERMINED  setup:FEAS_VIEWS_NOT_DECLARED, hold:FEAS_VIEWS_NOT_DECLARED,
                          drv:…, drc:…, lvs:…, antenna:…, ir:…, em:…, equivalence:…   (9 axes lost)

    without --contract  (the candidates declare their own views)
      b000: UNDETERMINED  em:FEAS_NOT_MEASURED, equivalence:FEAS_NOT_MEASURED         (2 axes)

Run correctly over all 21 committed candidate sets, the verdict is identical every
time: **7 axes adjudicated, 2 not measured.**

    21/21 rc=2 UNDETERMINED — em:FEAS_NOT_MEASURED,em:FEAS_INCOMPLETE_VIEW_SET,
                              equivalence:FEAS_NOT_MEASURED,equivalence:FEAS_INCOMPLETE_VIEW_SET

This reproduces the campaign's own published verdict: `ppa-crosslayer/records/summary.json`
records `feasibility_verdict: UNDETERMINED` with `em` and `equivalence` UNDETERMINED
for every trial. The gate agrees with the record set. It is running, it is examining
real silicon measurements, and it is refusing to call any published candidate
FEASIBLE — which is the honest answer.

### The finding: THREE equivalence relations, and the axis needs the one nobody proved

The rows are NOT missing. Each `candidates.json` carries
`equivalence.verdict`, `reliability.em.violations` and
`reliability.em.worst_ratio` as `vibeic.ppa.metric.v1` records — 67 distinct
metric names across the 21 sets, those three among them. They are
`status: NOT_MEASURED`, each with a stated reason, and the reason is where the
finding is:

    equivalence.verdict     status NOT_MEASURED
      "the proven pair is RTL against 'post_dft_netlist.v (synth)', which names
       no post-layout netlist. The routed netlist that became the layout was not
       the gate side of this proof, so it establishes no post-route equivalence"

Three different equivalence relations exist in this campaign and they are not
interchangeable:

  1. `ppa-crosslayer/equivalence/equiv_*.json` — `candidate_rtl == baseline_rtl`,
     12 records, yosys, all PASS. This is the one v1.11.66 quotes when it says
     every RTL behind every number is proven equivalent to the baseline, and it
     is a claim about the REWRITE, not about the layout.
  2. flow step 13 — candidate RTL against the candidate post-DFT netlist. The
     `equiv_*.json` records name this one explicitly to say they are NOT it
     ("step 13 passes on a rewritten candidate by construction and cannot
     reject one").
  3. what the `equivalence` feasibility axis at `stage: post_route` requires —
     the ROUTED netlist that became the layout.

(1) and (2) are filed. (3) is not proven by either, and the record says so in
its own `reason` field rather than letting (1) stand in for it. The adjudicator
is not blind to the proofs; it is refusing a proof of a different pair. That is
the correct behaviour and the gap is real.

`em` DID run — `openroad-psm`, `reports/phase3/em.json`, hash recorded — and
produced no verdict:

    reliability.em.violations   "the current-density screen states verdict
                                 'nothing', which is neither PASS, FAIL nor SKIPPED"
    reliability.em.worst_ratio  "the screen states no `summary.worst_utilization`,
                                 so no segment was screened against a Jmax and no
                                 ratio exists"

So the missing artefact for the `em` axis is not an analysis run; it is an EM
screen that reaches a verdict. Two different repairs, and conflating them would
send someone to re-run a tool that already ran.

**Correction.** An earlier draft of this report said the `equivalence` axis was
`FEAS_NOT_MEASURED` "because no `vibeic.ppa.metric.v1` row in any
`candidates.json` names that axis", and that `em` "has no producer at all: no
electromigration analysis ran". Both are wrong. The rows exist, both tools ran,
and the reasons above are what the records actually say. The wrong version would
have sent a reader to wire up a producer that is already wired.

---

## 5. PPA frontier recomputes — STILL-CANNOT

**Input it needs.** An `objectives` list — `[{key, metric, sense: min|max, scope}]` —
read from `--contract` or, absent that, from the candidates document itself
(`_ppa/pareto.py:objectives_from_document`).

**It does not exist.** Measured: no `objectives` key in any of the 82 contracts, in
any of the 21 candidates documents, or anywhere else under `ppa-e2e/` or
`ppa-crosslayer/`. The only in-repo emitter of that key is `arch_dse_pareto.py`,
which is a different subsystem and files nothing here.

    [CANNOT CHECK] the contract declares no objective, so there is no trade-off
                   to compute a frontier over

**Exact missing artefacts, both of them:**

  1. an `objectives` declaration, and
  2. a published `frontier.json` for the gate to be *under test* against.

Neither exists. Note that (2) is what makes this a genuine STILL-CANNOT rather than
a fixable wiring bug: `objective.json` in each trial names the search's single
objective (`area.design_report.um2`, scope `{stage: post_route, tool: openroad,
fill: post_fill}`) and `summary.json` records the direction, so an `objectives`
document COULD be derived. But with no published frontier to refuse, the gate would
be recomputing a frontier and then checking it against itself. A gate marking its
own paper is not a gate. Deriving the objectives *and* the frontier here to obtain
rc=0 would be manufacturing the pass this brief forbids.

**Who would produce it:** the search runner. `ppa-crosslayer/tools/summarize.py`
already computes the ranking that `RESULT.md` publishes as a Pareto set
(`z21` a Pareto improvement, `u01` a trade, `pareto INCOMPARABLE` for one pair) —
it emits that as prose and tables and never as a `frontier.json`. Making it write
one, alongside the `objectives` it is already optimising against, is the step that
takes this gate live. That is a lane-owned change to a search tool, not a wiring fix.

---

## 6. PPA arms solved one problem — RUNS-AND-PASSES

**Input.** Two `vibeic.ppa.contract` documents, baseline and candidate.
**Producer.** Same as gate 2.
**It exists.** 82 contracts, giving 80 published baseline/candidate pairs.

    ppa-crosslayer  b000 vs each of the other 20 trials   20 pairs   20 rc=0
    ppa-e2e         baseline vs each of 60 trials         60 pairs   60 rc=0
                                                          --------   --------
                                                          80 pairs   80 PASS

    [PASS] problem, analysis and toolchain identities MATCH and the implementation
           identity differs — these two runs are comparable.

Zero findings. The 80 pairs the two campaigns actually compared were all comparing
the same problem.

---

## What the exemption should have said

Four of the six exemptions rest on the sentence "no run in this repository has filed
one yet". For gates 1, 2, 4 and 6 that sentence is contradicted by 17, 82, 21 and 80
committed documents respectively. The gates were not blocked on a missing run; they
were pointed at a directory that moved two months before the exemption was written,
and nobody re-aimed them.

For gates 3 and 5 the sentence is true, and now it is true *with a named artefact
and a named producer* instead of a date.

---

# Part 2 — what was changed, and what it measures now

## The wiring, after

`tools/ci/repo_hygiene_gates.sh`, measured on a clean tree at a00f53f20 with the
changes on this branch:

| Gate row | Subject | Examined | rc |
|---|---|---|---|
| PPA head-to-head records | published corpus, other repository | 0 (pointer unset) | 2 |
| PPA head-to-head records (cross-layer campaign) | `ppa-crosslayer` | 15 records | **1** |
| PPA head-to-head records (end-to-end campaign) | `ppa-e2e` | 2 records | 2 |
| PPA measurement contract (cross-layer campaign) | `ppa-crosslayer` | 21 contracts | **0** |
| PPA measurement contract (end-to-end campaign) | `ppa-e2e` | 61 contracts | **0** |
| PPA measurement contract | published corpus, other repository | 0 (pointer unset) | 2 |
| PPA measurement coverage | `trials/b000/records_flat.json`, 148 rows | denominator absent | 2 |
| PPA promotion feasibility (cross-layer campaign) | `ppa-crosslayer` | 21 candidate sets | 2 |
| PPA frontier recomputes | `trials/z23/candidates.json` | no objective declared | 2 |
| PPA arms solved one problem (cross-layer campaign) | `b000` vs `ppa-crosslayer` | 20 pairs | **0** |
| PPA arms solved one problem (end-to-end campaign) | `baseline` vs `ppa-e2e` | 60 pairs | **0** |

Six zero-second rows examining nothing became eleven rows examining 15 + 2 + 21 +
61 + 148 + 21 + 2 real documents, plus three rows that still cannot look and now
say exactly what they are missing.

## The one red, and why it is not wired around

`PPA head-to-head records (cross-layer campaign)` exits 1. The finding is `h2h_F`,
described in Part 1. It is acknowledged in `tools/ci/gate_red_since.json` with an
owner and a 200-commit bound. A row there **grants no leniency** — the file's own
header says so and the suite still exits 1 — it only starts a clock that fails the
landing gate if the red outlives it. Acknowledging is taking on a deadline, not
escaping one.

The alternative was to leave the gate pointed at a directory that does not exist,
where it would have gone on reporting NOT_CHECKED in zero seconds for another three
months. That is the trade this lane refuses.

## Two defects found in the gates themselves

**A corpus identified by filename.** `ppa_head_to_head_check.corpus_records` was
`corpus.glob("**/*head_to_head*.json")`. It missed 15 real records and refused 2 of
this checker's own report artefacts as if they were records (`TOO_FEW_ARMS ... got
0`). Records are now identified by a declared `schema` of `vibeic.ppa.comparison.*`,
with the legacy filename kept only as a fallback for pre-schema records and as the
way an *unreadable* file stays in the population instead of vanishing.

`record_schema()` is deliberately not used for this: it reads a missing declaration
as v1, and "declares nothing" is exactly what a neighbouring document that is not a
record also does.

**Two documents called "contract".** `ppa_feasibility_check` and `ppa_pareto_check`
want `required_views` / `limits` / `objectives`; `ppa_contract_check` wants
`vibeic.ppa.contract.v1` (identities, evidence manifest). The shipped wiring handed
all three the same path. Measured, giving the feasibility gate the contract-v1
shape overrides the `required_views_by_axis` the candidate sets already declare and
loses all nine axes to `FEAS_VIEWS_NOT_DECLARED`. The `--contract` argument is gone
from that row.

## Negative controls

`test_issue1241_corpus_identifies_records_by_declaration.py`, run against the
**pre-fix** program: **4 failed, 3 passed.**

    test_a_record_under_any_filename_is_in_the_corpus
    test_this_programs_own_report_is_not_a_subject
    test_dropping_the_report_never_drops_the_record_it_is_about
    test_a_record_that_lost_its_arms_is_still_refused_not_mistaken_for_a_report

With the fix: 46 passed (7 new + 39 pre-existing in
`test_issue1121_ppa_head_to_head.py`).

`test_issue1241_ppa_record_gates_take_a_corpus.py`: 11 passed. Its load-bearing
assertion is that the corpus roll-up is severity-ordered and not `max()` — under
`max()`, `[1, 2]` rolls up to 2, and adding one unreadable document to a corpus
holding one refused document would SUBTRACT the finding. That shape is not
hypothetical; `ppa_head_to_head_check`'s `_SEVERITY` comment records it happening.

## Honest limits of this lane

- **The full `repo_hygiene_gates.sh` suite was not run to completion here.** The
  eleven PPA rows were each executed directly, on a clean tree, and their exit codes
  are the ones tabulated above. The `gate_red_since.json` row is structurally
  correct but was not adjudicated against a live dispatch record.
- **A pre-existing red, reproduced on a pristine a00f53f20 and NOT caused by this
  lane:** `test_issue1241_vendored_attribution_wired.py::test_the_audit_returns_a_clean_verdict`
  reports 3 checkers that nothing but their own test runs —
  `closed_loop_edge_check.py`, `ppa_pr_scope_check.py`, `slot_pad_budget_check.py`.
  One of those is a PPA checker. It is the same class of defect as the six gates
  above and is not in this lane's scope.
- **The brief named an `ppa-crosslayer/eco-readjudication/` bundle.** It does not
  exist on `origin/main` at a00f53f20 and no path in the tree matches
  `readjudication`. The per-candidate contract and feasibility JSON it describes is
  what `ppa-crosslayer/records/trials/*/{contract,candidates,feasibility_report}.json`
  holds, and that is what was used.
- **Gates 3 and 5 were NOT made to pass.** Both could have been given a document
  authored here — an `expected` list, an `objectives` list, a `frontier.json` — and
  both would then have gone green. Neither was, because a denominator written after
  the run and a frontier checked against its own recomputation are the two shapes
  those gates exist to refuse.

---

# Part 3 — the whole hygiene suite, before and after, on clean trees

Both runs: separate worktrees, `git clean -xdfq`, `PYTHONDONTWRITEBYTECODE=1`,
nothing else touching the tree while the run was in flight.

|  | `origin/main` a00f53f20 | this branch |
|---|---|---|
| gates declared | 85 | 90 |
| decided (PASS or FAIL) | 75 | **80** |
| passed | 69 | **73** |
| failed | 6 | **7** |
| NOT CHECKED | 10 | 10 |

**The failure sets differ by exactly one row**, and it is the intended one:

    comm -13 base_failures mine_failures  ->  PPA head-to-head records (cross-layer campaign)
    comm -23 base_failures mine_failures  ->  (empty)

The six pre-existing failures are unchanged and untouched by this lane:
`checker execution wiring`, `d3 declaration/manifest parity`, `declaration scans
strip comments`, `flow-gate enforcement audit`, `gates are wired to something`,
`liar census controls still fire`.

The ledger row adjudicates:

    gate_red_since: 90 gate(s) declared, 17 red (1 acknowledged, 16 NEW), 1 ledger row(s)
      acknowledged red: PPA head-to-head records (cross-layer campaign)
    [PASS] gate_red_since: every red is NEW or owned by a live, unexpired acknowledgement
    rc=0

## The NOT CHECKED count did not move, and that is the honest number

Ten before, ten after. What changed is what is behind it. Before, six of those
ten rows opened nothing: `benchmark-data/ppa/contract.json: absent`,
`no such bundle`, `candidates not found`, each in zero seconds. After, the six
PPA rows that still report NOT CHECKED are:

  - **2 rows** whose subject genuinely lives in another repository — the published
    corpus, reachable only through `$VIBE_IC_BENCHMARK_DATA`. Their declarations no
    longer claim that no record exists.
  - **1 row** over 2 real records that cannot be decided because both declare a
    timing `rc_corner` key with no value.
  - **1 row** over 21 real candidate sets, 7 of 9 axes SATISFIED on every one.
  - **1 row** over a real 148-row record set with no declared denominator.
  - **1 row** over a real candidate set with no declared objective.

A row that reads 148 metric records and says "nothing told me what should have
been measured" and a row that says "that file is not there" are both rc 2, and
they are not the same fact. Only the second one can be fixed by looking somewhere
else.

## A note on measuring

The first attempt at the "after" run was **void as a measurement**: this report was
being appended to while the suite was in flight, and `policy_direction_pin_check`
— which creates isolated mutation workers from HEAD and needs a clean tracked
checkout — reported UNDETERMINED and the row failed. It does not fail on a tree
nobody is editing. The numbers above are from a re-run on a committed, untouched
tree. The failing row is recorded here rather than quietly dropped, because a
reader comparing two runs deserves to know which one was the measurement.

---

# Part 4 — the four UNDETERMINED head-to-head records have ONE root cause

Gate 1 refuses one record and cannot decide four. The refusal (`h2h_F`) is Part 1.
The four undetermined ones are worth naming precisely, because three of them share
a single missing field and the campaign already demonstrates the fix in its own
tree.

## `rc_corner: null` on every slow-corner timing scope

    h2h_A                                         SCOPE_SENTINEL
    ppa-e2e/records/head_to_head.json             SCOPE_SENTINEL
    ppa-e2e/records/head_to_head_diagnostic_power.json  SCOPE_SENTINEL

All three, both arms, the same field:

    timing_wns_ns.scope = { "stage": "post_route_extracted", "process": "ss",
                            "voltage_v": 1.6, "temperature_c": 100.0,
                            "rc_corner": null, ... }

And the records that PASS, at the typical corner:

    h2h_B, h2h_C … h2h_O
    timing_wns_ns.scope = { ..., "process": "tt", "rc_corner": "max", ... }

Every `process: tt` timing scope in this campaign states its RC corner. Every
`process: ss` timing scope leaves it `null`. So the slow-corner post-route
extraction ran without recording which parasitic corner it extracted at, on both
arms of every comparison that uses it.

The gate's objection is not pedantry: `null == null`, so two numbers taken under
conditions nobody recorded would satisfy a scope-equality test and read as taken
under the SAME conditions. Its own words — *"`null` and `""` are not
unknown-corner markers … State the field or omit the key."* Omitting the key is
also accepted, and it means something different and honest: this measurement has
no RC corner. Writing `null` claims there is one and declines to say which.

**Repair, one field, in the producer:** whatever writes the `ss` timing scope
should emit the RC corner it extracted at, exactly as the `tt` path already does.
This is a defect in the RECORD, not in the design and not in the gate.

## `h2h_B`: a synthesis-stage power number with no operating mode

    h2h_B                                         SCOPE_INCOMPLETE
      power_mw.scope = { "stage": "synth", "scenario": "default", "process": "tt",
                         "liberty": "sky130_fd_sc_hd__tt_025C_1v80.lib", ... }
      -> "power_mw scope does not declare ['mode']"

`h2h_C` measures power at `post_route_extracted` and its scope carries
`"mode": "functional"`. The `stage: synth` power path does not. Same one-field
repair, same producer-side fix, and the compliant shape already exists two records
over.

## Why this matters for the headline

`h2h_A` and `h2h_B` compare the cross-layer winner against `vibe-ic-phase3-defaults`
— the untuned baseline, which is the comparison `h2h_F` cannot make. Twelve such
comparisons PASS, so the lane's claim against the shipped default is carried. But
the two that pair the slow corner or the synthesis-stage power with it are the two
that would extend that claim to the SS corner and to pre-layout power, and neither
can be decided until one field is written.

## The brief's third data source does not exist

`ppa-crosslayer/eco-readjudication/`, named in the brief as holding per-candidate
contract and feasibility JSON, is on **no branch of this repository**: 1524 remote
refs scanned, 0 carry that path. The only `readjudication` matches anywhere are
four unrelated test files under `programs/tests/`. What it describes is what
`ppa-crosslayer/records/trials/*/{contract,candidates,feasibility_report}.json`
holds, and that is what every number in this report was measured against.

## The two STILL-CANNOT gates, checked against the whole repository

The exemptions for gates 3 and 5 rest on a claim about absence, so the absence was
measured over every ref this repository has, not just `main`:

    1524 remote refs scanned
      frontier.json               0 branches
      ppa/coverage.json           0 branches
      ppa-crosslayer/eco-readjudication/   0 branches

Neither artefact has ever been published on any branch of this repository. That is
the difference between an exemption that says "not yet" because nobody looked and
one that says it after looking everywhere there is to look.

---

# Part 5 — the guard, so this cannot happen again quietly

vibe-ic#1710 re-aimed four hygiene gates after v1.10.56 moved `benchmark-data/`
out of this repository. The six PPA record gates were aimed at the same tree and
were not in that sweep. They went on pointing at `benchmark-data/ppa/*` for two
months, and **nothing could have noticed**: `run_tolerating_uncheckable` renders
rc 2 as NOT_CHECKED, which is exactly what those gates *should* report when they
cannot look. The roll-up was correct and useless at the same time. Neither the
exemption expiry, nor the roll-up, nor any other test can see a gate that has
quietly stopped having a subject.

`test_issue1241_ppa_gates_are_aimed_at_a_population_that_exists.py` is that
signal. For every PPA record-gate invocation in `tools/ci/repo_hygiene_gates.sh`
it resolves the declared input and asserts:

  1. it exists;
  2. an in-tree corpus holds at least one document — counted with the
     **checker's own corpus walk**, so the guard cannot drift from what the gate
     will actually find;
  3. no checker is aimed **only** at `benchmark-data/`, which on a host without a
     clone means it examines nothing, forever.

It asserts nothing about the verdict. `h2h_F` is refused today; that is a finding,
not a wiring defect, and this file is indifferent to it. The only claim is that
each gate has a subject to reach a verdict *about*.

**Negative control, against the wiring exactly as it shipped on a00f53f20:**

    7 failed, 3 passed
      test_every_ppa_checker_is_aimed_somewhere_that_exists[ppa_contract_check.py]
      test_every_ppa_checker_is_aimed_somewhere_that_exists[ppa_feasibility_check.py]
      test_every_ppa_checker_is_aimed_somewhere_that_exists[ppa_head_to_head_check.py]
      test_every_ppa_checker_is_aimed_somewhere_that_exists[ppa_measurement_check.py]
      test_every_ppa_checker_is_aimed_somewhere_that_exists[ppa_pareto_check.py]
      test_every_ppa_checker_is_aimed_somewhere_that_exists[ppa_problem_integrity_check.py]
      test_no_ppa_exemption_still_claims_that_no_record_has_been_filed

    with the branch's wiring: 10 passed

This test would have gone red in v1.10.56, on the day the corpus left.

## Final measurement

Third hygiene run, committed and untouched tree, after the guard was added:

    baseline a00f53f20   declared 85  decided 75  passed 69  failed 6  NOT CHECKED 10
    this branch          declared 90  decided 80  passed 73  failed 7  NOT CHECKED 10

    failures on the branch and not the baseline:  PPA head-to-head records (cross-layer campaign)
    failures on the baseline and not the branch:  (none)

Each of the six pre-existing failures was diffed line by line between the two
runs and is byte-identical in content. Nothing in this lane made any of them
worse, and none of them was touched.

---

# Part 6 — a defect this lane introduced, found by reading its own output

`_corpus_location.refuse` is the one seam every corpus gate refuses through, and
it named `--corpus-may-be-absent` unconditionally:

    ... Point VIBE_IC_BENCHMARK_DATA at a clone of the published-corpus
    repository, or pass --corpus-may-be-absent if this repo need not carry one.

That is true for the three callers that offer the flag. The two `--corpus` modes
added by this lane deliberately do **not** offer it — the rc 0 `NO_CORPUS`
outcome the flag buys is a gate printing a pass over a population it never
opened, which is exactly what these gates are wired through this channel to
avoid — so passing it exits 2 as an argparse usage error.

    ppa_contract_check.py    tells the reader to pass --corpus-may-be-absent
                             and its --help does not offer it
    ppa_feasibility_check.py tells the reader to pass --corpus-may-be-absent
                             and its --help does not offer it

An instruction the reader cannot follow is worse than no instruction: it sends
them to debug their own invocation instead of the corpus. `refuse` now takes the
flag its caller actually offers, defaulting to the existing string so all three
pre-existing callers are byte-identical, and the two new ones say *"This gate
offers no way to call an absent corpus a pass."*

**One direction only, and the other is deliberately not asserted.** A gate that
offers the flag and does not mention it may simply have it already in effect:
`l_doc_field_producer_check` and `evidence_citation_resolves_check` both take the
rc 0 branch on an absent corpus, a different sentence that correctly names no
flag. The first draft of the test asserted the converse and failed both of them
for behaving correctly. The clause was deleted rather than the programs being
"fixed" to satisfy a test that was wrong.

Negative control against the pre-fix seam: **4 failed, 2 passed**, including the
behavioural assertion above. A positive control keeps it from passing vacuously —
`ppa_head_to_head_check` offers the flag, does not default it on, and must still
name it, so a repair that merely deleted the sentence everywhere goes red. And
`test_dropping_the_flag_never_changes_the_verdict` pins rc 2 across all three
origins with and without the parameter, so this cannot be a behaviour change
wearing a wording change's clothes.

## Fourth hygiene run, after the seam change

    declared 90  decided 80  passed 73  failed 7  NOT CHECKED 10   (321s)

    failures on the branch and not the pristine baseline:
      PPA head-to-head records (cross-layer campaign)
    failures on the baseline and not the branch:
      (none)

Identical to the third run. The seam change disturbed nothing.

---

# Part 7 — a gate under-aimed by its own argument, and rc 1 worn by a crash

## 2 of 80

Gate 6 was first re-aimed at the comparison each campaign quotes: cross-layer
`b000` vs `z23`, end-to-end `baseline` vs `t028`. That decided something — and it
decided about **two** pairs while **eighty** sit committed here. A gate examining
2 of 80 available comparisons is under-aimed by exactly the argument that
re-aimed it: a contract that drifts in trial 37 is a comparison nobody may quote,
and with two rows nothing would have said so.

    --corpus ppa-crosslayer   20 pair(s), 0 refused, 0 undetermined -> rc=0
    --corpus ppa-e2e          60 pair(s), 0 refused, 0 undetermined -> rc=0

**The baseline is never paired with itself**, and that is tested rather than
assumed. A contract compared against itself matches on every identity by
construction; counting it would be the gate writing its own evidence, and would
make a corpus holding a single document read as checked.

## An internal error was exiting 1, which is reserved for a finding

Found by a test fixture of mine that was malformed: an identity written as a bare
digest string instead of a record raises `AttributeError` out of
`identity.compare`. With no guard the traceback exits **1** — and §1 reserves 1
for a finding about the design. The roll-up would have read a crash as *"these
two runs were not solving the same problem"*, a verdict nothing reached.

This was a local accident while the gate compared one hand-named pair. With
`--corpus` sweeping a whole campaign, one badly shaped document decides the
entire row. `ppa_contract_check` has carried exactly this guard from the start;
`ppa_problem_integrity_check` now carries the same one, and an internal error is
rc 3.

Negative control against the pre-fix program and the two-pair wiring:
**9 failed, 10 passed** — every assertion in the new file, including
`test_an_internal_error_is_rc_3_and_never_rc_1`.

## Fifth hygiene run — the eleven PPA rows, final

    declared 90  decided 80  passed 73  failed 7  NOT CHECKED 10   (300s)

    NOT_CHECKED  PPA head-to-head records                        published corpus, other repo
    FAIL         PPA head-to-head records (cross-layer campaign)  15 records, 1 refused
    NOT_CHECKED  PPA head-to-head records (end-to-end campaign)    2 records, both undecidable
    PASS         PPA measurement contract (cross-layer campaign)  21 contracts
    PASS         PPA measurement contract (end-to-end campaign)   61 contracts
    NOT_CHECKED  PPA measurement contract                        published corpus, other repo
    NOT_CHECKED  PPA measurement coverage                        148 rows, no denominator
    NOT_CHECKED  PPA promotion feasibility (cross-layer campaign) 21 candidate sets
    NOT_CHECKED  PPA frontier recomputes                         no objective declared
    PASS         PPA arms solved one problem (cross-layer campaign) 20 pairs
    PASS         PPA arms solved one problem (end-to-end campaign)  60 pairs

    failures on the branch and not the pristine baseline:
      PPA head-to-head records (cross-layer campaign)
    failures on the baseline and not the branch:
      (none)

Six rows that opened nothing became eleven rows that open 15 + 2 + 21 + 61 + 148
+ 21 + 1 + 20 + 60 documents, one real refusal, and three rows that still cannot
look and now say precisely what they are missing.

---

# Part 8 — the PPA review checklist, run against this lane's own change

`ppa_pr_scope_check.py` is Appendix C of the PPA specification answered by
machine: twenty review questions, applicability decided from the change-set by
two independent arms, and a merge condition of *"every applicable question has
verifiable evidence, and every inapplicable question has a machine-checkable
reason."* Prose never satisfies a question, by design.

It is one of the three checkers the pre-existing `checker execution wiring` red
names as run by nothing but its own test. **It is not wireable into
`repo_hygiene_gates.sh`, and that is not an oversight** — it needs a commit
RANGE, and that file's header states the boundary explicitly: *"anything needing
a commit RANGE or a base SHA … stays inline in the workflow that has the
context."* Wiring it there would break the rule the file exists to keep. It
belongs in the PR workflow, and naming that is the honest disposition.

What it *can* do, today, with no wiring at all, is judge this branch.

## First run — 9 applicable, 9 unanswered

    [FAIL] ppa_pr_scope_check: 9 applicable, 11 N/A, 0 undetermined
                               (arms: path=RUN content=RUN)
      tokens: claim_surface, claims, controller, feasibility, gate, metric,
              pareto, report, security, tool
      [MISSING_EVIDENCE] Q1 Q2 Q3 Q4 Q5 Q7 Q11 Q12 Q19 — no answers document

The detector, not the author, decided those nine applied.

## Q19 was a real question, and it had not been asked

*"Was it tested against prompt injection, hallucinated metric, generic MCP
bypass, raw script, metacharacter, path/symlink traversal and arbitrary shell?"*

Four corpus walks landed on this branch and each globs `**/*.json` under a
directory and reads every match. "Which files are in the population" is not a
detail for these gates — it is the claim. So it was measured, on CPython
3.10.12:

    a symlinked DIRECTORY inside the corpus    NOT traversed
    a symlinked FILE inside the corpus         followed and counted

Both are now pinned, for opposite reasons.

**The directory arm is a guarantee.** `pathlib`'s `**` does not recurse into
symlinked directories, so a corpus cannot be silently extended to documents
living elsewhere — the population stays the tree the gate named. That is
load-bearing and it is *not this code's own doing*, which is exactly why it is
pinned: CPython 3.13 made it configurable (`Path.glob(recurse_symlinks=…)`), and
a future interpreter, or a rewrite reaching for `os.walk`, could change it with
nobody noticing. If that test goes red, the population these gates report is no
longer the population they searched.

**The file arm is a disclosure, not a defence.** A symlinked file *is* counted,
deliberately — dropping it would be "I could not follow it" becoming "it was
never filed", the exact substitution this whole family refuses. What a reader
must know is that its bytes may come from outside the tree the corpus names.
Written down rather than left to be discovered.

The other six arms are recorded as inapplicable **with a reason, not an N/A**:
this branch adds no prompt, model call or agent surface; emits no metric of its
own; adds no MCP tool or dispatch path; and runs no shell, subprocess or
interpolation into a command in any changed program — every one of them reads
JSON from disk and returns an exit code.

## Second run — PASS, with the evidence re-verified

    [PASS] ppa_pr_scope_check: 9 applicable, 11 N/A, 0 undetermined
                               (arms: path=RUN content=RUN)

    evidence states:  artefact VERIFIED  6
                      test     VERIFIED 14
                      prose    UNVERIFIABLE_BY_DESIGN  9

Six artefacts re-hashed and matched, fourteen test ids looked up in the files
that must define them, nine prose entries correctly counted as satisfying
nothing. The answers are `ppa-gate-audit/pr_answers.json`.

Q12 — *"does an outward claim's scope exceed its evidence?"* — is answered by
this lane's own subject: four exemptions claimed "no run in this repository has
filed one yet" over a tree holding 17 records, 82 contracts, 21 candidate sets
and 80 pairs. The claim exceeded the evidence by the entire population.
