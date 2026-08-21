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
   KEYWORDS — the seam shape the failing test names in its first line — so all
   ten tests in `test_hygiene_record_handover.py` still drive them and still
   pass. `argv` cannot reach them.
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

_Filled in below from the 1800 s run against the fix tree with the published
corpus bound._
