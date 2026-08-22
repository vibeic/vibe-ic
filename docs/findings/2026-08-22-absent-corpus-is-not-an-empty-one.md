# An ABSENT corpus is not an EMPTY one — the ruling, the measurement, and its bound

_Measured 2026-08-22 on host `8HD-6`, against `origin/main` at `81cd5321b` and
against `fix/j1764-absent-is-not-empty`, with the SHIPPED
`tools/ci/repo_hygiene_gates.sh` rather than with a fixture. Pure repository
gate machinery: no design, PDK, vendor or part identifier appears._

Closes the defect filed as vibe-ic#1764.

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

| tree | pointer | `corpora[].expansion` | recorded label |
|---|---|---|---|
| `origin/main` | UNSET (state A) | `EXPANDED` | `corpus "…" is EMPTY — nothing was checked over it` |
| `origin/main` | SET (state B) | `EXPANDED` | `corpus "…" is EMPTY — nothing was checked over it` |
| this branch | UNSET (state A) | **`NO_CORPUS`** | **`corpus "…" was NOT FOUND — nothing was opened to check`** |
| this branch | SET (state B) | `EXPANDED` | `corpus "…" is EMPTY — nothing was checked over it` |

The pointer used for the SET arm is a real clone of the published tree whose
`ic/` subtree carries **0** files matching `*/*/phase3/stage3/pnr/routed.def` —
i.e. the genuine #1763 population. **Row B is byte-identical before and after.**

The producer now says which state it is in, and names the thing that makes it
that state:

    state A, rc 3: NO_CORPUS: nothing at <repo>/benchmark-data/ic and
                   VIBE_IC_BENCHMARK_DATA is unset … NOTHING WAS SCANNED
                   NOT FOUND (rc 3): … 0 routed DEF(s) is the ABSENCE of a
                   measurement, not a measurement of zero.

    state B, rc 0: MEASURED EMPTY: git's index at <corpus> was read under 'ic'
                   and it publishes no */*/phase3/stage3/pnr/routed.def. This IS
                   a measurement …

## A second, LATENT collapse in the waiver — and an honest bound on it

There is one place a population refusal can become a pass:
`repo_hygiene_parallel._summary_rc` waives exactly one unexempted NOT_CHECKED,
the phase-1 bootstrap row for a corpus that was READ and publishes nothing.
An absent corpus reached that waiver wearing the same label and the same
`expansion`, so the waiver answered for it too. Measured, real producer through
the real `_gate_dispatch.sh`, then the real `_summary_rc`:

| tree | state | `expansion` | `_summary_rc` |
|---|---|---|---|
| `origin/main` | A absent | `EXPANDED` | **0** |
| `origin/main` | B read-empty | `EXPANDED` | 0 — intended bootstrap |
| this branch | A absent | `NO_CORPUS` | **2** |
| this branch | B read-empty | `EXPANDED` | 0 — unchanged |

**How far that actually reaches, stated against my own finding.** I first wrote
this up as "`main` closes the hygiene DAG green over a corpus nothing opened",
which is stronger than what is true. `repo_hygiene_parallel` has exactly one
production caller, `gatekeeper_review.repo_hygiene_gate`, and it binds the
corpus **before** the set (line 1230) and returns rc 2 with a named remedy if it
cannot:

    if script is None:
        corpus_env_or_none, corpus_refusal = _published_corpus_binding()
        if corpus_refusal is not None:
            return GateResult(name, 2, corpus_refusal)

`_published_corpus_binding` tries `VIBE_IC_BENCHMARK_DATA`, then
`VIBEIC_BENCHMARK_DATA_CHECKOUT`, then `$HOME/_matrix_benchmark_data`, and
refuses unless the result is the ROOT of a git checkout — measured against a
directory that is not one, it refuses rather than binding. And a pointer that is
**set and wrong** makes the producer rc 2 UNDETERMINED, not absent. So the only
way into `_summary_rc` is with a corpus that resolved: **state A cannot reach
the waiver on the production path.**

So this is a **latent** defect, not a live one, and the earlier phrasing in this
file and in commit `24a09728` overstated it. It is still worth fixing: the
binding is the single guard standing between an unmeasured corpus and a waived
refusal, and "one guard is enough" is not how the rest of this repository is
built. What the fix buys is that the waiver no longer *depends* on that binding
to be correct.

## What this changes operationally: nothing, measured

The real, complete `tools/ci/repo_hygiene_gates.sh` run to completion with the
pointer UNSET — the state a bare checkout of this repository is in — on both
trees:

| | declared | decided | passed | failed | NOT CHECKED | unexempted | exit |
|---|---|---|---|---|---|---|---|
| `origin/main` | 87 | 77 | 71 | 6 | 10 | 1 | **1** |
| this branch | 87 | 77 | 71 | 6 | 10 | 1 | **1** |

Byte-for-byte the same verdict counts and the same exit code. The **only**
difference in the whole record is the routed-DEF row:

    origin/main   expansion EXPANDED   'corpus "…" is EMPTY — nothing was checked over it'
    this branch   expansion NO_CORPUS  'corpus "…" was NOT FOUND — nothing was opened to check'

This is the answer to *"whatever you change must run clean on the current repo;
a guard that fires on the state we just shipped is not a guard"*: **nothing new
fires.** The row was blocking before and is blocking now, at the same severity,
in the same run, with the same closing rc. What changed is that it now tells the
truth about which state it is in.

(This corrects a claim in an earlier revision of this file that `lane_hygiene`
would begin returning 2 where it returned 0. It does not: `lane_hygiene` runs
`repo_hygiene_gates.sh`, whose closing rc is `gate_dispatch_finish`, and that
refused this row on `origin/main` already. The 6 failures above are pre-existing
on `origin/main` and are not touched by this change.)


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
  thereby misconfigured. Reversing it would change every other call site's
  behaviour to fix this one's.
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
  closing rc of the DAG. A hand-built record could not show this, because on
  `main` the defect *is* that the absent state is handed the empty row's label;
  a fixture that types the right label in has already fixed the bug it tests.
* `test_the_phase1_waiver_covers_the_measured_empty_row_and_not_the_absent_one`
  and `test_the_waiver_checks_the_shape_and_not_only_the_label` — these two pass
  on `main` as well. They are guards for the future, not the red, and this
  record does not claim otherwise.

**Red without the fix**, production code reverted to `origin/main` and the tests
kept: `5 failed, 13 passed` on the row-identity set, plus the closing-rc test.
The sharpest is the last one, because the log it captures contains the entire
defect in one place — the producer says it scanned nothing, and one line later
the run calls the corpus empty and closes 0:

    [routed-def corpus] NO_CORPUS: nothing at …/benchmark-data/ic and
    VIBE_IC_BENCHMARK_DATA is unset … NOTHING WAS SCANNED
       ^^ NOT CHECKED (rc 2, BLOCKING): corpus "…" is EMPTY
    AssertionError: the parallel hygiene DAG closed GREEN (rc 0) over a corpus
    that was NEVER OPENED … assert 0 == 2

and, in the machine-readable record,

    assert [{'name': 'published cells carrying a routed DEF', 'items': 0,
             'gates': 1, 'expansion': 'EXPANDED'}]     <- a MEASURED population
        == [{…                       'expansion': 'NO_CORPUS'}]  <- nothing opened

## Corpus sweep

43 test files that read `_gate_dispatch.sh`, `hygiene_finding_delta`,
`landing_merge_verdict`, `repo_hygiene_parallel`, `repo_hygiene_gates.sh` or the
routed-DEF producer, run on this branch and, where red, re-run on a pristine
`origin/main` worktree. 1170 passed, 2 skipped, 14 red — and every one of the 14
is accounted for below, none of them by this change:

* 262 passed / 2 skipped and 279 passed / 0 red — the two corpus-and-gate-wiring
  batches (23 files), clean.
* 294 passed / 1 red — the `repo_hygiene_parallel` consumer batch (12 files).
  The red is `test_orphan_scan_reads_the_landing_gate_runner.py::test_the_
  shipped_audit_no_longer_calls_the_coordinator_unreachable`, about two
  undeclared AUDIT_ONLY gates; **same test ID red on pristine `origin/main`.**
* 9 red in `test_landing_merge_verdict.py` (end-to-end `gatekeeper-verify-merge`)
  — **the same 9 test IDs are red on pristine `origin/main`.** Pre-existing.
* 3 red in `tools/ci/test_phase_b_activated_parity.py` and
  `test_gate_fixtures_discriminate.py` — **the same 3 IDs are red on pristine
  `origin/main`.** Pre-existing; the parity pair is the protected-tuple defect
  reported in `2026-08-22-protected-tuple-on-main-matches-neither-state.md`.
* 1 ordering flake in `test_gate_process_attestation.py`::`test_real_dispatch_
  writes_owner_only_records_into_its_summary`. Re-measured 2026-08-22 in
  isolation, and the earlier "passes 3/3 in isolation" in this file was too
  weak a statement to be worth making: it is a REAL intermittent, not a
  load artefact. It races on the order two parallel gates append their
  attestation records, and it flakes **on a pristine `origin/main` worktree
  too** — 5 passed / 1 failed in 6 consecutive isolated runs there, 2 passed /
  1 failed in 3 on this branch. Pre-existing, not this change: its fixture
  script never calls `gate_dispatch_over`, so no line changed here is on its
  path. Not fixed here because it is a different defect from #1764 and a fix
  for it belongs in a change somebody chose; recorded rather than left as an
  unexplained red.

No test was relaxed, no assertion widened, no baseline written.

## Independent re-measurement of this branch, 2026-08-22

The record above was written by the run that made the change. Re-measured after
it, on a clean worktree of `fix/j1764-absent-is-not-empty` at `9b355d2ba`,
`PYTHONDONTWRITEBYTECODE=1`, host load 70:

* **The shipped gate list, diffed between the two trees.** The strongest form
  of "nothing new fires", and it needs no fixture at all: run the real
  `tools/ci/repo_hygiene_gates.sh --list` with `VIBE_IC_BENCHMARK_DATA` unset
  on a clean `origin/main` worktree and on this branch, normalise the worktree
  path, and diff. **87 declared gates on both trees, and the diff is exactly one
  line:**

      -corpus "…routed DEF" is EMPTY — nothing was checked over it  [population: producer rc 0, 0 item(s) over …]
      +corpus "…routed DEF" was NOT FOUND — nothing was opened to check  [population: producer rc 3 — NO CORPUS RESOLVED, nothing was opened, over …]

  No gate appeared, none disappeared, none changed severity. On `main` the same
  log carries the contradiction in two adjacent lines — the producer prints
  `NOTHING WAS SCANNED` and the dispatcher then reports the corpus `expanded
  over 0 item(s)`. On this branch the producer adds `NOT FOUND (rc 3): … the
  ABSENCE of a measurement, not a measurement of zero` and the rollup agrees
  with it.
* The 28 test files that name `gate_dispatch_over`, `_gate_dispatch.sh`,
  `GATE_CORPUS_STATE` or the routed-DEF producer: **597 passed, 6 skipped,
  1 red** — and the 1 is the `test_gate_process_attestation.py` ordering
  intermittent above, which flakes on pristine `origin/main` as well.
* **The red without the fix, reproduced.** The six production files reverted to
  `origin/main` and every test on this branch kept: **6 failed, 13 passed** in
  `test_routed_def_corpus_dispatch.py`. The failures are exactly the pair-
  identity set plus the closing-rc test:
  `test_an_unconfigured_moved_corpus_is_explicit_no_corpus`,
  `test_the_absent_exit_code_is_one_number_in_two_languages`,
  `test_an_absent_corpus_and_a_read_but_empty_one_do_not_share_a_verdict`,
  `test_the_dispatcher_gives_absent_and_empty_different_rows`,
  `test_the_shipped_hygiene_script_reports_this_checkout_as_NOT_FOUND`,
  `test_an_absent_corpus_does_not_close_the_hygiene_dag_green`. The last one
  captures the whole defect in one log: the producer prints `NO_CORPUS: …
  NOTHING WAS SCANNED`, the next line calls the corpus `EMPTY`, and the DAG
  closes rc 0.
* `test_an_unconfigured_moved_corpus_is_explicit_no_corpus` is the one
  pre-existing test whose assertion changed. It was **tightened, not relaxed**:
  every assertion it made on `main` still stands, and `returncode == 0` became
  `returncode == NO_CORPUS_RC` plus an explicit `returncode != 0`, plus two new
  assertions that the diagnostic names what it looked for. That reversal IS the
  behaviour change this issue asked for, and it is argued in full above.
