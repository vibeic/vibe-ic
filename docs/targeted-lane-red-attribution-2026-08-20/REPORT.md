# The fourteen: the targeted lane's red cases, named and split

_2026-08-20. Selection: `ci_targeted_test_select.py --base origin/main` — 49 files,
reproduced exactly. Base = clean `origin/main` `49d2b3328`. Candidate = `jnorec/assembled`
`706b14400` (4 commits, 5 files). The SAME 49-file selection was run per file against BOTH
trees, by the same plain pytest in the shape `pytest_per_file_junit.run_one` uses
(`-o junit_family=xunit1 --junitxml=<per-file>`, cwd = plugin root), so between the two
sides only the SUBJECT differs. Run TWICE end to end in two environments — on the host, and
inside the manifest's own pinned image `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…` — so that
no conclusion rests on one machine._

A count with nothing behind it is what this exercise exists to end, so every number below is
a list.

---

## 0. THE NAMER DID NOT EXIST, AND THE ONE WRITTEN TO REPLACE IT REFUSED TWICE

The brief names `$HOME/.claude/fleet/rg_name_reds.py` as "a namer that refuses to report an
empty directory as 'no reds'". **It is not on 8HD-4, not on 8HD-8, and nowhere under
`~/.claude` on either** — the same disappearance the brief warns about, one layer up. The
contract was re-implemented rather than assumed (`evidence/name_reds.py`). It refuses, at
rc 2 with a named reason and no red list printed, when the junit directory holds no XML, when
a file marked RECORDED has no junit behind it, or when a junit is unparseable; it prints the
count of files that produced evidence beside every red count, so "0 reds" cannot be read
without its denominator; and files with no record are printed as BLIND — reds UNKNOWN, never
zero — and excluded from the split rather than classified from the side that happened to have
evidence.

It earned its keep on this job. The first attempt to name the container runs returned
**rc 2 on both**: the runs had recorded container-side junit paths that do not resolve on the
host, so every RECORDED file had no junit behind it. A namer that globbed a directory would
have printed "0 reds" over 88 real failures.

## 1. THE MEASUREMENT

| environment | tree | files | RECORDED | NORECORD | NOTRUN | cases | reds |
|---|---|---:|---:|---:|---:|---:|---:|
| host | base `49d2b3328` | 49 | 49 | 0 | 0 | 1466 | 35 |
| host | cand `706b14400` | 49 | 49 | 0 | 0 | 1474 | 41 |
| pinned image | base `49d2b3328` | 49 | 49 | 0 | 0 | 1466 | 41 |
| pinned image | cand `706b14400` | 49 | 49 | 0 | 0 | 1474 | 47 |

**NORECORD 0 in all four, and that is itself a finding.** The landing tier reported
`test_pytest_per_file_junit.py` as NORECORD — STALLED after 300 s. At a 420 s bound it
completes in **58.9 s** (host cand), **55.9 s** (host base), **68.9 s** / **69.5 s** in the
pinned image. The file does not hang; it was cut off just short. What that cut off is in §4.

## 2. THE THREE-WAY SPLIT

### INTRODUCED — red only on the candidate (7)

```
test_ci_harness_timeout_ceiling_check.py::test_semantic_landing_harness_has_no_elapsed_ceiling
test_ci_harness_timeout_ceiling_check.py::test_the_json_record_carries_what_the_text_says
test_ci_harness_timeout_ceiling_check.py::test_the_shipped_tree_is_clean
test_ci_harness_timeout_ceiling_check.py::test_a_recorded_advisory_that_stopped_existing_is_deleted
test_ci_harness_timeout_ceiling_check.py::test_each_root_prints_its_own_file_count
test_ci_harness_timeout_ceiling_check.py::test_the_advisory_residual_does_not_grow_unreviewed
test_pytest_per_file_junit.py::test_the_landing_harness_declares_semantic_progress_not_elapsed_time
```

### FIXED — red on base, green on the candidate (1)

```
test_ci_harness_timeout_ceiling_check.py::test_the_two_trees_use_different_globs_for_a_measured_reason
```

Fixed by **`706b14400`**, which lowered six inner `subprocess.run(timeout=...)` bounds in
`tools/ci/test_landing_runtime_preflight_gate.py` and `tools/ci/test_phase_b_activated_parity.py`
to named constants at or under the published per-call ceiling. Base's failure names the
offending call sites verbatim (`…test_landing_runtime_preflight_gate.py:153
subprocess.run(timeout=600)` …); on the candidate they are gone. The commit's claim is true
and is confirmed here independently, in both environments.

### PRE-EXISTING — red on both (34 host / 40 image)

Three populations, and they are not the same kind of thing. §5, §6, §7.

### NOT DETERMINED (0)

No node was classified across a blind file: all 49 files produced evidence on both sides in
both environments.

### THE SPLIT IS NOT AN ARTEFACT OF ONE MACHINE

41 nodes appear in both environments. **Buckets that disagree between host and pinned image:
0.** Every environment-specific node lands in PRE-EXISTING, red on both sides, so no
environment difference can move a node into or out of the candidate's column.

## 3. ALL SEVEN INTRODUCED REDS ARE ONE DEFECT

Every one of the seven carries the same string:

```
semantic pytest driver is not the exact reviewed executable
  (sha256=37d80899488be20df90185d9e4037572535ee30373cd9acc1cf7896b67c9960a,
   expected=5d270fa98e8aff656998e3c23a116e3d85ad55ce35d119807cf8e94a263b9cf0)
```

`ci_harness_timeout_ceiling_check.py:288` carries a hand-written literal:

```python
_SEMANTIC_DRIVER_SHA256 = (
    "5d270fa98e8aff656998e3c23a116e3d85ad55ce35d119807cf8e94a263b9cf0"
)
```

That is `pytest_per_file_junit.py` **before** the candidate's move, 127578 B. The candidate's
tree holds the post-move bytes, 140237 B, `37d80899…`. The checker does not read the
manifest — `grep -n "protected_landing_transition\|manifest"` over it returns nothing. It
compares the live driver against a constant compiled into a second file.

**The manifest shows the move cannot be completed as prepared:**

```
current  (activated-at-v1-10-96)              next  (maxfail-truncation-classifier-v1-next)
  ci_harness_timeout_ceiling_check.py           ci_harness_timeout_ceiling_check.py
      ad07cda77  c880c76331911841  90369            ad07cda77  c880c76331911841  90369   <- FROZEN
  pytest_per_file_junit.py                      pytest_per_file_junit.py
      539b6644f  5d270fa98e8aff65  127578           dd463b9ba  37d80899488be20d  140237  <- MOVES

PATHS THAT MOVE current -> next: [pytest_per_file_junit.py]
```

`70c06f9a3` opened a ONE-PATH move on `pytest_per_file_junit.py` while freezing
`ci_harness_timeout_ceiling_check.py` — the file that hard-pins the digest of the very path
being moved. Activating the move therefore invalidates a frozen path by construction. And the
mechanism's own rule, recorded in `70c06f9a3`'s message as wrong-attempt #1, is that the
manifest "always carries exactly one IN-FLIGHT move", so this transition has no room to carry
the re-pin it requires.

### TRIAGE: real defect in the SUBJECT; every remedy is POLICY — described, and STOPPED

The checker states the contract the candidate did not meet, in its own comment: *"any
executable rewrite that can affect reachability must be reviewed together with a new digest."*
The candidate rewrote the driver in `3b6080692` and `9eb21d12e` (+284 lines) and did not
re-pin. The defect is the candidate's.

Three remedies exist and **each one is a policy decision, not this agent's**:

1. Re-pin `_SEMANTIC_DRIVER_SHA256` to `37d80899…`. One line — but
   `ci_harness_timeout_ceiling_check.py` is a protected path frozen in BOTH manifest states,
   so editing it makes the tree disagree with both recorded tuples. That is exactly the
   failure `70c06f9a3` documents for `step_metrics.py`, which "refused every landing,
   including landings with nothing to do with it".
2. Re-PREPARE with a TWO-path move. That changes what a move is allowed to contain.
3. Make the checker derive the digest from the manifest and accept `current` OR `next`. The
   file says in its own words that this is "intentionally an explicit policy migration, never
   a heuristic match".

**Nothing was changed and no check was weakened to go green.** Options 1 and 3 both alter
protected gate bytes; option 2 is the gatekeeper's.

### A SECOND DEFECT, IN THE CHECK, VISIBLE ONLY BECAUSE THE FIRST ONE FIRED

Three of the seven do not report the cause at all:

```
FileNotFoundError: [Errno 2] No such file or directory: '…/r.json'
```

`test_a_recorded_advisory_that_stopped_existing_is_deleted`, `test_each_root_prints_its_own_file_count`
and `test_the_advisory_residual_does_not_grow_unreviewed` open the checker's `--json` output
without first asserting that the process which writes it exited 0. When the checker refuses it
exits non-zero before writing the record, and the test dies on a missing file. One legible red
becomes three illegible ones and the sentence naming the real cause appears in none of them.
Real defect in the check → **described, and stopped at.**

## 4. THE NORECORD HID THE CANDIDATE'S OWN SELF-DIAGNOSIS

The seventh introduced red is
`test_pytest_per_file_junit.py::test_the_landing_harness_declares_semantic_progress_not_elapsed_time`
— green on base, red on the candidate, the same digest message, at line 2008 of the
candidate's **own** test file.

That is the test that names this defect most directly, and the landing tier could not see it:
that file was its single NORECORD. The stall did not merely lose a file's result — it lost the
one node that says what is wrong with the candidate. NOTHING TO CHECK IS NOT A PASS, in its
sharpest form. The stall itself is `jnorec`'s and is already assigned; it is not touched here
beyond measuring that at a 420 s bound the file finishes in under 70 s in both environments.

## 5. PRE-EXISTING, POPULATION A — 7 real reds, and whose they are

```
test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step15]
test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step17]
test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step19]
test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step20]
test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step30]
test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step32]
test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step31]
```

Node-for-node identical on both trees in both environments; the candidate neither caused nor
touched them. d3: *"N declared output(s) cite a run root NO corpus can supply, so the
corpus-absent skip must not cover them"*. d7: *"step 31: required_outputs is INCOMPLETE — 1
load-bearing artefact(s) it never declares"*.

**Whose: `gsweep` (8HD-6).** The basis is evidence, not elimination alone. `gunattr`'s own
brief, read on 8HD-d, scopes it to two lanes — `full:repo-tools-tests` (45 files, `tools/`)
and `full:unselectable-tests` (111 files). Both nodes above are in `programs/tests/`, outside
both lanes. By the brief's own binary the remainder is `gsweep`'s. **8HD-6 was unreachable
from here** (`192.168.1.106` connection refused, `.116` no route), so `gsweep`'s brief could
not be read to confirm directly, and that limit is stated rather than papered over.
**Not fixed here, per instruction.**

## 6. PRE-EXISTING, POPULATION B — 27 nodes that are NOT repository reds

All 27 base-side reds in `test_pytest_per_file_junit.py` come from the ENVIRONMENT, and the
proof is that the two environments break it for two *different* reasons:

* host — `ValueError: Plugin already registered under a different name: timeout=<module
  'pytest_timeout' from '~/.local/lib/python3.10/site-packages/pytest_timeout.py'>` (15 of
  the 27 carry that string; the other 12 are downstream of the same crashed nested session);
* pinned image — `ModuleNotFoundError: No module named 'pytest_timeout'` /
  `ImportError: Error importing plugin "pytest_timeout"` (0 carry the host string).

The file's tests launch nested pytest sessions; in each environment `pytest_timeout` is wrong
in a different way, so every assertion about what the nested run recorded fails. Neither
environment is the landing tier's hermetic arm profile, which pins the exact interpreter
environment. **These are not evidence of reds on `origin/main`**, the landing tier never
counted them (the file was its NORECORD), and they are excluded from the attributable
population and named here so nobody re-counts them.

They do not disturb the split: 27 on base and 28 on cand in BOTH environments, and the single
extra on cand is the digest node of §4, in both.

## 7. PRE-EXISTING, POPULATION C — 6 nodes that are MY container mount

Red only in the pinned-image runs, and only because the worktrees' `.git` pointer
(`/home/reyerchu/vibe-ic/.git/worktrees/…`) was not mounted into the container:

```
test_matrix_d3_outputs_produced.py::test_d3_waived_unproven_entries_have_no_committed_artefact
test_program_inventory_no_drift.py::test_a_source_mismatch_is_not_checked_rather_than_a_drift_verdict
test_program_inventory_no_drift.py::test_an_untracked_stray_module_does_not_move_any_count
test_program_inventory_no_drift.py::test_check_mode_exits_zero_on_the_committed_tree
test_program_inventory_no_drift.py::test_the_inventory_is_enumerated_from_the_tracked_set
test_selector_second_hop_helpers.py::test_an_unmapped_path_that_nothing_names_is_still_the_floor
```

The d3 one says so itself, and refuses rather than guessing — which is the behaviour one
wants:

> `git ls-tree -r HEAD` exited 128 under /work/base, which DOES carry git metadata — so this
> is a broken environment, not a tree without commits. Refusing to read that as 'nothing is
> tracked at HEAD': every artefact below would be reported NOT PRODUCED while it sits
> committed on disk.

**Proved by removing the cause:** re-run in the same image with `/home/reyerchu/vibe-ic`
mounted read-only, all six pass on both trees — `1 passed, 112 deselected` for the d3 node and
`30 passed in 13.07s` for the other two files. My harness, not the repository, and stated here
rather than left in the count.

## 8. RECONCILING WITH THE LANDING TIER'S "14" — THIRTEEN NAMED, THE FOURTEENTH NOT

The landing tier measured `recorded 48 / NORECORD 1 / red cases 14`. Excluding the same
NORECORD file, **both environments here independently name the same THIRTEEN**:

| environment | reds | minus the NORECORD file | minus my mount artefacts (§7) |
|---|---:|---:|---:|
| host | 41 | 13 | 13 |
| pinned image | 47 | 19 | **13** |

and the thirteen are:

| # | node | bucket |
|---:|---|---|
| 1 | `test_ci_harness_timeout_ceiling_check.py::test_semantic_landing_harness_has_no_elapsed_ceiling` | INTRODUCED |
| 2 | `test_ci_harness_timeout_ceiling_check.py::test_the_json_record_carries_what_the_text_says` | INTRODUCED |
| 3 | `test_ci_harness_timeout_ceiling_check.py::test_the_shipped_tree_is_clean` | INTRODUCED |
| 4 | `test_ci_harness_timeout_ceiling_check.py::test_a_recorded_advisory_that_stopped_existing_is_deleted` | INTRODUCED |
| 5 | `test_ci_harness_timeout_ceiling_check.py::test_each_root_prints_its_own_file_count` | INTRODUCED |
| 6 | `test_ci_harness_timeout_ceiling_check.py::test_the_advisory_residual_does_not_grow_unreviewed` | INTRODUCED |
| 7 | `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step15]` | PRE-EXISTING — gsweep |
| 8 | `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step17]` | PRE-EXISTING — gsweep |
| 9 | `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step19]` | PRE-EXISTING — gsweep |
| 10 | `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step20]` | PRE-EXISTING — gsweep |
| 11 | `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step30]` | PRE-EXISTING — gsweep |
| 12 | `test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step32]` | PRE-EXISTING — gsweep |
| 13 | `test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step31]` | PRE-EXISTING — gsweep |

Plus a fourteenth red the landing tier could NOT see, behind its NORECORD:
`test_pytest_per_file_junit.py::test_the_landing_harness_declares_semantic_progress_not_elapsed_time`
— INTRODUCED, same cause as 1-6 (§4).

**THE FOURTEENTH OF THE LANDING TIER'S FOURTEEN IS NOT REPRODUCED AND IS NOT NAMED HERE.**
It is not invented to close the arithmetic, and one tempting way to close it is written down
so that nobody else takes it: the pinned-image run yields 19 after the NORECORD file, and
dropping five of the six mount artefacts of §7 while keeping
`test_d3_waived_unproven_entries_have_no_committed_artefact` gives exactly 14. That is
arithmetic, not evidence — the sixth artefact is the same kind of thing as the other five,
proved green when its cause is removed, and keeping it only because 14 is the number being
looked for is precisely the move this document exists to refuse.

Two honest readings remain, and this measurement does not choose between them: the fourteenth
is environment-dependent in the hermetic arm profile that was not reproduced here (§9), or it
is a count whose fourteenth member nobody has ever named. **What is settled either way is the
split**: it is red on both trees or it is not, and no node in either environment moved between
buckets (§2). Six of the landing tier's fourteen are the candidate's; seven are `gsweep`'s and
pre-date it; the fourteenth is unnamed and, whatever it is, is not shown to be the candidate's.

## 9. WHAT WAS NOT RUN

* The full `programs/tests` suite — never, on either tree, in either environment. Only the
  49 selected files, per file.
* The landing tier's own hermetic arm profile (`network: none`, `read_only: true`,
  `user 65534`, tmpfs `/tmp`, env-i exact arm profile). The pinned IMAGE was used; the rest of
  the profile was not. That is why §6 and §7 exist rather than being invisible.
* `tools/ci/test_landing_runtime_preflight_gate.py` and `tools/ci/test_phase_b_activated_parity.py`
  as tests. The selector does not select them — it reports
  `tools/ci/test_phase_b_activated_parity.py` as UNMAPPED, "the smoke floor, which is not
  evidence about them" — and the `tools/` lane is `gunattr`'s.
* `programs/pytest_per_file_junit.py` was not touched, read-only throughout. Its bytes are
  `dd463b9ba…`, 140237 B, matching the protected-landing manifest's `next` tuple exactly.
* No fix was applied and no check was weakened. All seven candidate-introduced reds trace to
  one cause whose every remedy edits protected gate bytes or the transition mechanism.

## 10. THE DEFECT IS LIVE ON THE CANDIDATE'S CURRENT TIP, NOT ONLY ON THE TIP MEASURED

`jnorec` has since rebased. `$HOME/_jnorec_wt` is now on `jnorec/land` `3e6c1bfc8` — the same
four commits re-authored onto a newer main, plus a fifth
(*"a 24-second run was reported as a 300-second hang, because the reason was read out of the
buffer the subject writes"*). `706b14400`, the tip measured above, is NOT an ancestor of it.

**The §3 defect survives the rebase, with a third digest:**

```
jnorec/land 3e6c1bfc8
  live  pytest_per_file_junit.py                   ddbca015ba56032e   144004 B
  next  pytest_per_file_junit.py                   ddbca015ba56032e   144004 B   <- rolled
  current pytest_per_file_junit.py                 5d270fa98e8aff65   127578 B   <- NOT rolled
  current AND next ci_harness_timeout_ceiling_check.py  c880c76331911841  90369  <- still FROZEN
  and that frozen file still contains
      _SEMANTIC_DRIVER_SHA256 = "5d270fa98e8aff656998e3c23a116e3d85ad55ce35d119807cf8e94a263b9cf0"
```

The move is still one path wide, still on `pytest_per_file_junit.py`, and still freezes the
file that hard-pins that path's digest. **Measured, not inferred** — running the ceiling
check against `3e6c1bfc8` reproduces the same six nodes:

```
6 failed, 80 passed in 4.73s
  test_semantic_landing_harness_has_no_elapsed_ceiling
  test_the_json_record_carries_what_the_text_says
  test_the_shipped_tree_is_clean
  test_each_root_prints_its_own_file_count
  test_the_advisory_residual_does_not_grow_unreviewed
  test_a_recorded_advisory_that_stopped_existing_is_deleted
```

So this is not a finding about a superseded branch. Whatever lands tonight carries it unless
the policy decision in §3 is taken first.
