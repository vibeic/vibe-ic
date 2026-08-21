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
    ppa-crosslayer/equivalence/equiv_*.json       12 proven-equivalence records

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

### The finding: the equivalence proofs exist and the adjudicator cannot see them

`ppa-crosslayer/equivalence/` holds 12 committed equivalence records
(`equiv_csa_add1.json`, `equiv_nr_rca.json`, …) and the v1.11.66 commit states that
every RTL behind every published number is proven equivalent to the baseline. The
`equivalence` axis is nevertheless `FEAS_NOT_MEASURED`, because no
`vibeic.ppa.metric.v1` row in any `candidates.json` names that axis. The proof was
run and is not wired into the record. That gap is real and it is a gap in the
*record*, not in the design — which is why the gate says UNDETERMINED and not PASS.

`em` has no producer at all: no electromigration analysis ran in either campaign.

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
