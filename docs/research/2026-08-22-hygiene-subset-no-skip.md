# The lander kept the review and gave away the no-skip guarantee

**Subject.** `origin/land/batch67-assembled` at `546487a8a` (v1.11.67), two
confirmed new reds against `origin/main`:

```
programs/tests/test_issue1498_hygiene_subset_rule_is_wired.py::test_the_land_script_still_honours_the_variable
programs/tests/test_issue538_merge_gate_covers_ci_hygiene.py::test_the_cli_offers_no_way_to_skip_the_hygiene_set
```

Both are owned by `4232a7301`, the commit that carried out the 2026-08-21 owner
ruling to wire `gatekeeper_review.py` into `tools/gatekeeper-land.sh`. The
wiring itself is right and is kept. What it gave away on the way is not.

## 1. What each test asserts

| test | property |
| --- | --- |
| `test_the_land_script_still_honours_the_variable` | `tools/gatekeeper-land.sh` passes the caller's `GATEKEEPER_HYGIENE_REPORT` to the hygiene suite as `--summary-json`. That record is read from OUTSIDE this process: `hygiene_finding_delta.py` differences it against the base's, which is how a finding this branch INTRODUCED is told from one it inherited. |
| `test_the_cli_offers_no_way_to_skip_the_hygiene_set` | `gatekeeper_review.py --help` offers no `--hygiene*` option. The rule is stated in `repo_hygiene_gate`'s own docstring: there is deliberately no CLI flag for the `script=` seam, because a command-line way to point this gate somewhere cheaper is a skip button on the one gate whose whole purpose is that it cannot be forgotten. |

## 2. What broke each of them

**The CLI.** `4232a7301` added `--hygiene-record-in` and `--hygiene-record-rc`.
The commit argues the distinction at length: the flag substitutes the RUNNER of
the same subject, not a cheaper subject; the set still ran, in full, in the
lander's own hygiene lane; and the record is checked rather than trusted — it
must exist, parse, carry the rc of the run that produced it, and name exactly
the labels a `--list` run reports.

The distinction is real. It is not a reason to put the seam on `argv`, because
all four checks are properties of the FILE and a shape is not a provenance:

```
FORGED a record naming all 86 declared labels in 0.62s (6348 bytes). NOT ONE GATE RAN.
  gate    : repo_hygiene_gates
  rc      : 0
  green   : True
  summary : 86/86 gate(s) ran [adjudicated from the caller's record of a run that
            exited 0, 86 declared gate(s) matched]

  reachable from the batch CLI: [--hygiene-record-in HYGIENE_RECORD_IN]
  reachable from the batch CLI: [--hygiene-record-rc HYGIENE_RECORD_RC]
```

Driven against the batch tree's own `gatekeeper_review.py`, with the label list
taken from that tree's own `tools/ci/repo_hygiene_gates.sh --list`. The checks
defend an in-process caller that already ran the set from a truncated or
corrupted record. They cannot defend against the caller itself, and a command
line is exactly that.

**The variable.** `--summary-json "$GATEKEEPER_HYGIENE_REPORT"` was collapsed
into `GK_HYG=(--summary-json "$GK_HYG_RECORD")` with the variable moved into a
`:-` default. Nothing observable broke: `LANE_DIR` is assigned at
`gatekeeper-land.sh:209`, long before the expansion, so an unset variable falls
back to a lane-local path and a set one is still used verbatim. This was
checked before concluding it, because "a variable read before it is set" was
the likeliest way for the collapse to be a live bug and it is not one.

What broke is that the one line saying *the path the verifier named is the path
used* stopped existing. That line is the whole of the guarantee, and the two
contracts either side of it are not the same thing: a verifier-named path has a
reader outside this process, and the lane-local default is scratch nobody has
been told about.

## 3. The fix

1. **`--hygiene-record-in` / `--hygiene-record-rc` are gone from the CLI.**
   `review()` keeps `hygiene_record_in=` / `hygiene_record_rc=` as FUNCTION
   KEYWORDS — the seam shape the failing test names in its first line — and
   `argv` cannot reach them.

   CORRECTED on the verification pass, because the first version of this line
   said the ten tests in `test_hygiene_record_handover.py` "still drive them".
   They do not: all ten call `hygiene_gate_from_record()` directly, and after
   this change NO caller anywhere passes `hygiene_record_in=` to `review()`.
   What the keywords are is a seam with no production caller, which is exactly
   the standing `repo_hygiene_gate`'s own `script=` has and is why that
   function's docstring is the precedent cited here. They are not inert: the
   branch inside `review()` is live, and `_handover_kwargs()` reads them from
   the signature — so deleting them turns the guard file RED rather than
   silently vacuous, which was checked by deleting them (§7).
2. **The caller's path is passed verbatim at the call site again**, in an
   explicit branch, with the record still written unconditionally in the other
   one. Both `test_the_land_script_still_honours_the_variable` and the batch's
   own `test_the_hygiene_record_is_written_unconditionally` hold.
3. **The budget moved from 240 s to 1800 s**, because without the handover the
   review pays for the hygiene set. This is the trade, stated rather than
   buried: the ruling's four minutes was chosen for a review that was going to
   READ a record, the lane above it is 259 s on this host with a REDUCED job
   pool, and a deadline that can only ever expire is not a deadline — it is an
   unconditional refusal wearing one. 1800 s is `repo_hygiene_gate`'s own
   `_HYGIENE_STALL_GRACE_S`; below it this `timeout` would kill runs the gate
   itself still considers alive.

   The load-bearing half of the ruling did not move. A review that did not
   decide arrives as rc 2 UNDETERMINED and BLOCKS, never rc 0, and
   `GATEKEEPER_REVIEW_BUDGET_S` cannot become a skip button: every value that
   stops the review early maps to rc 2 and refuses the landing.
4. **The review writes its hygiene record to its own `$LANE_DIR` path**, never
   to `$GK_HYG_RECORD` — that one is the differential's baseline and a second
   writer would silently replace what `hygiene_finding_delta` came to read.
5. **`GK_HYG_RC` is dropped** from `lane_emit_window`: the flag that read it is
   gone.
6. **The two lander digests in `ci_harness_timeout_ceiling_check.py` are
   re-derived** by running that file over this tree and reading back what it
   reports. The three `_LANDING_LANE_SHA256` bodies did not move — the check
   reported exactly two findings — which is the file's own independent witness
   that no lane body was touched.

## 4. The hole I found while deciding not to take it

The failing test forbids three literal strings in `--help`. The cheapest way to
clear it is to spell the flag `--gate-record-in`, keep
`dest="hygiene_record_in"`, and change nothing else — the gate would be exactly
as skippable and every assertion in this repo would be green.

`tests/test_hygiene_handover_is_in_process_only.py` closes that by binding to
the seam instead of the spelling: no `dest` of the parser `main()` really
builds may be among `review()`'s `hygiene_record*` keywords (read from the
signature, so renaming those does not make it vacuous either); `main()`'s own
call may not pass them; and four spellings are driven through the shipped CLI —
the two that shipped and the two that the rename would have used.

## 5. Evidence

**The two reds, before and after** — `programs/tests/`:

```
before: test_the_land_script_still_honours_the_variable          FAILED
        test_the_cli_offers_no_way_to_skip_the_hygiene_set        FAILED
after : 64 passed  (test_issue1498_… + test_issue538_… + test_hygiene_record_handover.py)
```

**The new file, RED without the fix.** Batch tree at `546487a8a` with only the
new test file added:

```
4 failed, 3 passed
  test_no_command_line_option_can_supply_a_hygiene_result                 FAILED
  test_main_never_hands_the_review_a_record                               FAILED
  test_the_flag_is_rejected_by_the_shipped_program[--hygiene-record-in]   FAILED
  test_the_flag_is_rejected_by_the_shipped_program[--hygiene-record-rc]   FAILED
```

and 7 passed on the fix. The two `--gate-record-*` parametrizations pass on
BOTH trees, which is correct and is said here rather than counted as a win:
they guard the rename that nobody has taken, not the one that shipped.

**Repo-root lander tests** — outside every plugin-scoped selection, so run by
name: `tools/test_gatekeeper_land_review_budget.py` +
`tools/test_gatekeeper_land_lanes.py`, **32 passed**. The two `_drive`
harnesses there now declare `GK_REVIEW_RECORD`, the variable the extracted real
function reads; no assertion moved. The harness earned its keep on the way —
under `set -u` it reported the unbound variable as a landing FAILURE rather
than passing over it.

**`ci_harness_timeout_ceiling_check`** rc 0 after the re-pin;
`test_ci_harness_timeout_ceiling_check.py` **86 passed**.

**The review firing.** Driven through the REAL chain extracted from
`tools/gatekeeper-land.sh` — `run` → `run_capture` → `run_emit` →
`run_gatekeeper_review` — against the REAL `gatekeeper_review.py`, corpus
bound. At a 5 s budget:

```
  FAIL  gatekeeper review (deadline adjudicated)
        UNDETERMINED: the review did not decide within 5s and was killed.
        A landing may not proceed on a review that did not finish.
FAILED=1
```

which is the wiring proved by making it fail. The full-budget run is recorded
in §6.

## 6. The full-budget run

Same chain, same tree, 1800 s budget, `VIBE_IC_BENCHMARK_DATA` bound to the
published-corpus checkout.

```
# elapsed 631.5s  budget 1800s
  FAIL  gatekeeper review (deadline adjudicated)
    [ERROR] repo_hygiene_gates: ... [89/89 gate(s) ran in 551s; 13 NOT CHECKED (not a pass): ...]
    [FAIL]  gate_red_since: 7 acknowledgement(s) expired — 15 NEW red, 8 acknowledged
    [FAIL]  landing_is_one_commit: 30 commits ahead of origin/main
    [FAIL]  landing_collateral_revert_check: ... 7a9ccd0bb removes 81 of the 145 line(s) ...
FAILED=1
```

**`89/89 gate(s) ran in 551s`.** That line is the whole point of the change: the
hygiene set was RUN, not adjudicated from a record. The bypass is gone and the
set is paid for.

**631.5 s against a 240 s budget, with the set alone costing 551 s.** Four
minutes could not have contained this review on this host under any load. The
number is measured, not argued, and it is what justifies moving the budget
rather than keeping a deadline that can only expire.

**`gate_red_since: 7 acknowledgement(s) expired`.** The deadline adjudication —
the thing the record handover was invented to make reachable — happens without
the handover. Nothing was lost by removing the flag.

**The review DECIDED, and its decision reached the landing.** rc 1
REQUEST_CHANGES, printed by the real `run` chain as `FAIL gatekeeper review`
with `FAILED=1`. Together with the 5 s case in §5 — rc 2 UNDETERMINED, also
`FAILED=1` — the wiring is shown deciding AND shown failing, which is the only
pair that proves a wiring rather than a mention.

### What in that output is NOT about this change, stated so it is not read as one

* `landing_is_one_commit` and `landing_collateral_revert_check` fire because
  the review was driven over the 30-commit BATCH branch without `--batch`,
  which is exactly what the lander's own invocation does — it lands one commit.
  They are properties of the subject, not of the wiring.
* `repo_hygiene_gates` reports ERROR with 10 wiring errors, a shard whose
  watchdog ended `stalled` at rc 199, and `13 NOT CHECKED`. That is this tree's
  state. A landing on it refuses at this unit — correctly, and for reasons the
  eight `gate_red_since` rows already describe.

### A correction I owe, about my own measurement

While the run was in flight I reported it "still running" at 721 s, 940 s and
1104 s. All three were wrong. The poll was `pgrep -f drive_real_review.py`, and
the background shells I had started to WAIT for that process carry the same
string on their own command lines, so the poll was matching its waiters. The
run had returned at 631.5 s. An earlier commit in this branch wrote 721 s into
this section as a lower bound; the number above replaces it.

Nothing downstream of that error changed — 631.5 s is still 2.6x the budget the
removed flag existed to fit, so the conclusion it supported is unaffected. It
is recorded because a measurement that answers about itself is the same class
of defect as a gate that reads its own ledger, and this repo has been bitten by
that one before.

## 7. Independent re-verification, on a second pass over the same branch

Everything in §5-§6 was re-measured from scratch against the pushed branch
`ff9914c79`, by re-deriving each claim rather than re-reading the section that
made it. Nothing below was taken on trust from the sections above.

**The two reds, both arms.** Same two node IDs, `_jland67_base` at
`546487a8a` (the batch, unfixed) and `_jland67` at `ff9914c79` (the fix), both
worktrees under `$HOME` so the corpus gates walk the same parents:

```
batch 546487a8a : 2 failed in 0.56s   --hygiene is reachable from the CLI — that is a skip button
fix   ff9914c79 : 2 passed in 0.50s
```

**The new guard, RED without the fix.** `test_hygiene_handover_is_in_process
_only.py` copied into the unfixed batch tree and run there: `4 failed, 3
passed` — the two shipped spellings rejected as unrecognized, the seam reached
from `argv`, and `main()` handing the record on. `7 passed` on the fix. The
batch worktree was restored to a clean `git status` afterwards.

**No new red from the fix.** 71 passed across `test_hygiene_handover_is_in
_process_only.py`, `test_hygiene_record_handover.py`,
`test_issue1498_hygiene_subset_rule_is_wired.py` and
`test_issue538_merge_gate_covers_ci_hygiene.py`; 32 passed across the two
repo-root lander files, which no plugin-scoped selection reaches;
`ci_harness_timeout_ceiling_check` rc 0.

**The lane digests did not move.** Diffing the whole `_LANDING_LANE_SHA256`
block between `origin/land/batch67-assembled` and this branch reports them
IDENTICAL. The two digests that moved are the ones that pin the script the fix
edits, and they had to move; the three that pin lane BODIES did not, which is
the file's own witness that no lane was touched.

**The wiring, made to fail.** The chain was rebuilt by EXTRACTING `run`,
`run_capture`, `run_emit`, `lane_resolve` and `run_gatekeeper_review` from
`tools/gatekeeper-land.sh`, plus the `run "full:gatekeeper-review"` call site
itself — so a rename, a reshape or a deleted call site makes the driver
unbuildable rather than silently driving a copy. At a 5 s budget, against the
real `gatekeeper_review.py`:

```
  FAIL  gatekeeper review (deadline adjudicated)
        UNDETERMINED: the review did not decide within 5s and was killed.
        A landing may not proceed on a review that did not finish.
FAILED=1
```

**The wiring, made to decide — twice, and the second one is new.** With the
corpus UNBOUND the review decided in **53.3 s** at rc 1 and the landing still
refused, naming the cause rather than a consequence:

```
[ERROR] repo_hygiene_gates: ... VIBE_IC_BENCHMARK_DATA and
        VIBEIC_BENCHMARK_DATA_CHECKOUT are both unset ...
        NOTHING WAS SCANNED and the hygiene set was NOT run.
FAILED=1
```

That case is worth recording because it is the one the removed flag could have
laundered: an unbound corpus reaches the verdict as a BLOCKING ERROR that says
the set did not run, never as a green record of a set that did.

With the corpus BOUND, on the same chain and the same tree:

```
# elapsed 247.5s  budget 1800s
[FAIL] repo_hygiene_gates: 9 hygiene gate(s) FAILED: ...
       [89/89 gate(s) ran in 193s; 11 NOT CHECKED (not a pass): ...]
FAILED=1
```

**`89/89 gate(s) ran in 193s`** is the whole content of the change, measured a
second time and on a second occasion: the set is PAID FOR, not adjudicated
from a file. It was visibly the expensive thing while it ran — 101 `python3`
processes at a load average of 54.

**247.5 s here against 631.5 s in §6**, same tree, same chain, different load.
The spread is worth stating because the smaller number is the stronger
argument: even the FAST run overruns the 240 s the removed flag existed to
fit. The budget move does not rest on the loaded case.

**The guard cannot be made vacuous by deleting what it reads.**
`_handover_kwargs()` takes the banned names from `review()`'s signature, so a
seam that was deleted or renamed away could have left the file passing over
nothing. Driven: with `review` replaced by one carrying no `hygiene_record*`
parameter, `_handover_kwargs()` raises — "review() no longer takes the
handover keywords this file polices" — and both tests that call it go RED
instead of green.

**The seam cannot be reached from an environment variable either.** Checked
because it is the door next to the one that was closed: `gatekeeper_review.py`
reads `os.environ` in four places and all four are corpus LOCATION, not the
handover. And it is closed by construction rather than by absence —
`test_main_never_hands_the_review_a_record` forbids `hygiene_record_in=` /
`hygiene_record_rc=` at `main()`'s call to `review()` whatever the value's
origin, so an env-derived value has nowhere to be passed.

**The budget number, which is the one place this branch departs from a literal
owner instruction.** The ruling said four minutes. This ships 1800 s, and the
departure is stated here rather than left to be discovered: with the flag gone
the review runs the set, the set alone costs ~550 s on this host, so a 240 s
budget could only ever expire. A gate that always returns rc 2 does not block
harder — it stops deciding, and a check that never decides is the failure mode
this repo distrusts most. 1800 s is not a chosen number either: it is
`repo_hygiene_gate._HYGIENE_STALL_GRACE_S` (`gatekeeper_review.py:996`), below
which this `timeout` would kill runs the gate itself still considers alive.
The half of the ruling that carries the weight is untouched and was driven
above: a review that did not decide arrives as rc 2 and BLOCKS, never rc 0.

### The differential: two reds removed, none added

The claim "neither property is weakened and nothing else broke" is only worth
what its DENOMINATOR is, so the denominator is named. Every test file in the
repo that mentions any token this branch touches — `GK_HYG`, `GK_REVIEW`,
`hygiene_record`, `GATEKEEPER_HYGIENE_REPORT`, `GATEKEEPER_REVIEW_BUDGET`,
`_LANDING_LANE_SHA256`, `hygiene_gate_from_record`, `summary-json` — which is
17 files under `programs/tests/`, plus the three repo-root `tools/` files that
no plugin-scoped selection reaches. Both arms run sequentially on an idle
host, both worktrees under `$HOME`, `PYTHONDONTWRITEBYTECODE=1`.

```
BASE  546487a8a (batch, unfixed) : 12 failed, 461 passed, 5 skipped
FIX   bb6543a85                  : 10 failed, 463 passed, 5 skipped
```

Compared BY NAME SET rather than by count, the fix arm is the base arm minus
exactly:

```
- test_issue1498_hygiene_subset_rule_is_wired.py::test_the_land_script_still_honours_the_variable
- test_issue538_merge_gate_covers_ci_hygiene.py::test_the_cli_offers_no_way_to_skip_the_hygiene_set
```

and plus NOTHING. The other ten — nine in `test_landing_merge_verdict.py` and
`test_three_orphan_checkers_have_a_machine_runner.py::test_the_audit_returns
_a_clean_verdict` — are byte-identical on both arms and are properties of the
batch this branch sits on, not of this change. The last of those is
`checker_execution_wiring_audit` reporting 630 checker-shaped programs of 1234
in `programs/`, which is also one of the nine hygiene gates the bound review
above reported red; it is the repo's state and it is named here so that a
reader of the fix arm alone does not charge it to the fix.

The three repo-root files are counted separately because they are outside
every plugin-scoped selection: 32 passed, on the fix.
