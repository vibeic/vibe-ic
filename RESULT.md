# RESULT — the feasibility gate can answer

**Branch** `agent/jppafeas-feasibility-producers`
**Base** `origin/main` @ `e36d81c0a` — *v1.11.33*, cut fresh, worktree clean at cut.
**Commit** `925ecd555` — 16 files, +2492 / −49.

> **Note on the base.** The brief said `v1.11.19..v1.11.47` landed this morning.
> `git fetch origin main` (twice, verified against `git ls-remote`) puts
> `origin/main` at `e36d81c0a`, **v1.11.33**. I cut from what the remote actually
> points at and re-fetched before pushing. If v1.11.47 exists somewhere I could
> not see it, this branch needs a rebase and the A/B below needs re-measuring —
> an A/B is only as current as its base.

---

## The headline, as one measurement

Same candidate document, same records, two gates:

```
$ python3 ppa_feasibility_check.py --candidates cand_full.json
BASE  rc=2   baseline: UNDETERMINED
             setup:FEAS_METRIC_ABSENT  hold:FEAS_METRIC_ABSENT  drv:FEAS_METRIC_ABSENT
             drc/lvs/antenna/ir/em/equivalence: FEAS_VIEWS_NOT_DECLARED, FEAS_METRIC_ABSENT

MINE  rc=0   baseline: FEASIBLE
```

A candidate can now be FEASIBLE, so the head-to-head's "both arms feasible"
condition can hold, so a PPA comparison can be defended.

**The timing records in that document are what `_ppa/timing.py` emits TODAY**
(`worst_slack`, no `wns`) — this is reachable on run trees that already exist,
not only on runs made after the emitter fix.

**And the base cannot reach it under any view declaration.** I gave it its best
shot, twice:

| candidate document | BASE | MINE |
|---|---|---|
| `required_views_by_axis` per axis | rc=2 UNDETERMINED | **rc=0 FEASIBLE** |
| one global `required_views` = the two timing corners | rc=2 | rc=2 |
| one global `required_views` = `{stage}` only | rc=2 | rc=2 |

The last two rows matter as much as the first. **Per-axis views are load-bearing,
and nothing here made UNDETERMINED disappear by widening what counts as
satisfied** — under a global view declaration my gate still refuses, exactly as
the base does.

---

## Per item

### F-3 / R3 — seven axes had no producer

**New:** `_ppa/signoff.py` (library) + `ppa_signoff_records.py` (CLI, rc 0/2/3).

It reads the run's own sign-off artefacts and emits `vibeic.ppa.metric.v1`
records with real provenance (path + sha256 + parser + parser sha256). **Six of
the seven now have a producer.** DRV does not — see "what I could not settle".

| metric | artefact it is read from |
|---|---|
| `physical.drc.violations` | `reports/phase3/drc_signoff.json` + `reports/phase3/drc_vacuous.json` |
| `physical.lvs.verdict` | `reports/phase3/lvs_verdict.json` |
| `physical.antenna.violations` | `reports/phase3/antenna.json` |
| `power.ir.violations`, `power.ir.worst_drop_v` | `reports/phase3/ir_drop.json` |
| `reliability.em.violations`, `reliability.em.worst_ratio` | the current-density screen's report |
| `equivalence.verdict` | `reports/lec.json` |

On a closed run: **6 axes SATISFIED** where the base had `FEAS_METRIC_ABSENT` on
all seven.

**It invents nothing.** Every reader answers one of exactly two ways — the
artefact states the fact, or `NOT_MEASURED` with a reason naming what is missing.
There is no third branch. Measured refusals, each one a shipped test:

* **DRC** applies the three-way discriminator from
  `fixtures/ppa/drc/zero_three_ways/expected.json` — as *that decision table*,
  driven in the tests by the fixture's own `expected.json` rather than by numbers
  I wrote. The report carries two of the three facts; the third (did the deck run
  over geometry) is not in the report and never can be, so it comes from
  `drc_vacuous_pass_check`'s artefact. A run with no vacuity artefact is
  NOT_MEASURED, not a clean.
* **Antenna** over an incompletely routed design → NOT_MEASURED. Null counts are
  not read as zero.
* **IR** with no declared `budget_pct_vdd` → no violation count exists (there is
  no line to be over). The drop itself is still MEASURED, for the axis's
  contract-limit proof.
* **Equivalence** proving RTL against a netlist that names no post-layout netlist
  → NOT_MEASURED with the gate netlist quoted. A *failed* LEC is MEASURED, not
  NOT_MEASURED: reporting a real finding as "could not check" hides it.
* **LVS** verdicts are reported verbatim. `INCOMPLETE` and `WARN` are not mapped
  to failures — they are verdicts the axis does not accept, which is a different
  sentence and a different fix.

**Corner-independent facts are emitted ONCE.** The reference bridge had to emit
each physical fact once per required timing view — N records carrying one source
hash, into an index whose entire job is to notice when two numbers claim to be
the same fact — purely because `required_views` was global. F-11 removed the
need; a test asserts the duplication does not come back.

**`scope.stage`** is required by `_ppa/metrics.py` and no artefact states one. It
is not guessed: each source declares its stage together with a `stage_basis`
sentence naming the input that makes it that stage, and both travel into the
record's `provenance`. A reader can check the claim instead of discovering later
that it was a guess.

### F-17 — the EM report supports no violation count

The finding is right about `reports/phase3/em.json`: segment count and peak
current, **no violation count and no declared limit**. But the fact is not
missing from the flow — **`em_current_density_check.py` already computes it**,
screening every segment against the PDK's Jmax and listing offenders. Its
`offender_count` is `reliability.em.violations`, and its `summary.worst_utilization`
(J/Jmax) is *exactly* `reliability.em.worst_ratio`, unit `1`.

So the honest answer is better than "the artefact does not carry the fact": the
artefact that carries it is a different one, and it ships. `em.json` **alone**
still yields NOT_MEASURED, and the screen's own `SKIPPED` verdict (report
present, Jmax present, nothing mapped) is carried through as NOT_MEASURED with
the screen's message — never as a clean.

### F-8 / R9 — power records cannot satisfy their own REQUIRED_SCOPE

`_ppa/power.py` now fills `process`, `voltage_v` and `temperature_c` from
`opensta.parse_liberty_pvt(report["liberty"])` — the parser the same lane already
ships, against the file name the record already carries.

**The half that matters is what it must not do.** `check_scope_parity` tests
required keys for *presence*, so `process: None` would satisfy the key check and
then compare equal to another `None` — two records that say nothing about their
corner, passing as the same corner. Worse than the refusal it replaces. So **only
what the parser resolved is emitted**; an unresolvable or *ambiguous* stem leaves
the key out and records the parser's own gap reason in `provenance`. And
`check_scope_parity` now refuses a present-but-null required key outright
(`SCOPE_SENTINEL`).

`mode` is still not emitted — no power artefact states an operating mode. The
refusal is correct and it stays; the caller supplies it through the existing
`extra_scope` hook. See requests to the lander.

### F-11 — `required_views` is global

**The decision, since the brief asked for one rather than a patch:**

**Yes, an unmeasured required view should sink the axis, and that is unchanged.**
A corner nobody ran is a corner nobody ran. What was wrong was not the strictness
— it was that one list was applied to nine axes measured in *different scope
namespaces*. Setup and hold sign off across process corners; DRC, LVS, antenna,
IR, EM and equivalence are single measurements over one database and have no
process corner at all. A contract declaring its timing corners therefore also
demanded them of DRC, leaving DRC permanently uncovered unless its producer
faked N scopes.

So: `FeasibilityPolicy.required_views_by_axis`, falling back to the global
`required_views` for any axis it does not name — a contract written before this
field adjudicates *identically* (tested). There is no spelling that means "any
view will do": an axis named with an **empty** list is UNDETERMINED, exactly as
an undeclared global list is (tested). A key naming no known axis is dropped
rather than silently honoured (tested).

**And the record now SAYS which views were measured**, so a reader can re-decide.
Every `AxisResult` publishes `coverage`, one row per declared view:

| state | meaning | the fix it points at |
|---|---|---|
| `MEASURED` | a record covers the view and the proof was evaluated | — |
| `NOT_MEASURED` | a record covers the view and could not support the metric — **with the artefact's own reason and the source path** | a better artefact |
| `NO_RECORD` | nothing covering this view names the metric | a run |

Those last two used to be one sentence with no view named at all. The coverage is
published on SATISFIED axes too, so questioning the view set does not require
making the axis fail first. `ppa_feasibility_check.py` also publishes
`views_used_by_axis` — what the gate *resolved*, not only what the contract wrote.

### F-15 — no STA artefact prints a hold `wns`

The brief predicted the honest answer and it was right, and it turned out to be
**both** halves.

**The emitter.** `phase3_one_shot_runner.py`'s two multi-corner sign-off stanzas
— the ones that decide setup at the slow corner and hold at the fast one — emit
`report_worst_slack` and `report_tns` and **never `report_wns` at all**. So
`timing.hold.wns_ns` was NOT_MEASURED on every view of every run, for every
design: the hold axis was structurally unprovable, and that is a property of the
flow, not of any chip. Both stanzas now ask, through `_report_wns_tcl(rpt_c, flag)`
(`-max` for setup, `-min` for hold), guarded by `catch` in the runner's own
established idiom so a build that rejects the flag cannot abort a sign-off script
that has already written its setup half. On failure the reason is *written into
the report* and no marker appears, so an absent wns stays visible as a refusal
rather than becoming a silent skip.

`_ppa/timing.py` will not derive the wns from the worst slack, and **it is right
not to** — §3 says hash the value you parsed. I did not touch that.

**The axis.** The emitter fix only helps runs made after it. The tool already
prints the fact under its other name, on every run that exists — so
`timing.{setup,hold}.worst_slack_ns` is admitted as a proof group. This is **not
a relaxation** and I did not take that on trust:

```
wns = min(0, worst_slack)          (_ppa/timing.py's own header;
                                    measured in tests/test_ppa_timing.py, where
                                    one view reports worst slack 0.19 beside wns 0.00)

wns >= 0  <=>  min(0, worst_slack) >= 0  <=>  worst_slack >= 0
```

Same predicate, so it admits no candidate the wns proof would refuse. A test
sweeps both signs and the boundary over both checks and requires the two verdicts
to agree. Three more tests hold the line: a negative worst slack still VIOLATES;
a no-paths view (worst_slack left at INF, which `_ppa/timing.py` already emits as
NOT_MEASURED) is **not** rescued; and a violation in one group is not outvoted by
a satisfied other group.

### F-18 / R12 — `derive_feasibility` requires a count, and LVS is not a count

**I changed the shape rather than encoding "matched" as 0.** A check now states
its result as `violations` (a count), `status` (`CLEAN`/`VIOLATIONS`/`NOT_CHECKED`)
or `verdict` (a literal). The `comparison.v2` schema documents all three, with an
`anyOf` requiring at least one, plus `top_cell` — because a match between two
circuits nobody named is not a fact about this design.

The verdict accept-sets are **sourced from the accept sets `_ppa/feasibility.py`
declares on the matching axis**, so there is one statement in the repository of
what an LVS pass looks like — and a test asserts the two agree rather than
trusting me to keep them in step.

Consequences, each tested:
* `status: CLEAN` everywhere → FEASIBLE (was NOT_CHECKED, on a record valid
  against the shipped schema).
* `lvs: {verdict: MATCH, top_cell: core}` → FEASIBLE, with no count written about
  a verdict.
* `lvs: {verdict: MISMATCH}` → INFEASIBLE, not merely unchecked.
* `status: NOT_CHECKED` **outranks** a leftover count — an explicit "I did not
  check this" must not be resurrected.
* A `verdict` on a check with no verdict spelling (`drc: {verdict: "looks fine"}`)
  → NOT_CHECKED. Free text does not buy a pass.
* **Contradiction:** `status: CLEAN` beside `violations: 3` → INFEASIBLE, and the
  contradiction is named in `contradicting`. The measured count decides, because
  this module's own stance is that an assertion beside its own evidence is where
  a record has room to be dishonest cheaply.
* Every count-shaped record written before this change derives identically.

### F-18, one layer down — the canonical shape could not express a verdict

Found while building F-3, and it was blocking it. `_ppa/metrics.validate()`
hard-required a numeric value, so `physical.lvs.verdict` and
`equivalence.verdict` — **two of the nine axes the gate proves** — were refused
`VALUE_NOT_A_NUMBER` by the very shape the gate reads. That is not a rule about
LVS; it is the record shape and the gate disagreeing about what a metric is.

`is_verdict_metric()` derives it from the name (last segment `verdict`), in the
same style as `metric_domain`, so a new verdict metric needs no edit. A verdict
record is held to everything else — a value is required, the empty string is not
one (two empties compare EQUAL, so two circuits nobody compared would read as
agreeing), and `unit` must be `"verdict"`. What it is exempt from is arithmetic,
and `compare()` returns `NOT_NUMERIC` with **no `delta_b_minus_a` key** rather
than `float()`-ing two strings: a delta of 0 printed for two verdicts reads as
"no regression" on a pair that were never numbers. A *number* declaring
`unit: "verdict"` is refused too.

---

## A/B, by TEST ID

Same 33 files both sides, run **serially** (`-p no:randomly`, no `-n`), on
`e36d81c0a` vs `925ecd555`:

```
BASE   6 failed, 774 passed, 11 skipped
MINE   6 failed, 774 passed, 11 skipped      + 89 new tests, all green
diff of the sorted FAILED test-ID lists: EMPTY
```

The 6 reds are **identical test IDs on both sides** and are pre-existing:

```
tests/test_ppa_contract.py::test_a_clean_contract_passes_both_schemas
tests/test_ppa_contract.py::test_a_clean_declaration_builds_and_validates
tests/test_ppa_contract.py::test_a_clean_verdict_discloses_what_it_examined
tests/test_ppa_contract.py::test_the_disclosure_moves_with_the_document
tests/test_ppa_contract.py::test_the_embedded_run_manifest_is_validated_against_its_own_schema
tests/test_ppa_contract.py::test_the_json_report_is_written_when_it_is_asked_for
```

Cause, measured on the pristine base:

```
[UNDETERMINED] PPA-C-010: jsonschema is not importable here, so the contract's
               shape was NOT validated. This is not the schema passing
$ python3 -c "import jsonschema"  ->  ModuleNotFoundError
```

That is the undeclared dependency the e2e lane also recorded. The refusal is
correctly worded; the missing dependency is not mine and I did not paper over it.

**New tests: 89, all green.**

| file | tests | covers |
|---|---|---|
| `test_ppa_signoff_records.py` | 32 | F-3, F-17 — positive / negative / vacuous |
| `test_ppa_feasibility_views_and_slack.py` | 29 | F-11, F-15 |
| `test_ppa_verdict_and_scope_shapes.py` | 28 | F-18, F-8 |

`tests/test_ppa_feasibility_separation.py::test_the_gate_has_no_numeric_margin_of_its_own`
is an **exact** enumeration of `FeasibilityPolicy`'s fields, so adding
`required_views_by_axis` required updating it. I extended the enumeration and the
docstring (arguing why a per-axis view list is a view declaration and not a knob)
rather than loosening the assertion to a filter — the exactness is the guard, and
it still fails on any field added later.

### Positive / negative / VACUOUS for the new checker

```
rc=0  a run that measured something              8 records, 5+ MEASURED
rc=2  an empty run directory                     [CANNOT CHECK] + 8 NOT_MEASURED rows
rc=3  a path that is not a directory / no args
rc=1  NEVER returned — this program reports evidence; the gate makes findings
```

The rc=2 artefact is checked too, not only the exit code: it holds eight
well-formed NOT_MEASURED records. A `--json` file that looked clean beside an
honest exit code is a defect this repository has shipped before.

---

## Mutation arms — 15 of 15

Revert the fix → the named test goes RED → restore → GREEN. Script:
`scratchpad/mutate.py`. Every row verified green-before *and* green-after, so a
test that was already failing cannot be mistaken for a working arm.

| # | reverted | test that goes red |
|---|---|---|
| 1 | DRC: trust the report's bare zero | `test_the_drc_discriminator_is_the_fixture_s_table[ran_on_empty_layout]` |
| 2 | EM: read `em.json`'s `MEASURED` as a clean | `test_the_em_measurement_artefact_alone_supports_no_count` |
| 3 | LEC: accept a proof over any gate netlist | `test_a_pre_layout_lec_proof_is_not_post_route_equivalence` |
| 4 | Antenna: read an unrouted check's zero as a zero | `test_an_antenna_check_over_an_unrouted_design_is_not_a_zero` |
| 5 | Per-axis views: always fall back to the global list | `test_a_corner_independent_axis_no_longer_needs_the_timing_corners` |
| 6 | Coverage: publish no rows | `test_the_coverage_separates_a_view_nobody_ran_from_one_that_could_not_be_read` |
| 7 | Drop the hold `worst_slack` proof group | `test_the_hold_axis_is_provable_from_a_report_that_prints_only_worst_slack` |
| 8 | Emitter: stop asking one stanza for the wns | `test_both_multi_corner_signoff_stanzas_ask_the_tool_for_the_wns` |
| 9 | Deriver: require an integer count on every floor check | `test_status_clean_everywhere_derives_feasible` |
| 10 | Deriver: let an assertion outvote a measured count | `test_a_self_contradicting_check_is_decided_by_the_measured_count` |
| 11 | Record shape: a verdict is not a metric | `test_a_verdict_record_is_a_valid_canonical_record` |
| 12 | Record shape: subtract two verdicts | `test_two_verdicts_are_never_subtracted` |
| 13 | Power: do not fill the PVT | `test_the_pvt_the_liberty_names_reaches_the_scope` |
| 14 | Power: emit the PVT keys as **null** when unresolved | `test_an_unreadable_liberty_stem_leaves_the_keys_OUT_and_says_why` |
| 15 | Parity: accept a present-but-null required scope key | `test_a_present_but_null_required_scope_key_is_refused` |

Arms **14** and **15** are the ones I care most about: they are the arms against
*my own fix* becoming the next defect.

---

## Other gates

* `source_chip_agnostic_check` — **PASS**, 1503 files, NDA panel 4588/4588. No
  foundry name, node, SKU or codename anywhere in the new source or this file.
* `programs/INDEX.md` and `PROGRAM_INVENTORY.json` — **regenerated**, not
  hand-edited. The inventory diff is exactly my additions (+1 top-level, +1
  catalogued, +5 tree `.py`, +3 test files); no other lane's drift absorbed.
  (`gen_program_inventory.py` counts TRACKED files, so it had to run *after* the
  commit — worth knowing.)
* `test_program_inventory_no_drift.py` — back to the base's exact 4 reds; the
  fifth (`test_catalogued_agrees_with_the_shipped_index`) was mine and is fixed.
* `tools/ci/protected_landing_transition.json` — **no protected path touched**,
  verified mechanically against the manifest. Nothing for the lander to re-render.
* No plugin version bump. Nothing pushed to `main`. No `--write-baseline` on any
  gate. No GDS, geometry, pin or rule deck touched — nothing in this branch
  changes what a tool measures, only what is done with what it measured.
* `tools/ci/repo_hygiene_gates.sh` — **identical to base**, A/B'd on a clean
  committed tree:

  ```
  BASE   76 of 86 decided — 67 passed, 9 failed; 10 NOT CHECKED
  MINE   76 of 86 decided — 67 passed, 9 failed; 10 NOT CHECKED
  diff of the sorted "^^ FAILED" gate lists: EMPTY
  ```

  Worth recording how nearly I mis-read this. Run against a **dirty** worktree it
  reported one extra failure (`an argued direction is pinned`) and one extra
  NOT CHECKED (`gates are host-independent`), because both gates create isolated
  workers from `HEAD` and said so:

  ```
  DIRTY_CHECKOUT: host-independence was NOT checked — tracked files are modified,
  so the worktree at HEAD does not carry them and every one would read as a
  difference about the edit rather than about the gate. This is not a pass.
  ```

  Committing first made both go away. Neither was a finding about this change,
  and the gates were explicit about that rather than leaving me to guess.

---

## What I could NOT settle

**1 — DRV has no producer, and the reason is granularity, not absence.**
This is the seventh axis and the one I did not close. The extractor exists and is
shipped: `sta_corner_record_completeness_check.extract_drv(text)` returns
per-kind `max_slew` / `max_capacitance` / `max_fanout` counts *and* a `queried`
flag that distinguishes "the limit was met" from "the tool was never asked" —
which is exactly the distinction the DRV axis needs. **But it is report-scoped,
not view-scoped**: it accumulates counts across every section of a report and
returns one answer per file, while `timing.drv.*` must be matched against a
`required_view`. Two ways forward, and both belong to lanes that own the code:

  * `extract_drv` gains per-section attribution — it already tracks the section
    banner regex, so the state is there; or
  * DRV is emitted at *report* scope with the stage the report's `STA_BASIS`
    stamp declares, and the contract declares `drv: [{stage: …}]`. Per-axis
    required views (F-11) make this reachable now, where it was not before.

I did not write a second STA-report reader in `_ppa/signoff.py` to do it:
`_ppa/timing.py` already owns STA parsing and already derives the per-view scope,
and a second reader is the drift the backend/domain split exists to prevent.

**2 — `mode` is still absent from the power scope.**
Three of the four keys `REQUIRED_SCOPE["power_mw"]` wants now come from the
liberty stem. The fourth is an *operating* mode and no power artefact states one.
`activity.declared_mode` is the activity basis, not an operating mode, and using
it would be exactly the fabricated scope field the module refuses. The refusal
stands and the caller must supply it.

**3 — I could not verify `report_wns -min` against a real OpenSTA build.**
The evidence that it is accepted is strong and in-repo (`tests/test_ppa_timing.py`
carries a real report body containing `wns min 0.00`, so the tool does emit the
min-side label), but I did not run the pinned image to confirm the *flag* spelling
on the build the flow uses. That is precisely why the emitter change is wrapped
in `catch` with a written `SIGNOFF_WNS_UNAVAILABLE reason=$_wnserr` line: if the
flag is wrong, the sign-off script still completes and the report says so out
loud. It would still be worth one real run to confirm.

**4 — the six pre-existing `test_ppa_contract.py` reds** are the undeclared
`jsonschema`. Not mine, not fixed here, reported above with the measurement.

**5 — the `EM_SCREEN_RELS` path list is a convention, not a contract.**
`em_current_density_check.py` writes wherever `--json` points, and no flow step
pins that path. I look under three names and the record states which one it
found; if the flow never runs the screen, EM is NOT_MEASURED, which is honest but
means the axis is only as reachable as the step that is not yet wired.

---

## REQUESTS TO THE LANDER

**R-A — wire `ppa_signoff_records.py` into the flow, and pin the EM screen's
output path.** The producer is shipped and tested but nothing calls it. Two
steps: run it after sign-off to emit the bundle, and give
`em_current_density_check.py --json` a fixed destination
(`reports/phase3/em_current_density.json` is the first name I look under). Until
the screen runs, `reliability.em.violations` is NOT_MEASURED — correctly, and
uselessly.

**R-B — contracts must declare `required_views_by_axis`.** The A/B above shows
this is load-bearing: with only a global `required_views`, my gate refuses
exactly as the base does. `ppa_contract_build.py` should emit a per-axis block,
and the stages my producer declares (`signed_off_gds` for DRC,
`post_route_extracted` for LVS, `post_route` for antenna/IR/EM/equivalence) are
in `_ppa/signoff.SOURCES` with the basis for each.

**R-C — DRV, per item 1 above.** Either `extract_drv` gains per-section
attribution, or DRV is emitted at report scope. This is the last of the seven and
the only one still `FEAS_METRIC_ABSENT` on a closed run.

**R-D — declare or bundle `jsonschema`.** Six shipped tests are red on a stock
`python3`, and every contract a downloaded plugin builds gets rc=2. Also on the
e2e lane's list (their #11); repeating it because it cost me a base A/B to
diagnose.

**R-E — `power.py` needs an operating `mode` from somewhere.** Per item 2. Either
the flow declares one (`pvt_matrix.json` when it names exactly one) and the
caller passes it through the existing `extra_scope` hook, or `REQUIRED_SCOPE`
should say why power needs a mode that nothing produces.

**R-F — the STA_BASIS stamps (the e2e lane's request #1) are still the highest-
value unfixed thing in this area, and they are not mine.** I fixed the missing
`report_wns`; the missing `STA_BASIS` stamp on the same two multi-corner emitters
is a separate three-line change and it is what makes 48 of 56 timing rows
unstageable. My worst-slack proof group makes hold provable *despite* it, but
setup and hold both still need those rows to carry a stage before they can be
adjudicated per corner.

**R-G — nothing to re-render.** No pinned protected path is touched by this
branch, verified against `tools/ci/protected_landing_transition.json`.
