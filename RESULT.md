# The record producers and the record consumer, made to agree

Branch cut from `origin/main` at **`e36d81c0a`** — `landing(ACTIVATE): wire what
the fourteen lanes shipped` **[v1.11.33]**. Fetched 2026-08-21; that is the tip
`origin/main` actually carries. The brief named a v1.11.19..v1.11.47 batch — the
last eleven of those (v1.11.34..v1.11.47) are not on `origin/main` from here, so
this branch is cut from v1.11.33 and everything below is measured against it.

Items: **F-2, F-4, F-5, F-9, F-13** and lander requests **R5, R6, R7, R8, R10**.

Every fix has two halves, because shipping only the first is what lets these
come back: the code is reconciled, **and the rule that was missing is written
into `docs/PPA_INTERFACES.md` with a test that fails if the two sides drift
again**. The contract gained one new subsection per class of disagreement:
**§2** (the unit rule), **§2.1** (a second record under one identity), and
**§3.1** (the five identities, and what belongs in each).

---

## What changed, per item — and WHICH SIDE moved

### F-5 / R6 — the unit of a count · **the PRODUCER moved**

`_ppa/area.py` declared `"cells"`, `"wires"` and `"wire_bits"`; `_ppa/metrics.py`
reads the `_count` suffix on a metric NAME as a claim about `unit` and demanded
`"count"`. Two files in one lane holding opposite rules. **Three** specs were
wrong, not one — the finding named `cell_count`, and `wire_count` and
`wire_bit_count` have the same defect:

```
area.proxy.cell_count      area.py says 'cells'      name claims 'count'  -> UNIT_CONTRADICTS_NAME
area.proxy.wire_count      area.py says 'wires'      name claims 'count'  -> UNIT_CONTRADICTS_NAME
area.proxy.wire_bit_count  area.py says 'wire_bits'  name claims 'count'  -> UNIT_CONTRADICTS_NAME
```

**`_ppa/area.py` is the side that changed.** The metric NAME is part of the
record's identity, and `unit_suffix_of` is the only cross-check in the system
positioned to catch an order-of-magnitude unit error — every consumer downstream
trusts `unit`. Relaxing `metrics.py` to accept `"cells"` would have removed that
check for **every** `_count` metric in the tree, and bought nothing: WHAT is
counted is already stated twice, by the metric name and by `AreaMetricSpec.what`.
The unit names the DIMENSION, never the thing counted.

Both halves of the reminder are enforced and tested: the record **carries** its
unit, and a record with no unit is **refused** (`NO_UNIT`), never assumed from
the name — `test_vacuous_a_record_with_NO_unit_is_refused_never_assumed`.

### F-4 / R5 — the three envelopes · **the CONSUMER moved**

`records_from_document` accepted one record, a bare list, or a
`metric_bundle.v1`, and **not one shipped producer writes any of the three**.
Measured on a real OpenROAD parse: the envelope holds **52 genuine records** and
the consumer indexed **0**.

**`_ppa/metrics.py` is the side that changed**, and the reason is structural
rather than a coin-toss: `bundle()` is built from a `MetricIndex`, and the index
**refuses a conflicting pair**. A producer forced to write a bundle could not
express "two artefacts disagree" *at all* — which is precisely what
`_ppa/backends/__init__.py` requires a backend to report. Making the producers
write bundles would have deleted the evidence between them.

New `M.RECORD_CARRIERS` maps envelope schema → the key its records live under.
An unregistered `vibeic.ppa.*` document is still **refused**, never read as empty
(rule 9). Measured after: `52 records -> OK 52`.

**Secondary, and it was real:** with every input unreadable the program still
wrote `{"records": []}` — byte-identical to a run that read a tree and found
nothing. The exit code was honest and the file was not. Now no bundle is written
when nothing was read, and a *partial* read writes a bundle that carries
`inputs_unreadable` so the file itself says what it could not open. The existing
test `test_vacuous_an_empty_directory_writes_no_bundle_that_reads_as_clean`
promised this in its name and its body admitted the opposite; it now asserts what
it says.

### F-9 / R7 — two readings of one metric under one scope · **I did NOT implement R7**

R7 asks for the source artefact to be put into `scope`. **I have not done that,
and I recommend against it.** It makes the collision go away by converting a
DETECTED conflict into two facts that quietly never compare again — the opposite
of what `_ppa/backends/__init__.py` requires ("A backend never resolves a
disagreement… ruling on the conflict is `_ppa/contract.py`'s job").

What I found instead is that **the index was calling agreement a conflict.**
Driving the backend over a real PnR directory:

| metric | openroad.log | openroad.metrics.json | before | after |
|---|---|---|---|---|
| `route.drc.violation.count` | **0** | **0** | `CONFLICTING_RECORD` | **corroboration, accepted** |
| `route.via.count` | 2502 | 2510 | `CONFLICTING_RECORD` | `CONFLICTING_RECORD` |
| `route.wirelength.um` | 12704.0 | 12722 | `CONFLICTING_RECORD` | `CONFLICTING_RECORD` |

The first row is two artefacts **confirming** a fact, and its refusal message
read "Two numbers claiming to be the same fact is a conflict" when the two
numbers were equal. One corroborated fact took down the whole record set.

`MetricIndex.add` now names four outcomes instead of two (contract §2.1):
byte-identical → `DUPLICATE_RECORD`; same status/unit/value from different bytes
→ **CORROBORATION**, kept once with the confirming artefact recorded in the
bundle's `corroborations`; different value → `CONFLICTING_RECORD`, and the
refusal now **names both source paths**; different value from the **same bytes**
→ `SAME_ARTEFACT_TWO_VALUES`, because identical bytes cannot support two numbers
and that is a parser defect, not a fact about the run.

Disagreement is still detected and still fatal to the claim. Records are left
byte-identical to what the producer parsed — corroboration lives in the index and
the bundle, not by rewriting parsed evidence.

### F-10 / R8 — every timing row emitted twice, and three slacks in one view

Two different defects, and the brief's dichotomy separates them exactly.

**(a) One reading read twice → the INPUT LIST was wrong.** `discover_reports`
de-duplicated on the *resolved path*, and the runner publishes each report into
two directories as separate files with identical bytes. Now it de-duplicates by
**content hash**, keeps the first in `_STA_DIRS` order, and each collapse is
reported as a note rather than dropped silently.

**(b) Three slacks under one scope → the SCOPE was wrong.**
`timing.*.worst_path_slack_ns` is emitted once per reported path and every one
carried the same scope. The scope now names the path: `path_startpoint` /
`path_endpoint` when the artefact gives them — an identity that is the same in
two runs of one design, so two arms stay comparable — and `path_ordinal` **only**
when it does not, since an ordinal moves if the tool reorders its output and a
cross-arm comparison over it should refuse. Never both.

Measured on the new specimen: 3 rows named by endpoints, 1 by ordinal, no two
rows from one artefact sharing a scope.

### F-2 — `--backend` drove no backend, including the ones that exist

All five shipped backends returned the same blanket rc=2. The CLI also had no
argument saying *what* to read.

`_ppa/backends/__init__.py` gains a driver seam: a backend that can turn one
path into records declares `extract_records()`; one that cannot declares
`NO_DRIVER_REASON`. Both are read by attribute, so teaching a backend to be
driven touches only that backend. `ppa_metric_extract.py` gains
`--backend TOOL --from PATH` (and `--stage` for the backend that needs it).

| backend | now |
|---|---|
| `openroad` | **drivable** — a run directory, a log, or a metrics JSON |
| `librelane` | **drivable** — see the caveat below |
| `yosys` | **drivable, requires `--stage`** — one transcript holds a generic and a mapped block; defaulting it compares a pre-techmap count against a mapped one |
| `opensta` | not drivable, **says why**: it produces a `Report`, and deciding what a slack MEANS is a domain rule |
| `orfs` | not drivable, **says why**: it parses AutoTuner rows the search layer holds, not an artefact on disk |

Measured end to end: `--backend openroad --from <run dir>` → 49 records indexed,
2 genuine conflicts refused, rc=1, no bundle. `--from <log>` → 35 records, rc=0,
bundle written.

**Also fixed here:** `RC_BAD_INVOCATION = 3` was defined in that file and never
used — `argparse` exits **2** on a usage error, which §1 reserves for "I could
not check". A typo and an unreadable input left a caller the same exit code. The
parser now exits 3, as §1 says.

### F-13 / R10 — which artefacts belong to `analysis`

The contract named five identities in a module-map line and never said what goes
in each, and the natural reading of "analysis artefacts" — the STA/DRC/LVS
reports — makes `ppa_problem_integrity_check` refuse **every** legitimate
comparison, because those files are outputs of the implementation.

**New contract §3.1** states the rule: *an artefact that varies with the
implementation may not sit in `analysis`.* `analysis` is the measurement
CONFIGURATION; it is never the reading.

**New finding `PPA-C-016`** makes it actionable. `PPA-C-012` is deliberately
unchanged — the comparison really is invalid — but when `analysis` differs **and
`implementation` differs**, the artefacts that moved are now named as misfiled,
with the rule and the fix. A bare digest mismatch sent the reader to diff two run
trees by hand.

The discriminator is tested too: `analysis` moving **alone** is a genuinely
different measurement (a moved corner) and must NOT be reported as misfiling.

§3.1 also records the F-14 hazard the E2E lane hit: a hash-based identity over an
emitted script is defeated by absolute host paths — emit it relative, or leave it
out of the identity **and say so**.

---

## The A/B, by TEST ID

Serial runs (`-p no:cacheprovider`, no `-n`), base measured in a **separate clean
worktree at `e36d81c0a`** so the two arms differ only by this branch.

**The PPA set** — `tests/test_ppa_*.py` + `test_readme_ppa_extractor.py` +
`test_issue1121_ppa_head_to_head.py` (39 files base, 41 after):

| arm | result |
|---|---|
| base `e36d81c0a` | **33 failed, 1085 passed** in 42.21s |
| this branch | **33 failed, 1123 passed** in 43.31s |

**The full affected surface** — every test file referencing `_ppa`,
`ppa_metric_extract`, `ppa_problem_integrity` or `PPA_INTERFACES` (47 base, 49
after):

| arm | result |
|---|---|
| base `e36d81c0a` | **35 failed, 1539 passed, 5 skipped, 2 xfailed** in 113.27s |
| this branch | **35 failed, 1577 passed, 5 skipped, 2 xfailed** in 113.54s |

**The failing TEST-ID sets are IDENTICAL on both arms — `comm` reports nothing in
either direction. No new failure, and no test that was red became green by
accident.** Both arms gain exactly **+38** passing tests, which is exactly the 38
this branch adds (13 + 13 + 3 + 6 + 3): 1085 -> 1123 and 1539 -> 1577.

### The 35 pre-existing reds are NOT mine, and here is what they are

| count | file | cause |
|---|---|---|
| 20 | `test_ppa_metrics_schema_agreement.py` | `jsonschema` |
| 12 | `test_ppa_contract.py` | `jsonschema` |
| 1 | `test_ppa_contract_fixtures.py` | `jsonschema` |
| 1 | `test_matrix_d2_falsifiable.py::test_d2_gate_has_a_reachable_fail[step1.6x]` | step 1.6x's one blocking clause reaches PASS on a deliberately-broken project |
| 1 | `test_not_verified_tier.py::test_no_new_undeclared_infrastructure_skip_appears` | `test_trusted_pytest_entry.py` carries an undeclared infrastructure-absent skip |

The `jsonschema` 33 are an **environment** fact with a real code defect behind
them, and it is worse than "not a declared dependency":

```
$ python3 -c "import jsonschema; print(jsonschema.__version__)"
3.2.0
E   AttributeError: module 'jsonschema' has no attribute 'Draft202012Validator'
```

`ppa_contract_check.py:118` guards `import jsonschema` and prints a correctly
worded `PPA-C-010` when it fails — but line 158 then uses
`jsonschema.Draft202012Validator` unconditionally. An **old but importable**
jsonschema walks straight past the guard and raises. The refusal is right; the
version check is missing. **Out of my items — reported, not fixed**, because
touching it would move my A/B baseline. See request 4.

---

## Mutation arms — every fix, reverted, with the test that goes red

Harness: revert one edit in place, run only the named test, restore. All ten went
red; a guard that cannot go red is not a guard.

| # | mutation | named test | verdict |
|---|---|---|---|
| 1 | `area.py` declares `"cells"` again | `..._agreement.py::test_every_area_metric_builds_a_record_its_own_consumer_ACCEPTS` | **RED** rc=1 |
| 2 | `RECORD_CARRIERS` holds only the bundle | `..._agreement.py::test_the_three_shipped_producers_write_documents_the_consumer_READS` | **RED** rc=1 |
| 3 | agreement called a conflict again | `..._second_record_identity.py::test_two_artefacts_that_AGREE_are_corroboration_not_conflict` | **RED** rc=1 |
| 4 | conflict detection removed | `..._second_record_identity.py::test_two_artefacts_that_DISAGREE_are_still_refused` | **RED** rc=1 |
| 5 | dedupe by resolved path again | `test_ppa_timing.py::test_a_report_published_into_two_directories_is_read_ONCE` | **RED** rc=1 |
| 6 | path identity dropped from scope | `test_ppa_timing.py::test_every_reported_path_row_says_WHICH_path` | **RED** rc=1 |
| 7 | openroad's driver removed | `test_ppa_metrics_extract_cli.py::test_the_backend_seam_actually_EXTRACTS` | **RED** rc=1 |
| 8 | the blanket backend refusal returns | `test_ppa_metrics_extract_cli.py::test_the_backend_seam_actually_EXTRACTS` | **RED** rc=1 |
| 9 | the misfiling diagnosis removed | `test_ppa_problem_integrity.py::test_a_report_declared_under_analysis_is_named_as_MISFILED` | **RED** rc=1 |
| 10 | an empty bundle is written again | `test_ppa_metrics_extract_cli.py::test_vacuous_an_empty_directory_writes_no_bundle_that_reads_as_clean` | **RED** rc=1 |

**Arm 4 is the one that matters most for F-9.** It proves the corroboration
change did not quietly disable conflict detection: force `_states_the_same_fact`
to always-true and the DISAGREE test goes red.

**Two arms I had to strengthen after they failed to go red, recorded because the
first version would have shipped a guard that guarded nothing:**

* my first F-2 guard asserted only that *some* backend is drivable — disabling
  openroad's driver left librelane and yosys and it stayed **green**. Replaced
  with an end-to-end guard through the process: `--backend openroad --from <log>`
  must exit 0 and index a record with the value the log states.
* my first path-identity test ran on a fixture with **one** path row, so "no two
  rows share a scope" was satisfied by having nothing to collide with. Added a
  specimen with three paths in one view, and asserted `len(path_rows) >= 4` and
  the exact value set so it cannot go vacuous again.

### Non-vacuity, checked rather than assumed

* the envelope census asserts it scanned `> 10` schemas before concluding;
* every registry-walking test asserts its registry is non-empty first;
* the path-identity test exercises **both** naming branches — measured 3 named,
  1 ordinal;
* `test_the_unit_rule_is_ENFORCED_and_not_merely_declared` re-applies the exact
  pre-v1.11.33 declaration and requires `UNIT_CONTRADICTS_NAME`, so the census
  cannot pass over a tree where the enforcer stopped firing.

**The census found a defect I had missed by hand.** It failed on first run naming
`vibeic.ppa.area_verdict.v1`, an envelope I had not seen in the findings. It is
an adjudication and not a record carrier, so it is classified as such — but that
is the census doing the job it was written for on its first execution.

---

## What I could NOT settle

**1. `librelane` produces records the canonical consumer refuses — a FOURTH
producer, and worse than the three.** F-4 named three; there are four. Measured:

```
design__instance__area   MEASURED -> ['BAD_METRIC_NAME', 'SCOPE_INCOMPLETE', 'NO_UNIT']
design__instance__count  MEASURED -> ['BAD_METRIC_NAME', 'SCOPE_INCOMPLETE', 'NO_UNIT']
timing__setup__ws        MEASURED -> ['BAD_METRIC_NAME', 'SCOPE_INCOMPLETE', 'NO_UNIT']
```

Its rows are invalid at the **record** level, not just wrapped in an unreadable
envelope: LibreLane's `design__instance__area` is not a canonical dotted name,
no row carries a `stage`, and **no row carries a `unit` at all**. I did **not**
fix it. Mapping those keys onto canonical names and units needs evidence for
each unit that I do not have here, and inventing them is the exact defect
`openroad.py` refuses by name ("It does not map a `-metrics` JSON key whose unit
it could not establish from evidence"). I drove it anyway rather than hiding it,
and said so in the driver's docstring, so the gap is loud instead of silent.

**2. The `timing_rows.v1` schema edit is additive, and §5 says v1 is never
edited.** Naming the path in scope needs three optional properties, and the
scope block is `additionalProperties: false` — which I kept, so an *undeclared*
scope key is still refused. Every document valid under the old schema stays valid
under the new one, and nothing hashes against the schema file (records carry
`vibeic.ppa.metric.v1`; the envelope hashes rows, not the schema). I judged that
§5's precondition — "once something has **hashed against it**" — is not met, and
that minting `timing_rows.v2` for three optional keys would ripple through the
producer, `RECORD_CARRIERS` and every consumer for no gain. **If the lander reads
§5 more strictly, the zero-schema-change alternative is R8's other option: emit
only the worst path per (clock, check) and drop the rest.** That needs no schema
edit; it discards the 2nd/3rd-worst paths, which is why I did not choose it.

**3. I could not reproduce the E2E lane's run tree.** Everything above is
measured against synthetic specimens transcribed from the real logs already in
`tests/`, plus a faithful OpenROAD run directory I built from
`LOG_MODERN` + a metrics JSON that disagrees in the direction the module
docstring records as measured. The 61-arm `spm` tree is not on this host, so the
F-13 numbers I quote are the E2E lane's, not re-measured by me; the F-13 *rule*
is re-proved here on the contract fixtures instead.

**4. `--backend` still cannot drive `opensta` or `orfs`,** and I did not force
it. Both now state their own reason. Wiring opensta would mean a second
implementation of `_ppa/timing.py`'s view rules inside a parser, free to disagree
with the first about one number.

---

## REQUESTS TO THE LANDER

**1 — `tools/ci/protected_landing_transition.json`: no change needed.** I
checked all 47 pinned paths against my diff: none of the 19 files this branch
touches is protected. No manifest re-render is required for this branch.

**2 — Please confirm the `timing_rows.v1` schema call** (What I could not settle,
2). Additive optional properties, `additionalProperties: false` retained. Say the
word and I will convert it to R8's emit-only-the-worst form, which needs no
schema change at all.

**3 — `_ppa/backends/librelane.py` needs an owner decision** (What I could not
settle, 1). Every MEASURED row it emits is refused three ways. It needs a
key→(canonical name, unit, stage) map like `openroad._JSON_MAP`, and each unit
needs evidence. Until then it is a backend that can be driven and whose output
the assembler refuses — which is honest, and useless.

**4 — `ppa_contract_check.py` needs a jsonschema VERSION check, not just an
import check.** Line 118 guards the import; line 158 uses
`Draft202012Validator` unconditionally. With `jsonschema 3.2.0` installed the
`PPA-C-010` refusal never fires and the program raises `AttributeError` instead.
That is 33 of the 35 reds on clean main on this host. Fix is a version guard
folded into the existing `PPA-C-010` branch. Out of my items, so untouched.

**5 — `_ppa/metrics.py` still has no `metric_bundle.v1` schema file**, and its
own comment raises this as a request to you. §5 says every instance document has
one; `schemas/ppa/` has no `metric_bundle`. My `RECORD_CARRIERS` census would
cover it the day it lands.

**6 — Two pre-existing reds on clean main are unrelated to this branch** and
belong to whoever owns them: `step 1.6x`'s only blocking clause reaches PASS on a
deliberately-broken project (`test_matrix_d2_falsifiable.py`), and
`test_trusted_pytest_entry.py` carries an undeclared infrastructure-absent skip
(`test_not_verified_tier.py`).

**7 — R7 was deliberately not implemented as written** (F-9 above). If you want
the artefact in `scope` after all, it should be a declared authority-order
resolution in `_ppa/contract.py` rather than a scope key, so the override is
named and printed as `PPA-C-015` instead of two facts silently ceasing to
compare.

---

## Files

```
docs/PPA_INTERFACES.md                      §2 unit rule, §2.1 second record, §3.1 identities
schemas/ppa/timing_rows.v1.schema.json      three optional path-identity scope keys
programs/_ppa/area.py                       F-5: three units, "cells"/"wires"/"wire_bits" -> "count"
programs/_ppa/metrics.py                    F-4 RECORD_CARRIERS; F-9 corroboration vs conflict
programs/_ppa/timing.py                     F-10a content-hash dedupe; F-10b path identity in scope
programs/_ppa/contract.py                   PPA-C-016 registered
programs/_ppa/backends/__init__.py          F-2 the driver seam
programs/_ppa/backends/openroad.py          F-2 driver
programs/_ppa/backends/librelane.py         F-2 driver (+ its refusal caveat, written down)
programs/_ppa/backends/yosys.py             F-2 driver, requires --stage
programs/_ppa/backends/opensta.py           F-2 NO_DRIVER_REASON
programs/_ppa/backends/orfs.py              F-2 NO_DRIVER_REASON
programs/ppa_metric_extract.py              F-2 --backend/--from; F-4 secondary; §1 rc=3
programs/ppa_problem_integrity_check.py     F-13 PPA-C-016 diagnosis
programs/tests/test_ppa_producer_consumer_agreement.py   NEW, 13 tests (F-4, F-5, F-2 census)
programs/tests/test_ppa_second_record_identity.py        NEW, 13 tests (F-9, §2.1)
programs/tests/test_ppa_timing.py           +3 (F-10a, F-10b)
programs/tests/test_ppa_metrics_extract_cli.py  +6 (F-2 end-to-end, F-4 secondary)
programs/tests/test_ppa_problem_integrity.py    +3 (F-13 negative/positive/discriminator)
```

No GDS was hand-edited, no geometry deleted, no pin moved, no rule deck relaxed.
No `--write-baseline` was run on any hygiene gate. No plugin version was bumped.
