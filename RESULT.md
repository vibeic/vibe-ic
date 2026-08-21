# PPA layer — a test suite for the LAYER, run, and what it found

**Base:** `e36d81c0a` (v1.11.33), cut from `origin/main` at 2026-08-21 10:34 UTC+8.
**Branch:** `agent/jppa-tests`. **Worktree:** `/home/reyerchu/_jppatests`.
**Version:** not bumped, per the brief. **Protected paths:** none touched (proof below).

Every number here traces to a command in this file. Where I did not measure
something I have written `NOT_MEASURED` rather than a default.

---

## 0. One thing I could not get

`ppa-e2e/FINDINGS.md` **does not exist** anywhere I can reach. Searched:

```
$ git ls-tree -r --name-only origin/main | grep -i 'ppa-e2e\|FINDINGS'   # nothing
$ git log --all --oneline --diff-filter=A -- '*ppa-e2e*'                 # nothing
$ find /home/reyerchu -maxdepth 6 -type d -name 'ppa-e2e'                # nothing
$ grep -rl "required_views" /home/reyerchu --include=*.md                # nothing
$ cd ~/benchmark-data && git ls-tree -r --name-only origin/main | grep -i ppa   # nothing
```

So I have the **five findings your brief names** (F-2, F-4, F-5, F-10, F-11) and
**not the other thirteen**. All five are reproduced below with a command. For the
thirteen I do not have, I drove the layer myself and found **six more defects**,
which are in §2 — but I cannot tell you which of them are your F-1/F-3/F-6…, and
I have not written tests for findings I have never read. **Send me the file and
I will finish that half.**

---

## 1. The A/B, by TEST ID

Counts are given because you asked for them, but the sets are what matter — and
the sets are disjoint in the right direction.

| | base `e36d81c0a` | branch | delta |
|---|---:|---:|---|
| `test_*ppa*` files | 46 | 53 | +7 |
| collected | 1219 | 1362 | +143 |
| **FAILED** | **33** | **0** | −33 |
| passed | 1185 | 1324 | |
| skipped | 1 | 14 | +13, all declared (§4) |
| xfailed | 0 | 24 | +24, all `strict=True` pins (§3) |

```
$ python3 -m pytest $(ls programs/tests/test_*ppa* ) -q -p no:randomly --tb=no -rf
  base   33 failed, 1185 passed, 1 skipped in 56.96s
  branch 1324 passed, 14 skipped, 24 xfailed in 62.47s
```

By test ID:

```
$ comm -23 ab_base.txt ab_mine.txt | wc -l     # red on base, green on branch:  33
$ comm -13 ab_base.txt ab_mine.txt | wc -l     # green on base, red on branch:   0
```

**Every one of the 33 base failures is accounted for, and I introduced no new red.**
Three were fixed by the `ppa_contract_check` repair in §2.5; the other 30 were one
root cause, §4.

Wider net — the 61 files that touch any patched program, run serially:

```
$ python3 -m pytest <61 files> -q -p no:randomly --tb=no -rf
  1 failed, 1641 passed, 14 skipped, 24 xfailed in 107.32s
```

The one failure is `test_not_verified_tier.py::test_no_new_undeclared_infrastructure_skip_appears`
and it is **red on pristine base with byte-identical output**, naming
`test_trusted_pytest_entry.py` — not a file of mine. Not caused by this branch;
not fixed by it either.

### The same run on a fully-provisioned host

The host ships `jsonschema 3.2.0`. I built a throwaway venv with `jsonschema
4.26.0` + `pyyaml` (in the scratchpad; **nothing installed on your machine**) to
find out whether the 30 base reds were hiding real defects:

```
$ <scratchpad>/venv/bin/python -m pytest <61 files> -q -p no:randomly --tb=no -rf
  1 failed, 1672 passed, 5 skipped, 24 xfailed in 103.60s
```

**They were not.** With a real draft-2020-12 validator the schema layer is clean:
`test_ppa_contract.py` + `test_ppa_contract_fixtures.py` +
`test_ppa_metrics_schema_agreement.py` = **92 passed**. The 33 were a host
condition reported as code failures.

---

## 2. What I changed, and why, per item

Seven fixes. Every one has a mutation arm in §5 that I **ran**.

### 2.1 The bad-invocation arm — 12 of 14 CLIs, measured

```
$ for f in programs/ppa_*.py; do out=$(python3 "$f" --this-flag-does-not-exist 2>&1); echo "$? $f"; done
  12 of 14 exited 2;  ppa_feasibility_check and ppa_pareto_check exited 3
```

`PPA_INTERFACES.md` §1 gives 3 to a bad invocation. `argparse` exits **2**, which
here means UNDETERMINED. That is not pedantry: §1 also says rc=2 must never be
mapped to PASS, and the way a flow gate honours that is to treat 2 as "nothing to
check here" — so a misspelled flag reads as a step with nothing to do and the run
carries on green having measured nothing.

### 2.2 …and the trap its obvious fix walks into

The two programs that had already fixed 2.1 did it with a bare
`except SystemExit: return RC_BAD_INVOCATION`. `--help` is also `SystemExit`, with
code 0:

```
$ for f in programs/ppa_*.py; do python3 "$f" --help >/dev/null 2>&1; rc=$?; echo "$rc $f"; done
  ppa_feasibility_check.py  rc=3
  ppa_pareto_check.py       rc=3
```

Asking a program what its flags are is not a bad invocation. **These two are the
same defect from opposite sides, which is why fixing either alone produces the
other** — so both are fixed in one place.

**New file `programs/_ppa/cli_exit.py`** (sha256 `52bc4f47…`, 4.0 KB) — reads
`exc.code` rather than catching the type: 0/None → rc 0, anything else → rc 3.
Applied to the **11 programs this branch owns**. Also `cli_exit.refuse()` for a
usage error found *after* parsing (`ap.error(...)` exits 2 as well) — 5 sites.

### 2.3 `ppa_predict_aggregate.py --cell-count 0` → rc **0**, publishing zeroes

```
$ python3 programs/ppa_predict_aggregate.py --cell-count 0 ; echo rc=$?
  - **Estimated area**: 0.0 um² (0.0000 mm²)
  - **Estimated power**: 0.00 uW
  rc=0
```

§2: "No numeric sentinels. `0`, `-1` and `""` never mean 'not measured'." A cell
count of zero is not a design with no cells; on every path that reaches this CLI
it is a count that was never taken. **Now rc=2 `[CANNOT CHECK]`, and no estimate
is printed at all** — a refusal that still prints the number gets the number
picked up downstream.

### 2.4 `ppa_metric_extract.py` → rc **0** over an empty record set

```
$ echo '{"schema":"vibeic.ppa.metric_bundle.v1","records":[]}' > b.json
$ python3 programs/ppa_metric_extract.py --records b.json ; echo rc=$?
  ppa_metric_extract: 1 document(s) named, 1 read, 0 unreadable, 0 record(s) indexed, 0 refused
  rc=0
```

The program **already** guarded `n_docs == 0`, with the comment *"An empty bundle
would read as a clean run."* A document that WAS read and holds zero records
produces the identical empty bundle. Same sentence, one level in, unguarded.
Now rc=2 with `code: EMPTY_RECORD_SET`.

### 2.5 `ppa_contract_check.py` → an internal error reported as **rc=1**

```
$ python3 programs/ppa_contract_check.py --contract c.json ; echo rc=$?
  AttributeError: module 'jsonschema' has no attribute 'Draft202012Validator'
  rc=1
```

The program guards `ImportError` on jsonschema, honestly, with *"This is not the
schema passing."* It does not guard **jsonschema present but older than 4.0**, so
the `AttributeError` escapes `raise SystemExit(main())` and the process exits
**1** — which §1 reserves for *a finding about the design*. **A missing library was
indistinguishable from a broken contract**, and unlike a 2 (which a caller may
skip) a 1 stops a sign-off with a finding nobody can act on.

Fixed two ways: the `hasattr` guard now returns an UNDETERMINED `PPA-C-010`
finding naming the version, and `__main__` catches any unexpected exception and
returns 3. This alone turned **3** of the 33 base reds green.

### 2.6 `ppa_head_to_head_check.py` — an honest refusal with the wrong marker

Printed `VACUOUS: … This is NOT a pass … rc=2.` — correct in English, but §1
requires `[CANNOT CHECK]` / `[REFUSE]` **so that a 2 can be found by grep**. Marker
added. (See §5, arm 6: my first version of this arm **could not go red**.)

### 2.7 `ppa_area_threshold_check.py` — bare `ERROR:` on four refusals

Three "artefact not found" cases printed `ERROR: …` and returned 2 with no marker.
Marker added. The fourth, *"provide `--threshold-pct` or `--prompt`"*, is a
statement about **argv**, not about an artefact — moved from rc=2 to rc=3.

### 2.8 Three tests that were wrong, fixed as tests

Not relaxed — tightened to the contract. Each is a case where the test pinned a
*mechanism* instead of the *behaviour*, and its own docstring already stated the
right intent.

| test | pinned | now |
|---|---|---|
| `test_ppa_page_claim_check::test_bad_invocation_is_not_a_design_finding` | `SystemExit.code == 2  # argparse's own; never 1` | `main([]) == 3` |
| `test_ppa_report_gen::test_bad_invocation_is_not_a_design_finding` | same | same |
| `test_v1_0_85_issue768…::test_acceptance_reference_flag_in_help` | `pytest.raises(SystemExit)` | `main(["--help"]) == 0` **and** the `--reference` grep |

The first two say *"rc=1 is a claim about silicon (§1). Arg errors must not borrow
it"* and then assert **2**, which is argparse's default and §1's UNDETERMINED. The
intent was right; the value was the wrong one of the two remaining codes. The
third asserted that `main(["--help"])` *raises*, which is a fact about argparse's
internals — the issue's acceptance command greps the help text, and that is now
asserted directly, plus the exit code, which is strictly more than before.

---

## 3. The new suite — 7 files, 165 tests

Named `test_ppa_layer_*` so they are addressable as a set. **Every arm is
parametrized by program or metric name**, so a red names the thing, not an index.

| file | tests | green | pinned |
|---|---:|---:|---:|
| `test_ppa_layer_exit_contract.py` | 72 | 69 | 3 |
| `test_ppa_layer_producer_consumer.py` | 36 | 24 (+2 skip) | 10 |
| `test_ppa_layer_backend_seam.py` | 17 | 12 | 5 |
| `test_ppa_layer_internal_error_is_not_a_finding.py` | 17 | 17 | 0 |
| `test_ppa_layer_vacuous_population.py` | 13 | 12 | 1 |
| `test_ppa_layer_feasibility_view_scope.py` | 6 | 3 | 3 |
| `test_ppa_layer_timing_view_dedup.py` | 4 | 2 | 2 |

Two structural choices, both because the alternative is how coverage rots:

* **Populations are DISCOVERED, not listed.** `ppa_*.py`, `_ppa/backends/*.py`,
  `area.AREA_METRICS`, `feasibility.DEFAULT_AXES` — a fifteenth program or a
  sixth backend is covered the day it lands.
* **Every discovered population has its size ASSERTED FIRST.** A glob that finds
  nothing makes every parametrized arm below vacuously green, which is this
  suite's own subject matter turned on itself.

### 3.1 The five E2E findings — reproduced, then pinned

Each is `xfail(strict=True)`: when the owning lane lands its fix the test
**XPASSes and the file goes red**, forcing the pin out. A pin that survives its bug
is a second bug, and it is the one that hides the first. §5 proves this fires.

**F-2 — `--backend` drives no backend, including the ones that exist.**
All 5 shipped backends and a misspelling return the same rc=2. The refusal is
*honest* (the module comment says an empty bundle for an undriven tool is exactly
the defect the contract removes), so I pinned only the "actually extracts"
arm — and added two arms that must stay green, because the wrong fix here is
"return 0 and write an empty bundle".
*Why no per-module test saw it: the flag was never invoked at all.*

**F-4 — three producers emit envelopes the canonical consumer REFUSES.**
Measured, driving each producer from its **own shipped fixtures**:

| producer | result |
|---|---|
| `power.metric_records` | **48 of 48 records refused** — `SCOPE_SENTINEL: scope.liberty is None` |
| `timing.timing_rows` | every row refused; **`MetricIndex.add` raises** `scope.stage is required` + 4× SCOPE_SENTINEL |
| `area.area_record` | 3 of 14 metrics refused (that is F-5) |

*Why no per-module test saw it:* `test_ppa_power.py` checks power's rules against
power's records; `test_ppa_metrics.py` checks metrics' rules against records built
by `metrics.measured()`. **Not one test ever hands a producer's output to
`metrics.validate`** — so the only property that makes the shared `schema` string
mean anything was tested by nobody.

The tests deliberately do **not** assert which side is right. Whether `liberty:
None` should be dropped or `validate` should accept a declared-absent scope field
is the record lane's call, and either makes them green.

**F-5 — the area lane's declared unit and the metrics lane's required unit disagree.**

```
area.proxy.cell_count       area says 'cells'      metrics requires 'count'
area.proxy.wire_count       area says 'wires'      metrics requires 'count'
area.proxy.wire_bit_count   area says 'wire_bits'  metrics requires 'count'
```
3 of 14. Each module is self-consistent; the pair is not.

*A correction to my own first probe:* I initially reported power as worse still,
`power.total_mw` carrying `unit="W"`. That metric name is mine, not the
producer's — power really emits `power.total_w`, and all four of its names agree
with their unit. The real power defect is the scope sentinel above.

**F-10 — every timing row emitted twice from byte-identical files.**
`timing.discover_reports` de-duplicates by **resolved path**, and a Phase-3 tree
carries the same sign-off report under `phase3/stage3/sta/` and
`reports/phase3/sta/`. Measured on two copies with one sha256:

```
rows: 8      distinct row_digest: 8      distinct (metric, scope): 4
metrics.record_key collisions: 4 of 4
```

*Why no per-module test saw it, and this is the interesting half:* the obvious
assertion **does not fire**. `row_digest` covers `source.path`, so the two copies
hash differently and `len(set(digests)) == len(rows)` passes **with the bug
present**. The duplication is visible only at `metrics.record_key` — the key the
timing lane never tested and the metrics lane never fed timing rows to. I left a
green test asserting that `row_digest` cannot see this, so the next author does
not reach for the instrument that already failed.

**F-11 — `required_views` is global, so one view poisons every axis.**
The widest blast radius of the five. One tuple is applied to all nine axes; six of
them (drc, lvs, antenna, ir, em, equivalence) are not per-corner facts at all.
Measured on a candidate **clean on all nine axes and measured at both declared
corners**:

| `required_views` | verdict | axes SATISFIED |
|---|---|---:|
| `()` | UNDETERMINED | 0/9 |
| one stage-only view | **FEASIBLE** | **9/9** |
| the two real STA corner views | UNDETERMINED | **0/9** |

The hard promotion gate returns FEASIBLE **only** when `required_views` holds a
single view so weak every axis satisfies it. Declare what a sign-off actually
declares and it can pass nothing — a gate that cannot be satisfied, which is the
mirror of a gate that cannot fail and just as useless. Even setup and hold poison
each other: a setup record can never cover the hold view.

*Why no per-module test saw it:* the feasibility suites exercise one axis at a
time with `required_views` matched to that axis. The defect is a property of the
**cross product**, and no test ever put a timing view and a DRC record in one
policy.

I also added a green test that empty `required_views` stays UNDETERMINED, so a
fix for F-11 cannot quietly take out the rule it was built to enforce.

### 3.2 The four arms, over the whole layer

`POSITIVE / NEGATIVE / VACUOUS / BAD INVOKE` for all 14 CLIs, discovered by glob.
The vacuous arm is split in two on purpose, because only the easy half was
reachable before:

* **absent** input — one shape for every program. Green across the layer.
* **present, well-formed, and EMPTY** — a different document per program: a bundle
  with `records: []`, a space with no lever, `candidates: []`, an empty corpus dir.
  This is where §2.3, §2.4 and the pinned `ppa_search_run` finding live. The file
  opens, the parse succeeds, the population is zero, and
  `for x in population: check(x)` falls straight through to 0.

---

## 4. The 30 remaining base reds — one cause, and it is the same shape again

All 30 were `jsonschema 3.2.0` lacking `Draft202012Validator`.
`test_ppa_metrics_schema_agreement.py` opens with an `importorskip` whose reason
says, correctly:

> *"This is a SKIP and not a pass: nothing here looked."*

and covers exactly one of the two ways the validator can be unavailable. **That is
the fourth time this layer guards one level too shallow** — with §2.4
(`n_docs == 0`), §2.5 (`ImportError`), and `ppa_predict_aggregate` citing §2 on
sentinels in its docstring while estimating from zero. That family is what
`test_ppa_layer_internal_error_is_not_a_finding.py` is about.

**New file `programs/tests/_ppa_jsonschema.py`** (sha256 `5eb6dbec…`): one
capability check, `HAVE_DRAFT_2020_12`, plus a `needs_draft_2020_12` marker.
Applied to the 9 affected tests in `test_ppa_contract.py`, the 1 in
`test_ppa_contract_fixtures.py`, and as a module guard on the agreement file.

**It routes through `not_verified_tier`, not through a bare `pytest.skip`.** A
plain skip is the same lie one level up — `test_not_verified_tier.py` exists
because an infrastructure-shaped skip that bypasses the tier is invisible to the
roll-up (vibe-ic#1128). So the run now says:

```
[NOT VERIFIED] 2 test(s) did NOT run their verification because what they verify
WITH was out of reach. These are NOT passes …
  2 x NOT_VERIFIED: jsonschema 3.2.0 has no Draft202012Validator (it arrived in
  4.0) … — remedy: python3 -m pip install 'jsonschema>=4'
```

An unanswered question with the command that answers it, instead of 30 reds that
say nothing true or 30 quiet green ticks. And §1 confirms the questions are
answerable: **92 passed** under the venv.

---

## 5. Mutation arms — every fix, reverted, named test confirmed red

Each was run: revert, run the named test, restore. `MUTATION APPLIED` was asserted
by the mutating script itself, because a replacement that silently does not match
proves nothing.

| # | fix reverted | named test | result |
|---|---|---|---|
| 1 | `cli_exit` returns argparse's 2 again | `…exit_contract::test_unknown_flag_is_bad_invocation_not_undetermined` | **11 failed** |
| 2 | `cli_exit` back to bare `except SystemExit` | `…::test_help_is_not_a_bad_invocation` + `…::test_cli_exit_helper_tells_help_from_usage_error_by_code` | **12 failed** |
| 3 | drop `report["records"] == 0` | `…vacuous_population::test_mutation_metric_extract_empty_bundle` | **1 failed** |
| 4 | drop the `cell_count <= 0` guard | `…vacuous_population::test_mutation_predict_aggregate_zero_cells` | **1 failed** |
| 5 | drop the `Draft202012Validator` guard | `…internal_error…::test_contract_check_never_exits_one_because_of_the_validator` + `…::test_contract_check_says_the_schema_was_not_applied` | **2 failed** |
| 6 | drop the `[CANNOT CHECK]` marker | `…vacuous_population::test_a_present_but_empty_population_is_never_a_pass[7]` | **1 failed** |
| 7 | revert markers to bare `ERROR:` | `…exit_contract::test_vacuous_refusal_is_marked[ppa_area_threshold_check.py]` | **1 failed** |

Each restored cleanly (`69 passed, 3 xfailed`; `12 passed, 1 xfailed`).

### Arm 6 failed to fail, and that is the useful part

The first time I ran it, the mutation applied (asserted), the marker verifiably
vanished from the program's output, and **the suite stayed green: 14 passed.** My
vacuous table reached `ppa_head_to_head_check` by the *absent-record* path, which
is a different branch from the *empty-corpus* path where the marker lives. A guard
that cannot go red is not a guard. I added the empty-corpus case (now case 7 of 8)
and re-ran; it goes red. Both fixes for the two positive-control fixes
(`test_mutation_metric_extract_still_passes_on_a_real_record`,
`…_still_estimates_a_real_count`) exist for the mirror reason: an unconditional
`return 2` would also have made the arms green.

### The strict pins fire too

Not asserted from pytest semantics — **run**. I simulated the record lane landing
F-5 (`'cells' → 'count'` in `_ppa/area.py`):

```
6 failed, 24 passed, 2 skipped, 4 xfailed
    …test_area_declared_unit_matches_the_unit_the_name_requires[area.proxy.cell_count]  … ×3
    …test_area_record_is_accepted_by_the_canonical_consumer[area.proxy.cell_count]      … ×3
```

Exactly the six pins, red on the fix, forcing their own removal. Restored.

---

## 6. What I could NOT settle

* **13 of the 18 E2E findings.** §0. Not guessed at, not invented.
* **Whether F-4 is the producers' bug or the consumer's.** Deliberate: both
  resolutions make the tests green and the choice is the record lane's.
* **The six defects in §2 that I found myself are not mapped to your finding
  numbers.** Some are probably among the thirteen; I cannot tell which.
* **`ppa_search_run.py` on a real trials document.** I exercised the plan path and
  the empty-space path. Driving a full search was out of scope for a test lane and
  is `NOT_MEASURED`.
* **§1 stream discipline.** `ppa_contract_check` puts its human summary on
  **stderr**; §1 says stdout, refusals on stderr. I noticed this while debugging
  one of my own wrong assertions and did **not** sweep the layer for it — asserting
  it could redden other lanes' files on a clause I have not measured everywhere.
  `NOT_MEASURED` across the other 13 programs. Worth a follow-up.
* **`test_ppa_actuator_registry.py` and `test_ppa_closure_state_machine.py`
  `import yaml` at module scope with no guard** — a COLLECTION ERROR, not a skip,
  on a host without pyyaml. Same family as §4. Not fixed: not my lane's files and
  the host has pyyaml, so it is a latent condition rather than a live red.
* **`test_not_verified_tier::test_no_new_undeclared_infrastructure_skip_appears`**
  is red on base and on this branch with identical output, naming
  `test_trusted_pytest_entry.py`. Not mine, not touched.

---

## REQUESTS TO THE LANDER

### A. Fixes in other lanes' files that I wrote the test for but did not make

Each is currently `xfail(strict=True)`; landing the fix turns the pin red and it
must then be deleted. Ordered by blast radius.

1. **F-11 — feasibility lane, `_ppa/feasibility.py`.** `required_views` must be
   scoped per axis (or per proof, or a view must declare which axes it binds).
   Today the hard promotion gate cannot return FEASIBLE for any candidate whose
   contract declares more than one view class. **9 of 9 axes UNDETERMINED** on a
   clean, fully-measured candidate. Test:
   `test_ppa_layer_feasibility_view_scope.py` (3 pins).

2. **F-4 — record-envelope lane, `_ppa/power.py` + `_ppa/timing.py` +
   `_ppa/metrics.py`.** Producers and the canonical consumer disagree about the
   shared shape. **48/48 power records** and **every timing row** are refused;
   `MetricIndex.add` raises on a real STA row. Either producers stop writing
   `None` scope fields (or record them as declared absences) or `validate`
   accepts one — your call, either turns the tests green. Test:
   `test_ppa_layer_producer_consumer.py` (10 pins).

3. **F-5 — record-envelope lane, `_ppa/area.py`.** Three metrics declare a unit
   the metric name refuses: `cells`/`wires`/`wire_bits` vs `count`. Included in
   the 10 pins above.

4. **F-10 — `_ppa/timing.py`.** `discover_reports` must de-duplicate by artefact
   **content** (`source.sha256`), not by resolved path. Test:
   `test_ppa_layer_timing_view_dedup.py` (2 pins).

5. **F-2 — whichever lane owns the extractor seam.** `ppa_metric_extract
   --backend` must drive the five modules in `_ppa/backends/`. Test:
   `test_ppa_layer_backend_seam.py` (5 pins). Two arms that must stay green are
   included, because the tempting wrong fix is "return 0 and write an empty
   bundle".

6. **Search lane, `ppa_search_run.py` — two, both one-liners.**
   * `--this-flag-does-not-exist` exits **2**; §1 says 3. `_ppa/cli_exit.py` ships
     in this branch and is the drop-in.
   * a space document declaring **no lever** returns **rc=0** with an invented
     `budget 1 trial(s) / 1 full-PnR: proposed 1`. Should be rc=2 `[CANNOT
     CHECK]`. Note the module docstring's *"`Budget()` with no arguments is
     `max_trials=1`"* is a defensible **module** decision; this is the **CLI**
     reporting PASS over an empty population.
   Tests: `…exit_contract` (1 pin), `…vacuous_population` (1 pin).

7. **Feasibility lane, `ppa_feasibility_check.py` + `ppa_pareto_check.py`.**
   `--help` exits **3**. Their `except SystemExit: return RC_BAD_INVOCATION` needs
   to read `exc.code`; `_ppa/cli_exit.parse_or_refuse` is exactly that.
   Test: `…exit_contract` (2 pins).

### B. Generated files — NOT regenerated, per §6 and your constraint

`PROGRAM_INVENTORY.json` is stale on this branch: **`test_files` 2685 → 2692**
(7 new test files; `programs_top_level` is unchanged at 1223 because
`_ppa/cli_exit.py` is not top-level and `_ppa_jsonschema.py` is under `tests/`).

`gen_program_inventory.py --check` is **already rc=1 on pristine base with 30
problems**, and its output is **byte-identical on base and on this branch**:

```
$ diff <(base: gen_program_inventory.py --check | sort) <(branch: … | sort)
  (no output)
```

so this branch adds nothing to that gate. Please regenerate on the merged tree
and take the generator's output rather than merging either side.

### C. Protected paths — none touched

```
$ python3 -c "<intersect git status --porcelain with protected_landing_transition.json>"
  protected paths in manifest: 48
  files I changed: 26
  INTERSECTION (protected paths I touched): NONE
```

`tools/ci/repo_hygiene_gates.sh` is untouched, so **no manifest re-render is
needed** and I have no sha256 to hand you.

### D. Two things worth a follow-up lane

* the §1 **stream discipline** sweep (§6) — human summary on stdout, refusals on
  stderr, across all 14 programs. I measured one violation and did not sweep.
* an **unguarded `import yaml`** in two PPA test files (§6).
