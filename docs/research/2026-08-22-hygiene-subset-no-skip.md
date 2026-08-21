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

### A third arm, because "two new reds" was a premise I had not checked

The differential above compares the fix to the BATCH, which answers "did the
fix break anything". It does not answer the question the batch's landing
actually turns on: were there only ever TWO new reds? The brief said so, my
own base arm reported twelve failures, and ten of them I had labelled
"pre-existing" on the strength of belonging to files this branch does not
touch. That is an argument, not a measurement, so it was measured.

Clean `origin/main` at `a00f53f20`, its own worktree under `$HOME`, same
selection. Two of the seventeen files do not exist on main —
`test_gate_red_since_rows.py` and `test_hygiene_record_handover.py`, both
added by the batch — so main runs fifteen. Neither contributes a failure on
any arm, so their absence cannot move the comparison.

```
MAIN   a00f53f20  (15 files) : 10 failed, 441 passed, 5 skipped
BATCH  546487a8a  (17 files) : 12 failed, 461 passed, 5 skipped
FIX    caee6baaf  (17 files) : 10 failed, 463 passed, 5 skipped
```

Compared BY NAME SET, `MAIN \ FIX` and `FIX \ MAIN` are **both empty**: the
fix's failures are exactly main's, neither more nor fewer. The batch's twelve
are those same ten plus the two this branch exists to remove.

The pass arithmetic closes on the same fact rather than being waved at: the
two batch-added files collect 22 tests, and 441 + 22 = 463. Every test that
passes on main still passes here.

So the brief's premise holds, and it holds as a measurement now: within this
selection the batch introduced exactly two reds, and this branch returns it to
main's failure set. The ten carried failures — nine in
`test_landing_merge_verdict.py` (`KeyError: 'corpus_transitions'` and a
merge-path verification that returns 0 where 2 is expected) and
`checker_execution_wiring_audit` reporting 630 checker-shaped programs of 1234
— are red on clean main and are nobody's regression in this batch. They are
named so that a re-measurement finding twelve does not read the ten as
collateral from this fix, and finding ten does not read them as fixed by it.

## 8. The other door: can a landing take a ROUTE that misses the review?

Closing the CLI door answers "can the review be handed a substitute". It does
not answer "can a landing avoid reaching the review at all", and the ruling
this branch implements rests on a claim about routes — *the lander is the ONE
path every landing takes*. That claim was checked rather than repeated.

**There are three landing-shaped scripts, and two of them are the third.**
`tools/gatekeeper-verify-merge.sh` and `tools/gatekeeper-land-differential.sh`
both invoke `tools/gatekeeper-land.sh` (12 and 13 references; the differential
runs `bash tools/gatekeeper-land.sh` for each arm, the verifier runs
`/subject/tools/gatekeeper-land.sh` in its container). Neither reimplements the
tier, and neither passes a flag that stops before it. So the review fires on
all three routes.

**Every early exit that precedes the review was read, and none of them lands.**
The review sits at `gatekeeper-land.sh:1607`, inside the full tier. Three
things can end the run before it:

| exit | what it does | can it land? |
| --- | --- | --- |
| `--cheap-only` (`:609`) | prints "full tier SKIPPED — no stamp will be written", `exit "$FAILED"` | **No.** It returns before every stamp write. |
| `GATEKEEPER_FAIL_FAST_NORECORD` + a targeted NORECORD (`:1514`) | `exit 2` | **No.** Non-zero and no stamp. |
| `GATEKEEPER_NO_STAMP=1` (`:1635`) | `rm -f` the stamp deliberately | **No.** Strictly stricter. |

The stamp is written at `:1654` and ONLY there, only when `FAILED -eq 0`, and
only after the review has contributed to `FAILED`. `tools/git-hooks/pre-push`
refuses any push to `main` whose HEAD is not the stamp's first line, so a run
that skipped the tier cannot authorise one.

`--cheap-only` does not delete an existing stamp, which was checked because it
is the obvious way for the flag to become a bypass. It is not one: a stamp
names a COMMIT, so the only stamp it can leave standing is one a FULL tier
already earned for that same commit — a run in which the review did fire.
Amend or add a commit and the hook's own comparison rejects it.

**What this does NOT close, said plainly.** `git push --no-verify` still steps
around the hook, and an operator who never runs the lander never reaches the
review. Wiring into the lander is strictly stronger than wiring into the hook —
it sits on the path an operator actually uses to land, and the hook's stamp is
minted by it — but neither defends against someone who runs neither. Nothing
in this repository can; that is a rule about people, and it is already written
as one ("never `--no-verify`"). It is recorded here so the ruling's phrase "the
one path every landing takes" is read as what it is: true of the three shipped
landing routes, not a claim that the tool cannot be walked past.

## 9. The batch took commit 1 of 11, and that is a NEW red

Written after the deliverable, because the batch moved while this branch was
being verified and the move is not safe as it stands.

`origin/land/batch67-assembled` is no longer `546487a8a`. It is now
`8c409aa5a`, "Merge fix/jland67-hygiene-subset-honoured into the batch
assembly" — this branch has already been taken. Its second parent is
`05732dd26`, which is the FIRST commit of this branch — the direct child of
`546487a8a` — and not its head. (The branch was 13 commits at `c71b023c4`.
An earlier draft of this section said eleven: that was the count when it was
MEASURED, at `caee6baaf`, and it was carried forward after the branch had
grown. A number copied past the state it described is the same defect as a
stale baseline, so it is corrected here rather than quietly. Nothing below
depends on it: the load-bearing facts are that only the first commit was
taken and that five of the six CODE commits were left behind, both of which
are re-derived below.)

Six commits touch code. Five of the six are not in the batch:

| commit | in the batch | what it carries |
| --- | --- | --- |
| `05732dd26` | **yes** | the CLI removal, the verbatim path, the budget |
| `2ce40937c` | no | the two re-derived lander digests |
| `d9322cdab` | no | the seam guard, and the `gatekeeper_review` comment that states the rule |
| `3d9d98731` | no | lander + budget harness + ceiling check |
| `bea866eb9` | no | lander + ceiling check |
| `bda520272` | no | the guard hardened to capture EVERY parser `main()` builds |

**Measured on the three heads.** `ci_harness_timeout_ceiling_check` pins the
landing script by digest, `05732dd26` edits that script, and the commit that
re-derives the pin was left behind:

```
OLD batch  546487a8a : rc 0  [PASS]
NEW batch  8c409aa5a : rc 1  [FAIL] gatekeeper-land.sh is not the complete reviewed
                             executable (sha256=29810dbb…, expected=dad5d0f1…)
                             …execution prefix… (cfc5dabc…, expected=df1eba03…)
this branch c71b023c4 : rc 0  [PASS]
```

The two target reds ARE fixed on `8c409aa5a` — 2 passed. So the partial take
bought the two reds and sold a gate that was green: a landing on `8c409aa5a`
refuses at `ci_harness_timeout_ceiling_check` instead. Note the observed prefix
`cfc5dabc…` is exactly the value `2ce40937c` re-pins to, which is the arithmetic
of the split stated in one line — the batch is carrying the edit and not its pin.

**And `test_hygiene_handover_is_in_process_only.py` is absent from the batch.**
That is the file that binds the ban to the SEAM rather than to three literal
strings. Without it, spelling the flag `--gate-record-in` with
`dest="hygiene_record_in"` restores the skip button with every assertion in the
repo green — §4 is the hole, and the batch currently has the hole open.

**The remedy, driven rather than proposed.** Trial merge of this branch at
`c71b023c4` into `8c409aa5a` in a scratch worktree: merges clean, and on the
result

```
ci_harness_timeout_ceiling_check : rc 0  [PASS]
the two target tests + the seam guard : 9 passed
```

So: re-merge this branch at its HEAD. Nothing needs re-pinning, no digest needs
recomputing, and no commit here needs dropping — the split is the whole defect.

## 10. A blocker in the batch that is NOT this branch's

Reported because it will stop the landing and it is easy to misattribute to the
work above. `landing_collateral_revert_check`, run directly on the batch's own
range:

```
origin/main..origin/land/batch67-assembled
FAIL: COLLATERAL REVERT: 1 finding(s) in 30 commit(s).
  7a9ccd0bb removes 81 of the 145 line(s) ddd7497a9 added to
  ppa-crosslayer/eco-readjudication/MANIFEST.json (56%)
  — and ddd7497a9 is being published by THIS SAME push.
```

Both commits are new in this batch and both are in `agent/jrows-eight-rows`;
`ddd7497a9` comes first and `7a9ccd0bb` revises it four commits later, so this
reads as a deliberate in-lane revision rather than a stale-branch clobber. The
gate does not grade intent and should not: its complaint is that the batch
publishes 145 lines and un-publishes 81 of them in one push, and its own remedy
is to re-land the lane from its delta or drop the earlier commit. The net effect
of the pair on that file is +131 lines, so the final state is not in dispute —
only how it is published.

`--batch` does not suppress this. `collateral_revert_gate` passes only
`--repo` and `--rev-range`; no batch flag reaches it, which was checked before
reporting it as a blocker.

## 11. The base moved twice, and a plain `git fetch` did not tell me

Written after `jmeas3` (8HD-6) reviewed §9 and corroborated it independently.

**Both heads moved while this was being verified.**

```
origin/main                   a00f53f20 (v1.11.66) -> 81cd5321b (v1.11.68), 30 commits
origin/land/batch67-assembled 546487a8a -> 8c409aa5a -> 137caae92
                              137caae92 = "Merge origin/main (v1.11.68) into the batch-67 assembly"
                              parents: 8c409aa5a (first) + 81cd5321b (second)
```

**And my remote-tracking ref lied about it.** `git fetch -q origin` in this
worktree left `origin/land/batch67-assembled` at `8c409aa5a`; the object
`137caae92` was not even present locally (`git cat-file -t` → bad object) while
`git ls-remote origin` reported it as the branch tip. The disagreement was only
visible by asking the REMOTE. A ref that is stale reads exactly like a branch
that did not move, which is the same shape as every other unmeasured-reads-as-a
-measured-zero in this repo. **`git ls-remote`, not the tracking ref, when the
answer decides whether a measurement is about the right tree.**

**What that costs the numbers above, stated rather than left to be found.** §7's
third arm was taken against `a00f53f20`, which is superseded. The delta this
branch introduces has not changed, and — checked — v1.11.68 touched NONE of the
four files this branch edits:

```
git diff --stat a00f53f20..81cd5321b -- tools/gatekeeper-land.sh \
    programs/gatekeeper_review.py programs/ci_harness_timeout_ceiling_check.py \
    tools/test_gatekeeper_land_review_budget.py
(empty)
```

so the two re-derived digests are still the right values for this branch's
lander. But the §7 arms are numbers about a tree nobody will create again, and
they are labelled as such rather than re-quoted.

**§9 re-verified against the CURRENT head**, not the one it was written about:

```
137caae92 as it stands : ci_harness_timeout_ceiling_check rc 1 FAIL
                         seam guard test file: ABSENT
137caae92 + this branch: merge CLEAN, 0 conflicted files
                         ci_harness_timeout_ceiling_check rc 0 PASS
                         the two target tests + the seam guard: 9 passed
```

The finding survives the base change intact, and so does the remedy.

**Independent corroboration, and the part of it that matters most.** `jmeas3`
measured the same failure on `137caae92` before merging, and reports the
observed prefix digest as
`cfc5dabcce04cd9a335114b36e6e565f4d9198996d457c917181f8a3f2bef419` — which is
exactly the value `2ce40937c` re-pins to, and which §9 named as the prediction
BEFORE that measurement existed. A diagnosis that predicts a digest and is then
handed that digest by someone else's run is a different thing from a plausible
story, which is why it is recorded here as confirmed rather than as agreed.

## 12. The review reaches hygiene through the PARALLEL runner, which is red on main

`jmeas3` measured, on a quiet host and after ruling out contention by re-running:

```
tools/ci/repo_hygiene_gates.sh (SERIAL)   : 71 passed, 6 failed, 0 wiring errors
programs/repo_hygiene_parallel.py, base   : 85 declared, 61 passed, 12 failed, 15 wiring errors
programs/repo_hygiene_parallel.py, head   : 87 declared, 62 passed, 12 failed, 19 wiring errors
```

every wiring error being `PROGRESS_PROTOCOL_INCOMPLETE` / watchdog
`outcome=stalled rc=199`. That is theirs, not mine, and is reported as theirs.

What is verified HERE is that it lands on this branch's evidence path.
`repo_hygiene_gate` picks its runner as

```python
parallel = repo / _HYGIENE_PARALLEL_REL
path = parallel if parallel.is_file() else (repo / _HYGIENE_SCRIPT_REL)
```

and `_HYGIENE_PARALLEL_REL` resolves to
`vibe-ic-marketplace/plugins/vibe-ic/programs/repo_hygiene_parallel.py`, which
IS a file in this tree — so the gate picks **PARALLEL**, not the serial script.
Resolved by importing the module and asking it, rather than by reading the
constant and assuming the file exists.

**Consequence for §7, and it cuts toward honesty rather than away.** The
headline there is `89/89 gate(s) ran in 193s`, and the same output reported
`11 NOT CHECKED (not a pass)` alongside 9 failing gates; the 631.5 s run in §6
reported 10 wiring errors and a shard whose watchdog ended `stalled` at rc 199.
Those were recorded at the time as "this tree's state". `jmeas3`'s base-vs-head
pair upgrades that from an assumption to a measurement: the wiring errors are
present on `origin/main` too, so they are NOT produced by removing the record
handover or by moving the budget. Making the review RUN the set does not create
them — it runs into them.

This is worth stating plainly because it is the one way this branch could be
blamed for someone else's red: it is the change that makes the hygiene set
actually execute inside the review, so it is the change present the first time
anyone SEES those wiring errors from the review's mouth.

## 13. Re-measured against the current head, and the noise floor caught a false positive

`jmeas3` warned that its full-suite instrument has a **+/-10 test-id noise
floor** — two runs of the SAME tree on the SAME host disagreed on ten ids, and
its raw "5 new red / 8 fixed" collapsed to ZERO new red after isolated re-runs.
Every differential in §7 and §9 was a SINGLE run per arm, so that warning
applies to them directly and it was acted on rather than noted.

Re-measured on the CURRENT head `137caae92`, same 17-file selection (all 17
exist there), arms sequential, and the candidate arm run TWICE:

```
batch as it stands  137caae92          : 16 failed, 457 passed, 5 skipped  (901s)
137caae92 + this branch, run 1         : 11 failed, 462 passed, 5 skipped (1052s, load ~31)
137caae92 + this branch, run 2         : 10 failed, 463 passed, 5 skipped  (686s, load ~6)
```

**What merging this branch CLEARS — exactly the six predicted, by name:**

```
- test_ci_harness_timeout_ceiling_check.py::test_a_recorded_advisory_that_stopped_existing_is_deleted
- test_ci_harness_timeout_ceiling_check.py::test_each_root_prints_its_own_file_count
- test_ci_harness_timeout_ceiling_check.py::test_semantic_landing_harness_has_no_elapsed_ceiling
- test_ci_harness_timeout_ceiling_check.py::test_the_advisory_residual_does_not_grow_unreviewed
- test_ci_harness_timeout_ceiling_check.py::test_the_json_record_carries_what_the_text_says
- test_ci_harness_timeout_ceiling_check.py::test_the_shipped_tree_is_clean
```

This is the §9 finding restated in the units that matter to a landing. The
split-merge does not merely make a program exit 1 — it costs the batch **six
named test nodes**, all in the file that pins the landing script by digest, and
taking this branch at its head clears all six and nothing else.

**And the one apparent NEW red was noise, which is why the repeat run existed.**
Run 1 reported one failure the as-is arm did not have:

```
+ test_landing_merge_verdict.py::test_the_tier_the_script_picks_matches_this_hosts_real_capability
```

Run 2, same tree, same selection, same host, does NOT have it. The two runs
differ on that id and on nothing else. Its name states what it measures — the
tier the script picks against **this host's real capability** — and run 1 ran at
load ~31 against run 2's ~6. So it is load-dependent, it is not a regression
introduced by this branch, and a single-run differential would have reported it
as one.

**The measured noise floor of THIS selection is 1 id, not 10.** That is smaller
than `jmeas3`'s full-suite figure and it is not a contradiction: this selection
is 17 files and ~478 tests where theirs was the full suite over ~77 reds. The
number that matters is that it is NOT ZERO — so the honest form of the §7 and
§9 differentials is "single run per arm, noise floor unmeasured at the time",
and this section is the one that measures it. The six cleared ids reproduce on
both runs, which is what makes them a result rather than a sample.

**Net for the landing: taking this branch clears 6 and adds 0.** The ten that
remain on both arms — nine in `test_landing_merge_verdict.py` and the
`checker_execution_wiring_audit` one — are the same ten carried on clean main
in §7, and they are not this branch's.

## 14. The containment check: main never got the skip button

The question this branch exists for is not "is the batch red" — it is whether
anything can land while stepping around the hygiene gates. Batch 68 landed 30
commits onto `main` (`a00f53f20` -> `81cd5321b`, v1.11.68) while this was being
verified, so the containment was checked rather than assumed.

```
main 81cd5321b, programs/gatekeeper_review.py : no --hygiene-record-in, no --hygiene-record-rc,
                                                no hygiene_record_in   (0 occurrences)
main 81cd5321b, tools/gatekeeper-land.sh      : run_gatekeeper_review  (0 occurrences)
the two target tests on main 81cd5321b        : 2 passed
```

So neither half of `4232a7301` reached `main`: not the flag, and not the lander
wiring it came with. The regression is confined to `land/batch67-assembled`, and
`main`'s no-skip guarantee is intact right now.

That also fixes the shape of what is outstanding. This branch is not repairing
something live on `main`; it is making sure the ruling's wiring arrives WITH its
guarantee rather than without it. The wiring and the regression came in one
commit, so the only two ways to land the ruling are this branch or a batch that
carries the hole — which is precisely why the split-merge in §9 matters and why
it is worth a re-merge rather than a shrug.

### Where the batch's `expected` digest comes from — the third writer

§9 said the batch "carries the edit without its pin" without naming where the
pin it DOES carry came from, which left the account one commit short. Measured
over `81cd5321b..137caae92`:

```
tools/gatekeeper-land.sh                     : 4232a7301 (jrows), 05732dd26 (this branch)
programs/ci_harness_timeout_ceiling_check.py : ff7b36be8 (jrows)
```

So there are three writers, not two. `4232a7301` wired the review and edited the
lander; `ff7b36be8` — jrows's own follow-up, "my own wiring reddened two gates" —
re-pinned the digests to match it, which is `dad5d0f1…`, the value the batch
reports as `expected` today. `05732dd26` then edits that same lander again, and
`2ce40937c` (not taken) re-pins to `e9d42ab4…`.

That is the whole mechanism in one line: **jrows did the edit-plus-re-pin pair
correctly, and the partial take of this branch broke the same pair a second
time.** The remedy is unchanged and the trial merge already demonstrates it —
taking this branch at its head supplies the missing half.

It is also the argument for treating an edit and its re-pin as atomic rather
than as two commits that happen to be adjacent: this file has now been split
from its subject once, by an assembler acting reasonably on a branch name.

## 15. Auditing my own §7 evidence: what "11 NOT CHECKED" actually was

§12 established that this branch makes the review run the set through the
PARALLEL runner, and that `jmeas3` measured that runner carrying wiring errors
on its trees. That puts a question mark over §7's own headline — if the runner
is unreliable, then "89/89 gates ran; 9 failed; 11 NOT CHECKED" might be partly
a measurement of the runner rather than of the tree. So the runner was driven
directly, with the corpus bound, and its per-label record read.

```
repo_hygiene_parallel.py --summary-json …   (188s, VIBE_IC_BENCHMARK_DATA bound)
declared=89  ran=89  decided=78  passed=69  failed=9  not_checked=11
wiring_errors=[]
```

**The 11 NOT CHECKED are missing-input UNDETERMINEDs, and they are correct.**
Six are PPA gates, and the remaining five are `macro OBS not crossed (spm)`,
`new tool diagnostic id (spm)`, `blocker list contract on committed reports`,
`engineering evidence fresh`, `input-doc claims vs installed PDK`. All are
invoked through `run_tolerating_uncheckable`. Driving one of them by hand:

```
$ python3 programs/ppa_contract_check.py --contract $ROOT/benchmark-data/ppa/contract.json
[CANNOT CHECK] ppa_contract_check: …/benchmark-data/ppa/contract.json: absent
   No contract was read, so nothing has been established about this run.
   This is NOT a finding about the design.
rc 2
```

`benchmark-data/` is not in this repository — the published corpus moved to
`vibeic/benchmark-data`, so the in-tree path these gates name does not exist.
The gates say so, in the exact vocabulary this repo uses for the distinction,
and the runner carries it through as NOT CHECKED rather than as a pass. That is
the `unmeasured-reads-as-a-measured-zero` failure mode NOT happening, and it is
worth recording as such: §7's "11 NOT CHECKED (not a pass)" was reporting an
honest refusal, not a defect and not a runner artifact.

**The 9 FAILs are real and are the tree's, not the runner's**: `flow-gate
enforcement audit`, `L-doc field producer`, `evidence citation resolves`,
`checker execution wiring`, `gates are wired to something`, `declaration scans
strip comments`, `published-evidence index honest`, `d3 declaration/manifest
parity`, `liar census controls still fire`. None is about the landing path this
branch edits.

**Where this DIVERGES from `jmeas3`, stated rather than smoothed over.** It
measured 15 and 19 wiring errors on its two trees, every one
`PROGRESS_PROTOCOL_INCOMPLETE` / watchdog `outcome=stalled rc=199`. This run
reports **zero**. The runs are not comparable enough to call either wrong: the
trees differ (`a00f53f20` / `833e8493f` vs this branch), and this run had
`VIBE_IC_BENCHMARK_DATA` bound at a real corpus checkout while I do not know
whether theirs did — a gate that cannot reach the corpus takes a different path
to its verdict than one that can. The honest statement is that the wiring
errors are real where they were seen and did not reproduce here, and that the
binding is the first variable to control if anyone wants to settle it.

**Net effect on §6-§7:** the headline stands and is slightly stronger than it
was written. The set genuinely ran, its refusals are honest refusals with named
missing inputs, and none of its 9 failures belongs to this branch.

## 16. The control I proposed, run: the corpus binding decides whether the runner completes

§15 named `VIBE_IC_BENCHMARK_DATA` as "the first variable to control" for the
wiring-error divergence between this host and `jmeas3`'s. Proposing a control
and leaving it for someone else is not much better than not proposing one, so it
was run: same tree, same runner, same host, one variable.

```
                       declared  decided  passed  failed  NOT_CHECKED  wiring_errors  outcome
corpus BOUND               89       78      69       9         11            0        completed, 188s
corpus UNBOUND             86       75      67       8         11            7        ERROR incomplete, 258s
```

The unbound arm's seven are exactly the signature `jmeas3` reported:

```
parallel coverage: arm A shard 3: PROGRESS_PROTOCOL_INCOMPLETE: unassigned gate
                   label in attestation progress: corpus "published cells …"
parallel coverage: Arm A produced unplanned attestations
parallel coverage: 'gates are host-independent': expected one owning shard record, got 0
[ERROR] parallel hygiene incomplete after 258s; coverage loss is not a result
```

**So the binding is not a detail of how the corpus gates are scored — it decides
whether the run COMPLETES AT ALL.** Unbound, the coverage protocol sees gate
labels in the attestation stream that it has no plan for, calls the arms
unplanned, and refuses the whole run as incomplete. Bound, the same runner
finishes clean with zero wiring errors.

Note the DECLARED count moves too, 86 -> 89. The set contains a loop corpus
(`published cells carrying a routed DEF`) that expands over corpus items, so
binding the corpus changes the denominator as well as the verdicts. A run
comparing 86-declared against 89-declared is comparing two different sets, which
is worth knowing before anyone diffs two hygiene records.

**What this does and does not settle.** It reproduces the qualitative defect on
demand and gives it a cause: unbound corpus -> PROGRESS_PROTOCOL_INCOMPLETE ->
run refused. It does NOT prove that is the only cause of what `jmeas3` saw — its
counts were 15 and 19 against this arm's 7, on different trees. The honest claim
is: binding flips this runner between "completes clean" and "refuses as
incomplete" on one tree, so it must be controlled before any conclusion is drawn
from that runner, and it is the first thing to try in reproducing the peer's
numbers.

**And it matters to the landing path**, which is why it is in this document
rather than filed elsewhere: `gatekeeper_review` reaches hygiene through this
runner (§12), and this branch is what makes the review actually run it. A
landing whose environment lacks the corpus binding does not get a hygiene
verdict — it gets a refusal — and that is the correct behaviour, but only if
whoever reads it knows that "incomplete" here means "unbound", not "broken".

### A measurement error of my own, on the way to this one

The first unbound arm was launched as
`env PYTHONDONTWRITEBYTECODE=1 -u VIBE_IC_BENCHMARK_DATA python3 …`. GNU `env`
takes `-u` BEFORE assignments; after one, it is read as the command name. The
process died instantly with `env: '-u': No such file or directory` — and my poll
watched for the OUTPUT FILE, so "died in 0 s" and "still running" were the same
observation. I waited ten minutes on a process that never existed.

Same defect as everything in §15 and the reason it is written down: an absent
result read as a pending one. The fix in the re-run was to (a) assert the
variables really were unset by printing them from inside the interpreter before
launching, and (b) poll the LOG as well as the file, so a dead run announces
itself instead of looking patient.

## 17. §16 was too tidy: binding is a cause, not THE cause — and the counts should have been names

`jmeas3` falsified the part of §16 that mattered, with the one fact I could not
see from here: **its runs were already bound.** The wrapper that produced its 15
and 19 wiring errors exported
`VIBE_IC_BENCHMARK_DATA=/home/reyerchu/_matrix_benchmark_data`, a real shallow
clone with 114 published cells. So "bound" and "0 wiring errors" are not the
same thing, and §16's control — which is still valid as far as it goes — does not
explain their numbers.

§16 hedged correctly (*"does NOT prove that is the only cause"*), and the hedge
is now cashed rather than quietly dropped: **it is not the only cause.**

### Everything I have, tabulated, with the variables I did not control named

| run | corpus | host | hygiene time | wiring errors | verdicts |
| --- | --- | --- | --- | --- | --- |
| review, this session (§7) | bound | load ~54 | 193 s | **0** | 89/89 ran, 9 FAIL, 11 NC |
| direct, this session (§16) | bound | quiet | 188 s | **0** | 78/89 decided, 9 FAIL, 11 NC |
| direct, this session (§16) | UNBOUND | quiet | 258 s | **7** | ERROR, incomplete |
| review, prior session (§6) | bound | unknown | 551 s | **10** | stalled shard rc 199, 13 NC |
| `jmeas3` base | bound | 2 pytest arms | 302 s | **15** | incomplete |
| `jmeas3` head | bound | 2 pytest arms | 604 s | **19** | incomplete |

Two things fall out, and neither is the clean story §16 told.

1. **Load ~54 on this host did NOT reproduce it.** The §7 review ran while the
   host carried a load average of 54 and its hygiene verdict is byte-for-byte
   the quiet run's: 89/89, 9 FAIL, 11 NOT CHECKED, zero wiring errors. So "busy
   host" is not sufficient either, at least not at that level.
2. **One BOUND run of mine did produce them** — §6, 10 wiring errors and a shard
   whose watchdog ended `stalled rc=199`, at 551 s against 193 s for the same
   set. That run was not a control: it was a different session on an earlier
   commit of this branch, and I do not know its load. It is listed because
   omitting the one datapoint that contradicts the tidy story would be the
   defect this whole document is about.

**Honest verdict: UNRESOLVED, and the missing input is named.** The correlation
that survives all six rows is with DURATION, not with binding or with load
directly — every run at 258 s or more shows wiring errors and every run at
193 s or less shows none. That is consistent with a progress-watchdog timing
sensitivity, and it is a hypothesis, not a finding: six rows with three
uncontrolled variables cannot separate cause from symptom.

**The control that separates them is `jmeas3`'s to run, and it is already
planned** — bound-and-quiet on ITS tree and ITS corpus. I am deliberately NOT
running the complementary bound-and-loaded arm here: generating load on 8HD-9
would corrupt the measurements of the four pytest arms other agents currently
have in flight on this host, and a peer's in-flight run is not mine to spend.
That is a real experiment left undone, named rather than skipped.

### The declared-count claim, redone as a NAME diff

`jmeas3` recommended diffing hygiene records by gate NAME rather than by count,
because counts are not comparable when the set can move. Applied to §16's own
table, which was making exactly that mistake — it reported `86 -> 89` and
explained it as "a loop corpus expands over corpus items", which is vague enough
to be unfalsifiable:

```
gates ONLY in bound (4):  DRC PASS is not vacuous (spm)          PASS
                          inner FAILs reach the verdict (spm)    PASS
                          macro OBS not crossed (spm)            NOT_CHECKED
                          new tool diagnostic id (spm)           NOT_CHECKED
gates ONLY in unbound (1): corpus "published cells carrying a routed DEF"
                           is EMPTY — nothing was checked over it  NOT_CHECKED

SHARED gates whose verdict MOVED (2):
  gates are host-independent        unbound=NOT_CHECKED -> bound=PASS
  published-evidence index honest   unbound=PASS        -> bound=FAIL

FAIL name symmetric difference: exactly one — published-evidence index honest
```

That is the whole 86 -> 89: four named gates appear and one named placeholder
disappears, net +3. The corpus here holds exactly ONE routed DEF, which is why
the loop expands to 4 gates and not more — a corpus with 114 cells would expand
differently, so `jmeas3`'s 85/87 and this tree's 86/89 are not comparable
numbers even in principle. **The name diff says which gate moved as well as how
many; the count says neither.** §16's table should be read through this block.

### And two grep errors of my own, made while writing this section

Both are the same defect as the `env -u` one in §16, so they are recorded rather
than quietly fixed:

* `grep -oE "stalled"` over the quiet run reported **20 matches** and I briefly
  read them as stall events. They are the substring inside **in-stalled** —
  `input-doc claims vs in***stalled*** PDK`. Zero stall events actually occurred.
* `grep -cE '\bwiring error'` over the unbound run's LOG reported **0**, while
  that run's summary JSON carries **7**. The log phrases them as
  `parallel coverage: …`. I was grepping for my own guess at the wording.

The rule both violate: **read the machine-readable record, not the prose.** The
runner writes `--summary-json` with a `wiring_errors` array precisely so nobody
has to pattern-match its console output, and I pattern-matched it twice in one
section while writing a document about instruments that answer the wrong
question.

## 18. The wiring errors are a WATCHDOG artifact, and the two graces do not match

§17 left the cause unresolved and named DURATION as the surviving correlate.
There is a mechanism behind that correlate, it is reproducible on demand, and
it does not require a busy host to demonstrate — which is why this control was
runnable here without spending anyone else's measurements.

**The control.** Same tree, same corpus, quiet host, default jobs. The ONLY
change is the runner's own forward-progress watchdog, `--stall-grace 5`:

```
[routed-def corpus] note: VIBE_IC_BENCHMARK_DATA overrides …
WATCHDOG_STALLED: configured forward-progress signals did not advance for > 5s
                  — killed as hung, not slow.

declared=89 decided=0 passed=0 failed=0 not_checked=89
wiring_errors: 387
  parallel coverage: arm A shard 0: PROGRESS_PROTOCOL_INCOMPLETE: attestation
                     progress ended before assigned gates completed: …
  parallel coverage: arm A shard 0: no summary (rc=199)
```

`PROGRESS_PROTOCOL_INCOMPLETE` and `rc=199` are **exactly** the signature
`jmeas3` reported. They are not a wiring defect in the gates. They are what a
shard leaves behind when the watchdog kills it: the progress attestation stops
mid-way, so the coverage protocol finds gates it planned for and no record of
them finishing, and reports the shard as incomplete.

**So the causal chain is: shard runs slowly -> internal watchdog kills it ->
its attestation is truncated -> coverage protocol reports
PROGRESS_PROTOCOL_INCOMPLETE.** Duration was the correlate because slowness is
the input to the watchdog. Load and corpus binding are two different ways of
making a shard slow; neither is the cause, which is why §16 and the load
hypothesis both fit some rows and not others.

### The number that makes this matter: 300 against 1800

```
repo_hygiene_parallel.DEFAULT_STALL_GRACE_S    = 300     # the runner's INTERNAL watchdog
gatekeeper_review._HYGIENE_STALL_GRACE_S       = 1800    # the review's OUTER supervisor
```

and `gatekeeper_review` **never forwards its value to the runner**. Verified by
AST rather than by grep, after a grep of mine got this wrong in both directions
within one section: `stall_grace` IS referenced twice inside
`repo_hygiene_gate`, but both references are to the review's own supervisor
wrapper —

```
 78:  [*command, "--summary-json", str(summary_path)],
 80:  stall_grace_s=stall_grace, poll_s=5,
 91:  f"record advanced for {stall_grace}s; nothing was concluded"
```

— and `"--stall-grace"` appears nowhere in `gatekeeper_review.py`. The runner
therefore always uses its own 300 s.

**There are two independent watchdogs with a 6x mismatch, and the tighter one is
the one nobody configured.** The review declares 1800 s of patience; the runner
it launches kills a shard that goes 300 s without a gate record. `jmeas3`'s two
bound runs took **302 s and 604 s** — both at or over that 300 s line, with 15
and 19 wiring errors. Every run of mine at or under 193 s produced zero. That is
six rows now explained by one constant.

**Why this belongs in THIS document rather than filed away.** This branch is
what makes `gatekeeper_review` actually run the hygiene set (§12), so it is the
change that puts every landing behind this watchdog. On a contended host a
landing will now see `ERROR — parallel hygiene incomplete`, refuse, and name
shards rather than gates. That refusal is CORRECT in the sense that a truncated
run is not a pass — it is the repo's own `unmeasured-reads-as-a-measured-zero`
rule holding. But it is a refusal about the HOST, not about the tree, and the
budget reasoning in §3 and in the lander's comment deserves the correction:
1800 s was chosen as "the gate's own `_HYGIENE_STALL_GRACE_S`, below which this
`timeout` would kill runs the gate itself still considers alive". That is still
a sound outer bound for the `timeout`, but it is NOT the grace that governs the
set — the set is governed by 300 s, six times tighter, from a different module.

**What I am NOT doing about it.** Raising `DEFAULT_STALL_GRACE_S`, or teaching
`repo_hygiene_gate` to forward its value, is a flow-level change to a watchdog
that exists to stop a hung run being read as a slow one. It needs the
flow-change acceptance standard — a bidirectional control proving the new value
still catches a genuine hang — and it is not this branch's subject. It is
reported here, with the reproduction recipe (`--stall-grace 5` on any tree), so
that whoever takes it has the mechanism rather than a symptom.
