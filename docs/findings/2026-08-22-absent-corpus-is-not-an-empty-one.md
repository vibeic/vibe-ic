# An ABSENT corpus is not an EMPTY one — the ruling, the measurement, and its bound

_Measured 2026-08-22 on host `8HD-6` with the SHIPPED
`tools/ci/repo_hygiene_gates.sh` rather than with a fixture, and RE-measured the
same day against the two commits by name: `81cd5321b`, the last commit before
the fix, and `a4caccefe`, `main` carrying it. Pure repository gate machinery: no
design, PDK, vendor or part identifier appears._

Closes the defect filed as vibe-ic#1764.

**This revision corrects an overstatement in the first one.** The first
revision, written by the run that made the change, said the fix stopped `main`
closing the hygiene DAG green and that `lane_hygiene` would begin returning 2
where it returned 0. Re-measured against both commits, neither is true as
stated: the closing rc of the shipped hygiene script is 2 in **both** states on
**both** commits, and the waiver the fix closes was not reachable in state A on
the production path. The defect and the fix stand; the claim about their reach
did not, and a record that overstates its own cost is the same class of error as
a row that overstates its own coverage. What is true, measured, is below.

## The two states, and why one name for both is a false claim

| state | what actually happened |
|---|---|
| **A** — nothing at `benchmark-data/`, `VIBE_IC_BENCHMARK_DATA` unset | nothing was opened |
| **B** — a corpus resolved, its index carries no routed DEF | it WAS read, and it holds none |

**B is a measurement.** Somebody looked, and the population is 0. **A is the
absence of a measurement.** Reporting A under B's sentence claims a measurement
nobody took, which is the same class of defect as calling rc 2 a pass.

## Measured, on the shipped wiring, both arms

`bash tools/ci/repo_hygiene_gates.sh --list --summary-json …`, over the corpus
`published cells carrying a routed DEF`:

| commit | pointer | `corpora[].expansion` | recorded label |
|---|---|---|---|
| `81cd5321b` (before) | UNSET (state A) | `EXPANDED` | `corpus "…" is EMPTY — nothing was checked over it` |
| `81cd5321b` (before) | SET (state B) | `EXPANDED` | `corpus "…" is EMPTY — nothing was checked over it` |
| `a4caccefe` (after) | UNSET (state A) | **`NO_CORPUS`** | **`corpus "…" was NOT FOUND — nothing was opened to check`** |
| `a4caccefe` (after) | SET (state B) | `EXPANDED` | `corpus "…" is EMPTY — nothing was checked over it` |

The pointer used for the SET arm is a git checkout whose `ic/` subtree is
tracked in the index and carries **0** files matching
`*/*/phase3/stage3/pnr/routed.def` — the shape of the genuine #1763 population,
which is what state B is. It has to be a real checkout, not a loose directory:
the producer reads git's INDEX, and over a directory git does not know it
answers rc 2 UNDETERMINED rather than 0, which is a third state again.
**Row B is byte-identical before and after.**

The producer now says which state it is in, and names the thing that makes it
that state:

    state A, rc 3: NO_CORPUS: nothing at <repo>/benchmark-data/ic and
                   VIBE_IC_BENCHMARK_DATA is unset … NOTHING WAS SCANNED
                   NOT FOUND (rc 3): … 0 routed DEF(s) is the ABSENCE of a
                   measurement, not a measurement of zero.

    state B, rc 0: MEASURED EMPTY: git's index at <corpus> was read under 'ic'
                   and it publishes no */*/phase3/stage3/pnr/routed.def. This IS
                   a measurement …

## The second collapse, in the waiver — and an honest bound on it

vibe-ic#1764 reads as a wording defect because both states already refuse at
`gate_dispatch_finish` (rc 2), and they do. But `gate_dispatch_finish` is not
the only closing verdict in the tier. `repo_hygiene_parallel._summary_rc` is the
closing rc of the parallel hygiene DAG, and it **waives exactly one unexempted
NOT_CHECKED**: the phase-1 bootstrap row for a corpus that was READ and
publishes nothing. An absent corpus reached that waiver wearing the same label
and the same `expansion`, so the waiver answered for it too.

Re-measured on both commits — the real producer through the real
`_gate_dispatch.sh`, then that same commit's own `_summary_rc` over the record
it produced:

| commit | state | `expansion` | `gate_dispatch_finish` | `_summary_rc` |
|---|---|---|---|---|
| `81cd5321b` (before) | A absent | `EXPANDED` | 2 | **0** |
| `81cd5321b` (before) | B read-empty | `EXPANDED` | 2 | 0 — intended bootstrap |
| `a4caccefe` (after) | A absent | **`NO_CORPUS`** | 2 | **2 — refused** |
| `a4caccefe` (after) | B read-empty | `EXPANDED` | 2 | 0 — **unchanged** |

Before the fix the two states were byte-indistinguishable in every column. After
it they differ in exactly two, and row B is untouched.

### How far that reaches, stated against my own first finding

The first revision of this file called this *"`main` closes the hygiene DAG
green over a corpus nothing opened"*. That is stronger than what is true, and
the bound belongs in the record next to the finding.

`repo_hygiene_parallel` has exactly one production caller,
`gatekeeper_review.repo_hygiene_gate`, and it binds the corpus **before** the
set and returns rc 2 with a named remedy if it cannot:

    if script is None:
        corpus_env_or_none, corpus_refusal = _published_corpus_binding()
        if corpus_refusal is not None:
            return GateResult(name, 2, corpus_refusal)

`_published_corpus_binding` tries `VIBE_IC_BENCHMARK_DATA`, then
`VIBEIC_BENCHMARK_DATA_CHECKOUT`, then `$HOME/_matrix_benchmark_data`, and
refuses unless the result is the ROOT of a git checkout carrying `ic/` with a
readable HEAD — it never returns rc 0 unbound. And a pointer that is **set and
wrong** makes the producer rc 2 UNDETERMINED, not absent. So the only way into
`_summary_rc` on that path is with a corpus that resolved: **state A could not
reach the waiver on the production path.** `script is not None` is a unit-test
seam with deliberately no CLI flag, so it is not a second way in.

So the waiver collapse was **latent, not live** — reachable by invoking
`repo_hygiene_parallel.py` directly on a machine with no pointer, not by a
review or a landing. It was still worth closing: that binding was the single
guard standing between an unmeasured corpus and a waived refusal, and "one guard
is enough" is not how the rest of this repository is built. What the fix buys is
that the waiver no longer *depends* on that binding being correct.
`test_every_unresolvable_corpus_is_an_ERROR_and_the_set_never_runs` pins the
binding; `test_an_absent_corpus_does_not_close_the_hygiene_dag_green` pins the
waiver. Neither now carries the other.

## What this changes operationally: no exit code moves, measured

The first revision claimed:

> A hand-run `tools/ci/repo_hygiene_gates.sh`, or `gatekeeper-land.sh`'s
> `lane_hygiene`, on a machine with no pointer exported: `full:repo-hygiene`
> now returns rc 2 where it used to return 0.

**That is false, and the measurement above is what refutes it.** `lane_hygiene`
(`tools/gatekeeper-land.sh:1373`) runs `bash tools/ci/repo_hygiene_gates.sh`,
whose closing rc is `gate_dispatch_finish` — not `_summary_rc`; the shell script
never calls the parallel runner. `gate_dispatch_finish` measured **2 in state A
on `81cd5321b` as well as on `a4caccefe`**. The row was blocking before and is
blocking now, at the same severity, in the same run, with the same closing rc.

* **The review / landing path: nothing changes.** It is always in state B, and
  state B is byte-identical before and after. #1763 is untouched.
* **A hand-run `repo_hygiene_gates.sh` with no pointer: nothing changes.**
  Still rc 2, still one blocking NOT CHECKED row. Only its *sentence* changed,
  from "is EMPTY — nothing was checked over it" to "was NOT FOUND — nothing was
  opened to check".
* **A direct `python3 repo_hygiene_parallel.py` with no pointer: this is the
  one behaviour change.** The absent-corpus row is no longer waived, so that
  invocation stops treating an unopened corpus as the bootstrap row.

This is the answer to the brief's *"whatever you change must run clean on the
current repo; a guard that fires on the state we just shipped is not a guard"*:
**nothing new fires.** What changed is that the row now tells the truth about
which state it is in.

Worth noting that `gatekeeper_review.py` already states this exact rule one
layer up, at the binding it performs:

> SET AND WRONG IS NOT ABSENT (`_corpus_location.py:26-29`), and NOTHING
> ANYWHERE is not a pass either. The two are different states with different
> remedies, so they get different sentences; neither is rc 0.

vibe-ic#1764 is that same rule missing one layer down.

## The ruling: which is blocking

**Both. Neither becomes a pass, and neither becomes exemptable.**

* **B (read, and empty)** stays exactly what it is today: an honest NOT CHECKED,
  unexempted, process-attested, `gate_dispatch_finish` refuses on it. This is
  the #1763 row and it is unchanged in bytes, for the reason #1763 gave — every
  published cell was withdrawn on 2026-08-20, so the population really is 0 and
  nothing was checked over it.
* **A (nothing opened)** is also a blocking, unexempted, process-attested NOT
  CHECKED. It gets its own row, its own sentence and its own expansion state
  (`NO_CORPUS`), because the only thing wrong with it before was the *sentence*,
  not the *severity*.

Nothing about this change can be used to stop the routed-DEF row blocking.

## Where I disagree with the issue, and why

vibe-ic#1764 proposed `may_be_absent=False`, which makes state A **rc 2 →
`producer FAILED — denominator unknown`**. I did not do that, and the reason is
that it replaces one wrong sentence with a different wrong sentence.

* rc 2 in this repository means UNDETERMINED-because-somebody-said-where-it-is-
  and-was-wrong: a broken pointer, a loose directory, a failed git query. In
  state A **nobody said anything and nothing is broken.** The producer worked
  and correctly reported that there was nothing to open.
* `_corpus_location.refuse(may_be_absent=True)` is a considered, documented
  opt-in — a repository that no longer carries the published tree is not
  thereby misconfigured. The issue proposed flipping it at this one call site,
  which leaves the opt-in standing but makes this producer disagree with every
  other consumer of `refuse` about what absence means; the fix taken leaves the
  opt-in standing *and* keeps the agreement, by adding a state instead of
  re-labelling one.
* The `producer FAILED` row says *"the $n item(s) below are what it managed to
  print and NOT the corpus"*. In state A there is no partial anything.

So state A leaves with `NO_CORPUS_RC = 3`, a code that meant nothing before,
and `GATE_DISPATCH_ABSENT_RC=3` in `tools/ci/_gate_dispatch.sh` matches it. The
two spellings live in two languages, which is exactly what drifts, so
`test_the_absent_exit_code_is_one_number_in_two_languages` pins them equal and
pins 3 clear of 0 (a measured population), 1 (a finding) and 2 (UNDETERMINED).

A producer that exits 3 **and** prints items has contradicted itself and is read
as `producer FAILED`, so a truncated population can never wear the quiet row.

## What pins it

Both states, as a pair, because the collapse was a statement about a pair:

* `test_an_absent_corpus_and_a_read_but_empty_one_do_not_share_a_verdict` —
  the producer, both states in one call, different rc and different message.
* `test_the_dispatcher_gives_absent_and_empty_different_rows` — the real
  producer through the real `_gate_dispatch.sh`: different labels, different
  `expansion`, different attested `semantic_sha256`, and **both** rc 2
  NOT_CHECKED with `exempt_until: None`.
* `test_the_shipped_hygiene_script_reports_this_checkout_as_NOT_FOUND` — the
  shipped script against this checkout, which is where the defect actually lived.
* `test_a_producer_that_claims_absence_and_prints_items_is_a_failure`.
* `test_a_corpus_nothing_opened_is_not_reported_as_one_that_was_read` — the
  downstream delta may not re-collapse what the dispatcher split.
* `test_an_absent_corpus_does_not_close_the_hygiene_dag_green` — **the one that
  matters**: both states end to end through the real wiring, asserting the
  closing rc of the DAG. A hand-built record could not show this, because at
  `81cd5321b` the defect *is* that the absent state is handed the empty row's
  label; a fixture that types the right label in has already fixed the bug it
  tests.
* `test_the_phase1_waiver_covers_the_measured_empty_row_and_not_the_absent_one`
  and `test_the_waiver_checks_the_shape_and_not_only_the_label` — these two pass
  at `81cd5321b` as well. They are guards for the future, not the red, and this
  record does not claim otherwise.

**Red without the fix, re-measured on this tree.** A clean worktree of this
branch with the three production files reverted and every test kept —
`tools/ci/routed_def_corpus.py` and `tools/ci/_gate_dispatch.sh` to
`81cd5321b`, `repo_hygiene_parallel.py` to `24a097287^` — run with
`PYTHONDONTWRITEBYTECODE=1`:

    7 failed, 57 passed in 23.26s

    FAILED test_an_unconfigured_moved_corpus_is_explicit_no_corpus
    FAILED test_the_absent_exit_code_is_one_number_in_two_languages
    FAILED test_an_absent_corpus_and_a_read_but_empty_one_do_not_share_a_verdict
    FAILED test_the_dispatcher_gives_absent_and_empty_different_rows
    FAILED test_a_corpus_that_was_read_and_holds_none_says_so
    FAILED test_the_shipped_hygiene_script_reports_this_checkout_as_NOT_FOUND
    FAILED test_an_absent_corpus_does_not_close_the_hygiene_dag_green

The two `test_repo_hygiene_parallel.py` waiver guards named above stayed green
under the revert, exactly as this record says they would — they are guards for
the future, and counting them as part of the red would have inflated it.

The sharpest failure is the last, because the log it captures holds the entire
defect in one place: the producer says it scanned nothing, and the very next
lines call the corpus empty and let the DAG close 0.

    [routed-def corpus] NO_CORPUS: nothing at …/benchmark-data/ic and
    VIBE_IC_BENCHMARK_DATA is unset … NOTHING WAS SCANNED, 0 routed DEF(s)
    were examined and nothing is claimed about them
       ^^ NOT CHECKED (rc 2, BLOCKING; no exemption): corpus "…" is EMPTY —
          nothing was checked over it [0s]
    AssertionError: the parallel hygiene DAG closed GREEN (rc 0) over a corpus
    that was NEVER OPENED … assert 0 == 2

and, in the machine-readable record,

    assert [{'name': 'published cells carrying a routed DEF', 'items': 0,
             'gates': 1, 'expansion': 'EXPANDED'}]     <- a MEASURED population
        == [{…                       'expansion': 'NO_CORPUS'}]  <- nothing opened

## The question a new expansion state always raises: what does an OLD reader do with it?

`NO_CORPUS` is a value that did not exist before, and `hygiene_finding_delta`
runs from **the verifier's tree, not the tree under test**
(`landing_merge_verdict.py:917-919` — "a tree under test must not be able to
supply the program that judges it"). So a candidate carrying this change can be
differenced by a verifier that predates it, and its `_validate_record` would
meet an expansion state it does not know.

Traced, not assumed. It raises `Refusal("unknown expansion state")` →
`compare` returns `status: REFUSED` → `landing_merge_verdict.py:1284` marks the
run **`unmeasurable = True`** and blocks:

    THE HYGIENE FINDING DIFFERENTIAL COULD NOT BE COMPUTED, so whether this
    branch introduced a hygiene finding is UNKNOWN

That is the correct direction, and the reason this needs no compatibility shim:
an old reader meeting the new state gets an **honest UNMEASURABLE that blocks**,
never a pass. The state it cannot parse is one it must not silently fold into
`EXPANDED` anyway — that fold is the whole defect.

It also should not arise on that path at all: `gatekeeper_review` binds the
corpus before the set, so the landing arms are in state B. Both statements are
here because the second is a single guard and the first is what happens when a
single guard is wrong.

The reverse direction is already handled: `hygiene_finding_delta._validate_record`
(`:603-611`) **accepts** `NO_CORPUS` alongside `EXPANDED` and `PRODUCER_FAILED`
rather than refusing, and says in the source why it is not folded into
`EXPANDED`. `absent_corpora` is read with `.get`, so a record from an older
dispatcher simply has none.

## Corpus sweep

### 1. The shipped gate list, diffed between the two states, on both commits

The strongest form of *"nothing new fires"*, and it needs no fixture: run the
real `tools/ci/repo_hygiene_gates.sh --list --summary-json` on a clean worktree
of each commit, once with `VIBE_IC_BENCHMARK_DATA` unset (state A) and once
pointed at a git checkout whose `ic/` subtree publishes no
`*/*/phase3/stage3/pnr/routed.def` (state B — the genuine #1763 population), and
diff the declared gate lists label for label.

| commit | declared | labels differing between state A and state B |
|---|---|---|
| `81cd5321b` (before) | 87 | **0 of 87** — the two states were indistinguishable |
| `a4caccefe` (after) | 93 | **1 of 93** — and it is the routed-DEF row |

The one line that differs, on the tree carrying the fix:

    state A   corpus "…" was NOT FOUND — nothing was opened to check   NO_CORPUS
    state B   corpus "…" is EMPTY — nothing was checked over it        EXPANDED

The 87 → 93 is 200 commits of new gates between the two, not this change: within
each commit the comparison is state A against state B on the same tree, which is
what the claim is about.

**State B's row is exactly the sentence #1763 adjudicated**, unchanged in bytes,
for the reason #1763 gave — every published cell was withdrawn on 2026-08-20, so
the population really is 0, and NOT CHECKED + BLOCKING are both correct there.
The brief's *"your change must leave that row saying exactly what it says today"*
is satisfied by measurement, not by assertion.

### 2. Every test file that reads the changed machinery

The population is a query, not a judgement call — every `test_*.py` under
`vibe-ic-marketplace/plugins/vibe-ic/programs/tests` and under `tools/ci`
matching

    gate_dispatch_over | _gate_dispatch\.sh | GATE_CORPUS_STATE |
    routed_def_corpus | repo_hygiene_gates\.sh | hygiene_finding_delta |
    repo_hygiene_parallel

which is **84 files** on this tree. Run on a clean worktree of this branch with
`PYTHONDONTWRITEBYTECODE=1`, and every red re-run on a clean worktree of
pristine `origin/main` at `a4caccefe`:

| batch | files | this branch | pristine `origin/main` |
|---|---|---|---|
| `programs/tests` (less the one below) | 80 | 1613 passed, 18 skipped, **2 failed** (18m50s) | the same 2 IDs red |
| `tools/ci` (grep-selected subset — **understated, see 2b**) | 3 | 37 passed, **4 failed** | **identical**: 37 passed, the same 4 IDs |
| `test_landing_merge_verdict.py` | 1 | 125 passed, **9 failed** (7m12s) | **identical**: 125 passed, the same 9 IDs, `diff` empty |

**1775 passed, 18 skipped, 15 red — and every red is red on `origin/main` too,
ID for ID. This branch introduces none.** (The `tools/ci` line of this table is
superseded by 2b, which runs that suite whole: 21 red, identical on both trees.) That is the brief's *"whatever you
change must run clean on the current repo"*, measured over the mechanically
derived population rather than a chosen one.

The 15 are pre-existing debt in three unrelated families, named so that a later
reader can tell them from anything this change could have caused:

* **2 in `programs/tests`** — `test_gate_red_since_rows.py::test_the_bound_is_
  what_refuses_and_not_some_other_clause` and `test_v1_9_63_issue693_repo_
  process_family_wiring.py::test_the_checker_population_covers_checker_shaped_
  names` (two generator scripts not in the checker population). Neither reads a
  corpus.
* **4 in `tools/ci`** — one fixture-discrimination pair, one mutation-fixture
  gate, and the two `test_phase_b_activated_parity.py` rows, which are the
  protected-tuple defect recorded in
  `2026-08-22-protected-tuple-on-main-matches-neither-state.md`.
* **9 in `test_landing_merge_verdict.py`** — the end-to-end
  `gatekeeper-verify-merge` arms. Both trees produced the same nine IDs and
  `diff` between the two lists is empty.

An earlier revision of this record reported 8 reds in the `programs/tests` batch
over a 75-file population. Six of those have been fixed on `main` since; the
population grew to 80 files in the same interval. The comparison that matters is
branch against `main` **at the same commit**, which is what the table above is.

No test was relaxed, no assertion widened, no baseline written. The only source
changes on this branch are prose in `repo_hygiene_parallel.py` and
`tests/test_routed_def_corpus_dispatch.py`; no executable line moved. Precisely:
a `#` comment block in `_summary_rc`, and — the part "comment blocks" was
wrong about — the **docstring** of `_legacy_empty_without_process`, which is a
runtime object rather than a comment. The distinction changes nothing here and
is measured below rather than asserted.

### 2b. The `tools/` selector gap — the sweep above understated its own population

**The `tools/ci` row above was selected by grep, and a grep is exactly the wrong
selector for this tree.** The `tools/` suite sits outside every selector this
repository ships; batch 68 shipped 16 reds through that same gap. The producer
this whole record is about — `tools/ci/routed_def_corpus.py` — lives there. A
3-file subset is not evidence about it.

So `tools/` was re-run WHOLE, on two clean worktrees, at the same commit:

| tree | commit | result |
|---|---|---|
| this branch | `c6ec85abb` | 863 passed, 6 skipped, **21 failed** (3m46s) |
| pristine `main` | `a4caccefe` | 863 passed, 6 skipped, **21 failed** (3m48s) |

`diff` of the sorted `FAILED` ID lists is **empty**. The branch introduces none.

The grep subset saw 4 of those 21. The other **17 were invisible to it**, in two
files it never selected — and both are pre-existing, unrelated to any corpus:

* **16 in `tools/test_gatekeeper_land_differential.py`**, all one shared cause:
  the fixture's candidate is byte-identical to its base, so the gate answers
  *"every path this branch touches is already byte-identical to <base> — there
  is nothing to land, and ancestry cannot see it"* and returns 2 where the test
  expects 0 or 1. A fixture-construction defect in that file, not a gate defect.
* **1 in `tools/test_liar_census.py`** —
  `test_nothing_the_flow_declares_is_left_unswept`, a stale hardcoded count:
  `assert 182 == 181`, with `unswept: []`. Nothing is unswept; the literal is
  one behind the tree.

Neither was touched. They are red on `main` at the same commit, and bumping a
stale literal or repairing someone else's fixture to clear a red is not this
change's business — the rule against rewriting a baseline to make a red go away
does not acquire an exception because the baseline belongs to another file.

**What this corrects:** the claim *"whatever you change must run clean on the
current repo"* was previously supported over a grep-derived population that
missed 17 reds. It now rests on the whole `tools/` suite, diffed ID for ID at
one commit. The conclusion did not move; the evidence under it did, and a record
that names its own weak selector is worth more than one that quietly kept it.

### 3. Re-verified independently, 2026-08-22, on both trees

Everything above was re-derived from scratch rather than re-read, because a
record that only ever gets re-read is a record nobody has checked.

**The executable delta between this branch and `origin/main` is empty.** Parse
both revisions of `repo_hygiene_parallel.py`, normalise every docstring to one
placeholder, and compare the ASTs:

    identical once docstrings are normalised — the delta is prose only

So the sweep on this branch and the sweep on `origin/main` are the same
measurement, and any red on one is a red on the other by construction. That is
the strongest available form of *"whatever you change must run clean on the
current repo"*: there is nothing left that could fire.

**The whole `tools/ci` directory, not the grep-derived subset.** Section 2 ran
the 3 files its query selected. Re-run over all 17:

| tree | result |
|---|---|
| `10563c3da` (this branch) | 238 passed, 6 skipped, **4 failed** (50.4s) |
| `a4caccefe` (pristine `origin/main`) | 238 passed, 6 skipped, **4 failed** (49.9s) |

Same four IDs on both, in the same order: `test_gate_fixtures_discriminate.py::
test_fixture_pair_discriminates[ppa_head_to_head_records]`,
`test_gate_mutation_fixture_check.py::test_the_real_repo_is_clean_under_this_
gate`, and the two `test_phase_b_activated_parity.py` rows. The branch
introduces none of them.

**The red, re-shown on the pre-fix tree.** `81cd5321b` carries neither
`NO_CORPUS_RC` nor `GATE_DISPATCH_ABSENT_RC` (grep: 0 occurrences in
`routed_def_corpus.py` and `_gate_dispatch.sh`). Drop *only* this branch's test
file onto that tree and run the nine tests it adds:

    6 failed, 3 passed

The six are `test_the_absent_exit_code_is_one_number_in_two_languages`,
`test_an_absent_corpus_and_a_read_but_empty_one_do_not_share_a_verdict`,
`test_the_dispatcher_gives_absent_and_empty_different_rows`,
`test_a_corpus_that_was_read_and_holds_none_says_so`,
`test_the_shipped_hygiene_script_reports_this_checkout_as_NOT_FOUND` and
`test_an_absent_corpus_does_not_close_the_hygiene_dag_green`. The three that
pass pre-fix pin invariants that already held and had to survive the change —
that they are green on both trees is the point of including them.

The last of the six is the one worth reading, because it prints the defect in
its own words on the tree that had it:

    AssertionError: the parallel hygiene DAG closed GREEN (rc 0) over a corpus
    that was NEVER OPENED. ... Got rc 0.
      ── corpus "..." is EMPTY — nothing was checked over it
      [routed-def corpus] NO_CORPUS: nothing at .../benchmark-data/ic and
      VIBE_IC_BENCHMARK_DATA is unset. ... NOTHING WAS SCANNED

The producer says *nothing was scanned*; the row two lines up says *is EMPTY*;
`_summary_rc` returns 0. **This was a manufactured pass, not a wording bug** —
which is why the record's headline is the pass and not the sentence.

**Both states, re-run through the real producer.** On `10563c3da`, no fixture,
just the shipped program:

    A  no benchmark-data/, VIBE_IC_BENCHMARK_DATA unset
       -> rc 3, 0 items, "NOT FOUND ... the ABSENCE of a measurement,
          not a measurement of zero. The line above names what was looked for."
    B  VIBE_IC_BENCHMARK_DATA -> a git checkout whose ic/ publishes no
       */*/phase3/stage3/pnr/routed.def
       -> rc 0, 0 items, "MEASURED EMPTY: git's index at <top> was read under
          'ic' ... This IS a measurement"

Different rc, different sentence, and each names the thing the other cannot: A
names what it looked for, B names the index it read. `test_routed_def_corpus_
dispatch.py` on this branch: **22 passed**.
