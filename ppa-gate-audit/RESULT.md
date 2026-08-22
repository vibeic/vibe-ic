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

> **This document is written in order, and later parts supersede earlier ones.**
> Part 1 is what the gates said when they were first pointed at real records; it
> is kept as written rather than edited, because a report whose early sections
> are quietly brought up to date cannot be checked against the commits that made
> the changes. Where a later part overturns something, the earlier text carries a
> SUPERSEDED note pointing at it. For the FINAL state of all eleven wired rows,
> read **Part 7**; for what gates 3 and 5 are actually missing, read **Part 9**.

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

> **SUPERSEDED IN PART, BY PART 9.** Naming a producer was not the whole answer.
> No schema in `schemas/ppa/` declares this document, so there is nothing yet for
> `ppa_contract_build.py` to produce *to*. The first landable step is a schema.

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

> **SUPERSEDED IN PART, BY PART 9**, and the literal claim above is worth
> separating from the impression it gives. *"No `objectives` key"* is still true —
> measured again, zero files under `ppa-e2e/` or `ppa-crosslayer/` carry that
> plural key. But five carry an `objective` (singular), and
> `ppa-e2e/search/winner.json` declares a full one: metric, scope and direction,
> with `declared_by: "this run -- the design declares NO PPA objective"`. So the
> tree does record what was being optimised; what it does not have is that
> declaration in the shape `ppa_pareto_check` reads, a SCHEMA for that shape, or
> an objective the DESIGN declared rather than the run. The last of those is the
> one that matters, and Part 9 is where it is argued.

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

---

# Part 9 — the brief asked for a SCHEMA, and that is the answer for gates 3 and 5

Ask 1 of this job is *"name the input each gate needs, exactly: a path, a schema,
a producer."* Parts 1 and 3 named paths and producers for the two gates that
still cannot check. The schema was left implicit, and following it up changes the
answer.

## The missing artefacts are UNSPECIFIED, not merely unproduced

Fourteen PPA schemas ship in `vibe-ic-marketplace/plugins/vibe-ic/schemas/ppa/`.
**None of them declares any of the three artefacts these two gates need.**

    an `expected` denominator — (metric, scope) pairs a run must produce   NO SCHEMA
    an `objectives` list      — [{key, metric, sense, scope}]              NO SCHEMA
    a published `frontier`    — the document the gate is under test against NO SCHEMA

`claims.v1` has a `coverage` block, but it is a claim denominator (`total`,
`by_status`), not the measurement denominator `ppa_measurement_check` reads.
`search_manifest.v1` has a `frontier_input`, which declares *what the Pareto lane
may see* — not the frontier it produced.

So the first landable step for either gate is **a schema, not a run**. That is
the same finding #1121 made about the head-to-head gate, in its own words: *"the
first landable step is not a number, it is the RECORD SCHEMA."* Naming a producer
was not enough; there is nothing yet for a producer to produce.

## The only objective in this tree is one a run wrote for itself

`ppa-e2e/search/winner.json` does declare an objective:

    "objective": { "metric": "area.design_report.um2",
                   "scope": { "stage": "post_route" },
                   "better_is": "lower",
                   "declared_by": "this run -- the design declares NO PPA
                                   objective (L19 die_area_budget_um=null,
                                   power_budget_uw=null)" }

The run says so itself, in the record, unprompted: **the design declares no PPA
objective at all.** Both L19 budgets are null.

This is a much stronger reason for gate 5's STILL-CANNOT than "no `objectives`
key exists". An objective could be lifted from this document in an afternoon. It
must not be, because a frontier recomputed against an objective the run chose for
itself, and then checked against a frontier derived from the same choice, is the
run grading its own exam twice. The gate is refusing the right thing.

## The frontier lane excluded all 60 candidates for a reason this tree contradicts

`ppa-e2e/search/manifest.json` — `frontier_stage: post_route_extracted`,
`included_count: 0`, `excluded_count: 60`. Every one carries:

    "code": "FEASIBILITY_UNDETERMINED",
    "detail": "feasibility lane not wired: _ppa/feasibility.py has not landed,
               so no setup/hold/DRV/DRC/LVS/antenna/IR/EM/equivalence evidence
               was read for this candidate"

Both clauses are false in the tree that ships them:

    _ppa/feasibility.py landed          1f9720028  [v1.11.26]
    this manifest was committed         f842978a7  [v1.11.42]   17 commits later
    the lane IS wired                   ppa-e2e/tools/analyze.py:59 invokes
                                        ppa_feasibility_check.py per trial
    evidence WAS read                   122 feasibility reports committed under
                                        ppa-e2e/records/ — 121 UNDETERMINED, 1 INFEASIBLE

**The outcome does not change**: 121 UNDETERMINED and 1 INFEASIBLE would admit
nobody to a frontier either. What changes is which fact is on the record. *"We
never looked"* and *"we looked and could not decide"* must never share a verdict
— that is the rule this entire lane is about, and a committed record asserting
the first while 122 documents beside it prove the second is the same defect one
directory over. A stale reason is indistinguishable from a live one to the next
reader, and it is the one that gets believed.

## One of the 60 ranked candidates is DRC-violating, and the ranking cannot say so

`ppa-e2e/records/trials/t033/feasibility_bridged_report.json`:

    drc         VIOLATED     FEAS_VIOLATION
    lvs         SATISFIED
    antenna     SATISFIED
    ir          SATISFIED
    setup hold drv em equivalence   UNDETERMINED

`t033` is row 6999 µm² in `winner.json`'s 60-row ranking. **It is not the
winner** — `t028` at 6136 µm² is, and the two are not close. But `winner.json`'s
ranking rows carry `trial`, `knobs`, `objective`, `unit`, `cost` and **no
feasibility term at all**, and its `excluded` list is empty. A reader of the
published ranking has no way to learn that one of the candidates in it violates
DRC; the answer is in a sibling directory, in a document the ranking does not
cite.

That is not a wrong number. It is a published ranking whose scope exceeds its
evidence — Appendix C question 12, asked of the campaign rather than of this
branch.

## What this changes, and what it does not

Gate 5's verdict stands: **STILL-CANNOT**. It is now better founded. The
exemption no longer rests on "no run has published one yet" (Part 1), nor on "no
producer writes one" (Part 3), but on three measured facts: no schema specifies
the artefact, the only objective in the tree is self-declared and says so, and
the campaign's own frontier lane admitted zero candidates. None of the four
findings above was produced by changing anything. They were read out of documents
that were already committed.

---

# Part 10 — gate 3's denominator, answered by sweep instead of by grep

Ask 2 of this job is *"find out whether that input can be produced from what this
repository already holds."* Part 1 answered it for gate 3 with a targeted grep
(`grep -rl '"expected"'` → nothing) and Part 9 added that no schema declares the
document. Neither is the same as having looked.

So both campaigns were swept: **every** JSON file under `ppa-e2e/` and
`ppa-crosslayer/`, walked to every depth, looking for a list of
requirement-shaped rows — entries that NAME a metric and carry no measured
`value` or `status`. That is the shape a declared denominator has, whatever it is
called and wherever it sits.

    82 declaration.json                        metrics: []   all 82, no exceptions
    82 contract.json                           metrics: []   all 82 (Part 1)
    requirement-shaped metric lists elsewhere  exactly one family, below

## The one family that turned up, and why it must not be used

    ppa-crosslayer/records/trials/*/feasibility_report.json
        .candidates[].axes[].coverage      6 rows per axis

Those rows are genuinely denominator-shaped: `{metric, view, state}` naming what
was looked for and whether a record existed. It would take an afternoon to
reshape one into an `--expect` document and let gate 3 run.

**It must not be**, for three reasons, and the third is decisive:

  1. It is derived, not declared. `_ppa/feasibility.py`'s hard-coded
     `DEFAULT_AXES` crossed with the candidate set's own `required_views_by_axis`
     — nobody stated it as a requirement of the run.
  2. It is post-hoc. The file is written *after* measurement, so coverage
     computed against it can only report what the adjudicator already decided to
     look for.
  3. **It is a checker's own output being used as the specification that checker
     is judged against.** That is not an analogy for a defect fixed tonight — it
     is the identical defect, one gate over. `ppa_head_to_head_check`'s corpus
     walk was matching its own `*_report.json` artefacts and refusing them as if
     they were records (Part 1, §1b). Feeding `feasibility_report.json` to
     `ppa_measurement_check` as its expectation would rebuild that same loop
     deliberately, having just removed it by accident.

## The answer, now exhaustive

**No pre-declared measurement denominator exists anywhere in this repository.**
Not in a contract, not in a declaration, not under another name, not at any depth
of either campaign. The only requirement-shaped rows in the tree are a checker's
own post-hoc output.

Gate 3 stays **STILL-CANNOT**, and the sentence behind it is now a measurement
rather than a search that stopped early. The missing artefact is a document
declaring, *before the run*, which `(metric, scope)` pairs that run is required
to produce — with a schema, which does not exist either (Part 9).

---

# Part 11 — reproduced from the pushed branch, on a checkout that had never run it

Every number in Parts 1–10 was measured in one worktree. A result measured once,
in the tree that produced it, is a result whose host-dependence nobody has tested
— and this repository has a gate named `gates are host-independent` precisely
because that has bitten before.

So a second worktree was created from the pushed commit
`f040adb0fbcd62e7f21172935a6b8c7ef93e4300`, `git clean -xdfq`, and all eleven
wired rows were run there:

    rc=2  PPA head-to-head records                      no corpus (published, other repo)
    rc=1  PPA head-to-head records (cross-layer)        15 record(s), 1 refused, 2 undetermined
    rc=2  PPA head-to-head records (end-to-end)          2 record(s), 0 refused, 2 undetermined
    rc=0  PPA measurement contract (cross-layer)        21 contract(s), 0 refused, 0 undetermined
    rc=0  PPA measurement contract (end-to-end)         61 contract(s), 0 refused, 0 undetermined
    rc=2  PPA measurement contract                      no corpus (published, other repo)
    rc=2  PPA measurement coverage                      NO_EXPECTATION_SET
    rc=2  PPA promotion feasibility (cross-layer)       21 set(s), 0 infeasible, 21 undetermined
    rc=2  PPA frontier recomputes                       the contract declares no objective
    rc=0  PPA arms solved one problem (cross-layer)     20 pair(s), 0 refused, 0 undetermined
    rc=0  PPA arms solved one problem (end-to-end)      60 pair(s), 0 refused, 0 undetermined

**Identical to Part 7, row for row and count for count.** Nothing reported here
is an artefact of the tree it was produced in.

    91 passed   the six #1241 test files + test_issue1121_ppa_head_to_head.py
    PASS        Appendix C, 9 applicable, 0 undetermined, on the fresh checkout

The Appendix C run matters more than it looks: its answers document pins six
artefact digests, and they were re-hashed against a checkout that had never seen
them. An answer whose evidence only verifies in the tree that wrote it is not
evidence.

The seventh hygiene run — deliberately taken AFTER Parts 8–10 added roughly a
thousand lines of prose, because this repository has gates that read tracked
prose — is unchanged: declared 90, decided 80, passed 73, failed 7, NOT CHECKED
10, and a failure set differing from the pristine baseline by exactly the one
intended red, in both directions.

---

# Part 12 — the rows that could look, and still said nothing a reader could use

Part 7 left eleven wired rows: four PASS, one FAIL, six NOT CHECKED. Parts 9 and
10 argued the two NOT CHECKED rows whose input genuinely does not exist. This
part is about the other kind, and it is a defect Parts 1–11 did not see because
every one of them measured the EXIT CODE and none measured the SENTENCE.

Two rows read their populations, adjudicated them, and refused in a way nobody
could act on.

## `PPA head-to-head records (end-to-end campaign)` — rc 2, and two records that
   were indistinguishable in the output

Measured on `a758f4adc`, `--corpus ppa-e2e`, the whole of what the gate printed
about its two subjects:

    [UNDETERMINED] ppa_head_to_head_check: SCOPE_SENTINEL
      arm '…''s `timing_wns_ns` scope declares ['rc_corner'] with no value. …
    [UNDETERMINED] ppa_head_to_head_check: SCOPE_SENTINEL
      arm '…''s `timing_wns_ns` scope declares ['rc_corner'] with no value. …

Two blocks, byte-identical. Nothing said which document either was about, or
even that they were two documents rather than one reported twice.

**It was never derived and then lost — it was sitting in the report object.**
`evaluate` opens every report with `{"record": str(path)}`; `format_report`'s
PASS branch prints it and its refusal branch printed `r['code']` alone. So the
gate knew the answer on the line above the one it printed.

The FAIL branch shared the defect, which is why `h2h_F` — the refusal this
campaign's headline rests on — was reported for months as a code with no
document attached.

    after:  [UNDETERMINED] ppa_head_to_head_check: …/ppa-e2e/records/head_to_head.json: SCOPE_SENTINEL
            [UNDETERMINED] ppa_head_to_head_check: …/head_to_head_diagnostic_power.json: SCOPE_SENTINEL
            [FAIL]         ppa_head_to_head_check: …/ppa-crosslayer/records/h2h_F.json: BASELINE_TUNED_BY_US

**rc is unchanged: 2 over `ppa-e2e`, 1 over `ppa-crosslayer`.** Both refusals are
CORRECT and neither was converted. `rc_corner: null` really cannot be decided —
`null == null`, so two numbers taken under conditions nobody recorded would
satisfy a scope-equality test. What changed is that the refusal can now be acted
on.

## `PPA promotion feasibility (cross-layer campaign)` — rc 2 over 21 sets, and
   the refusal in full was one sentence naming nothing

    [CANNOT CHECK] at least one candidate was not adjudicated;
                   this run makes no claim about it

No candidate. No axis. No artefact. Over twenty-one adjudicated candidate sets.

**And the naming existed, one layer down, complete.** Part 4 of this report
quotes the reasons the records themselves give — the current-density screen that
states verdict `nothing`; the equivalence proof whose gate side is
`post_dft_netlist.v (synth)` and not the routed netlist. `_ppa/feasibility.py`
carries both through `AxisResult.coverage` as a `reason` lifted VERBATIM from the
metric row, together with the `sources` path that row cites, and
`ppa_feasibility_check` writes all of it into the `--json` report.

`tools/ci/repo_hygiene_gates.sh` passes no `--json`. So on the one channel a
reader ever sees, every one of those sentences was discarded and replaced by a
verdict code.

    after, per undecided axis, on stdout beside the verdict:

      …/trials/z23/candidates.json: z23: UNDETERMINED  em:FEAS_NOT_MEASURED,…
        em: MISSING `reliability.em.violations` at view {"stage":"post_route"}
            [NOT_MEASURED] -- the current-density screen states verdict
            'nothing', which is neither PASS, FAIL nor SKIPPED.
            cited artefact: reports/phase3/em.json
        equivalence: MISSING `equivalence.verdict` … the proven pair is RTL
            against 'post_dft_netlist.v (synth)', which names no post-layout
            netlist … cited artefact: reports/lec.json

**rc is unchanged: 2 over 21 sets, 0 infeasible, 21 undetermined.** Seven of nine
axes are SATISFIED on every set and two carry no measurement; no candidate may be
called promotable, and that was the honest answer before this change and is the
honest answer after it. The difference is that the reader is now told the EM
screen must reach a verdict and the equivalence proof must name the routed
netlist, instead of being told a code.

## Which of the two bugs each one was

The brief that produced this part offered two: a gate missing an artefact it has
not NAMED, and a gate declared to check something that checks nothing. Measured,
**both rows are the first and neither is the second.** Each opened its corpus,
read every document, and reached a per-subject verdict — 2 records and 21
candidate sets, printed by the gates themselves. What each failed to do was say
what it needed.

That distinction is why no row here was converted to rc 0. An inert gate is
repaired by making it run; a gate that runs and refuses correctly is repaired by
making the refusal usable, and turning it green would have required editing a
record to claim a measurement nobody took.

## The finding on `h2h_F`, repaired at the producer and NOT at the gate

Part 1 named it: the baseline arm `vibe-ic-pnr-only-searched` declares
`tuned_by_this_project: true`. Both arms are configurations this project chose —
`p04`, the place-and-route-only search winner, against `z23`, the cross-layer
search winner. That is a within-project ABLATION, and an informative one: it
isolates what the cross-layer search adds over a place-and-route-only search.
What it is not is a head-to-head, whose entire claim is a comparison against an
opponent we did not tune.

**The record is not edited, not re-filed and not removed, and the gate goes on
refusing it.** Two producer-side defects let it be written, and both are closed:

  1. `ppa-crosslayer/tools/head_to_head.py` takes `--baseline-tuned`, whose own
     help text reads *"the gate refuses a baseline we tuned"*. The producer was
     therefore TOLD, in its own invocation, that the document it was about to
     write could not be a head-to-head — and it stamped
     `vibeic.ppa.comparison.v2` on it anyway, filed it in the head-to-head
     corpus, and left the contradiction to surface at a hygiene gate after the
     number had been published. It now refuses at write time and says what to
     file instead.

  2. `schemas/ppa/comparison.v2.schema.json` states the rule in PROSE — *"A
     baseline must declare false"*, in the description of the very property —
     and expressed no constraint. A producer validating its output against the
     shipped schema was told the document was well formed. This is NOT one of
     the cross-arm relations that schema's own description correctly says JSON
     Schema cannot express: it reads two properties of ONE arm. It is now an
     `if role == baseline then tuned_by_this_project: false` clause, and
     validating the fifteen committed cross-layer records against the amended
     schema refuses exactly one of them:

         h2h_F   'True was expected to be False'  at arms[0].tuned_by_this_project

     That is the same finding the gate makes, made at the point of production.

  **Filing the ablation properly still has no home**, and that is named rather
  than papered over: no schema in `schemas/ppa/` declares a within-project
  ranking document. The first landable step is a record schema, not a number —
  the same conclusion Part 9 reached for gates 3 and 5, and #1121's before it.

## A crash that was exiting 1

Found by a malformed fixture, exactly as Part 7's was. An arm whose `design` is
written as a bare digest STRING instead of a mapping raises out of
`check_same_problem`; `evaluate` catches only `Refusal`, so the traceback escaped
and the interpreter exited **1** — which in this contract means *"these two runs
did not solve the same problem"*, a verdict nothing reached. In corpus mode one
such document decides the entire row.

`ppa_contract_check` has carried a guard from the start and
`ppa_problem_integrity_check` gained one in Part 7. `ppa_head_to_head_check` did
not. It now returns **2**, not 3, and the distinction is corpus mode: the
invocation was correct, and a corpus of fifty records where one is badly shaped
is not a bad invocation. The record and the exception are named, and the missing
input is named too — a document of the shape the schema declares. Anything
raised OUTSIDE the per-record loop is still rc 3, matching `ppa_contract_check`.

## The guard, and it generalises past these two rows

`programs/tests/test_rc2_over_a_nonempty_population_names_the_artefact.py`.
Its sibling, `…_ppa_gates_are_aimed_at_a_population_that_exists.py`, asserts a
gate HAS a subject. This one asserts that a gate which has one, opens it, and
then refuses, says what it needs. Two clauses, both countable:

  1. **Subject named.** At least as many distinct EXISTING paths as the roll-up
     says it could not decide. The candidate paths come from the CHECKER'S OWN
     corpus walk, so the guard cannot drift from what the gate opened.
  2. **Absent input named.** For each named subject, a REFERENT somewhere in
     either stream: a backticked field or metric name, an artefact path other
     than the subject itself, or a flag the reader could supply. A
     SCREAMING_CASE code is not a referent — `FEAS_NOT_MEASURED` names a verdict,
     not a thing to go and get.

It runs on a synthetic corpus it builds itself, so it holds on a host carrying no
campaign data, AND on every in-tree `--corpus` row parsed out of the wiring.

**It asserts nothing about verdicts.** An rc 2 that is correct stays rc 2 and
this file is satisfied; the one thing it will not accept is an rc 2 a reader
cannot act on.

**Two of its own assertions were wrong first, and both are recorded rather than
quietly fixed.** `test_the_two_blocks_are_not_byte_identical` passed against the
broken program, because splitting the stream on the marker put the trailing
roll-up inside the last block and made two identical refusals compare unequal.
And `_referents` counted `--corpus` from the gate's own header line, so negative
control B passed against a program with all of its naming removed — a gate could
have satisfied this entire file by repeating the argument it was called with.
Both are now pinned by `test_a_verdict_code_alone_is_not_a_referent`.

## A third row family, found while measuring: rc 3, and quieter than rc 2

Re-running all eleven wired rows exactly as `repo_hygiene_gates.sh` invokes them
turned up two that Part 7 recorded as rc 0 and that now exit **3**:

    [ppa_problem_integrity_check] REFUSE (bad invocation): --baseline/--candidate
    and --corpus were both given. One names a single document and the other names
    a population; running either one silently would report a verdict about
    something the caller did not ask about. Give exactly one. rc=3.

Reproduced on a pristine `a758f4adc`, so it is not this branch's doing.
`--corpus` mode was rewritten to GROUP contracts by their problem identity and
pair inside each group — which needs no baseline — and the refusal of the
two-flag form is deliberate and argued in the program. The wiring was not
updated with it, so `PPA arms solved one problem` had stopped examining any pair
at all, in both campaigns.

**rc 3 is quieter than rc 2 and that is why it survived.** An rc 2 at least says
"I could not look" and the roll-up renders it NOT_CHECKED, which is a state a
reader can go and interrogate. rc 3 says the CALLER got the arguments wrong, and
nothing in the roll-up distinguishes it from a row that ran — the same blind spot
Part 5 describes for the six original gates, arriving through the argument list
instead of through the corpus path.

The flag is removed. Measured after:

    cross-layer  21 contract(s), 1 problem group,  210 pair(s), 0 conflicts -> rc 0
    end-to-end   61 contract(s), 1 problem group, 1830 pair(s), 0 conflicts -> rc 0

Part 7 recorded 20 and 60 pairs for the baseline-against-each form. Grouping
compares every pair inside the group, which is the stronger question and the one
the program now asks: a contract that drifts between trials 37 and 38 is a
comparison nobody may quote, and pairing both only against the baseline could
not have seen it.

`test_no_wired_ppa_gate_is_a_bad_invocation` is the guard, and it needs no
mutation to demonstrate: run it against the pristine wiring and both rows go red
with the refusal quoted above.

## Negative controls

Three throwaway trees, each with ONE repair reverted, nothing else changed.

    A — the record path removed from `format_report`'s refusal branch
        3 failed, 10 passed
          test_a_refusal_over_two_records_names_both_of_them
          test_the_two_blocks_are_not_byte_identical
          test_every_wired_corpus_gate_that_refuses_names_what_is_missing[ppa_head_to_head_check.py-ppa-e2e]

        ppa_head_to_head_check.py --corpus ppa-e2e: rc 2 over a population of 2
        with 2 undecided, and the output names 0 of them. A refusal whose
        SUBJECT is unnamed cannot be acted on.

    B — the per-axis MISSING lines removed from `ppa_feasibility_check`
        2 failed, 11 passed
          test_a_feasibility_refusal_names_the_metric_and_the_cited_artefact
          test_every_wired_corpus_gate_that_refuses_names_what_is_missing[ppa_feasibility_check.py-ppa-crosslayer]

        ppa_feasibility_check.py --corpus ppa-crosslayer: rc 2 and these
        subjects are named but nothing says what is ABSENT from them -- no
        field, no artefact, no flag, only verdict codes. 'rc 2' with no named
        missing input is the failure mode this layer exists to end.

    C — the wiring restored to its pristine two-flag form
        2 failed
          test_no_wired_ppa_gate_is_a_bad_invocation[--baseline|--corpus]  x2

        ppa_problem_integrity_check.py --baseline …/b000/contract.json
        --corpus …/ppa-crosslayer
        is wired with arguments its own program refuses as a bad invocation,
        so this row decides nothing and the roll-up cannot tell it from one
        that ran.

## A pre-existing red in the sibling guard, fixed on the way past

`test_every_in_tree_corpus_holds_at_least_one_document` was RED on `a758f4adc`
before anything in this part was written: `corpus_contracts`,
`corpus_candidate_sets` and `corpus_candidates` were replaced by a SELECTION
PREDICATE handed to `_ppa_corpus.collect`, and the guard's population counter
went on calling the old names. It raised `AttributeError` on THREE of the six
checkers, so the guard could not see half its family — the same class of defect
it exists to catch, one level up. Counting now goes through the seam, which
keeps the original property that the count is the checker's own reckoning.

**And it is one of THIRTY-ONE, which is named here rather than left to be
found.** The same selection of PPA test files, run on a pristine `a758f4adc`
with `git clean -xdfq`, before anything in this part existed:

    32 failed, 603 passed, 104 skipped, 4 xfailed

Every one of the 31 not fixed above is the SAME cause and none of them is a
finding about any gate's behaviour: a test reaching for a program internal that
a refactor renamed and did not follow.

     9  `_ppa_pi_cli` has no attribute `_CONTRACT_SCHEMA`
     4  `corpus_contracts`      (ppa_contract_check)
     3  `_ppa_contract_cli` has no attribute `_CONTRACT_SCHEMA`
     2  `corpus_candidates`     (ppa_problem_integrity_check)
     2  `corpus_candidate_sets` (ppa_feasibility_check)
     1  `_CANDIDATES_SCHEMA`    (ppa_feasibility_check)
    10  the remainder, in `test_ppa_layer_exit_contract.py` and
        `test_ppa_layer_internal_error_is_not_a_finding.py`, over four programs
        this branch does not touch — `ppa_agent_context_build`,
        `ppa_diagnostic_router`, `ppa_pr_scope_check`, `ppa_signoff_records`

That is four guard FILES over the PPA gate family raising `AttributeError`
before they reach an assertion, so the properties they were written to hold are
currently held by nothing. It is a real gap and it is a different lane from this
one: repairing it is per-test-site work across four files with no shared fix, and
this branch's scope is one refused record and two refusals that named nothing.
**Recorded as a request, with the exact counts, rather than half-done.**

The same selection on this branch:

    31 failed, 618 passed, 104 skipped, 4 xfailed

    failures on this branch and not the baseline:  (none)
    failures on the baseline and not this branch:
      test_issue1241_ppa_gates_are_aimed_at_a_population_that_exists.py
        ::test_every_in_tree_corpus_holds_at_least_one_document

---

# Part 13 — reproduced from the pushed branch, and a count in Part 12 corrected

Part 11 established the rule this part follows: a result measured once, in the
tree that produced it, is a result whose host-dependence nobody has tested. Every
number in Part 12 was measured in the worktree that authored it. So a second
worktree was created from the pushed commit `48ea29e6b`, `git clean -xdfq`,
`PYTHONDONTWRITEBYTECODE=1`, and all of it was run again on a checkout that had
never seen it.

## The eleven wired rows

    rc=2  PPA head-to-head records                      published corpus, other repo
    rc=1  PPA head-to-head records (cross-layer)        15 records, 1 refused
    rc=2  PPA head-to-head records (end-to-end)          2 records
    rc=0  PPA measurement contract (cross-layer)        21 contracts
    rc=0  PPA measurement contract (end-to-end)         61 contracts
    rc=2  PPA measurement contract                      published corpus, other repo
    rc=2  PPA measurement coverage                      148 rows, no denominator
    rc=2  PPA promotion feasibility (cross-layer)       21 candidate sets
    rc=2  PPA frontier recomputes                       no objective declared
    rc=0  PPA arms solved one problem (cross-layer)      210 pair(s)
    rc=0  PPA arms solved one problem (end-to-end)      1830 pair(s)

**Identical to Part 12, row for row.** And the naming itself reproduced, which is
the part that matters here — an rc that travels while the sentence does not would
be the same defect wearing a passing exit code:

    [FAIL] ppa_head_to_head_check: .../ppa-crosslayer/records/h2h_F.json: BASELINE_TUNED_BY_US
    [UNDETERMINED] ppa_head_to_head_check: .../ppa-e2e/records/head_to_head.json: SCOPE_SENTINEL
    [UNDETERMINED] ppa_head_to_head_check: .../ppa-e2e/records/head_to_head_diagnostic_power.json: SCOPE_SENTINEL
      em: MISSING `reliability.em.violations` ... cited artefact: reports/phase3/em.json
      em: MISSING `reliability.em.worst_ratio` ... cited artefact: reports/phase3/em.json
      equivalence: MISSING `equivalence.verdict` ... cited artefact: reports/lec.json

    83 passed   the new guard + the three #1241/#1121 files it sits beside
    PASS        source_chip_agnostic_check, 1553 file(s), no forbidden token

## A COUNT IN PART 12 IS WRONG, AND IT IS CORRECTED HERE RATHER THAN EDITED THERE

Part 12 records negative control A as **3 failed, 10 passed**. Re-run from the
pushed commit it is **4 failed, 23 passed**:

    test_a_refusal_over_two_records_names_both_of_them
    test_the_two_blocks_are_not_byte_identical
    test_an_internal_error_is_rc_2_and_names_the_record_not_rc_1     <- the fourth
    test_every_wired_corpus_gate_that_refuses_names_what_is_missing[ppa_head_to_head_check.py-ppa-e2e]

Nothing regressed and nothing was overstated in the direction that flatters this
branch — the control got STRONGER, not weaker. The cause is ordinary and worth
naming so nobody hunts for a subtler one: control A was measured when the guard
file held 13 tests, and `test_an_internal_error_is_rc_2_and_names_the_record_not
_rc_1` was written afterwards. It depends on the same record naming, so it joins
the control. The file now holds 27 tests, which is where `23 passed` comes from.

Control B re-run from the pushed commit is **2 failed, 25 passed** — the same two
tests Part 12 names, against the same larger file.

**Part 12's number is left standing.** This report's header rule is that later
parts supersede earlier ones and that early sections are not quietly brought up
to date, because a document edited in place cannot be checked against the commits
that made the changes. A stale count that a reader can reproduce and see
superseded is worth more than a corrected one they must take on trust.

## What this part does NOT change

No program, no gate, no test and no wiring line. Part 13 is prose in an audit
document; every verdict above is the one the pushed commit already produced.

---

# Part 14 — the exact-path rows, and an rc 2 that was hiding an rc 1

Part 12's guard enforces one rule: a gate that returns rc 2 over a population it
opened must name what is missing. It enforces it on the four `--corpus` gates.
**Two wired rows refuse over a non-empty population through an EXACT PATH**, not
a corpus — `--coverage` and `--candidates` — so the guard never reached them and
the rule went unenforced on a third of the family. Applying it by hand found
three things, and the third is the most serious defect this lane has produced.

## The two refusals, as they stood

    PPA measurement coverage      148-row bundle
      [CANNOT CHECK] NO_EXPECTATION_SET: ... neither --expect nor the bundle
      declares what should have been measured. ...

    PPA frontier recomputes       1 candidate set, 148 metric records
      [CANNOT CHECK] the contract declares no objective, so there is no
      trade-off to compute a frontier over

The first names a flag and never the BUNDLE it opened. The second names nothing
at all — no document, no key, no flag — over a set it had already read and
counted. Both now name the document, the population they read, and the artefact
they need; `ppa_pareto_check` names BOTH of the two Part 9 identified, because a
reader told to declare objectives and not told a published frontier is also
required will build the self-marking pass that gate exists to refuse.

**Neither rc changed. Both are still 2, and both are still correct.**

## AND AN rc 2 WAS HIDING AN rc 1

`run_coverage` states its own severity rule, twenty lines below the defect:

    # An invalid record is a finding about the record set and outranks a
    # coverage gap, for the same reason 1 outranks 2 everywhere else here.

That rule could never fire. `_index_from` establishes the record refusals on the
function's FIRST line — fully, with no further input needed, because a record
that is invalid is invalid whatever a denominator says — and then
`_expected_from` RAISES over a completely independent absent input, so the report
carrying `record_refusals` is never built and the rule never runs.

Measured on the wired row, `ppa-crosslayer/records/trials/b000/records_flat.json`
— **148 rows, 54 refused, and the gate reported NOT_CHECKED and named none of
them**:

    44 x SCOPE_SENTINEL           `scope.clock` is None
     8 x SAME_ARTEFACT_TWO_VALUES one artefact, read twice, two values
     2 x CONFLICTING_RECORD       one metric+scope, two MEASURED values

The two CONFLICTING_RECORDs are not a shape complaint. They are two artefacts of
the same run stating different numbers for the same fact:

    route.wirelength.um   openroad.log 16511.0   vs   openroad.metrics.json 16522
    route.via.count       openroad.log 4151      vs   openroad.metrics.json 4159

A claim citing either binds to neither number. That had been sitting in a
published campaign record set, behind an rc 2, for as long as the row has been
wired.

**These are two INDEPENDENT questions over one bundle** — "are these records
valid" (answered: no, 54 times) and "did the run measure what it was required
to" (undecidable: nothing declares the requirement). Answering the second with
silence about the first is this lane's defect in its more dangerous direction: an
unearned PASS at least looks like a claim, while an unearned NOT_CHECKED looks
like diligence.

The ordering is fixed. `PPA measurement coverage` is now **rc 1**, it prints all
54 refusals, and it STILL SAYS the coverage question is separately undetermined —
an rc 1 about the records is not an answer about coverage, and the row says so.

### This is the one verdict change in the lane, and it is stated loudly

    PPA measurement coverage    rc 2  ->  rc 1

Nothing was made green. A row that reported NOT_CHECKED now reports a finding it
had already computed and discarded. The suite was ALREADY red from the
acknowledged `h2h_F` row, so this does not flip the batch; it adds a second red.
`gate_red_since.json` is NOT edited — a NEW red passes that ledger by its own
rule, and acknowledging a red found an hour ago would be taking on a deadline to
avoid stating a finding.

### A defect introduced while fixing it, and caught by this branch's own rule

The first version of the ordering fix returned `"coverage": None`, and `main`
read `report["coverage"]["rows"]` unconditionally. `TypeError`, traceback,
interpreter exit **1** — a crash publishing itself as a finding, which is the
exact defect Part 12 repaired in `ppa_head_to_head_check` and Part 7 in
`ppa_problem_integrity_check`. It is recorded rather than quietly corrected
because it is evidence about the class: this shape is easy to reintroduce, three
programs in this family have now carried it, and only a test catches it.
`test_a_refused_record_is_rc_1_even_when_the_denominator_is_absent` asserts
`"Traceback" not in output` for that reason.

## The eleven wired rows, final

    rc=2  PPA head-to-head records                      published corpus, other repo
    rc=1  PPA head-to-head records (cross-layer)        15 records, 1 refused, NAMED
    rc=2  PPA head-to-head records (end-to-end)          2 records, both NAMED
    rc=0  PPA measurement contract (cross-layer)        21 contracts
    rc=0  PPA measurement contract (end-to-end)         61 contracts
    rc=2  PPA measurement contract                      published corpus, other repo
    rc=1  PPA measurement coverage                      54 of 148 records REFUSED  <- CHANGED
    rc=2  PPA promotion feasibility (cross-layer)       21 sets, artefacts NAMED
    rc=2  PPA frontier recomputes                       both missing artefacts NAMED
    rc=0  PPA arms solved one problem (cross-layer)      210 pair(s)
    rc=0  PPA arms solved one problem (end-to-end)      1830 pair(s)

## Negative controls

    D — the denominator refusal put back in front of the record refusals
        1 failed, 30 passed
          test_a_refused_record_is_rc_1_even_when_the_denominator_is_absent

        AssertionError: a conflicting record is a finding about the record set
        and this returned 2
          [CANNOT CHECK] NO_EXPECTATION_SET: ... 1 record(s) indexed, 1 refused
          ... rc=2.
        assert 2 == 1

    E — the frontier refusal returned to its one-sentence form
        1 failed, 30 passed
          test_a_frontier_refusal_names_the_document_and_BOTH_missing_artefacts

        AssertionError: [CANNOT CHECK] the contract declares no objective, so
        there is no trade-off to compute a frontier over
        assert '.../candidates.json' in '[CANNOT CHECK] the contract declares
        no objective, so there is no trade-off to compute a frontier over\n'

And the paired half, so the rc-1 rule cannot be satisfied by a gate that refuses
everything: `test_the_paired_half_a_clean_bundle_with_no_denominator_is_still_rc_2`
pins a VALID bundle with no denominator at rc 2. The STILL-CANNOT verdict this
row has carried all along is untouched where it is earned.

## Regression

Same targeted selection as Part 12, plus the five files covering the two programs
changed here:

    31 failed, 769 passed, 104 skipped, 4 xfailed
    failures on this branch and not the base: (none)

---

# Part 15 — the guard's own blind spot, closed the same way the gates' were

Part 14 found the two exact-path rows BY HAND, because the guard's live arm
reached only `--corpus` rows. It then covered them with fixtures in `tmp_path`
and left the arm as it was. That is the same defect this file has been about,
one level up: the rule was enforced on the wired corpus rows and NOT on the
wired exact-path rows, so re-aiming `PPA measurement coverage` or
`PPA frontier recomputes`, or wiring a new exact-path row, escaped it entirely.
A fixture proves a program behaves; only the wiring arm proves the ROW is
guarded.

Measured, before:

    test_every_wired_corpus_gate_that_refuses_names_what_is_missing
      [ppa_head_to_head_check.py-ppa-crosslayer]     7 rows, all --corpus
      [ppa_head_to_head_check.py-ppa-e2e]            and NEITHER exact-path row
      [ppa_contract_check.py-ppa-crosslayer]
      [ppa_contract_check.py-ppa-e2e]
      [ppa_feasibility_check.py-ppa-crosslayer]
      [ppa_problem_integrity_check.py-ppa-crosslayer]
      [ppa_problem_integrity_check.py-ppa-e2e]

After — one arm, both shapes, running the wiring's OWN argv rather than a
reconstructed `--corpus` one:

    test_every_wired_gate_that_refuses_names_what_is_missing
      [ppa_head_to_head_check:corpus:ppa-crosslayer]
      [ppa_head_to_head_check:corpus:ppa-e2e]
      [ppa_contract_check:corpus:ppa-crosslayer]
      [ppa_contract_check:corpus:ppa-e2e]
      [ppa_measurement_check:coverage:records_flat.json]     <- new
      [ppa_feasibility_check:corpus:ppa-crosslayer]
      [ppa_pareto_check:candidates:candidates.json]          <- new
      [ppa_problem_integrity_check:corpus:ppa-crosslayer]
      [ppa_problem_integrity_check:corpus:ppa-e2e]

`test_the_live_arm_reaches_both_wiring_shapes` is the paired half: an arm that
quietly resolved to corpus rows only is exactly the state this change ends, and
it would pass every case in silence.

## AND THE RULE HAD AN OPT-OUT

`_counts` reads the denominator out of the gate's OWN roll-up line. A gate that
prints no roll-up parses as population ZERO and takes the empty-corpus exit — so
**the cheapest way to satisfy this entire file was to print less.** That is not a
hypothetical: the two exact-path rows print no roll-up at all, which is how the
hole was noticed rather than reasoned about.

A population the CALLER knows now outranks a parsed one, and
`test_a_gate_cannot_escape_the_rule_by_printing_no_count` pins both directions —
silent with a parsed zero, refusing once the population is supplied.

## Negative control F — the extension has teeth on the WIRED row

Control E in Part 14 reverted the frontier naming and caught **one** test, the
fixture. The same revert against this part:

    2 failed, 31 passed
      test_every_wired_gate_that_refuses_names_what_is_missing[ppa_pareto_check:candidates:candidates.json]   <- NEW
      test_a_frontier_refusal_names_the_document_and_BOTH_missing_artefacts

    AssertionError: ppa_pareto_check.py --candidates .../trials/z23/candidates.json:
    rc 2 over a population of 1 with 0 undecided, and the output names 0 of them.
    A refusal whose SUBJECT is unnamed cannot be acted on.
      named: []
      --- output ---
      [CANNOT CHECK] the contract declares no objective, so there is no
      trade-off to compute a frontier over
    assert 0 >= 1

The second failure is the fixture, which Part 14 already had. The FIRST is the
wired row, which nothing guarded until now.

## No verdict changes

No program changed in this part. The guard file holds 34 tests.

    31 failed, 772 passed, 104 skipped, 4 xfailed
    failures on this branch and not the base: (none)

---

# Part 16 — how far the defect goes, measured instead of assumed

Every part so far has fixed PPA rows and left the obvious question unasked: the
rule is stated about *a gate*, so is the rest of the suite the same? Parts 12–15
scoped the guard to the PPA family without saying why. That is an unexplained
limit, and an unexplained limit on a guard is the shape this whole report is
about.

So the surface was measured. `repo_hygiene_gates.sh` wires **96** gate
invocations, **25** of them through `run_tolerating_uncheckable` — the wrapper
that renders rc 2 as NOT_CHECKED, and therefore the entire population this rule
could ever apply to. Eleven are PPA rows. The other **fourteen** were run by
hand, each from the cwd its own wiring line gives it.

    rc 0   ten   container login-banner parses · no upstream forked twice ·
                 PR bases reach main · STA engines agree · PDK via patch vs
                 layer min width · macro OBS not crossed · DRC PASS is not
                 vacuous · inner FAILs reach the verdict · new tool diagnostic
                 id · image-gated verifications are not silently skipped
    rc 2   three and every one of them already names what it needs
    n/a    one   gates are host-independent exceeded a 90s probe — a slow gate,
                 not a finding

## The three, and why none of them has the defect

    blocker list contract on committed reports
      "--dir <ROOT>/benchmark-data is not a directory"
      An EMPTY population living in another repository — the same excused shape
      as the two published-corpus PPA rows — and the path is named.

    engineering evidence fresh
      "NOT_GENERATED: <ROOT>/docs/ENGINEERING_EVIDENCE.md does not exist — this
       is NOT a pass; run `python3 tools/gen_engineering_evidence.py`."
      The artefact AND its producer, in the refusal. This is what Parts 1 and 9
      spent pages asking the PPA gates to do, already done here.

    input-doc claims vs installed PDK
      "[VACUOUS] ... examined nothing (reason: no_decidable_pdk_claim); this is
       NOT a pass over the design"
      "4 input document(s), 0 candidate claim(s) — contradicted=0 corroborated=0
       undecided=0"
      A THIRD shape, and it is legitimate. It read a non-empty corpus and found
      no decidable claim in it. Nothing is ABSENT from disk, so there is no
      artefact to name; it discloses the denominator instead and marks itself
      VACUOUS rather than passing.

## What this bounds

**The defect was concentrated in the PPA family.** Six gates that had never
checked anything (Part 1), two that checked and named nothing (Part 12), two
exact-path rows that named too little and one of them hiding an rc 1 (Part 14),
and two wired with arguments their own program refuses (Part 12) — all eleven
rows, one subsystem. The other fourteen tolerating rows in the same file are
already honest, and that is now a measurement rather than an assumption.

**The arm is NOT widened to them, deliberately.** Three of the fourteen need a
container image and one needs network, so pulling them into a pytest guard would
trade a defect this repository does not have for host-dependence it would then
have to manage — and `gates are host-independent` exists because that has bitten
before. The reasoning is recorded in the guard file's own docstring so the
scoping is answerable where a reader meets it, not only here.

A negative result is worth writing down at the same standard as a positive one.
Had it been skipped, the next person to ask "does this rule apply to the rest of
the suite?" would have had to run all fourteen again to find out that it does.

## No changes

No program, no gate, no wiring, no verdict. Part 16 is a measurement and a
docstring.

---

# Part 17 — guards that crashed, a guard that asserted a falsehood, and what is
# genuinely left

Part 12 recorded thirty-one pre-existing reds in the PPA guard family and called
them "per-test-site work across four files with no shared fix". That was
imprecise, and the imprecision mattered: nine of them were not the rename family
at all, and one of the nine was a guard reporting a defect that does not exist.

## A FALSE RED — a guard asserting a defect that is not there

`test_contract_check_says_the_schema_was_not_applied` gates on
`HAVE_DRAFT_2020_12` — *is the REFERENCE jsonschema usable here* — and then
asserts about the PROGRAM. The program resolves its engine through
`_ppa/schema_validation.resolve`, which prefers the reference library and falls
back to `_ppa/jsonschema_bundled`, which SHIPS WITH THE PLUGIN. On a host with
jsonschema 3.2.0 the reference is unusable, so the skip did not fire, so the test
ran, and it reported:

    AssertionError: the contract's shape went unvalidated and nothing said so
      [FAIL] PPA-C-010: the document violates contract.v1 at <document root>:
             'resolutions' is a required property
      [FAIL] PPA-C-010: the document violates contract.v1 at <document root>:
             'run_manifest' is a required property
      ...

The shape HAD been validated — by the bundled engine — and three violations were
printed directly above an assertion claiming nobody looked.

`_ppa_jsonschema` is RIGHT to ask about the reference library, and says so in its
own docstring: the tests it guards call `Draft202012Validator` themselves as an
independent cross-check, and handing them the bundled engine would make that
cross-check the plugin agreeing with itself. But this test calls nothing itself,
so its predicate was one layer off the thing it asserts about. It now asks
`resolve()` — the program's own question — and where the branch is unreachable it
says so through `not_verified_reason` with a remedy, so it lands in the
not-verified roll-up as an unanswered question instead of a quiet green tick.

**A guard asserting a defect that is not there is the same disease as a gate
missing one that is, and it is the harder of the two to unpick, because the red
looks like work to do.**

## Eight missing table entries, in two sweeps that refuse to be incomplete

`test_no_ppa_program_lets_a_traceback_reach_the_exit_code` and
`test_vacuous_input_is_undetermined_not_pass` each `pytest.fail` for a program
their table does not name — *"its traceback arm is untested"*, *"its vacuous arm
is untested"*. That is those files holding themselves to the rule they hold the
programs to, and four programs had no entry in either.

All eight were MEASURED before being listed. No traceback anywhere; exit codes
3/3/1/3 on junk input and 2/2/2/3 on vacuous input. The first two take a
POSITIONAL document (`manifest`, `situation`), and pointing `--policy` at the
absent file instead is a BAD INVOCATION rather than a vacuous one — a distinction
that produced three misleading rc 3s in the first probe of this part, and which
the table now records.

`test_vacuous_refusal_is_marked` skipped those same four for want of an entry.
Three now reach its assertion and pass; the fourth skips only because the rc arm
already reports it. That file went `4 failed, 91 passed, 4 skipped` to
`99 passed, 1 skipped`.

## A CROSS-PROGRAM DISAGREEMENT ABOUT §1, declared rather than settled or buried

Handed a path argument that does not resolve, two PPA programs answer
differently, and each has a stated rationale:

    ppa_pr_scope_check    `--changed-file not found`        -> rc 2
    ppa_signoff_records   `run` is not a directory          -> rc 3

and `ppa_signoff_records`' own test argues its choice: *"3 and not 2: a path that
is not there is the caller's error, and a 2 would be indistinguishable from 'I
looked and could not tell'."* Its docstring declares the same.

Both readings are defensible and `PPA_INTERFACES.md` §1 does not adjudicate
between them. There were three ways to make the sweep green and two of them were
dishonest: "fix" one program to match a rule its own test argues against, or
quietly drop it from the table. `_VACUOUS_RC` records the disagreement instead —
a DECLARATION, not an exemption. `returncode != 0` stays unconditional, so
nothing there can buy a vacuous pass; only the choice between 2 and 3 is
declarable, and `test_the_vacuous_rc_declaration_can_never_buy_a_pass` refuses 0
and 1 outright.

**This is a question for the contract's owner, not for this branch.** It is
written down so it is answerable, not answered.

## What is genuinely left, characterised properly this time

    targeted selection, 28 files:  31 failed -> 22 failed, 816 passed
    new failures: NONE

The remaining **22** are one cause — a test reaching for a program internal that
a refactor renamed — but Part 12's "no shared fix" undersold WHY, and the real
reason is the thing worth recording:

    PI.corpus_candidates(corpus, baseline)    gone
    CC.corpus_contracts(corpus)               gone
    FC.corpus_candidate_sets(corpus)          gone
    CC/PI._CONTRACT_SCHEMA, FC._CANDIDATES_SCHEMA   gone

These are not renames with a one-line forwarding address. The PROPERTIES those
helpers carried moved to a different level. `corpus_candidates(corpus, baseline)`
existed so that

    test_the_baseline_is_never_paired_with_itself
        assert PI.corpus_candidates(tmp_path, base) == []

could hold the program to it. Self-exclusion now lives in `check_corpus`'s
problem-grouping, and it demonstrably still holds — 21 contracts in one group
produce 210 pairs, which is exactly 21x20/2, so no contract is paired with
itself. Selection likewise moved from a schema constant to a SHAPE predicate
(`is_candidate_set`), which is why `_CANDIDATES_SCHEMA` has no successor at all.

So a shim restoring the old signatures inside the test file would make those
tests VACUOUS — the exclusion would be performed by the test and then asserted by
the test, with the program no longer in the loop. That is the defect this entire
report is about, manufactured deliberately to turn a red green.

**Repairing them honestly means re-expressing each property at the level it now
lives** — assert the pair COUNT and that no pair has both sides equal, rather
than asserting a helper's return value. That is better than what was there, and
it is a rewrite with its own reasoning per assertion, not a sweep. It is left
undone and described, with the exact list above, so the next person starts from
the diagnosis rather than from the AttributeError.

## No program changed in this part, and no verdict

Every repair here is in a test file. The eleven wired rows are exactly as Part 14
lists them.

---

# Part 18 — the guard family is green, and what being dark had cost

Part 17 left 22 tests red and described the repair rather than doing it. Done
now. The targeted PPA selection, which was **32 failed / 603 passed** on the
pristine `a758f4adc`, is **840 passed, 0 failed**.

    a758f4adc      32 failed, 603 passed, 104 skipped, 4 xfailed
    this branch     0 failed, 840 passed, 102 skipped, 4 xfailed
    new failures    NONE, at every step

## WHAT BEING DARK HAD COST: a wired gate crashing into an rc 1

`test_an_internal_error_is_rc_3_and_never_rc_1` had been red on
`AttributeError: module has no attribute '_CONTRACT_SCHEMA'`. While it was red,
the guard it pins **was not in the program**:

    two contracts that GROUP on a well-formed `problem` identity, whose
    `analysis` is a bare digest STRING instead of a record
      -> AttributeError out of `identity.compare`
      -> traceback escapes `check_corpus`
      -> the interpreter exits 1

and 1 is the code §1 reserves for *"these two runs were not solving the same
problem"* — a verdict nothing reached. In corpus mode ONE such document decides
a row over a whole campaign, and the wired rows sweep 21 and 61 contracts.

**Part 7 of this report states that this program "now carries the same one".**
On this tree it did not. Two things had to be true at once for that to survive:
a claim in the audit, and the test that would have contradicted it failing for
an unrelated reason. That is the shape worth remembering — not the missing
`try`, but that a dark guard let a false claim stand in a document whose whole
purpose is measurement.

Repaired per pair (rc 2, naming both contracts, the exception, and the missing
input) and at the top level (rc 3, matching `ppa_contract_check`). Negative
controls: with the per-pair guard removed the row exits 3 and one bad pair
decides it; with both removed, the traceback.

## THREE FILES, THREE DIFFERENT REPAIRS, and the difference is the point

Part 17 said a shim would make these tests vacuous. That was true of ONE of the
three, and treating all three the same would have been wrong in both directions.

**`test_issue1241_problem_integrity_takes_a_corpus.py` — REWRITTEN.** `--corpus`
mode was rebuilt: it no longer takes a baseline and pairs everything against it,
it GROUPS by problem identity and pairs inside each group. `corpus_candidates(
corpus, baseline)` did not move, it stopped existing, and a shim restoring its
signature would have put the baseline-exclusion inside the test and then
asserted it there, with the program out of the loop. Every property is now
asserted where it lives, and every number was MEASURED before it was asserted:

    comparable pair                      rc 0, 1 pair    <- THE POSITIVE CONTROL
    one contract alone                   rc 2, 0 pairs   <- never self-paired
    three comparable                     rc 0, 3 pairs   = C(3,2)
    toolchain differs                    rc 1, PPA-C-012
    comparable + an unreadable document  rc 2
    REFUSED pair + an unreadable one     rc 1            <- never softened
    a contract under another filename    rc 0, 1 pair    <- by declaration

The positive control is the load-bearing one: a file of refusal tests alone is
satisfied by a gate that refuses everything.

The fixture also had to hash to its own digest — `PPA-C-001` refuses a contract
whose `contract_digest` does not match its content, so a fixture omitting it is
refused for THAT, and every test built on it asserts a refusal it did not mean
to cause. Three wrong probes were spent before that surfaced.

**`..._corpus_walks_cannot_be_extended_by_a_symlink.py` — ADAPTED, legitimately.**
Here the thing under test IS the walk, and the walk is still program code:
`collect` is the shared seam and the predicate is the gate's own. Nothing moves
into the test. Three of its four rows had been raising AttributeError, so the
symlink property — that `**` does not recurse into a symlinked directory, which
is what keeps a corpus from being silently extended to documents elsewhere — was
being held for ONE walk instead of four.

**`..._ppa_record_gates_take_a_corpus.py` — ADAPTED, plus two corrections.**

  * `CC.main([]) == 2` was stale and is now 3. §1 separates them deliberately:
    2 is "I could not look", 3 is "you invoked me wrong". Collapsing them is
    exactly how a stale flag in the wiring reads as a row that ran — which is
    not hypothetical, it is Part 12's `PPA arms solved one problem` finding.
  * "an unreadable document stays in the corpus" is now asserted on
    `scan.unreadable` rather than `scan.records`. A document that cannot be
    parsed cannot be SELECTED — there is nothing to run a predicate on — and
    `collect` splits the two deliberately. The load-bearing half is unchanged:
    the verdict is 2 and the file is NAMED, never dropped to a silent pass. The
    test additionally pins that the denominator says "unreadable", so the
    population cannot be silently mis-sized.

## The eleven wired rows, re-verified after the program change

    rc=2  PPA head-to-head records                      published corpus, other repo
    rc=1  PPA head-to-head records (cross-layer)        15 records, 1 refused, NAMED
    rc=2  PPA head-to-head records (end-to-end)          2 records, both NAMED
    rc=0  PPA measurement contract (cross-layer)        21 contracts
    rc=0  PPA measurement contract (end-to-end)         61 contracts
    rc=2  PPA measurement contract                      published corpus, other repo
    rc=1  PPA measurement coverage                      54 of 148 records REFUSED
    rc=2  PPA promotion feasibility (cross-layer)       21 sets, artefacts NAMED
    rc=2  PPA frontier recomputes                       both artefacts NAMED
    rc=0  PPA arms solved one problem (cross-layer)      210 pair(s)
    rc=0  PPA arms solved one problem (end-to-end)      1830 pair(s)

Unchanged from Part 14. Chip-agnostic guard PASS over 1553 files.

---

# Part 19 — the whole suite, both trees; and Part 14 said something false

Every measurement in Parts 12–18 was a gate run BY HAND, one row at a time, plus
targeted pytest. The suite those rows live in was never run. That is the gap this
part closes, and closing it overturned a claim.

Both runs: separate worktrees, `git clean -xdfq`, `PYTHONDONTWRITEBYTECODE=1`,
nothing else touching either tree.

|  | `a758f4adc` | this branch |
|---|---|---|
| gates declared | 93 | 93 |
| decided | 83 | **84** |
| passed | 76 | **78** |
| failed | 7 | **6** |
| NOT CHECKED | 10 | **9** |
| seconds | 436 | 543 |

    failures on this branch and not the base:
      PPA measurement coverage
    failures on the base and not this branch:
      PPA arms solved one problem (cross-layer campaign)
      PPA arms solved one problem (end-to-end campaign)

**One red added, two removed, and both directions are earned.** The added one
reports 54 record findings the gate had already computed and discarded. The two
removed now compare 210 and 1830 real pairs where they previously compared none.

The four reds present in both — `evidence citation resolves`, `gates are
host-independent`, `L-doc field producer`, `liar census controls still fire` —
are untouched by this branch, and three of them carry rows in
`gate_red_since.json`. So does `PPA head-to-head records (cross-layer
campaign)`, which is still red and still refusing `h2h_F`, exactly as the brief
required.

## PART 14 SAID SOMETHING FALSE, AND THIS IS THE CORRECTION

Part 14 argued the two `PPA arms solved one problem` rows had been failing
invisibly:

> **rc 3 is quieter than rc 2 and that is why it survived.** ... nothing in the
> roll-up distinguishes it from a row that ran

**That is wrong.** Measured on the pristine base, the dispatcher rendered them:

    ── PPA arms solved one problem (cross-layer campaign)
    [ppa_problem_integrity_check] REFUSE (bad invocation): --baseline/--candidate
    and --corpus were both given. ... Give exactly one. rc=3.
       ^^ FAILED: PPA arms solved one problem (cross-layer campaign) [0s]

`^^ FAILED:`, with the program's refusal printed directly above it. Both rows
were LOUD, they were counted in the failure total, and anyone reading the
roll-up would have seen them. What was true is narrower and still worth fixing:
they were red, they had stayed red, and while red they examined zero pairs. What
was NOT true is that the roll-up hid them.

The claim was reasoned from `run_tolerating_uncheckable`'s name — it tolerates
rc 2, so rc 3 must fall through to something quieter — instead of from a run.
Part 14's paragraph is left standing and superseded here, per this report's
header rule. It is a good example of the failure this whole document is about
pointing at its own author: **an assertion about what a reader would see, made
without being a reader.**

## What that changes about the fix, and what it does not

Nothing about the repair. `--corpus` mode was rewritten to need no baseline, the
wiring still passed one, and the rows decided nothing — that was true before this
part and is true after it. Only the argument for urgency was overstated, and
overstated in the direction that flatters the person making it.

## The NOT CHECKED count, and what is behind it

Ten before, nine after, and the one that moved is `PPA measurement coverage` —
from NOT_CHECKED to FAILED, because it now reports findings instead of being
silent about them. The nine that remain:

    blocker list contract on committed reports   empty population, other repo
    engineering evidence fresh                   artefact + producer NAMED
    input-doc claims vs installed PDK            non-empty corpus, no decidable claim
    PPA head-to-head records                     published corpus, other repo
    PPA measurement contract                     published corpus, other repo
    PPA head-to-head records (end-to-end)        2 records, both NAMED
    PPA promotion feasibility (cross-layer)      21 sets, artefacts NAMED
    PPA frontier recomputes                      both artefacts NAMED

Eight rows, every one of which now says what it is missing. That is the whole
point of the branch, measured in the suite rather than row by row.

---

# Part 20 — `h2h_F` re-filed as what it is, under a kind proposed for it

Parts 1 and 12 named the finding and fixed the two producers so the document
could not be written again. The record itself was left refused, deliberately.
This part does the other half.

## The kind did not exist, and that was the finding

Fourteen schemas ship under `schemas/ppa/` and **not one declares a
within-project ranking**. That absence is why the ablation was filed as
`vibeic.ppa.comparison.v2` in the first place — it was the only shape available
that could hold two arms and three metrics — and why
`ppa_head_to_head_check` refused it `BASELINE_TUNED_BY_US` for two months.

`vibeic.ppa.ablation.v1` is that missing kind, and it is **proposed, not
assumed**. The argument is here and in the schema's own description; if the
reviewer prefers a different shape, the RECORD is what matters and it re-files
again. What must not happen is a third option: leaving a real measurement filed
under a claim it cannot support because no better box exists.

## What makes it worth having: exclusivity in BOTH directions

    comparison.v2   a `baseline` arm MUST declare tuned_by_this_project: false
    ablation.v1     EVERY arm MUST declare tuned_by_this_project: true

A document cannot satisfy both, so a mis-filing is refusable by SHAPE from
either side rather than only by a checker that happens to read it.

The second clause is the load-bearing one, and it is there to close a hole this
schema would otherwise have dug. An arm this project did not tune is an
OPPONENT, and a document holding one is a head-to-head that must face the
fairness conditions. Without `const: true`, re-filing a real head-to-head as an
ablation would be a way out of them — **a hiding place built by the very fix
that closed the mis-filing**.
`test_a_REAL_head_to_head_cannot_HIDE_here` pins it.

## Nothing was deleted, weakened or edited

The arms are asserted byte-identical to the refused document before anything
else is claimed about them:

    area_um2      6136.0   vs   6040.0
    power_mw       0.559   vs    0.540
    timing_wns_ns    0.0   vs      0.0
    both arms      tuned_by_this_project = true

The record carries its `provenance` — former path, former schema, the refusal
code — and the checker's own refusal report is KEPT beside it as
`ablation_pnr_only_vs_crosslayer.refusal_that_caused_it.json`. **A re-filing
whose causing refusal has been deleted is indistinguishable from a record that
was always this kind.**

The ablation is also the informative half of this campaign that the twelve
passing head-to-heads cannot show: they measure the cross-layer winner against
`vibe-ic-phase3-defaults`, and only this document isolates what the cross-layer
search adds over a place-and-route-only search. Losing it to make a gate green
would have been the worse trade by a distance.

## The gate is untouched, and the corpus is what changed

No assertion relaxed, no exemption added, no date moved. Selection is by
DECLARED SCHEMA, so re-filing is what removes the document from the corpus —
not a rename, not a move.

    before   15 record(s), 1 refused, 2 undetermined, 12 accepted  -> rc 1
    after    14 record(s), 0 refused, 2 undetermined, 12 accepted  -> rc 2

## IT IS rc 2 AND NOT rc 0, AND THE 0 IS NOT AVAILABLE HONESTLY

The two remaining undecidables are the pre-existing unrecorded-field defect Part
4 has described from the start, and **neither field exists anywhere in this
repository to copy**:

    h2h_A  SCOPE_SENTINEL     `timing_wns_ns.rc_corner` is null at process=ss
           MEASURED: 1213 `ss` timing scopes in this tree carry an `rc_corner`
           key and ZERO of them state a value.
           >> BOTH FIGURES ARE WRONG. Re-measured over `scope` dicts only, it is
           >> 2641 stating none and ONE stating `max`. See Part 21.

    h2h_B  SCOPE_INCOMPLETE   `power_mw` scope declares no `mode` at stage=synth
           MEASURED: 546 power scopes in the campaign's own record set and NOT
           ONE carries a `mode`.
           >> THIS CLAIM IS BACKWARDS. 2286 power scopes DO carry `mode`, 1730
           >> of them at `stage=synth`. The real obstruction is that the
           >> PRODUCER could not emit the key and the cited run tree is not in
           >> this repository. See Part 21.

Making the row green would mean writing two fields no artefact states — an
invented measurement, which is the unearned pass this whole document refuses.
The honest verdict for *"the slow-corner RC parasitic corner was never
recorded"* is NOT_CHECKED, and it stays NOT_CHECKED until a producer records it.
That repair is `_ppa/timing.py` emitting the corner it extracted at, exactly as
the `tt` path already does, followed by a re-run — lane-owned work, not a
re-labelling.

## The ledger row, and a gap in the rule that governs it

`gate_red_since.json` acknowledged this gate as red. It no longer is, so the row
is deleted — the file's own instruction is *"delete the row in the SAME commit
that fixes the gate"*, and deleting an acknowledgement REMOVES a deadline rather
than granting anything. The row's own `why` had already named this exit: the red
*"closes when that record is either relabelled as a within-project comparison or
re-measured against an untuned baseline"*.

**`gate_red_since_check`'s `stale` finding would not have caught it** — that
fires only when the acknowledged gate PASSES, and this one became NOT_CHECKED.
Recorded rather than fixed; the rule belongs to the ledger's owner.

**But the row was not merely obsolete — it had EXPIRED, and that makes the
deletion a necessity rather than tidiness.** Measured by running the checker
over the same dispatch record with each ledger:

    base ledger    9 finding(s), rc 1
    this branch    8 finding(s), rc 1

    the one that differs:
      [expired] PPA head-to-head records (cross-layer campaign): red since
      a00f53f20948 — 217 commit(s) ago, and the bound this row set for itself
      was 200. vibe-ic#1241 owns it

So the acknowledgement had already come due. Leaving it would have been a hard
`[expired]` failure on a red that no longer exists, and the row's own `why` had
named this exact exit: the red *"closes when that record is either relabelled as
a within-project comparison or re-measured against an untuned baseline"*. The
first of those is what Part 20 did.

The other **eight** findings are pre-existing and none is this branch's: four
`stale` rows whose gates already passed on `a758f4adc`, and expiries including
`liar census controls still fire`, 286 commits past a bound of 35. The checker
was failing on the base tree and fails on this one for the same reasons, one
row fewer. It is not wired into `repo_hygiene_gates.sh` — it runs in the landing
gate against a `--summary-json` dispatch record — which is why it took a
deliberate run to see any of this.

## One clause of the declaration corrected, and the date untouched

The `uncheckable_until` text ended *"and this corpus produces one today"*,
naming `h2h_F`. That is now false. The date is unchanged, no leniency changed,
and no exemption was added — only a sentence of fact. Leaving a false sentence
in a landing record is the disease this branch is about.

## A defect in this branch's own guard, surfaced by the row changing

With the cross-layer row at rc 2 instead of 1, the naming rule in
`test_rc2_over_a_nonempty_population_names_the_artefact.py` began demanding that
the **twelve PASSING** head-to-heads say what was "missing" from them. Nothing
is. An rc-2 corpus verdict is a roll-up of many per-subject verdicts, and a
subject that PASSED owes no referent; forcing a gate to invent an absence for a
record it accepted is the mirror image of the defect that file exists to catch.

Fixed, pinned in both directions, and negative controls A and B were re-proved
after the loosening — 4 and 2 failures — so the skip is not a hole.

## Negative control: the refusal, disabled surgically

One condition flipped, no structure touched:

    2 failed   test_a_baseline_this_project_tuned_is_refused
               test_a_tuned_baseline_is_refused_even_when_we_would_have_won

    E   AssertionError: assert 0 == 1
    E    +  where 1 = C.RC_REFUSED

    6 failed across the two files.

The record that was refused now passes. And the SCHEMA clause is an independent
guard: the ablation tests still pass under that mutation, because they validate
shape rather than program behaviour, so removing one does not silence the other.

## Regression

    targeted selection, 31 files:  913 passed, 0 failed
    chip-agnostic guard            PASS, 1553 files
    PROGRAM_INVENTORY.json and the four stated counts in the two READMEs
    re-derived for the added test file.

# Part 21 — the rc-0 verdict re-measured, and two of Part 20's numbers were wrong

Part 20 concluded that rc 0 is not honestly available for the cross-layer row.
That conclusion SURVIVES. The two measurements it rested on do not, and the
correction matters because one of them was not merely miscounted — it was
backwards.

## What Part 20 claimed, and what the tree actually says

Both counts below are over dicts that are the value of a key literally named
`scope`, which is the only thing `check_scope_parity` reads. Part 20's numbers
counted `gaps` and `provenance` dicts too — those carry an `rc_corner` key as
the NAME OF A GAP, not as a measurement condition, and folding them in is what
produced the wrong totals.

    CLAIMED  "1213 `ss` timing scopes carry an `rc_corner` key and ZERO state a value"
    MEASURED  2641 state none and ONE states `max`. The count was wrong and
              "zero" was wrong. The substance survives: the `ss` path records
              the RC corner essentially never, and h2h_A is not the exception.

    CLAIMED  "546 power scopes in the campaign's own record set and NOT ONE carries a `mode`"
    MEASURED  2286 power scopes DO carry `mode: functional`; 1012 do not.
              Restricted to `stage=synth`, where h2h_B's number was taken,
              1730 carry a mode and 1012 do not. THE CLAIM IS BACKWARDS: the
              majority of synth-stage power scopes state the very field Part 20
              said none of them state.

Part 20 used those two numbers to argue that green "would mean writing two
fields no artefact states". For `mode` that argument does not hold, and it
should not have been made.

## The real reason h2h_B cannot be repaired here, which is narrower

Not "no artefact states a mode". The correct statement is two facts:

  1. THE PRODUCER COULD NOT EMIT IT. `_ppa/power.metric_records` built its
     `base_scope` from five literals plus three keys resolved off the liberty
     stem, and NO branch of it could set `mode`. The only way in was
     `extra_scope`, and a census of the tree finds its three call sites are ALL
     in tests. So every power record that module has ever written was one
     required key short BY CONSTRUCTION — refused by `ppa_head_to_head_check`
     for a field its own producer had no way to fill. The module's docstring
     had already diagnosed this class for the other three keys ("this module
     emitted four of the six"), fixed those three, and left `mode`.

  2. THE RUN TREE IS NOT HERE. h2h_A and h2h_B cite `/home/reyerchu/_jxlayer/
     run/trials/...`, which this repository does not carry. Even with the
     producer repaired, those two records cannot be REGENERATED here.

So the row stays rc 2, and the deliverable is the producer repair plus this
correction — not a green row.

## The producer repair

`_ppa/power.py` gains `_mode_for(project)`, a verbatim mirror of
`_ppa/timing.py._mode_for`: the mode comes from the run's own
`pvt_matrix.json`, and only when exactly one mode is declared. A mirror rather
than a cleverer rule on purpose — `REQUIRED_SCOPE` names `mode` on BOTH axes and
`check_scope_parity` compares them key by key, so two modules resolving it
differently would make the two axes of one run disagree about that run.

The discipline the module already states is kept exactly: only what was resolved
is emitted, a mode nothing declares is left OUT rather than nulled, and the
reason is recorded in `provenance.mode_gap`. Nulling it would have satisfied the
consumer's PRESENCE check and then compared EQUAL to another arm's null — the
`SCOPE_SENTINEL` hole, reopened by the repair that closes `SCOPE_INCOMPLETE`.

`power_total_vs_budget_check` is the one production caller and now passes
`project`.

WHAT THIS DOES NOT DO: it does not turn any row green, and it changes no shipped
record. The corpus is static JSON; both campaign rows read rc 2 before and after.

## Negative control

    if False:  # NEGATIVE CONTROL: the mode resolution reverted
        base_scope["mode"] = mode

    FAILED tests/test_ppa_producer_consumer_agreement.py::
           test_the_power_producer_CAN_satisfy_every_key_its_consumer_requires
    E  AssertionError: the power producer cannot emit these keys its own
       consumer requires, so every record it writes is SCOPE_INCOMPLETE by
       construction: ['mode']
    E  assert not ['mode']

## The BASELINE_TUNED_BY_US refusal, re-proved on this tree

    if False:  # NEGATIVE CONTROL: refusal removed

    FAILED tests/test_issue1121_ppa_head_to_head.py::test_a_baseline_this_project_tuned_is_refused
    FAILED tests/test_issue1121_ppa_head_to_head.py::test_a_tuned_baseline_is_refused_even_when_we_would_have_won
    FAILED tests/test_issue1121_ppa_head_to_head.py::test_cli_returns_the_same_code_as_evaluate
    FAILED tests/test_issue1121_ppa_head_to_head.py::test_the_pointer_actually_aims_the_gate
    FAILED tests/test_issue1121_ppa_head_to_head.py::test_adding_an_undetermined_record_cannot_subtract_a_refusal
    FAILED tests/test_issue1121_ppa_head_to_head.py::test_corpus_severity_order_is_refused_then_undetermined_then_ok
    6 failed, 155 passed

    E  AssertionError: assert 0 == 1
    E   +  where 1 = C.RC_REFUSED

NOTE FOR THE READER: `test_ablation_is_not_a_head_to_head.py` — the file the
re-filing shipped — passes with the refusal removed, all 17 of them. It pins the
two document kinds apart; it does not pin the refusal. The red lives in
`test_issue1121`, and anyone checking that claim by running the ablation file
alone would get a false all-clear.
