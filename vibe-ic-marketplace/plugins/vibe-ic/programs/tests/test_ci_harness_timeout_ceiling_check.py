"""Unit tests for ci_harness_timeout_ceiling_check.py (vibe-ic#542).

Pins, in the order the gate can be wrong:

  * the harness bound is READ from the workflows, ALL of them, and the binding
    one is the MINIMUM — the repo declares four and they disagree;
  * an unreadable bound is rc 2 with a "NOT a pass" sentence, never rc 0;
  * `ast`, not grep: a `def runner(cmd, timeout=3600)` signature and a
    `--timeout=900` inside a docstring are not bounds;
  * the callee allowlist: aliases and `from`-imports resolve, exception
    constructors do not count, same-file wrappers do, unresolvable callees are
    ADVISORY and are printed rather than silently dropped;
  * a bound spelled as a module constant is resolved — that shape hid the
    single largest offender in the tree from the report that opened the issue;
  * …and so is a bound spelled as a PARAMETER DEFAULT (vibe-ic#1277), which
    was worse than unjudged: the call left the findings, the advisories AND
    the readable-bound denominator, so two spellings of one 1800 s bound gave
    `1 readable bound / FAIL` and `0 readable bounds / 0 not judged / PASS`;
  * a call inside a test carrying `@pytest.mark.timeout(N)` is judged against
    `N // 3`, because N is the bound pytest-timeout really applies to that
    item — and a marker BELOW the harness bound tightens the ceiling, so it is
    a model rather than an escape hatch;
  * FALSIFIABILITY against the real tree: inject an offender, the shipped gate
    goes rc 1 and names it; remove it, rc 0.

Every DURATION bound in this file is `_T`, over a synthetic `tmp_path` tree that
parses in well under a second. The launches over the REAL repository tree carry
no duration at all: they go through `_gate_over_the_real_tree`, which bounds a
LACK OF FORWARD PROGRESS, because a whole-tree parse timed on a shared host
measures the host (see `_T_TREE`, which survives as that stall grace). The last
test asserts both values are inside the ceiling the gate itself computes — a
test file that policed the corpus while breaking the rule would be its own
counter-example.
"""
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))


_PROG = _PROGRAMS / "ci_harness_timeout_ceiling_check.py"

#: Inner bound for a launch over a SYNTHETIC tree — a `tmp_path` checkout with a
#: workflow file and a handful of test modules. Those are a pure parse over a few
#: files and measure in well under a second, so 30 s is ~100x headroom and half
#: the ceiling the gate itself publishes.
_T = 30

#: Inner bound for a launch over the REAL repository tree, which is a different
#: population and now a much larger one. MEASURED rather than rounded, on
#: c43fe4057 in the shipped container image, 32 cores:
#:
#:   uncontended, 3 runs   16.87 / 17.09 / 16.82 s   (before the two fixes below)
#:   uncontended, 3 runs   13.75 / 13.53 / 13.70 s   (after)
#:   8 concurrent copies   worst 15.10 s  (after) — the landing lane's own
#:                         concurrency, read from the failing run's
#:                         `FALLBACK_RESOURCE_CAP ... requested=8 selected=8`
#:   32 concurrent copies  worst 43.75 s  (after) — 4x the lane's concurrency,
#:                         standing in for the whole-host load that made a
#:                         nominally-8-job lane exceed 30 s at v1.11.91
#:
#: WHY THE NUMBER MOVED, and which half of it is legitimate. v1.11.91 wired
#: `wall_clock_bound_standing_in_for_a_verdict` into this gate, so every run now
#: also sweeps 4405 modules that no run of it used to touch. Two parts:
#:
#:   * 3.3 s of that was AVOIDABLE and is gone — the sweep built a full parent
#:     map (a second `ast.walk`) for all 1777 process-spawning modules when 5 of
#:     them contain a comparison for it to answer about. Fixed in the sweep; the
#:     findings and the denominators it publishes are byte-identical.
#:   * the rest is HONEST WORK. Parsing 4405 modules costs 5.9 s and there is no
#:     cheaper way to know a module parses, which is what the census publishes as
#:     its denominator. Narrowing what the sweep looks at would un-wire what
#:     v1.11.91 wired, so it is not on the table.
#:
#: …AND THEN THE NUMBER ITSELF WAS THE DEFECT (timeout-as-verdict campaign).
#: Every line above is a measurement of DURATION, and the conclusion drawn from
#: it was a larger duration. That is the shape the campaign exists to remove: a
#: wall-clock bound on a whole-tree launch is a reading of THE HOST, not of the
#: gate. When it expired the run did not report "the host was loaded" — it
#: raised `TimeoutExpired` out of `subprocess.run` and the item went RED, in a
#: file nobody had touched, and the fix on offer was always another number. The
#: history above is itself the evidence: 30 was measured, defended in prose, and
#: still exceeded at v1.11.91 by nothing but load, and 60 is only 1.37x the
#: worst contention already observed. The next lane wider than 32 jobs takes it.
#:
#: So the whole-tree launches no longer carry a duration at all. They go through
#: `_gate_over_the_real_tree` below, which bounds NO FORWARD PROGRESS instead:
#: the gate parses 4405 modules and burns CPU from start to finish, so its
#: `utime+stime` advances between every pair of looks however loaded the host
#: is, and it can never be killed for being slow. A gate that genuinely wedges
#: still dies, because a wedged parse advances neither CPU nor I/O.
#:
#: `_T_TREE` SURVIVES AS THAT STALL GRACE, and the reason it keeps this value is
#: unchanged in form: 60 s is the CEILING this gate computes on this tree
#: (`180 s harness // 3`), and `test_this_files_own_bounds_are_inside_the_ceiling`
#: still asserts it. Holding the grace at or under the ceiling is what keeps the
#: diagnosis THIS file's to make: a stall is named `WATCHDOG_STALLED` well
#: before the 180 s harness could kill the session out from under it — and a
#: killed session writes no junit, which is the record-loss #1654 measured.
#: What it is NOT any more is a claim about how long the gate may take.
_T_TREE = 60










# ── the bound is read, and all of it ─────────────────────────────────────────











# ── the resolver must not climb out of the checkout it was handed ────────────



























































# ── an unreadable bound is not a pass ────────────────────────────────────────





# ── ast, not grep ────────────────────────────────────────────────────────────

_CEIL = 60










# ── the callee allowlist ─────────────────────────────────────────────────────













# ── the population is every tree a pytest lane runs ──────────────────────────









# ── a bound spelled as a constant ────────────────────────────────────────────





# ── a bound spelled as a PARAMETER DEFAULT (vibe-ic#1277) ────────────────────















# ── the bound that will REALLY apply to the call ─────────────────────────────



















# ── falsifiability against the real tree ─────────────────────────────────────









#: The advisory residual on the shipped tree: ZERO, and the number is no longer
#: a baseline anybody has to maintain.
#:
#: THE RESIDUAL WAS A DRIFTING COUNT AND THAT IS WHY IT WENT RED. It landed at
#: 10 with a prose note explaining each entry, and it was 11 before this change
#: — the eleventh (`S._bounded_vvp(timeout=120)`) arrived with a test that had
#: no reason to know a count in a different file governed it. A count baseline
#: cannot say WHICH entry is new, so the only way to answer that question was to
#: re-read all of them; and "raise it to 11" is available at every step and
#: never fails loudly. That is the shape #527/#530/#534 each spent a version
#: removing from a waiver registry, reintroduced as a single integer.
#:
#: So the eleven were read and every one was LOWERED to the ceiling instead,
#: measured rather than argued: at each of those call sites the callee is
#: monkeypatched (`R._run`, `dosr._run`/`_docker_exec`, `lec_run._docker`,
#: `S.subprocess.run`) or builds a STRING and launches nothing
#: (`tdf._build_batch_script`), so the worst case is microseconds and 60 s is
#: not a constraint on any of them. Nothing was suppressed and no exemption
#: survives: the population is unchanged and the numerator is empty.
#:
#: At zero the assertion below is also the strongest it can be. A NEW
#: unresolvable bound above the ceiling turns it red with the file, line and
#: callee named — which is the report the count could never produce.
#:
#: ── AND THEN ONE ENTRY WOULD NOT LOWER (vibe-ic#1022) ────────────────────────
#: The count above went red at 2, and re-reading both showed they are not the
#: same kind of entry. One was the eleven's kind and was LOWERED
#: (`test_matrix_artefact_mutation_channel.py`, worst single replay MEASURED at
#: 1.55 s under a 900 s bound — 60 s constrains nothing). The other is the first
#: entry in this corpus where the bound is REAL and the ceiling is genuinely too
#: low for it: `test_matrix_mutation_ledger.py::REPLAY_TIMEOUT` reaches one
#: `subprocess.run` per pytest cell whose worst case MEASURED over the full
#: 24-pair witness plan is 42.61 s at `jobs=8` / 26.8 s uncontended, so 60 s is
#: 1.41x the contended worst case and would fire on work that passes today.
#:
#: THE FIX FOR THE COUNT IS NOT A BIGGER COUNT — it is to stop being a count.
#: Everything the note above says against `10 -> 11` is true of `0 -> 1`: it is
#: available at every step, it never fails loudly, and it cannot say WHICH entry
#: is new. A NAMED set says all three. It keeps the property that made zero
#: strong (anything unrecorded fails, by name), and it adds the one zero could
#: not have: the recorded entry carries its measurement and its reason, so the
#: next reader inherits the evidence instead of an integer.
#:
#: The entry below is recorded, NOT waived. It is reachable in the 180 s lane
#: (verified: `ci_targeted_test_select.py --base HEAD` emits 15 files at the
#: smoke floor and 17 once `programs/matrix_mutation_ledger.py` is touched, the
#: two extra being this entry's file and the artefact channel's). Its correct
#: remedy is the checker's SECOND one — move the two replay-driven tests out of
#: the 180 s lane — which needs a lane that does not exist in this tree yet.
#: When it does, delete this entry and the set is empty again.
#: ── AND THE ENTRY HAD TO CARRY WHAT THE EXPIRY COSTS (vibe-ic#1654) ─────────
#: The recording below was honest and its measurement is sound, and it was still
#: only half the fact. It reasons about the call's DURATION — how long the bound
#: permits — and a reader of it learns "this test is slow". What it did not say
#: is what happens to the EVIDENCE when the bound is reached, and those are
#: different properties.
#:
#: MEASURED at 1adbf3444 with three files, one of them hanging in this entry's
#: exact shape (`Future.result` -> `Condition.wait` -> `waiter.acquire`):
#: `--timeout-method=thread` cannot interrupt a blocking `waiter.acquire()`, so
#: pytest-timeout dumps the stacks and takes the PROCESS down, and a process
#: that dies never writes its `--junitxml`. The green file that had already
#: PASSED lost its record with it, and `ls` on the junit target reported
#: `No such file or directory`. In the 91-file selection that opened #1654 the
#: blast radius was the other 90 files, on BOTH arms — which is the permissive
#: direction, because the merge gate's failed-set differential reads both arms
#: from junit and an absent record must never be read as a clean one.
#:
#: So the consequence is recorded HERE, beside the duration, and the fix is not
#: a re-bound: `programs/pytest_per_file_junit.py` gives each selected file its
#: own session and its own report, so this entry's expiry now costs THIS file's
#: record and names it (`NORECORD`) instead of the run's. The relocation the
#: entry asks for is still the right remedy for the DURATION half and is still
#: owed.
_REVIEWED_ADVISORY_RESIDUAL = {
    ("programs/tests/test_matrix_mutation_ledger.py", "L.replay_many"): (
        "REPLAY_TIMEOUT=900 bounds one `_run_cell` pytest-cell subprocess. "
        "MEASURED 24-pair witness plan, 32 cores, instrumented at `_run_cell`: "
        "32 invocations, worst single call 42.61 s at jobs=8 / 26.8 s "
        "uncontended (dimension-7 cell). 60 s is 1.41x that and would fire on "
        "passing work. Needs relocation out of the 180 s lane, not a re-bound. "
        "RECORD-LOSS CONSEQUENCE (vibe-ic#1654): when this bound is reached the "
        "180 s harness has already killed the SESSION, and a killed session "
        "writes no junit — so the expiry used to cost the whole run's "
        "machine-readable record, not just this file's result (measured: 1 "
        "hanging file of 91 selected, both arms, neither junit written). "
        "`programs/pytest_per_file_junit.py` now confines that loss to this "
        "file and NAMES it; the relocation is still owed for the duration."
    ),
}






# ── the gate is dispatched, not merely present ───────────────────────────────



def test_the_gate_reaches_the_merge_gate_through_the_same_script():
    """The merge gate INVOKES the hygiene script (#538) instead of re-listing
    it, so a gate declared there cannot be missing here. Pinned by reading the
    merge gate's own invocation rather than by trusting the comment."""
    src = (_PROGRAMS / "gatekeeper_review.py").read_text(errors="replace")
    assert "tools/ci/repo_hygiene_gates.sh" in src
    assert "--summary-json" in src


# ── this file obeys the rule it enforces ─────────────────────────────────────



# ── the marker is a DIAL, so it is capped (vibe-ic#1734) ─────────────────────
#
# One case per DOOR, not per number. The withheld v1.10.62 fix closed `0` and left
# `2700`, and its own self-check advertised coverage of `timeout(0)` BY NAME while
# a 900 s bound walked through the positive-marker door. Each test below is a door.









# ---------------------------------------------------------------------------
# THE INSIDE OF THE SAME CLAIM — `wall_clock_bound_standing_in_for_a_verdict`
#
# This gate concludes "elapsed time is not a test verdict" about the OUTER
# harness. The sweep that asks it of the INSIDE — a short forward-progress
# deadline killing a spawned subject and reporting the kill as a finding, with
# no record of the load — was reachable from nothing but its own unit test.
# It is imported here and its census is PRINTED and RECORDED every run.
#
# ADVISORY BY ITS OWN HEADER ("VERDICT CLASS: **ADVISORY**"), so the pair of
# tests below assert BOTH halves: the census sees the offender, and the gate's
# exit code does not move because of it.
# ---------------------------------------------------------------------------

#: A module the sweep's predicate fires on: it spawns, it compares an elapsed
#: wall-clock reading against a bound under the 2.0 s floor, the branch that
#: comparison controls reports a substantive finding, and nothing in it says
#: what the load was.
_OFFENDER = '''\
import subprocess
import time


def test_child_advances():
    proc = subprocess.Popen(["true"])
    started = time.monotonic()
    elapsed = time.monotonic() - started
    assert elapsed < 0.45, "did not advance — killed as hung, not slow"
'''

#: THE SAME MODULE WITH THE REMEDY THE SWEEP ASKS FOR, and nothing else: the
#: bound, the spawn and the assertion all stay. Only the message gains the load.
_REMEDIED = _OFFENDER.replace(
    'assert elapsed < 0.45, "did not advance — killed as hung, not slow"',
    'assert elapsed < 0.45, ("did not advance at load %r — killed as hung, "\n'
    '                        "not slow" % (os.getloadavg(),))').replace(
    "import subprocess", "import os\nimport subprocess")
assert _REMEDIED != _OFFENDER
