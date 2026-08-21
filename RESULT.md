# RESULT — a corpus mode for the five PPA record gates, and the seventh wire

Base: `origin/land/ppa-tf` @ `bb90724dcd7ebe8d31474d5245a54fdce112b527`
(v1.11.32). `origin/main` is still `867de4289` / v1.11.18, so the brief's
fallback base applies. **v1.11.33 has not landed anywhere I can fetch** — this
matters and §4 says exactly how.

Branch: `jcorpus/ppa-corpus-mode`. Not pushed to `main`. No plugin version
bumped. No baseline written. `flow/phase1_phase2_phase3.yaml` untouched.
`tools/ci/protected_landing_transition.json` untouched.

Three commits:

| | commit | what |
|---|---|---|
| 1 | `3e35451b6` | `--corpus` for the five record gates, through `ppa_head_to_head_check`'s seam |
| 2 | `76aa77c77` | one `run` line: `closed_loop_edge_check` |
| 3 | `9a100b5eb` | an unused `typing` import, dropped |

Every measurement below is against `9a100b5eb` on one side and pristine
`bb90724dc` in a second worktree on the other. Both arms were run from
`_jcorpus/base` and `_jcorpus/tree`, never by stashing on a shared tree.

---

## 1. The corpus seam I copied, and why

`ppa_head_to_head_check.check_corpus` does four things. Three of them are
copied verbatim into `programs/_ppa_corpus.py`; one is deliberately not.

| | what | copied? |
|---|---|---|
| location | `_corpus_location.resolve()` / `.refuse()` | **yes, verbatim** |
| aggregation | `_SEVERITY = {REFUSED: 2, UNDETERMINED: 1, OK: 0}` + `worst_rc` | **yes, verbatim** |
| vacuous arm | zero records → rc 2, never rc 0 | **yes**, and the root is now named on stderr too |
| record discovery | `_RECORD_GLOB = "**/*head_to_head*.json"` | **no — see below** |

**Location.** `_corpus_location` exists because three gates re-derived the same
question on the same day and got it wrong the same way. Adding a fourth,
fifth… ninth hand-rolled answer would have been the same mistake at five times
the scale, so the five delegate: `$VIBE_IC_BENCHMARK_DATA` is followed, a
pointer that is SET AND WRONG stays UNDETERMINED and is never excused by
`--corpus-may-be-absent`, and "the corpus lives in another repository" is a
separate stated NO_CORPUS. Measured, on all five, in
`test_ppa_corpus_mode.py::test_a_pointer_that_is_set_and_wrong_is_never_excused`.

**Aggregation.** `flow_compliance_check.__check_program_exit_zero` maps rc 2 →
VACUOUS_PASS and rc 1 → FAIL, so 2 is the larger integer and the weaker
verdict. Aggregating a corpus with `max()` therefore lets ADDING a record
SUBTRACT a refusal — a defeat-the-gate primitive. `worst_rc` is
`ppa_head_to_head_check`'s own aggregator, and
`test_ppa_corpus.py::test_worst_rc_is_severity_order_and_not_integer_order`
asserts the difference explicitly (`max([1, 2]) == 2` sits in the test body as
the counter-example).

### The one thing I did NOT copy: the filename glob

`ppa_head_to_head_check` finds records with `**/*head_to_head*.json`. The
complaint that produced this task is *"a record filed under any other name is
simply not judged"* — and a filename glob answers that complaint with a
smaller version of itself. So `_ppa_corpus.collect` walks every `*.json` under
the corpus and selects on the **parsed document**:

| gate | selector | why that one |
|---|---|---|
| `ppa_contract_check` | `schema == vibeic.ppa.contract.v1` | PPA_INTERFACES §5: every instance document carries its schema as its first key |
| `ppa_problem_integrity_check` | same | it compares two contracts |
| `ppa_measurement_check` | `schema == vibeic.ppa.metric_bundle.v1` | coverage is a set-level question, so the record is the bundle |
| `ppa_feasibility_check` | a mapping with a `candidates` list, excluding this lane's own output schemas | the candidate-set document has no declared schema, so the selector is structural |
| `ppa_pareto_check` | same | same |

The two output documents (`vibeic.ppa.feasibility.v1`,
`vibeic.ppa.pareto_frontier.v1`) carry a `candidates` key too, and reading one
as an input would adjudicate the gate's own verdict as if it were a run.
`test_feasibility_does_not_read_its_own_verdict_document_as_an_input` builds a
real report with the real CLI, drops it into a corpus, and asserts rc 2 VACUOUS.

**The cost is disclosed, not hidden.** Every corpus run prints files-opened
beside records-selected. Measured against the largest corpus on this machine:

```
$ python3 programs/ppa_contract_check.py --corpus <repo>/benchmark-data
[PPA contract records] VACUOUS: ... (41708 JSON file(s) opened under
<repo>/benchmark-data, 0 published contract record(s) selected, 5 unreadable)
rc=2
                                                    6.77 s, 140 MB peak RSS
$ python3 programs/ppa_feasibility_check.py --corpus <repo>/benchmark-data
                                                    2.94 s, 141 MB peak RSS
```

41,708 files, under 7 s, and it finds zero PPA records — which agrees with
`docs/PPA_CURRENT_STATE.md` §3: the first PPA run has not been published. A
walk that finds nothing over a named 41,708 is a very different sentence from a
walk that finds nothing and does not say how hard it looked.

Incidental, reported and NOT fixed here (not my lane): five tracked
`*_si_timing.json` artefacts in that corpus are **truncated JSON** and named
individually by the new refusal. They are the `5 unreadable` above.

### A file nobody could parse is not a file that held no record

`*.json` that does not parse is not thereby "not a PPA record" — nobody looked.
Those are counted, NAMED, and raise the verdict to UNDETERMINED. Same rule
`_corpus_location` applies one level up to a broken pointer, and the same rule
that keeps "I could not look" from arriving as "there are none".

---

## 2. The three decisions the brief asked me to get right

### 2a. An empty corpus stays rc=2, with the root NAMED

Not rc 0, ever. These five exist to refuse a vacuous 100 % coverage, a frontier
nobody recomputed, and "every candidate is feasible" over an empty list — a
corpus mode that answered "found nothing" with a pass would have rebuilt all
three one level up.

```
$ python3 programs/ppa_contract_check.py --corpus <empty dir> ; echo rc=$?
[PPA contract records] VACUOUS: the corpus at <empty dir> carries no published
contract record(s), so NOTHING WAS VALIDATED (0 JSON file(s) opened under
<empty dir>, 0 published contract record(s) selected). This is NOT a pass: a
gate that has never met an artefact cannot have cleared one. rc=2.
rc=2
```

Five tests, one per gate (`test_*_corpus_vacuous_is_rc2_and_names_the_root`),
each asserting **both** the rc and that `str(corpus)` appears in the refusal.

And, separately, that an **absent** corpus is not an **empty** one:
`Path.glob` yields nothing for a missing directory, so without the resolution
branch both print the same zero. `test_an_absent_corpus_is_not_an_empty_one`
asserts, for all five, that only one of them says `no corpus at`.

### 2b. An exact path and a corpus are never both silently accepted — rc 3

**Decision: refuse.** `PPA_INTERFACES` §1 makes 3 the code for a bad
invocation — never a design FAIL, never "not checked". Stated in all five
docstrings and in `--help`.

| gate | refused combination |
|---|---|
| `ppa_contract_check` | `--contract` + `--corpus` |
| `ppa_measurement_check` | `--coverage`/`--compare` + `--corpus` |
| `ppa_feasibility_check` | `--candidates` + `--corpus` |
| `ppa_pareto_check` | `--candidates`/`--frontier` + `--corpus` |
| `ppa_problem_integrity_check` | `--baseline`/`--candidate` + `--corpus` |

`--contract` on the feasibility and pareto gates deliberately **does** compose
with `--corpus`: it is not a record under test, it is the policy / declared
objective set the whole corpus is adjudicated against. That is stated in both
docstrings.

**This is where I diverge from `ppa_head_to_head_check`, on purpose.** The
brief said to do what that gate does; that gate accepts both and lets
`--corpus` win **without saying so**, which cannot be reconciled with "must not
both be silently accepted". I took the requirement and am reporting the
divergence rather than copying the silence. It is not hypothetical — MEASURED
on this base:

```
$ python3 programs/ppa_head_to_head_check.py <record it REFUSES> --corpus <empty dir>
VACUOUS: the corpus carries no head-to-head record ... rc=2.
rc=2                          # the named record is never mentioned

$ python3 programs/ppa_head_to_head_check.py <the same record>
[FAIL] ppa_head_to_head_check: TOO_FEW_ARMS
rc=1
```

A refusal (rc 1, a finding about silicon) silently downgraded to rc 2 because
two arguments were both accepted. The one-line fix is in §5 as a lander
request; I did not apply it, because that file belongs to the benchmark lane.

### 2c. Two records for one identity is a CONFLICT, not a pick

`records[0]` is the move that destroys this. A gate that needs "the contract"
and finds two has not found the contract — it has found a disagreement, and
choosing buries it exactly the way `_ppa/contract.py` refuses to bury two
sources that disagree about a key (PPA-C-003: *"this contract does not choose
between them because choosing would bury the disagreement inside a digest"*).

`_ppa_corpus.identity_conflicts` is that rule at corpus scale. Per gate:

| gate | identity | comes from |
|---|---|---|
| `ppa_contract_check` | digest of the whole `identities` map | `_ppa.canonical_json.digest_of` |
| `ppa_problem_integrity_check` | same | same |
| `ppa_measurement_check` | `(metric, scope_digest)` | **`_ppa.metrics.record_key`** — the gate's own identity, not the metric name |
| `ppa_feasibility_check` | `candidate_id` | the candidate entry |
| `ppa_pareto_check` | `candidate_id` | the candidate entry |

Two claimants with **different** content → rc 1, both paths and both content
digests named. Two claimants that are **byte-identical** → a copy, not a
disagreement: printed as a NOTE and never silently deduplicated, because a
record set whose size depends on how many times somebody ran `cp` is its own
defect (that is `MetricIndex.add`'s own argument, one level down).

The contract-conflict fixture is built so the rc can only have come from the
conflict: two contracts over the **same run tree** differing only in a metric
value, each built by the real builder, each individually rc 0 — asserted in the
test before they are put in one directory together.

Contracts that declare **no** `identities` cannot be keyed. They are excluded
from the conflict scan and the exclusion is PRINTED, because a silent exclusion
is a denominator nobody can see; their own PPA-C-007 rows still reach the
verdict through the per-record run.

### The one place the corpus mode could not express the question, said out loud

`ppa_problem_integrity_check` needs a **pair**, and a corpus has no
baseline/candidate labels. Rather than pick an arm, corpus mode groups
contracts by their `problem` identity — which is the gate's own subject, "were
these two runs solving the same problem?" — and compares every unordered pair
inside a group.

* A group of **one** is rc 2 with its path named. One arm cannot be shown to be
  solving the same problem as anything, and one arm is not a comparison that
  passed.
* A contract with no MEASURED `problem` identity is not grouped at all, and
  says so. Grouping the unmeasured together would compare two runs on the
  strength of a shared absence — the exact inference PPA-C-007 exists to refuse.
* The one asymmetric clause in the comparison is the mutation allow-list, which
  the exact mode applies to the `--candidate` side only. **Corpus mode applies
  it to both arms of every pair**, so no arm escapes its own allow-list by
  being read first.

---

## 3. The fixtures — positive, negative, VACUOUS for every corpus mode

`programs/tests/test_ppa_corpus_mode.py` (54 tests) drives the five CLIs as
subprocesses, because the flow acts on the EXIT CODE and an in-process
`main(argv)` leaves the verdict-to-exit-code mapping unmeasured.
`programs/tests/test_ppa_corpus.py` (14 tests) tests the shared seam directly.

| gate | positive | negative | VACUOUS | conflict | both-given |
|---|---|---|---|---|---|
| `ppa_contract_check` | clean contract at `nested/deep/whatever-name.json` → **0** | `contract_digest` broken → **1**, PPA-C-001 | empty dir → **2**, root named | two contracts, one `identities`, different metric → **1** | `--contract` + `--corpus` → **3** |
| `ppa_measurement_check` | complete bundle at `deep/unexpected-name.json` → **0** | one expected row with NO RECORD AT ALL → **1**, `NO RECORD AT ALL` | empty dir → **2**, root named | two bundles, one `(metric, scope)`, different value → **1** | `--coverage` + `--corpus` → **3** |
| `ppa_feasibility_check` | clean candidate at `runs/not-named-candidates.json` → **0** | one dirty LVS → **1** | empty dir → **2**, root named | one `candidate_id`, two files, different metrics → **1** | `--candidates` + `--corpus` → **3** |
| `ppa_pareto_check` | two-candidate sweep at `sweep/run-17.json` → **0** | only admitted candidate INFEASIBLE → **1**, `PARETO_EMPTY_FRONTIER` | empty dir → **2**, root named | one `candidate_id`, two files, different triple → **1** | `--frontier` + `--corpus` → **3** |
| `ppa_problem_integrity_check` | two arms of one problem grouped and compared (`1 pair(s) compared`, PPA-C-013) | two DIFFERENT problems → two groups of one → **2**, `has ONE arm` | empty dir → **2**, root named | two contracts, one `identities` → **1** | `--baseline` + `--corpus` → **3** |

Three positives deliberately file the record under a name no glob would guess.
That is the property under test, not decoration.

Plus, parametrised over all five gates:

* `test_an_absent_corpus_is_not_an_empty_one` — both rc 2, only one says `no corpus at`
* `test_the_absent_corpus_opt_in_states_the_zero_it_did_not_take` — rc 0 **and** `NOTHING WAS SCANNED`
* `test_a_pointer_that_is_set_and_wrong_is_never_excused` — rc 2 even with `--corpus-may-be-absent`
* `test_a_file_nobody_could_parse_is_not_a_file_that_held_no_record` — rc 2, file named
* `test_every_corpus_run_discloses_its_denominator`

and, on the seam itself: severity order vs integer order, an unknown rc treated
as most severe, conflict vs copy vs neither, a conflict naming **every**
claimant rather than the first two, a selector that RAISES not being read as
"no", and delegation to `_corpus_location` for both the absent and the
broken-pointer rows.

`ppa_contract_check` also has `test_contract_corpus_identical_copies_are_disclosed_not_deduplicated`
and `test_contract_neither_path_nor_corpus_is_not_a_pass`.

### Mutation arms — revert it, the named test goes red

Each mutation was applied to `programs/_ppa_corpus.py`, the named selection was
run, then the mutation was reverted by the inverse edit (never
`git checkout --`) and the same selection re-run. `__pycache__` cleared on both
sides of every arm. `git status` clean afterwards.

| mutation | what it restores | mutated | restored |
|---|---|---|---|
| `vacuous()` returns `RC_OK` | an empty corpus passes | **6 failed** | 6 passed |
| `both_given()` returns `RC_OK` | an exact path + a corpus both accepted | **6 failed** | 6 passed |
| `identity_conflicts()` returns `([], [])` | the corpus walk takes the first match, says nothing | **9 failed** | 9 passed |
| `report_unreadable()` always `RC_OK` | an unparseable file silently skipped | **6 failed**, 1 passed | 7 passed |
| `open_corpus()` skips the `is_dir` branch | an absent corpus read as an empty one | **6 failed** | 6 passed |

(The one that stays green under the fourth mutation is
`test_a_selector_that_raises_has_not_answered_no`, which asserts on
`scan.unreadable` directly and does not route through `report_unreadable` — it
is the fixture for a different half of the same rule.)

---

## 4. `closed_loop_edge_check` — re-measured, wired, and what actually happened

### The re-measurement, on MY base

```
$ git log --oneline -1
bb90724dc ppa(report): claims.json ... [v1.11.32]
$ python3 programs/closed_loop_edge_check.py ; echo rc=$?
[PASS] closed_loop_edge_check: checked 22 declared closed_loop edge(s) over 69
step(s); every edge resolves to a declared step, closes a loop, carries a
trigger, and leaves a step whose gate can produce a verdict. Edges: 1.6x->1,
2->1, 3->1, 4->1, 5->1, 8->7, 9->1, 10->7, 13->9, A7->A3, A9->A3, 14->9, 20->19,
23->32, 24->15, 25->21, 26->21, 27->21, 28->15, 31->32, 32->32, 33->17
rc=0
```

**rc 0**, and byte-for-byte the sentence the brief quoted. Also re-run from
`$ROOT` (not the plugin directory), because that is the cwd the wired line gives
it: rc 0 there too. So it is wired as `run`, on the line the brief specified,
directly after `run "flow dependency graph"` — the flow document's other graph.

### The expected effect did NOT happen, and the reason is the base

The brief expected `checker execution wiring` and `gates are wired to
something` to go FAIL → PASS. **They do not, on this base.** By name:

| gate | base `bb90724dc` | with my line |
|---|---|---|
| `checker_execution_wiring_audit` | rc 1, **7** names | rc 1, **6** names |
| `gate_is_wired_check` | rc 1, **7** names, unwired 65 | rc 1, **6** names, unwired 64 |

The seven, identical in both gates:

```
closed_loop_edge_check                    <- removed by my line
closed_loop_executable_coverage_check
ppa_contract_check
ppa_feasibility_check
ppa_measurement_check
ppa_pareto_check
ppa_problem_integrity_check
```

`closed_loop_edge_check` is the one that leaves both lists, and it is the only
one that leaves. The other six are the SIX GATES THE JWIRE LANE WIRED — and
that work is not on `origin/land/ppa-tf`, on `origin/main`, or on any branch I
can fetch (I grepped every `origin/*` ref for a `repo_hygiene_gates.sh` that
mentions any of the seven: zero hits). v1.11.33 has not landed.

So the brief's sentence "*it is the SEVENTH name … and it is the reason both
still exit 1*" is true **on jwire's tree** and not on mine, where it is the
first of seven.

### The claim is still verifiable, and I verified it

Scratch tree only, reverted immediately, not committed: I added the six missing
`run` lines beside mine and re-measured.

```
[PASS] no NEW test-only checker (34 recorded); 1 deliberately unwired, disclosed
rc=0                                             <- checker_execution_wiring_audit

  gates: 615   unwired: 58 (baseline 59)   of those named in a skill: 28
  [NOTE] baseline shrank — now wired: analog_liberty_nonzero_delay_check.
[PASS] gate_is_wired: no gate newly unwired; the baseline has not grown.
rc=0                                             <- gate_is_wired_check
```

Both rc 0 with all seven wired; rc 1 with any of them missing. **My one line is
the last missing piece of that set, not a partial one** — and the six that
remain are a lander request (§5), not something I shipped a second copy of into
a pinned protected file that another lane is already editing.

That run also settles the baseline question the brief raised: with `unwired 58`
against `baseline 59`, `gate_is_wired_check` **returns rc 0 while the baseline
is shrunk**. `--write-baseline` is not needed to make it green and was not run.
The `[NOTE] baseline shrank — now wired: analog_liberty_nonzero_delay_check`
line is left standing, unchanged, as a decision for the owner.

---

## 5. A/B by TEST ID — zero new red

Selection, not the whole suite (measured earlier at load 276 with 0 free memory,
per the brief): every test my change can reach. That is 112 files —

* the 51 `test_ppa_*` / `test_closed_loop_*` / `test_readme_ppa_*` files, for the
  five gates and the seam;
* every one of the 62 files that parses `tools/ci/repo_hygiene_gates.sh`, for the
  one wired line (`grep -rln repo_hygiene_gates programs/tests/`).

Same selection both sides, `-p no:randomly`, `--timeout=600`, separate
`--basetemp` per arm (a shared basetemp makes two concurrent runs delete each
other's `tmp_path`).

```
BASE  bb90724dc   11 failed, 2409 passed, 19 skipped  (914.80s)
TREE  9a100b5eb   11 failed, 2477 passed, 19 skipped  (928.88s)
```

`+68` passed is exactly the two new files: `test_ppa_corpus_mode.py` 54 +
`test_ppa_corpus.py` 14.

By ID, not by count:

```
$ comm -13 base_failed_ids.txt tree_failed_ids.txt      # NEW RED
(empty)
$ comm -23 base_failed_ids.txt tree_failed_ids.txt      # fixed
(empty)
$ comm -12 base_failed_ids.txt tree_failed_ids.txt | wc -l
11
```

**Zero new red, and the same eleven IDs on both sides:**

```
test_issue1035_five_gates_declare_where_they_are_enforced.py::test_the_audit_exits_zero_and_names_none_of_the_five
test_issue1035_five_gates_declare_where_they_are_enforced.py::test_the_recorded_register_did_not_grow_to_absorb_the_five
test_issue1235_coverage_gate_declares_where_it_is_enforced.py::test_the_audit_exits_zero_and_names_this_gate_as_neither_kind_of_debt
test_issue1241_vendored_attribution_wired.py::test_the_audit_returns_a_clean_verdict
test_issue1470_atomic_declared_report.py::test_the_gate_is_green_and_the_ratchet_holds
test_issue927_blocking_gate_ignores_mutable_registry_pointer.py::test_the_blocking_verdict_is_identical_with_and_without_a_registry
test_issue927_blocking_gate_ignores_mutable_registry_pointer.py::test_the_blocking_half_makes_no_registry_call_at_all
test_macro_obs_gate_enforcement_declared.py::test_the_audit_exits_zero_and_names_neither_gate_as_debt
test_orphan_scan_reads_the_landing_gate_runner.py::test_the_shipped_audit_no_longer_calls_the_coordinator_unreachable
test_three_orphan_checkers_have_a_machine_runner.py::test_the_audit_returns_a_clean_verdict
test_v1_9_63_issue693_repo_process_family_wiring.py::test_the_checker_population_covers_checker_shaped_names
```

All eleven are red on pristine `bb90724dc` with nothing of mine in the tree.
Several of them assert `checker_execution_wiring_audit` exits zero — which is
the seven-unwired-gates state of §4 — so they will go green when the rest of
that set is wired, and stay red until then. Removing one of seven names does not
move any of them, and I did not expect it to.

Not run: the whole `programs/tests` suite. Explicitly out of scope per the
brief, and nothing outside the selection above imports the five gates, the new
seam, or the hygiene script.

---

## 6. Hygiene by GATE NAME — the FAIL set is byte-identical, plus one new PASS

Full `tools/ci/repo_hygiene_gates.sh --summary-json` on each arm.

```
BASE  bb90724dc   80 declared, 65 passed, 10 failed, 5 NOT CHECKED   275s   load 0.78
TREE  9a100b5eb   81 declared, 66 passed, 10 failed, 5 NOT CHECKED   285s   load 2.04
```

**The FAIL set, before and after, by name — identical, ten each:**

```
checker execution wiring
d3 declaration/manifest parity
declaration scans strip comments
declared reports are written atomically
flow-gate enforcement audit
gates are host-independent
gates are wired to something
image-version pins are internally consistent
liar census controls still fire
prose extractors read polarity
```

```
new in tree:  none
gone in tree: none
```

**NOT CHECKED, before and after — identical, five each:**

```
PPA head-to-head records
blocker list contract on committed reports
corpus "published cells carrying a routed DEF" is EMPTY — nothing was checked over it
engineering evidence fresh
input-doc claims vs installed PDK
```

**The only difference in the declared name set is the gate I added, and it
passes:**

```
added:   closed-loop edges resolve      PASS, 0 s
removed: none

── closed-loop edges resolve
[PASS] closed_loop_edge_check: checked 22 declared closed_loop edge(s) over 69
step(s); every edge resolves to a declared step, closes a loop, carries a
trigger, and leaves a step whose gate can produce a verdict.
```

So the suite goes **10 failed → 10 failed**, not the 9 → 7 the brief predicted.
The 9 is jwire's tree with their six gates wired and this seventh missing; my
base has neither, which is the same fact §4 measures from the other side. What
IS true on both trees: the gate I wired is green, it costs 0 s, and it added no
red.

`gates are host-independent` is red on both arms and was red before anything of
mine existed; both arms are recorded with their loadavg above because that gate
re-runs every other gate in a fresh worktree and is the one whose verdict a busy
machine could plausibly move. It did not move.

---

## 7. REQUESTS TO THE LANDER

### R1 (BLOCKING) — `tools/ci/repo_hygiene_gates.sh` is a pinned protected path

`tools/ci/protected_landing_transition.json` pins it at index 11 with
`roles: ["authority"]`, and `current` and `next` currently hold the SAME hash —
so this one-line addition needs a **PREPARE/ACTIVATE pair**. I did not touch
that file (lander-owned, transition `retire-37p5self-v1` in flight). Here are
the bytes to render the manifest with:

```
path      tools/ci/repo_hygiene_gates.sh
mode      100755                       (unchanged)

BEFORE (matches the pinned current/next on bb90724dc, verified)
  blob_oid  b9a7609f63487b9e1dd2f323fdcf0166c1f91e41
  sha256    f5889cd4155389473129eb24e782d89468d418d2386495b7e73d6c5411866f29
  size      105060

AFTER
  blob_oid  1b185000f5264c1e8c28a83b319b544b91cb333e
  sha256    a176f86b8c330879ce34a78c72fe669738bffaa5e281c1ef8a0b82216ee2c09b
  size      106024
```

`+964` bytes: one `run` line and thirteen comment lines. `bash -n` clean.
If jwire's six lines land in the same window, the AFTER hash changes and must be
re-rendered against the merged file — a manifest is rendered against ONE base
and a text merge of two produces a manifest that matches no tree.

### R2 — `ppa_head_to_head_check` accepts an exact path AND `--corpus`, silently

Measured in §2b: a record it would REFUSE (rc 1) plus an empty `--corpus`
returns rc 2 and never mentions the record. That is a finding about silicon
downgraded to "not checked" by an argument nobody was told won. The five gates
in this branch refuse the combination; the sixth still does not, and the file
belongs to the benchmark lane. The change is four lines in
`ppa_head_to_head_check.main`, immediately after `args = ap.parse_args(argv)`:

```python
    if args.corpus is not None and args.record:
        print("[PPA head-to-head records] REFUSE (bad invocation): a record "
              "path and --corpus were both given. Give exactly one. rc=3.",
              file=sys.stderr)
        return 3
```

No shipped caller passes both — the flow's step-36 clause is
`ppa_head_to_head_check --corpus .`, the hygiene line is
`--corpus "$ROOT/benchmark-data"`, and no test in
`test_issue1121_ppa_head_to_head.py` or `test_ppa_benchmark_fairness.py`
supplies both (grepped). The gate's docstring should gain one sentence saying
which wins, per the same rule the five now state.

### R3 — the other six gates that keep both wiring gates red

`checker_execution_wiring_audit` and `gate_is_wired_check` are rc 1 on
`origin/land/ppa-tf` over SEVEN names. My line removes one. The other six are
jwire's v1.11.33, which is not on any fetchable ref. If that work lands, nothing
here is needed. If it does not, these are the lines, and the corpus mode in this
branch is what makes the five PPA ones wireable at all:

```sh
run "closed-loop executable census" "$ROOT" python3 "$PG/closed_loop_executable_coverage_check.py"
run_tolerating_uncheckable "PPA contract records"     "$ROOT" python3 "$PG/ppa_contract_check.py"           --corpus "$ROOT/benchmark-data"
run_tolerating_uncheckable "PPA measurement records"  "$ROOT" python3 "$PG/ppa_measurement_check.py"        --corpus "$ROOT/benchmark-data"
run_tolerating_uncheckable "PPA candidate sets"       "$ROOT" python3 "$PG/ppa_feasibility_check.py"        --corpus "$ROOT/benchmark-data"
run_tolerating_uncheckable "PPA frontiers"            "$ROOT" python3 "$PG/ppa_pareto_check.py"             --corpus "$ROOT/benchmark-data"
run_tolerating_uncheckable "PPA problem integrity"    "$ROOT" python3 "$PG/ppa_problem_integrity_check.py"  --corpus "$ROOT/benchmark-data"
```

`run_tolerating_uncheckable`, not `run`, and MEASURED rather than assumed: all
five return **rc 2** in this repository, because `benchmark-data/` moved to its
own repository in v1.10.56 and is absent here. That is the same treatment
`ppa_head_to_head_check` already gets on the line above. **Do not add
`--corpus-may-be-absent`** to these five: it would turn that rc 2 into rc 0, and
the whole argument of this branch is that a gate which never met an artefact has
not cleared one. Both gates return rc 0 with these six plus mine (measured, §4).

### R4 — `docs/PPA_CURRENT_STATE.md` §5 goes stale when this lands

§5 is titled *"What is red on `main` right now"* and its subject is
`closed_loop_edge_check` being consulted by no automatic verdict. That stops
being true for that gate the moment commit 2 lands. The paragraph is still
correct about the other six names. I did not edit it: the file is measured
against `867de4289` and re-dating it to a commit I have not measured it against
would be worse than leaving it stamped.

### R5 — `RESULT.md` collides with `jreq/lander-three`

That branch also adds a root `RESULT.md`. Two lane reports are independent
documents and a text merge of them is meaningless; rename one at landing (this
one can become `RESULT_jcorpus.md`) or land them in separate commits and keep
both bodies.

### R6 — informational, for whoever owns the published corpus

The 41,708-file walk in §1 named five tracked `*_si_timing.json` artefacts under
`benchmark-data/ic/**/phase3/stage3/extracted/` that are **truncated JSON**
(unterminated string / missing delimiter, mid-file). Not my lane and not fixed
here; before this branch nothing walked that tree looking, so nothing reported
them.

### R7 — `gate_is_wired_check`'s shrunk baseline is left standing

`[NOTE] baseline shrank — now wired: analog_liberty_nonzero_delay_check. Re-run
with --write-baseline.` was NOT actioned, per the brief. Measured consequence:
with all seven wired the gate reports `unwired 58 (baseline 59)` and returns
**rc 0** — the shrunk baseline does not make it red, so writing the baseline is
a tidiness decision for the owner and not a landing prerequisite.

### R8 — every push from a worktree is blocked by a gate that cannot look

Not caused by this branch, and worth writing down because the dispatch doctrine
tells every agent to work in an isolated worktree. `benchmark-data/` is **not
tracked** (`git ls-files benchmark-data` → 0), so it exists only in the primary
checkout. The pre-push hook runs

```
benchmark_evidence_structure_check.py --tree benchmark-data --changed-since $PUSH_BASE
```

which in any worktree reports `UNDETERMINED: --tree benchmark-data is not a
directory` — and the hook correctly treats NOT CHECKED as not passed, so the
push is refused. The gate is right; it genuinely could not look.

The documented remedy works and is what I used — the pointer `_corpus_location`
exists for:

```
$ VIBE_IC_BENCHMARK_DATA=<path to a benchmark-data clone> git push -u origin <branch>
note: VIBE_IC_BENCHMARK_DATA overrides --tree benchmark-data -> <clone>
benchmark_evidence_structure_check: no evidence folders changed since origin/main
rc=0
```

Note the two are NOT the same verdict and must not be conflated: with the
pointer set and **no** `--changed-since`, the same gate returns rc 1 over
`5/60 conformant` — a real, pre-existing corpus condition that has nothing to do
with this branch and that the hook's `--changed-since` correctly scopes out.
Either document the pointer in the push instructions, or give the hook a stated
NO_CORPUS opt-in the way the hygiene gates have one; the current state makes
every worktree push look like a finding about the change being pushed.

### Not requests — checked and clean

* `programs/INDEX.md` / `PROGRAM_INVENTORY.json` need **no** regeneration:
  `_ppa_corpus.py` is `_`-prefixed and `tools/gen_programs_index.py` skips those
  (`--check` PASSES on this tree, 1150 programs indexed). None of the five
  gates' docstring first lines changed.
* `plugin_full_audit` D1 required a test for the new module by name; it has one
  (`tests/test_ppa_corpus.py`), and D1/D2 both PASS.
* No flow step, no gate clause, no schema and no `CAPTURE_ROUTING` entry is
  needed for anything in this branch.

---

## 8. Constraints, each one checked rather than assumed

| constraint | how it was honoured |
|---|---|
| do NOT push to `main` | branch `jcorpus/ppa-corpus-mode`; `main` never checked out in either worktree |
| do NOT bump the plugin version | `.claude-plugin/plugin.json`, `marketplace.json` and every version-bearing file untouched — `git diff bb90724dc..HEAD --stat` lists nine changed files plus this report, none of them a version file |
| do NOT `--write-baseline` on any hygiene gate | not run. §4 measures that `gate_is_wired_check` returns rc 0 with the baseline shrunk anyway, so the NOTE is a decision and not a blocker (R7) |
| do NOT touch `tools/ci/protected_landing_transition.json` | untouched; the manifest bytes it needs are in R1 instead |
| do NOT touch `flow/phase1_phase2_phase3.yaml` | untouched. `closed_loop_edge_check` READS it and asserts nothing about editing it |
| repo artefacts ENGLISH ONLY, no foundry / node / SKU / codename | the commit-message hook passed on all three commits; the diff and both new files were grepped for the vendor, node and tool-vendor vocabulary — zero hits. §1 deliberately reports the five broken corpus artefacts by directory pattern rather than by run label for the same reason |
| never `pgrep`/`pkill` a pattern that can match my own command line | no `pgrep`/`pkill` was used to control anything. One exploratory `pgrep -f` did match its own shell — it was replaced with a file-existence wait, and nothing was killed |
| do not run the whole `programs/tests` suite | 112 selected files, both arms, §5 |
| mutation restore never via `git checkout --` | every mutation was reverted by its inverse edit, `__pycache__` cleared on both sides, `git status` verified clean afterwards |
