# The 1178 direct points — grouped, and the first group fixed

The census's direct slice is `cls==A && direct==yes`: a call site passes its own
`timeout=` and the expiry becomes a failing verdict about the subject. The brief
for this lane was explicit — **do not start until you have grouped**, because a
tail of 1178 is not 1178 problems.

## The denominator is mine, not inherited

The census was measured at `2ffa7a594`; `main` is now `a4f6b4f33`, so line numbers
have drifted. Rather than trust them, every site was re-derived by AST on the
current tree: a call to `subprocess.{run,check_output,check_call,call,Popen}` /
`.communicate` / `.wait` carrying a `timeout*` kwarg, **not** enclosed by any
`try` whose handler can catch `TimeoutExpired` (which includes `SubprocessError`,
`Exception`, `BaseException` and a bare `except`).

| | |
| --- | ---: |
| files parsed | 4507 |
| parse failures | 0 |
| `timeout=` spawn sites | 1484 |
| …covered by a timeout-catching handler | 334 |
| **uncovered — this lane's slice** | **1150** |

1150 against the census's 1178. The gap is not disagreement: this derivation is
tighter, and it separates the census's own two false-positive kinds mechanically
rather than by sampling.

## The grouping

### By tree

| tree | sites |
| --- | ---: |
| `programs/tests/` | 1010 |
| `programs/` (non-test) | 68 |
| `mcp-eda/` | 36 |
| `tools/` (repo root) | 35 |
| `plugin/tools/` | 1 |

### By enclosing name — the tail is copy-paste, not variety

676 distinct enclosing names, but the top of the distribution is one helper
written 200 times:

| enclosing | files | sites |
| --- | ---: | ---: |
| `_run` | 200 | 200 |
| `_git` | 24 | 24 |
| `test_a_bad_invocation_is_rc_3` | 21 | 21 |
| `test_a_missing_tree_is_undetermined_not_a_pass` | 20 | 20 |
| `_run_gate` | 18 | 18 |
| `run` | 15 | 16 |
| `_cli` | 14 | 14 |
| `test_the_shipped_tree_passes_its_own_rule` | 14 | 14 |
| `_run_cli` | 9 | 9 |
| `_run_tclsh`, `test_chip_agnostic_guard`, `_gate` | 19 | 19 |

**355 sites in 12 name-families.** They are near-duplicates, not exact ones —
the 200 `_run` bodies are 157 distinct texts — so a single shared helper is a
large mechanical edit rather than a small one. What they DO share is the shape:
one `subprocess.run` and one constant.

### By the constant — this is the group that matters

| bound | sites | cumulative |
| ---: | ---: | ---: |
| `timeout=60` | 462 | 40 % |
| `timeout=30` | 103 | 49 % |
| `timeout=_T` | 94 | 57 % |
| `timeout=300` | 72 | 63 % |
| `timeout=120` | 36 | 69 % |
| `timeout=55` | 31 | 72 % |
| `timeout=1800` | 30 | 75 % |

**Four numbers cover 63 % of the slice, and one number covers 40 %.** `60` is the
number in the owner's ruling.

The clearest single piece of evidence in the slice sits beside one of them.
`tests/test_ci_harness_timeout_ceiling_check.py` defines `_T_TREE = 60` under a
comment recording what was actually measured for that call:

```
uncontended, 3 runs   13.75 / 13.53 / 13.70 s
8 concurrent copies   worst 15.10 s
32 concurrent copies  worst 43.75 s
```

43.75 s of a 60 s bound is consumed by load alone, on a 32-core host, at 4x the
landing lane's concurrency. The author measured the defect and then wrote the
number down anyway. Nothing about the subject changes between those rows.

## What was fixed

**29 sites in 12 landing gates — the `git`-plumbing group.** One cause: a gate
asks `git` a question under a wall-clock bound, and the expiry escapes as rc 1,
which downstream reads as *this commit is defective*.

`tracked_symlink_target_present_check` states the principle and then breaks it
three lines below:

> reporting it would make the gate fail on a machine rather than on a commit,
> which is the thing #555 is about

```python
r = subprocess.run(["git", "-C", str(root), "ls-files"], timeout=180)
```

Not hypothetical on the host these run on. Measured on the shared checkout
while writing this: **32 registered worktrees**, **20,670 loose objects**, 48
packs. Load average on this box moved from 12.45 to 1.43 over the few hours this
lane took — the same `git ls-files`, the same commit, an order of magnitude
apart in what it costs. That spread is the whole argument.

Two shapes, and the difference is load-bearing:

* **20 verdict-bearing reads** → `_pr.run`, and each gate's entry point maps a
  stall to **rc 2, announced**. Verified, not assumed: all 11 wrapped gates
  spell rc 2 "could not measure"
  (`_vacuous_exit.RC_PASS,RC_FAIL,RC_VACUOUS = 0,1,2`, plus `RC_NOTHING`,
  `RC_UNDETERMINED`, `RC_CANNOT_MEASURE`, `RC_NOT_CHECKED`).
* **9 best-effort cleanups** (worktree remove/unlock/prune, `checkout --`) →
  `_pr.run_best_effort`, rc 199, which their existing `if rc == 0` already
  handles.

Keeping those two apart is the whole point. An rc at a *verdict* site would let
every `if rc != 0: fail` in the repo convert a host condition straight back into
a finding about the subject.

rc 2 still blocks the landing sweep — `_gate_dispatch.sh` maps it to NOT_CHECKED
by design. That is intended: the outcome is as blocking as before, but the reason
is now **true**. "This gate could not finish looking" is actionable; "this commit
has a broken pointer" was not, because it was false.

### The replacement primitive

`programs/_progress_run.py`, deliberately `subprocess.run`-shaped so a site
converts by deleting `timeout=`. It reuses `_watchdog`'s supervision loop rather
than reinventing it, and judges three signals: output bytes, `utime+stime` summed
over the child **and its live descendants**, and `read_bytes+write_bytes`. Any
signal advancing = progressing, and a progressing child is never killed. Nothing
advancing across N **consecutive looks** = stalled. N counts looks, not seconds.

Two defects in the first draft, both worth recording because both are the same
error this lane exists to remove:

* the poll cadence was derived **downward** from a measured spawn floor
  (0.0126 s here), producing a 3 s stall window that would have murdered anything
  blocked on a slow network read — which moves neither CPU nor block-I/O. The
  measurement now only ever makes the primitive **more** patient:
  `max(30 s, floor x 100)`.
* `input=` set `stdin=PIPE` and never wrote to it — a silent hang, which is
  precisely the failure mode being removed. It refuses out loud instead.

## Evidence

* 10 gates driven against one fixed subject tree from both arms: identical rc and
  byte-identical output, 0 differences.
* The first sweep **proved nothing, and said so**: under `python3 -I` every gate
  died at import (isolated mode drops site-packages), and argparse's rc 2 for an
  unrecognised argument reads exactly like a gate's own rc 2 UNDETERMINED. Both
  arms agreeing on a crash is not agreement about the change.
* Identical output is also what *"my code never ran"* looks like, so the calls
  were **counted**: 6 gates reached the primitive across 19 real calls
  (target_present 4, portability 1, worktree_is_clean 5, noop_verdict 6,
  doc_table 1, conflict_resolve 2).
* Both arms of the 10 owning test files: **209 passed, 3 skipped**, identical.
* `_progress_run`'s own control is bidirectional and each test drives the SAME
  child through both shapes, asserting they DISAGREE: a quiet CPU-bound child is
  refused by `timeout=0.6` and completes under a 0.6 s **stall** window; a
  motionless child is still caught. 10 passed.

## Rejected as false positives

**16**, all mechanically separable, none requiring a judgement call:

| callee | n | why |
| --- | ---: | --- |
| `runner.run(...)` | 8 | `runner = _kl.find_runner()` — a call-through |
| `run(...)` | 6 | a local helper; 4 of them are `mcp-eda/.../de10lite/driver.py`, whose `run()` **already catches** `TimeoutExpired` and returns rc 124 — indirect *and* covered, two reasons |
| `_s.run`, `M.run` | 2 | call-throughs |

A further 2 sites sit in files that patch `subprocess.run`, so nothing is spawned.

This is a **correction to the census**, and it runs the other way from the
sampled 80 %: on the tightened direct-subprocess definition the false-positive
rate in this slice is 16/1150 ≈ **1.4 %**, not ~20 %. The census predicted this
("the tightened direct-subprocess count is the more accurate one"); this measures
it.

## Two corrections to the framing — both were nearly shipped as confident claims

**1. The landing harness no longer has an elapsed ceiling.**
`ci_harness_timeout_ceiling_check`'s docstring describes
`pytest --timeout=180 --timeout-method=thread`, and reasoning from it produces a
conclusion that is now false — that deleting an inner bound in a test merely
*relocates* the verdict to a coarser session kill. Measured on this tree instead:
all three landing pytest populations run through
`pytest_per_file_junit.py --stall-after 300`, a **stall** parameter; `--timeout=`
appears nowhere; `pytest-timeout` is *deliberately* absent — "elapsed time is not
a test verdict". The gate itself now reports **"fixed elapsed ceiling: none"**.

So the 1010 test rows are safely convertible. Nothing above them re-imposes a
clock.

**2. Converting a file *completely* can break a self-referential test.**
Attempted and **reverted**: all 35 sites in
`tests/test_ci_harness_timeout_ceiling_check.py` (one cause — the constant `_T`).
The conversion is clean and 88 tests pass, but
`test_this_files_own_bounds_are_inside_the_ceiling` fails on

```python
assert sites, "no bound was READ — has the scan stopped working?"
```

Base 89 passed; candidate 1 failed / 88 passed. The guard is a non-vacuity check
on the *scanner*, and a file with genuinely zero bounds makes it unsatisfiable —
the ideal end state breaks the check that polices the way there. The correct
repair re-anchors the guard onto a fixture that still contains a bound, while
asserting separately that this file has no offenders. That is strictly stronger,
but it is an edit to another subsystem's non-vacuity guard and needs its own
bidirectional control, so it was not done unverified. **Whoever takes the test
tail hits this on every self-policing file.**

## Left, and why

* **`programs/tests/` — 1010 sites.** Convertible (see correction 1), and the
  four-constant grouping above is the order to do it in. Not started here beyond
  the one reverted trial.
* **`mcp-eda/` — 36 sites.** 32 are in `test/`; the only 4 in tool code are the
  rejected `driver.py` call-throughs. There is **no direct user-visible verdict
  defect in `mcp-eda/`** — priority 2 in the brief is empty once read.
* **`tools/` (repo root) — 35 sites.** 24 in tests, 11 in non-test. Not started.
* **`gate_host_independence_check.py:467, :986`** — `timeout=timeout`, the bound
  the gate deliberately imposes on the subject it drives. A different question
  from this lane's, and left alone.
* **`shape_b_sample_export.py:362`** — an `iverilog` bound carrying an explicit
  `# watchdog-exempt:` justification. Class A, but it belongs to
  `loop_watchdog_compliance_check`'s exemption bookkeeping. Deprioritised, not
  rejected.

## Not measured, by name

Converted but **not exercised** by a run that reached the call — stated rather
than implied:

* `published_record_staleness_check.py` — its `check-ignore` site needs a
  superseded record present to reach.
* `attestation_preflight_check.py` — refused my invocation at rc 3 on both arms.
* `ci_ran_at_all_check.py`, `benchmark_run_manifest.py`,
  `policy_direction_pin_check.py`, `gate_host_independence_check.py` — covered by
  their owning test files (both arms identical) but not by a direct corpus run
  that entered the converted line.
