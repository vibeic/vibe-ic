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

This run was later rebuilt from scratch on this tree; the 7 IDs match, the
pass count does not, and the reason is a selector gap in this run itself.
See section 6 — it supersedes the totals above, not the IDs.

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

### 4. Re-checked a second time, 2026-08-22, by the simplest construction available

Everything in section 3 was re-derived rather than re-read.  This section does
the same to section 3, and it deliberately uses a *different, simpler* fixture,
because a record confirmed only by the construction that produced it has been
confirmed by nothing.

**The red, with no revert at all.**  Section 3 showed it on a worktree of this
branch with three production files hand-reverted.  A hand-revert is a
construction, and a construction can be wrong.  So instead: check out
`81cd5321b` — the pristine parent of the fix commit `ef0399606`, nothing edited
— copy in **only** this branch's test file, and run it whole.

`81cd5321b` carries neither name (`grep -c 'NO_CORPUS_RC\|GATE_DISPATCH_ABSENT_RC'`
is `0` in both `routed_def_corpus.py` and `_gate_dispatch.sh`):

    7 failed, 15 passed in 6.27s

    FAILED test_an_unconfigured_moved_corpus_is_explicit_no_corpus
    FAILED test_the_absent_exit_code_is_one_number_in_two_languages
    FAILED test_an_absent_corpus_and_a_read_but_empty_one_do_not_share_a_verdict
    FAILED test_the_dispatcher_gives_absent_and_empty_different_rows
    FAILED test_a_corpus_that_was_read_and_holds_none_says_so
    FAILED test_the_shipped_hygiene_script_reports_this_checkout_as_NOT_FOUND
    FAILED test_an_absent_corpus_does_not_close_the_hygiene_dag_green

**The same seven IDs as section 3, in the same order, from an unrelated
fixture** — and the sharpest one prints the same log, ending `assert 0 == 2`
under *"the parallel hygiene DAG closed GREEN (rc 0) over a corpus that was
NEVER OPENED"*.  The same file on this branch: **22 passed**.  Section 3's
count of *"6 failed"* is over the nine tests the change ADDS; the seventh is
`test_an_unconfigured_moved_corpus_is_explicit_no_corpus`, which pre-existed and
was re-pinned.  The two framings agree; this one states the denominator it used.

**No test was deleted and no assertion relaxed — mechanically, not asserted.**
Diff the test file `81cd5321b..HEAD` and keep only removed lines matching
`def test` or `assert`:

    -    assert proc.returncode == 0, proc.stdout + proc.stderr

That is the whole removal.  **Zero `def test` lines were removed**, and the one
removed assertion was replaced by a strictly stronger pair on the same object —
`== _no_corpus_rc()` *and* `!= 0`, plus three new assertions requiring the
sentence to name `benchmark-data`, name the environment variable, and *not* say
`MEASURED EMPTY`.  Re-pinning a test whose subject deliberately changed is the
opposite of relaxing it: the old line asserted the collapsed behaviour.

**The executable delta to `origin/main` is empty — both files, not one.**
Section 3 checked `repo_hygiene_parallel.py`.  Parse *both* changed Python files
at `origin/main` and at this tip, normalise every docstring to one placeholder,
compare the ASTs:

    repo_hygiene_parallel.py                AST-identical: True   raw-identical: False
    tests/test_routed_def_corpus_dispatch.py  AST-identical: True   raw-identical: False

So this branch changes no executable line against `a4caccefe`.  Any sweep on it
is the same measurement as a sweep on `main`, by construction rather than by
coincidence — which is the strongest available form of the brief's *"whatever
you change must run clean on the current repo"*.

**The `tools/` suite whole, at this tip.**  `tools/` sits outside every selector
this repository ships (batch 68 shipped 16 reds through that gap), and the
producer this record is about lives there, so it is run whole and not grepped:

    tools/   863 passed, 6 skipped, 21 failed   (121.66s)   at `faaf10d6b`

Identical to the pair section 2b measured at `c6ec85abb` and at pristine
`a4caccefe`, and identical by construction given the empty AST delta above.  All
21 are the two pre-existing clusters section 2b named — 16 in
`test_gatekeeper_land_differential.py` (a fixture whose candidate is
byte-identical to its base), 4 in `tools/ci` and 1 stale literal in
`test_liar_census.py`.  None was touched: bumping someone else's stale count to
clear a red is the one thing this branch may not do.

**What the #1763 row still says.**  Unchanged, and checked at the source rather
than inferred.  In `_gate_dispatch.sh` the rc-0 arm still emits the literal
`corpus "$corpus" is EMPTY — nothing was checked over it` and still dispatches
`_dispatch 2 0`, so the empty-but-read corpus keeps its exact label, its rc 2,
its NOT CHECKED and its BLOCKING.  The absent corpus does not borrow that row:
it gets `corpus "$corpus" was NOT FOUND — nothing was opened to check`, its own
`GATE_CORPUS_STATE` of `NO_CORPUS` rather than `EXPANDED`, and it is equally
blocking.  Neither state is a pass, which was never negotiable.

### 5. Is the collapse singular? The class-level sweep, measured

The change repairs ONE producer.  `_corpus_location.py`'s own header calls the
class the defect — *"THE FOUR OUTCOMES, AND COLLAPSING ANY TWO OF THEM IS THE
DEFECT"* — so a record that fixes one row and never asks whether a sibling
shares it has closed a row, not a defect.  This section asks, and answers it by
running the siblings rather than by reading them.

**The dispatcher side is singular by construction.**  A corpus can only collapse
at `gate_dispatch_over` if it is dispatched as an attested POPULATION.  Across
the tree there is exactly one production call site with
`GATE_DISPATCH_ATTEST_POPULATION=1` — `tools/ci/repo_hygiene_gates.sh:847` — and
its producer is `routed_def_corpus.py`, the subject of this record.  (The only
other `gate_dispatch_over` call is `test_gate_concurrency.sh`'s toy corpus.)  So
no second row could have been collapsed at the dispatcher.

**The producer side: `may_be_absent` cannot be taken by accident.**
`_corpus_location.refuse` declares `may_be_absent` with **no default** — of its
seven parameters only `opt_in_flag` has one — so every call site must state the
opt-in explicitly.  In the whole production tree exactly **one** call site passes
a literal `True`: `routed_def_corpus.py:412`, the one this change compensates
for with its own rc 3.  Every other production caller forwards the operator's
`--corpus-may-be-absent`, so the decision is made at the command line and not
baked in.

**That forwarding is the wider surface, so it was measured, not reasoned about.**
Six programs route the flag into `refuse`, and the PPA family reaches it through
`_ppa_corpus.open_corpus`.  Three of those gates, both states, flag on and off,
`VIBE_IC_BENCHMARK_DATA` unset (**a 3-gate sample — widened to all 13 in 5b,
which supersedes this table**):

| gate | state | `--corpus-may-be-absent` | rc |
|---|---|---|---|
| `ppa_head_to_head_check` | A absent | no | **2** |
| `ppa_head_to_head_check` | A absent | yes | **0** |
| `ppa_head_to_head_check` | B read, empty | no | **2** |
| `ppa_head_to_head_check` | B read, empty | yes | **2** |
| `ppa_contract_check` | A / A / B / B | no / yes / no / yes | 2 / 0 / 2 / **2** |
| `ppa_measurement_check` | A / A / B / B | no / yes / no / yes | 2 / 0 / 2 / **2** |

**The opt-in moves the ABSENT arm only.  It never reaches the empty one.**  That
is the property that matters, and it is the one a reader would most want checked:
no operator flag anywhere in this family can turn a corpus that was read and
holds nothing into a pass.  State B is rc 2 in all six of its cells.

And the two sentences are already distinguished, each naming what the other
cannot — the same test this record applies to its own producer:

    A  [PPA head-to-head records] NO_CORPUS: nothing at <path> and
       VIBE_IC_BENCHMARK_DATA is unset ... NOTHING WAS SCANNED, 0 published
       head-to-head record(s) were examined and nothing is claimed about them

    B  [CANNOT CHECK] VACUOUS: the corpus carries no head-to-head record, so
       nothing was validated. This is NOT a pass ... rc=2.
       ... 0 head-to-head record(s) found in 0 JSON document(s) scanned

A names what it looked for; B names the population it read *and* the number of
documents it opened to find it.  `_ppa_corpus.open_corpus`'s docstring states
the thesis of this whole record independently and got there first: *"A CORPUS
THAT IS NOT THERE IS NOT AN EMPTY CORPUS ... a denominator asserted over a
population nobody searched."*

**Conclusion, stated as narrowly as the evidence supports.**  The collapse
vibe-ic#1764 names was singular: it existed where a producer's rc 0 already
carried a second meaning — *"I read an index and it publishes none"* — and
`routed_def_corpus.py` was the only program in that position.  The PPA family
never collapsed the pair because it never overloaded rc 0 that way, and this
section verifies that by running it rather than by trusting the comment that
says so.  Nothing here was changed; a sweep whose answer is *"no sibling has
it"* ships as evidence, not as a patch.

### 5b. The sweep above sampled 3 gates and generalised — here are all 13

Section 5 measured three PPA gates and concluded about a family.  That is the
same weak-selector move section 2b caught in section 2, and catching it once is
not a licence to repeat it, so the claim is re-derived over **every production
program that reaches `_corpus_location.refuse`** — 13 of them, both states, flag
on and off.  52 cells.

The gates split by how they take their corpus, and the split matters because it
changes which state A is reachable:

| how the corpus is named | gates |
|---|---|
| `--corpus DIR` on the command line | `ppa_head_to_head_check`, `ppa_contract_check`, `ppa_measurement_check`, `ppa_feasibility_check`, `ppa_pareto_check`, `ppa_problem_integrity_check`, `cross_layer_reference_check`, `step_internal_fail_bubble_up_check` |
| resolved from the pointer / default only | `published_record_staleness_check`, `l_doc_field_producer_check`, `evidence_citation_resolves_check`, `tracked_symlink_portability_check`, `citation_routing_is_true_check`, `benchmark_evidence_index`, `benchmark_evidence_structure_check`, `tracked_symlink_target_present_check` |

**Result — the one column that matters is the last.**

| state | pointer | `--corpus-may-be-absent` | rc |
|---|---|---|---|
| **A** absent | unset, nothing anywhere | no | **2** UNDETERMINED |
| **A** absent | unset, nothing anywhere | yes | **0**, `NO_CORPUS` named |
| **A'** absent | **set and wrong** | no | **2** UNDETERMINED |
| **A'** absent | **set and wrong** | yes | **2** — the opt-in does *not* excuse a broken pointer |
| **B** read, empty | either | no | **2** |
| **B** read, empty | either | **yes** | **2** — never 0, in every gate measured |

**State B is rc 2 in all of its cells, in all 13 gates, with the opt-in flag on.**
(`benchmark_evidence_index` answers rc **1** there — a refusal, stronger still.)
No operator flag anywhere in this family can turn a corpus that was read and
holds nothing into a pass.  That is the property vibe-ic#1764 is about, and it
holds across the family without exception.

**And the sweep surfaced a fourth outcome being kept correctly distinct.** Row
A' was not in section 5's sample and is the interesting one: with the pointer
*set and pointing at nothing*, the opt-in is ignored and the rc stays 2.  That is
`_corpus_location` honouring its own header — a pointer that is SET AND WRONG is
an operator mistake, not "the corpus lives elsewhere", and no flag may excuse it.
So the four outcomes the header names are all separately observable in one run:

    pointer set and wrong        -> 2, always, opt-in ignored
    no corpus anywhere, no flag  -> 2
    no corpus anywhere, opt-in   -> 0, NO_CORPUS, names what it looked for
    corpus read, holds none      -> 2 (or 1), names the population it read

**What this corrects in section 5.** The conclusion did not move — no sibling
shares vibe-ic#1764's collapse — but section 5 supported it over 3 of 13 gates
and one of the two state-A variants, and said so as if it had checked the family.
It now rests on all 13 and on both variants.  A record that widens its own
selector twice is a record whose selector can be trusted the third time; one that
quietly kept the sample is not.

### 6. The red itself, re-derived on this tree — and the one file the red's own selector left out

Every number above was re-measured at least once except one: the **red**.  The
`7 failed, 57 passed` under "Red without the fix" was carried forward from the
run that produced it, and a record that re-derives its sweep twice and takes its
own central claim on trust has the priority backwards.  So the revert was rebuilt
from scratch — a throwaway detached worktree at `0d398cb04`, the three production
files put back (`tools/ci/routed_def_corpus.py` and `tools/ci/_gate_dispatch.sh`
to `81cd5321b`, `repo_hygiene_parallel.py` to `24a097287^`), every test kept, the
revert committed so the tree measured CLEAN, `PYTHONDONTWRITEBYTECODE=1`.

**The revert is real, checked before the tests ran:** `NO_CORPUS_RC` occurs 0
times in the reverted producer and `GATE_DISPATCH_ABSENT_RC` 0 times in the
reverted dispatcher.

**The collapse reproduces at the producer, both states, one command each:**

    reverted   A absent -> rc 0, 0 items      B read-empty -> rc 0, 0 items
    this tree  A absent -> rc 3, 0 items      B read-empty -> rc 0, 0 items

On the reverted tree the two are byte-indistinguishable, which is exactly what
vibe-ic#1764 filed.

**The red, by test ID — the set matches this record exactly, 7 for 7:**

    7 failed, 74 passed in 26.72s

    FAILED test_an_unconfigured_moved_corpus_is_explicit_no_corpus
    FAILED test_the_absent_exit_code_is_one_number_in_two_languages
    FAILED test_an_absent_corpus_and_a_read_but_empty_one_do_not_share_a_verdict
    FAILED test_the_dispatcher_gives_absent_and_empty_different_rows
    FAILED test_a_corpus_that_was_read_and_holds_none_says_so
    FAILED test_the_shipped_hygiene_script_reports_this_checkout_as_NOT_FOUND
    FAILED test_an_absent_corpus_does_not_close_the_hygiene_dag_green

All 7 are in `test_routed_def_corpus_dispatch.py` (7 of its 22).  The counts are
compared by **ID and not by total**, because a total is the one number that moves
for reasons that have nothing to do with the defect.

**The count moved, and the reason is a selector gap in the red's own run.**
`57 -> 74` is not a change in behaviour: 22 + 17 + 42 = 81 = 7 + 74, and the
earlier `64` is 22 + 42.  The original red ran
`test_routed_def_corpus_dispatch.py` and `test_repo_hygiene_parallel.py` and
**omitted `test_corpus_location.py`** — the tests for the very module whose
`may_be_absent` opt-in this whole ruling turns on.  This is the same weak-selector
move as sections 2b and 5b, caught a third time, and it is recorded rather than
quietly corrected.

**Adding those 17 changes nothing, and that is the point.**  All 17 pass on the
reverted tree and all 17 pass on this one.  `_corpus_location`'s own contract is
untouched in both directions, which is the claim "Where I disagree with the issue"
makes when it says the fix *leaves the opt-in standing* — that claim was argued
there and is measured here.  `test_repo_hygiene_parallel.py` is 42 green under the
revert, confirming that its two waiver guards are guards for the future and not
part of the red, exactly as this record already said.

**What the sharpest failure prints on the reverted tree**, the whole defect in
four consecutive lines of one log:

    [routed-def corpus] NO_CORPUS: nothing at .../benchmark-data/ic and
    VIBE_IC_BENCHMARK_DATA is unset ... NOTHING WAS SCANNED, 0 routed DEF(s)
    were examined and nothing is claimed about them
       ^^ NOT CHECKED (rc 2, BLOCKING; no exemption): corpus "..." is EMPTY —
          nothing was checked over it [0s]
    AssertionError: the parallel hygiene DAG closed GREEN (rc 0) over a corpus
    that was NEVER OPENED ... Got rc 0.
    assert 0 == 2

The producer says it scanned nothing; the next line calls the corpus empty; the
DAG closes 0.  Fixed tree, same three files: 22 + 17 + 42 = 81 passed.

### 7. The sweep asked about producers. It did not ask about RECORD consumers.

Sections 5 and 5b answered *"is the collapse singular?"* by enumerating every
program that reaches `_corpus_location.refuse` — 13 of them, both states, flag
on and off.  That is the **producer** side, and the answer there holds.  But a
collapse can also live in a program that reads the dispatcher's `corpora` row
**back**, and the sweep never asked about those.  Three exist:

| record consumer | covered before this section |
|---|---|
| `repo_hygiene_parallel._summary_rc` | yes — §"The second collapse, in the waiver" |
| `hygiene_finding_delta._validate_record` | yes — §"what does an OLD reader do with it?" |
| `tools/gatekeeper-verify-merge.sh:810` `base_has_exact_legacy_routed_empty` | **no** |

The third was missed because it is neither a producer nor a Python consumer: it
is a shell function wrapping a heredoc, so both selectors walked past it.  It is
also the most expensive place the defect could have lived.  It decides whether
the BASE arm is in the one state that authorises `build_trusted_transition_
evidence` — the trusted parent **enumerating and executing** the routed corpus
on the landing path.  A base arm whose corpus nothing opened, accepted there,
would have the landing build trusted transition evidence over a measurement
nobody took.

**Measured, not read.**  The shipped predicate lifted verbatim out of the script
and driven over records the real `_gate_dispatch.sh` wrote, five cells, on
`81cd5321b` (before the fix) and on this branch:

| cell | before: `expansion` → verdict | after: `expansion` → verdict |
|---|---|---|
| stub producer `exit 3`, SHA bound | `PRODUCER_FAILED` → refuses | **`NO_CORPUS`** → refuses |
| no pointer, SHA bound | `PRODUCER_FAILED` → refuses | `PRODUCER_FAILED` → refuses |
| pointer → read-empty, SHA bound | `EXPANDED` → **AUTHORISES** | `EXPANDED` → **AUTHORISES** |
| no pointer, no SHA | `EXPANDED` → refuses | **`NO_CORPUS`** → refuses |
| pointer → read-empty, no SHA | `EXPANDED` → refuses | `EXPANDED` → refuses |

**The verdict is identical in every cell on both commits.**  This consumer was
never collapsed, and #1763's row keeps exactly the authority it has today.

It is held by **two independent guards**, and naming both matters because the
interesting one is not the obvious one:

1. `_corpus_location` already refuses **rc 2 UNDETERMINED** for a bound SHA with
   no checkout — *"GATEKEEPER_BENCHMARK_DATA_SHA is set but VIBE_IC_BENCHMARK_
   DATA is unset, so no byte-attested checkout is bound to that SHA"*.  Inside
   `gatekeeper-verify-merge.sh`, which exports that SHA into **both** arms, this
   is the only way state A could arise — and there it is a broken pointer, not
   an absent corpus.  So the question of which row to wear never came up.
2. Without that SHA the predicate refuses on `benchmark_data_sha` equality
   anyway (the record carries `null`).

**So this ships as a regression pin, not as a fix, and it is not red on
`81cd5321b`.**  Calling it a fix would repeat exactly the overstatement the top
of this file already corrected once.  What
`test_the_landing_transition_authorizer_never_accepts_an_unopened_corpus` pins
is that the predicate keeps refusing an unopened corpus **without leaning on
guard 1** — on the record itself, not on the pointer binding being right, which
is the same shape of single-guard dependence §"How far that reaches" closed in
the waiver.

**Which bytes do that refusing — re-measured at the branch head, because the
first version of this section named only one of them.**  The predicate carries
**two** in-predicate guards against an absent-corpus record, not one, and each
refuses on its own.  Four mutations of the shipped bytes, each driven over the
same real-dispatcher record the test builds — `expansion: "NO_CORPUS"`, gate
label *"… was NOT FOUND — nothing was opened to check"*, `benchmark_data_sha`
**matching**, so guard 1 is satisfied and cannot be what refuses:

| mutation of the shipped predicate | authorizer | the pin |
|---|---|---|
| widen the `expansion` comparison to accept `NO_CORPUS`, literal kept | refuses — the gate-label filter still selects nothing | **green** |
| widen the gate-label filter to accept the `NOT FOUND` label too | refuses — the exact `expansion` dict still fails | **green** |
| widen **both**, both literals kept | **AUTHORISES** | **red** on the substantive assertion: `assert 0 == 1`, *"a base arm whose corpus was NEVER OPENED authorised the trusted parent to enumerate and execute the routed corpus"* |
| drop `"expansion"` from the dict comparison altogether | — | **red** on the shape check: *"the landing-transition authorizer no longer mentions `\"expansion\": \"EXPANDED\"`"* |

So the sentence this paragraph replaces — *"the strict dict equality against
`expansion: "EXPANDED"` is what makes guard 2 unnecessary"* — was half the
truth, and the half it left out is the reassuring one: the gate-label filter is
an equal partner, and **either one alone** already refuses.  The substantive
assertion goes red only when **both** are widened, which is exactly the state
worth catching — widening one is harmless, widening both hands the landing a
corpus nothing opened.  The remaining move, deleting a literal rather than
widening a comparison, is what the shape check covers: it requires the predicate
to still mention `"expansion": "EXPANDED"`, `is EMPTY` and `benchmark_data_sha`.
So the pin rests neither on a single comparison nor on a single string search.
The predicate's bytes are lifted out of the shipped script rather than restated,
and the extraction asserts what it took, so a rename fails loudly here instead
of leaving the test silently measuring nothing.

### 8. Re-verified at the branch head, independently

Every measurement above was made at `c6ec85abb` or earlier; eleven commits have
landed on the branch since.  Re-run at `ce79b380e`, on a clean detached worktree
of `origin/main` and a clean checkout of the branch, `PYTHONDONTWRITEBYTECODE=1`:

| what | result |
|---|---|
| producer, state A (no pointer) | rc **3**, 0 items, `NOT FOUND (rc 3) … ABSENCE of a measurement` |
| producer, state B (git checkout, index holds no routed DEF) | rc **0**, 0 items, `MEASURED EMPTY … names the index it read` |
| producer over the REAL corpus this host carries (`~/_matrix_benchmark_data`) | rc **0**, `MEASURED EMPTY`, 0 routed DEF in its index — **#1763's row, unchanged** |
| `test_routed_def_corpus_dispatch` + `test_corpus_location` + `test_repo_hygiene_parallel` | **82 passed** (81 + §7's pin) |
| whole `tools/` suite, this branch | 863 passed, 6 skipped, **21 failed** |
| whole `tools/` suite, pristine `origin/main` `a4caccefe` | 863 passed, 6 skipped, **21 failed** |
| `diff` of the two sorted `FAILED` ID lists | **empty — the branch introduces none** |

The 21 are the pre-existing reds §2b names and neither was touched.  Counts are
reported alongside IDs and the conclusion rests on the IDs, because a total is
the one number that moves for reasons unrelated to the change.
