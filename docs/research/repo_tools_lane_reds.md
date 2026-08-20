# The reds in the repo-tools landing lane, named

`tools/gatekeeper-land.sh:run_repo_tools_pytest` is the landing arm that runs the
repo-level tests under `tools/`. For a long time it selected nothing — the
targeted selector is plugin-scoped by construction and the script invokes it with
`cwd=$PLUGIN` — and when the arm was switched on, its failures were **counted and
never named**. A count with no names is the defect this repository hunts
everywhere else: a status field standing in for the thing it claims to measure.

This document names every one of them, on a stated commit, with the command that
produced them.

## 0. The commit, the command, and the summary line

Subject: `origin/main` at **46db018669** (`v1.11.7`), in a `--no-hardlinks` clone.

```
$ find tools \( -name 'test_*.py' -o -name '*_test.py' \) -type f | sort > selection.txt
$ VIBEIC_TRUSTED_PYTEST_SITE=auto PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 vibe-ic-marketplace/plugins/vibe-ic/programs/pytest_per_file_junit.py \
      --selection selection.txt --junit merged.xml --cwd "$PWD" \
      --stall-after 300 --aggregate-check --aggregate-stall-after 300 \
      --fallback-jobs 8 --fallback-rescue-jobs 32 --stop-after-failures 0 \
      -- python3 -I vibe-ic-marketplace/plugins/vibe-ic/programs/trusted_pytest_entry.py \
         -q -p no:cacheprovider
```

pytest's own summary line:

```
6 failed, 801 passed, 6 skipped in 127.39s (0:02:07)
```

the driver's own aggregate line:

```
AGGREGATE_COMPLETE  rc=1  cases=813  red=6
asked 43  recorded 0  NORECORD 0  NOTRUN 0
```

**`NORECORD 0`.** Every selected file was actually looked at. This matters more
than the number: the same arm reports the *identical* shape when the protected
runtime cannot run at all, and `landing_pytest_runtime_preflight.py` records
exactly that measurement — `asked 40 recorded 0 NORECORD 40` — for the repo-tools
arm at `7c376e348`. A NORECORD run is not a green lane and it is not zero reds.
`VIBEIC_TRUSTED_PYTEST_SITE=auto` is what makes this host able to produce a
record at all; without it, `python3 -I` cannot import the runner from
`~/.local/lib/python3.12/site-packages` and every file comes back UNKNOWN.

### The corpus, and a correction to two earlier numbers

* 43 files / **813** pytest nodes at 46db018669. The frequently-quoted
  "28 files / 552 tests" was measured at `a38902d16` and is that commit's number,
  not this one's.
* The lane was carried as "roughly 50 red cases". **The real number is 6.** The
  40-file NORECORD measurement quoted above is a plausible origin for a "~50"
  that was never reds at all, but that is a hypothesis and is not asserted here.

## 1. The six, named

| # | test |
|---|------|
| 1 | `tools/ci/test_landing_runtime_preflight_gate.py::test_the_host_lane_lets_the_same_tree_record` |
| 2 | `tools/ci/test_phase_b_activated_parity.py::test_the_manifest_is_a_well_formed_authorised_transition` |
| 3 | `tools/ci/test_phase_b_activated_parity.py::test_the_current_tuple_is_the_tuple_recorded_where_the_manifest_was_authored` |
| 4 | `tools/ci/test_phase_b_activated_parity.py::test_the_live_tree_is_exactly_one_recorded_state_and_never_a_mixture` |
| 5 | `tools/ci/test_phase_b_activated_parity.py::test_the_move_is_exactly_the_paths_the_two_states_disagree_on` |
| 6 | `tools/test_liar_census.py::test_nothing_the_flow_declares_is_left_unswept` |

Six rows, and that is the whole list — no "and N others". Six reds, **three**
root causes. Nothing here is flaky, environment-dependent, or an artefact of how
the lane is invoked. Every other `::test_` name in this document is labelled as
being OUTSIDE this corpus: it belongs to the same root cause and was measured and
fixed alongside, but it is not one of the six the lane reported.

## 2. Class M — the protected-landing transition manifest names no move (#2 #3 #4 #5)

### What is wrong

`tools/ci/protected_landing_transition.json` on `origin/main` carries
`current.id == next.id == activated-at-tier-preflight` with byte-identical
tuples. The verifier's **own parser** refuses exactly that:

```
Refusal: manifest current and next state ids are equal
         tools/ci/protected_landing_transition.py:327
```

`build_receipt()` parses the BASE manifest before it looks at any candidate, so
that refusal is reached by **every landing whose base is `origin/main`**. The
predicate has existed since `7c376e348`, the commit that introduced the manifest,
so this was never a rule change that outran the data.

Measured across the manifest's whole history:

| commit | current.id | next.id |
|---|---|---|
| `7c376e348` | legacy-landing-v1 | semantic-landing-v1 |
| `46964e1fb` | live-at-v1-10-74 | select-guard-census-partition-v1 |
| `15e4c463a` | activated-at-v1-10-79 | xdist-per-worker-progress-v1-next |
| `521fd735d` | activated-at-v1-10-81 | 1704-shrink-plus-liar-census-v1-next |
| `533c71285` | activated-at-v1-10-87 | arm-exit-bytecompile-v1-next |
| `1fda956ba` | activated-at-v1-10-96 | landing-diagnostics-…-v1-next |
| **`1f1749d2d`** | **activated-at-v1-11-1** | **activated-at-v1-11-1** |
| `b161ec6e5` | activated-at-v1-11-1 | activated-at-v1-11-1 |
| `eda53573f` | activated-at-tier-preflight | activated-at-tier-preflight |

A **second, independent** defect lives in the same artefact: two protected files
moved with no authorisation at all, so the live tuple matched *neither* recorded
state.

```
matrix_mutation_ledger.py            manifest ea0716e56d   live 2f397e6e49
tests/test_matrix_63x8_coverage.py   manifest 80a26e3390   live 61ecd6df78
$ git log --oneline eda53573fa..46db018669 -- <those two>
00d9dc261 feat(precheck): a general tape-out precheck for a design with no operator [v1.11.4]
```

### Why it kept happening

Every manifest in this history was transcribed by hand, 47 file records at a
time, and two commits (`1f1749d2d`, `eda53573f`) tried to express "nothing is
pending" by settling `current` onto `next`. **There is no settled manifest.** A
manifest names the LAST transition and keeps naming it: after an ACTIVATE the
live tuple equals `next`, `_match_state` returns `next.id`, and every subsequent
landing is STEADY against the same unchanged bytes. Collapsing the two states is
never necessary and always fatal.

### Fixed

* `tools/ci/protected_landing_manifest_author.py` — renders a manifest from an
  **observed** tree instead of a transcription. Path/role policy and the runner
  profile are copied from the manifest already in the tree (they are policy, not
  observation, and re-deriving them would be a second opinion about what is
  protected); the tuples come from `protected_landing_transition._observe_files`,
  the same function the verifier uses; and the finished object is handed back to
  `parse_manifest` before it is written, so a manifest this program emits and the
  verifier refuses is refused at authoring time rather than committed.
  `serialise()` round-trips the in-tree bytes exactly, so re-authoring an
  unchanged tuple produces no diff.
* `tools/ci/test_protected_landing_manifest_author.py` — 8 tests, under `tools/`
  on purpose so the repo-tools arm covers it. Three of them are the refusals that
  would otherwise allow the same malformed shape to be rendered again (a manifest
  that moves nothing; a move naming an unprotected path; a move to the bytes the
  tree already holds).
* The manifest is re-authored with it, as a **PREPARE** that moves no protected
  bytes: `current` is the tuple the PREPARE commit holds — which finally records
  the two files that drifted at `00d9dc261` — and `next` authorises one move, the
  host-lane widening in Class H below, installed by the following **ACTIVATE**.

Red → green, against the verifier's own code:

```
before   parse_manifest(origin/main bytes)   Refusal: current and next state ids are equal
after    parse_manifest(new bytes)           ACCEPTED
         _match_state(tree at the PREPARE)   live-at-v1-11-7                    (== current)
         _match_state(tree at the ACTIVATE)  host-lane-multi-directory-v1-next  (== next)
```

### What is NOT settled, precisely

1. **The manifest records `tools/gatekeeper-land.sh`'s bytes, and that file is
   under active change** (the landing-gate parallelism work). Any commit that
   moves a protected byte must re-author the manifest — that is the design, not a
   defect — so whoever lands next after such a change must run:

   ```
   python3 tools/ci/protected_landing_manifest_author.py \
       --repo . --commit HEAD \
       --transition-id <new-id> --current-id <live-state-id> --next-id <new-id>-next \
       --next-file <protected/path>=<file holding its future bytes> \
       --out tools/ci/protected_landing_transition.json
   ```

   commit that alone (PREPARE), then install the bytes (ACTIVATE).
2. **A manifest cannot be authored from a base whose manifest does not parse.**
   `build_receipt` calls `parse_manifest(base_manifest)` first, so a landing that
   uses `origin/main` as its base still refuses until the corrected manifest is
   itself on main. The in-design route is the `bootstrap` subcommand, and that is
   the landing owner's ceremony, not something a branch can perform for them.
   This is stated rather than worked around.

## 3. Class H — the host lane could not name a split runner closure (#1)

### What is wrong

`VIBEIC_TRUSTED_PYTEST_SITE` accepted exactly **one** directory, and a test
runner's import closure is not always one directory's worth of modules. Measured
on this fleet at 46db018669:

```
pytest, _pytest, pluggy, iniconfig, packaging  ->  ~/.local/lib/python3.12/site-packages
pygments                                       ->  /usr/lib/python3/dist-packages
```

`pytest` imports `pygments` lazily, at terminal-writer time, so a lane naming the
first directory *imports* the runner and then dies mid-session with
`No module named 'pygments'` — the "imports and cannot report" shape
`landing_pytest_runtime_preflight` exists to catch, arriving as a NORECORD.

The system interpreter survives it only by accident: `-I` suppresses the USER
site directory and keeps `/usr/lib/python3/dist-packages`. An interpreter that
keeps neither — a `-S` shim, a virtual environment, which is what a host that
followed `CONTRIBUTING` may well run a landing from — could not open the lane AT
ALL on this fleet, however precisely it named the directory the runner is in.

**The blast radius is larger than the one red.** The same cause leaves five more
positive controls red, outside this corpus, at the same commit:

```
FAILED programs/tests/test_trusted_pytest_entry.py::test_the_named_lane_records_where_the_same_entry_refused
FAILED programs/tests/test_trusted_pytest_entry.py::test_the_lane_is_inserted_at_the_front_not_appended
FAILED programs/tests/test_trusted_pytest_entry.py::test_the_identity_record_still_shows_which_lane_answered
3 failed, 6 passed, 2 skipped in 2.25s

FAILED programs/tests/test_landing_pytest_runtime_preflight.py::test_the_named_lane_makes_the_same_interpreter_report
FAILED programs/tests/test_landing_pytest_runtime_preflight.py::test_the_cli_exit_code_is_two_for_refuse_and_zero_for_pass
2 failed, 5 passed in 1.65s
```

All six, including #1, fail with the identical `No module named 'pygments'`.
Those tests were measuring the HOST rather than the gate — the fleet's real lane
works, and this session proves it: `VIBEIC_TRUSTED_PYTEST_SITE=auto` ran the
whole 43-file corpus, 813 cases, on this host. What did not work was naming the
closure *explicitly*, which is the only thing an interpreter without a system
site directory can do.

### Fixed

* `trusted_pytest_entry._host_lane` accepts an `os.pathsep`-separated value and
  inserts each segment at position 0 in the order named. Every segment goes
  through the SAME resolution and the SAME two refusals as before — absolute,
  resolves strict, is a directory, and not under the subject checkout or the
  programs directory — so widening the value does not widen what may be named. A
  single directory behaves exactly as it always did; an unset value still changes
  nothing.
* Both test files now name the whole closure — the runner's own directory first,
  then the `site-packages`/`dist-packages` directories an isolated interpreter
  keeps — instead of half of it.
* Added, so a widened value cannot become a way to pass:
  `test_a_half_closure_lane_is_not_silently_completed` (a runner-only lane must
  still refuse, and must NAME the missing module — a silent fallback to the
  host's own site directories is what the entry's docstring refuses; on an
  installation whose closure IS one directory it asserts the recording instead,
  so it cannot invert inside the pinned image),
  `test_every_named_directory_answers_in_the_order_it_was_named` (asserted on
  `sys.path` from inside the recorded session),
  `test_an_empty_segment_in_the_lane_is_refused`, and
  `test_a_lane_that_does_not_hold_the_runner_still_refuses` in the gate file, so
  its positive control can tell an honoured lane from an ignored one.

Red → green, on this host:

```
before   6 failed  (1 in this corpus, 3 in test_trusted_pytest_entry.py,
                    2 in test_landing_pytest_runtime_preflight.py)
after    19 passed, 2 skipped in 5.39s   (the gate file + the entry's own tests)
         8 passed in 4.28s               (test_landing_pytest_runtime_preflight.py)
```

## 4. Class C — a shrink-detector literal that did not follow the flow (#6)

### What is wrong

```
assert pop["swept"] == pop["declared"] == 175
AssertionError: {... 'declared': 178, 'swept': 178, 'unswept': [], 'unrecognised': {} ...}
```

The PIN holds. `swept == declared` (178 == 178), `unswept` empty,
`unrecognised` empty. Only the literal is stale, and the test's own docstring
says it "is meant to move whenever the flow does".

### Fixed

The clause **set** was diffed rather than the count compared:

| | |
|---|---|
| `03f7b945d7` (last commit that moved the literal) | declared=175 swept=175 |
| `46db018669` (origin/main) | declared=178 swept=178 |

added, attributed to the commits that added them:

* `69ce9260d` — `program_exit_zero: tapeout_docs_gen --project . --out-dir reports/phase3/docs`
* `00d9dc261` — `program_exit_zero: general_precheck . --json reports/phase3/general_precheck.json`
* `00d9dc261` — `program_exit_zero: tapeout_declaration_check . --json reports/phase1/tapeout_declaration.json`

removed: **none**. `by_kind` moves `program_exit_zero` 110 → 113 with `advisory`
37 and `optional` 28 unchanged. So this is a grow, not a churn, and raising the
literal is the maintenance the test specifies — not a gate being greened.

Red → green:

```
before (second worktree at 46db018669)  1 failed, 107 passed in 15.37s
after                                   108 passed in 21.98s
```

### Not settled, and deliberately so

This is the **third** time this literal has lagged the flow (169→170, 170→175,
175→178). A hand-maintained number that must be remembered by an author editing a
different file is prose wearing an assertion. The obvious deterministic
replacement — derive the floor from the previous flow blob — would catch every
shrink with nothing to remember, but it would also leave a *deliberate* shrink no
way to be authorised. That is a call for the flow's owner, so it is written into
the test and recorded here rather than taken unilaterally.

## 5. One more finding, made while fixing #1 and fixed with it

`landing_pytest_runtime_preflight.entry_probe` runs its child with `cwd` set to a
synthetic subject directory, so a **relative** `--programs` — whose
`entry.is_file()` check had already passed against the caller's cwd — did not
resolve for the child, and the program reported "the trusted entry could not
execute and report one synthetic test": a cause it did not have. Measured on the
same tree both ways:

```
--programs vibe-ic-marketplace/plugins/vibe-ic/programs        probe_returncode 2  ok false
--programs $PWD/vibe-ic-marketplace/plugins/vibe-ic/programs   probe_returncode 0  ok true
```

This is not one of the six; it is the same rule the six are about — "I could not
look" must never reach a reader as "I looked". `entry` is now made absolute
before the probe, with a regression test proven red at 46db018669.

## 6. Summary

| class | reds | fixed |
|---|---|---|
| M — the transition manifest names no move, and two protected files drifted unrecorded | 4 | yes, plus the program that stops it recurring; the two follow-ups in §2 are named and open |
| H — the host lane could not name a split runner closure | 1 here, 3 more outside this corpus | yes |
| C — a shrink-detector literal lagged the flow | 1 | yes; the recurring-staleness question is named and left to the flow's owner |

The lane, re-run on the branch with the identical command (44 files now — the new
authoring test lives under `tools/` so the arm covers it):

```
816 passed, 6 skipped in 126.28s (0:02:06)
AGGREGATE_COMPLETE  rc=0  cases=822  red=0
asked 44  recorded 0  NORECORD 0  NOTRUN 0
LANE_RC=0
```

against the baseline in §0: `6 failed, 801 passed, 6 skipped`, `rc=1 cases=813
red=6`. Six named, six closed, and the run is still a record rather than an
absence.
