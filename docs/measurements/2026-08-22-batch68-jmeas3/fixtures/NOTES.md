# batch68's two gates landed without the fixtures the repo requires — closed

Batch 68 added two gates to `tools/ci/repo_hygiene_gates.sh`:

    :334   table rows belong to tables               doc_table_row_placement_check.py
    :1208  a printed population agrees with its pin  emitter_population_pin_check.py

Both landed carrying NEITHER fixture and absent from `gate_fixture_debt.json`,
which makes both NEW-OR-UNEXCUSED under the rule the repo states in the gate's
own output: **a gate lands with both directions or it does not land.**

The measurement report records this at 15:15 as a defect batch68 introduced
*inside a test that was already red*, where no id-level differential can report
it. It named the defect and deliberately left it open, for a stated reason:
writing fixtures for someone else's gate risks asserting what the gate DOES
instead of what it SHOULD do. That risk is real. It is answered below by driving
each mutation from the defect the gate's own docstring says it was written for,
rather than from the gate's current behaviour.

## THE RED, SHOWN

`python3 tools/ci/gate_mutation_fixture_check.py`, clean checkouts, one arm each:

    a4caccefe   main today       14 NEW-OR-UNEXCUSED   10 carry BOTH   rc 1
    045114294   + this branch    12 NEW-OR-UNEXCUSED   12 carry BOTH   rc 1

    CLOSED (base minus branch), and it is exactly the two:
      'a printed population agrees with its pin'
      'table rows belong to tables'
    NEWLY UNEXCUSED (branch minus base): none

The gate still exits 1 because **12 other gates remain unexcused. They are not
batch68's and this branch claims nothing about them.**

## THE BASELINE WAS NOT TOUCHED, AND THE GATE SAYS SO ON BOTH SIDES

    baseline (gate_fixture_debt.json) still excuses 72 gate(s)   <- base
    baseline (gate_fixture_debt.json) still excuses 72 gate(s)   <- branch

Adding two entries to that register would turn this red green in one line. It is
a baseline rewrite to make a failure go away, which is the one move the brief
forbids outright. The file is byte-identical on both sides.

## THE MUTATIONS ARE THE MEASURED DEFECTS, NOT INVENTED ONES

Each gate's docstring records the defect it was written for. Each fixture applies
that shape:

* **table rows belong to tables** — the same two lines, the same count, in the
  same words, with the DELIMITER ROW left behind by the paste so they land
  mid-paragraph. Placement changes; content does not. This is the gate's own
  stated case: an agreement gate reads the number, finds it correct, and cannot
  see that the sentence it replaced is gone.
* **a printed population agrees with its pin** — a fourth `incr` site arrives in
  the emitted Tcl and the literal denominator stays at `>= 3`. That is verbatim
  the lane the gate's docstring measured on 2026-08-21.

Neither mutation removes the corpus. Absence would drive `_vacuous_exit`'s tier,
which proves only that a gate notices an empty corpus — and the protocol forbids
it. Proved rather than promised, below.

## THE FIXTURES DISCRIMINATE — CHECKED BY MUTATION, NOT ASSERTED

A fixture that passes is not evidence until something makes it fail
(`mutation_check.txt`). Every mutant is caught, and each for the right reason:

    table   / delimiter row left in place (no mutation)      -> CAN-FAIL ACCEPTED (rc 0), refused
    table   / expected fragment the gate never prints        -> rejected, but NOT for the declared reason
    emitter / counter stays at 3 sites (no mutation)         -> CAN-FAIL ACCEPTED (rc 0), refused
    emitter / refuse by REMOVING the subject (vacuous route) -> rc 2, refused: never says the expected thing
    restored, both fixtures as committed                     -> can_pass ok, can_fail ok

The fourth line is the important one: the forbidden absence route does not
silently work here. It produces `rc 2` and the engine refuses it.

## WHY THE EMITTER FIXTURE SUPPLIES THE EXECUTABLE, AND WHY IT IS STILL THE REAL GATE

The dispatcher declares that gate as `python3 programs/emitter_population_pin_check.py`
with cwd `$PLUGIN` — a RELATIVE path and no `$PG` — and the gate's `--programs`
defaults to the directory the program itself sits in. So for THIS declaration,
redirecting the subject necessarily redirects the file that runs; that is the
argv the dispatcher really uses, not the fixture reaching for it.

Handled the strict way: the shipped program and its four private imports are
COPIED OUT OF THE REAL TREE AT RUN TIME, byte for byte, never stubbed and never
vendored into `gate_fixtures/`. The bytes executed are the bytes that land, and
no copy exists here that could drift.

## NOTHING ELSE MOVED — the whole `tools/` region, both sides, clean worktrees

    a4caccefe   21 failed, 863 passed, 6 skipped   25.53s
    045114294   21 failed, 865 passed, 6 skipped   27.11s
    NEWLY RED: none      FIXED: none      (+2 = the two new discriminate params)

The base figure reproduces the measurement report's recorded 21/863/6 for
a4caccefe exactly, on an independent run.

## THE IMPROVEMENT IS INVISIBLE TO AN ID-LEVEL DIFFERENTIAL — SHOWN WITH THE REPORT'S OWN INSTRUMENT

`test_the_real_repo_is_clean_under_this_gate` is red on BOTH sides (it goes green
only at zero unexcused gates), so it cancels and `comm` reports nothing. Running
`tools/ci/pytest_finding_delta.py` from `measure/pytest-finding-delta` over the
two arms (`finding_delta.txt`) recovers what was lost:

    findings: base 18 -> candidate 16
    - no longer said: NEW-OR-UNEXCUSED: 'a printed population agrees with its pin' ...
    - no longer said: NEW-OR-UNEXCUSED: 'table rows belong to tables' ...
    - no longer said: [FAIL] ... 14 finding(s)      (candidate says 12)
    - no longer said: ... 10 carry a CAN-FAIL fixture; 10 carry BOTH   (candidate says 12/12)

This is the instrument's first use by someone other than its author, and it works.

### ONE LIMITATION OF THAT INSTRUMENT, EARNED BY USING IT

Its closing line here reads:

    2 finding(s) were INTRODUCED inside tests that were already red

**Both are the assertion's own SUMMARY lines, restated with new numbers** (`12
carry BOTH`, `12 finding(s)`) — and the change they record is an IMPROVEMENT.
A reader acting on that count alone would have the direction exactly backwards.
The signal is in the `- no longer said` lines, which the tool does print.

This also settles, by construction, a question the report leaves ambiguous: at
13:30 the instrument reported **4** findings introduced by batch68 while section
(1) names **2** defects. Both are right and they are not in conflict — the 4 is
2 real `NEW-OR-UNEXCUSED` gates plus the 2 restatement lines that moved with
them, exactly the shape reproduced here in the opposite direction. **The defect
count is 2.** Suggested refinement for whoever owns the instrument: count and
report restated summary lines separately from new findings, and say which
direction a changed count moved.

## WHAT WAS NOT DONE

No `--write-baseline`, on any gate. `gate_fixture_debt.json` untouched. No
assertion relaxed, no regex widened, no test deleted, no baseline rewritten. No
production code touched — both gate programs and the dispatcher are byte-
identical to main. No GDS touched. Nothing pushed to main. No version bumped.
The 12 remaining unexcused gates are not diagnosed and nothing is claimed about
them.

## HYGIENE, BOTH SIDES, SEPARATE TREES — the branch moves nothing

Two clean checkouts, `git clean -xdfq` and `PYTHONDONTWRITEBYTECODE=1` in both,
one arm each, hygiene and pytest never sharing a checkout (the branch arm was
restarted after an early launch on a tree still holding uncommitted evidence —
a dirty worktree invents failures that vanish on commit, so that run was
discarded rather than reported):

    a4caccefe   83 of 93 decided — 81 passed, 2 failed; 10 NOT CHECKED, 0 WROTE CORPUS, 462s
    045114294   83 of 93 decided — 81 passed, 2 failed; 10 NOT CHECKED, 0 WROTE CORPUS, 497s

    gate-name sets: IDENTICAL, 93 = 93
    NEWLY FAILED:   none
    the same two failures on both sides, and they are not this branch's:
        ^^ FAILED: PPA measurement coverage
        ^^ FAILED: liar census controls still fire

83 + 10 = 93 reconciles on both arms. The base figure reproduces the
measurement report's recorded `83 of 93 — 81 passed, 2 failed; 10 NOT CHECKED`
for a4caccefe on an independent run, and `PPA measurement coverage` — the gate
the report flagged as arriving red with v1.11.69 and left undiagnosed — is
confirmed red here a fourth time. It is still not diagnosed and this branch
claims nothing about it.

`gates are host-independent` PASSED on both arms at load ~27, consistent with
the report's narrowed finding that its NOT CHECKED threshold sits above load 48.
