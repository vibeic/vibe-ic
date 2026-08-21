# DISTIL — six captured recoveries into the program layer

Branch: `agent/jcapture-bucket-a-gates` (pushed), based on `origin/main`
`6dfe15a32` [v1.11.62].
Records: `/tmp/capture_20260821/{recoveries,summary}.json` + three sketch files.

Everything below was MEASURED on this branch, in a fresh `git worktree` off
`origin/main`, with `PYTHONDONTWRITEBYTECODE=1` exported and the tree clean —
because rule 6 is about exactly the failure that happens when it is not.

## The verdict in one table

| # | rule | already a program? | new program | corpus sweep | findings |
|---|---|---|---|---|---|
| 1 | `landing_noop_is_not_verified` | no | `landing_noop_verdict_check.py` | 200 local branches vs `origin/main`, against an independent oracle | 0 false refusals, 0 false passes |
| 2 | `generated_test_list_minimum_guard` | no (emptiness only, in two places) | `generated_test_list_min_guard.py` | see §2 | 0 |
| 3 | `version_claim_sits_in_a_table_row` | no (`plugin_version_prose_sync_check` checks agreement) | `doc_table_row_placement_check.py` | 1174 documents / 18961 table-shaped lines, plus 1370 historical blobs | 0 on HEAD; **25 in history** |
| 4 | `emitter_population_and_its_test_pin_move_together` | no | `emitter_population_pin_check.py` | 1232 programs + 1619 single-program test files | 0 |
| 5 | `a_prepare_describes_the_tree_it_lands_on` | **YES — no new program** | — | — | — |
| 6 | `attestation_gates_refuse_a_dirty_checkout_before_running` | partly (`landing_worktree_is_clean_check` ignores untracked BY DESIGN) | `attestation_preflight_check.py` | 4168 files under the programs root | 0 clean / 3 named when dirty |

62 tests across six files, all green. Every gate exits 0 on this repository.

---

## 0. The shared site the five gates needed: `programs/_gate_usage_exit.py`

The repo's convention is `0 PASS / 1 FAIL / 2 VACUOUS`. `argparse` exits **2**
for a bad command line, so one code carries two unrelated meanings.
`_gate_invocation` measured the cost: of 241 registered structural gates driven
by the P0 umbrella, **39 never got past argument parsing** and every one was
recorded as a benign input-missing skip.

`_gate_usage_exit` moves the usage tier to **rc 3** with a `USAGE_ERROR:`
line-start token. Both `error()` and `exit()` are overridden, because argparse
raises status 2 from internal paths `error()` never sees. `--help` still exits 0.

*Not a collision with #651's rc-3 waiver tier*: `flow_compliance_check:3107` —
"a bare rc=3 with no sentinel stays a FAIL". Nothing here emits the
`PASS_WITH_WAIVERS` sentinel. `_analog_producer_common` solved the same collision
with `EX_USAGE` (64) for PRODUCERS; the choice is recorded in the docstring
rather than left as an inconsistency for a reader to find.

One site, not five copies — `gate_discloses_denominator_check` recorded fourteen
gates that had each pasted a shared convention with "no shared site to fix", and
`test_gate_usage_exit.py::test_every_bucket_a_gate_uses_this_site_rather_than_its_own_copy`
is what keeps a sixth gate from pasting instead of importing.

---

## 1. `landing_noop_is_not_verified` → `programs/landing_noop_verdict_check.py`

**Existing program? No.** Grepped `programs/` and `tools/`: `landing_merge_verdict.py`
decides the merge REFUSAL (#1019) from failed-test/gate differentials and forms no
opinion about content identity; `salvage_landed_probe.py` answers "is this
BEHAVIOUR in main" by transplanting a test onto three trees, deliberately not a
byte question; `landing_collateral_revert_check`, `landing_is_one_commit_check`
answer other questions. The only "nothing to land" decision in the tree is
`gatekeeper-land-differential.sh:231`, `[ "$BASE_SHA" = "$HEAD_SHA" ]`, which is
ancestry.

**The rule.** Every path the lane touches (`merge-base(branch,target)..branch`)
is compared BLOB-OID against the target — a git blob's object name is the hash of
its content, the same instrument `tools/ci/trusted_worktree_attest.py` uses. Four
per-path verdicts, each a different remedy and each named: `IDENTICAL`,
`CONTENT`, `ABSENT` (target never saw it), `UNDELETED` (target kept a file the
lane removed). `--generated GLOB` LABELS a path, never waives it — the measured
lane lost three non-generated files behind one generated one.

`--claim {noop,work}` makes the exit code answer the CALLER'S claim, so neither
seam has to invert a verdict.

**Four arms + mutation** (`programs/tests/test_landing_noop_verdict_check.py`, 13 tests):

| arm | test | result |
|---|---|---|
| positive | `test_a_lane_whose_bytes_are_all_in_the_target_is_a_verified_noop` | rc 0, prints `2 path(s)` |
| negative | `test_a_partly_landed_lane_refuses_the_noop_and_names_the_paths` (+ ABSENT, UNDELETED, `--generated`) | rc 1, names `a.txt`, does NOT name the path that did land |
| VACUOUS | `test_a_branch_that_touches_nothing_is_vacuous_and_says_so` | rc 2 + `VACUOUS_PASS:` marker on stderr |
| bad invocation | `test_a_ref_that_does_not_resolve_is_rc3_not_rc2`, `test_an_unknown_flag_is_rc3_not_argparse_2` | rc 3 + `USAGE_ERROR:` |
| **mutation** | `test_reverting_the_refusal_makes_the_partial_land_pass` | `classify()`'s `IDENTICAL if b == t else CONTENT` → `IDENTICAL`; the fixture that is rc 1 above becomes rc 0 |

**CORPUS SWEEP.** Every local branch (200) against `origin/main`:

```
examined=200  rc0=29 (verified no-op)  rc1=79 (refused)  rc2=92 (vacuous)
false_refusals=0   false_passes=0
```

The oracle is INDEPENDENT of the program: `git diff --name-only origin/main <branch> -- <touched paths>`,
a different instrument from `ls-tree` blob names. A false refusal is an rc 1
whose oracle diff is empty; a false pass is an rc 0 whose oracle diff is not.
Neither occurred. Script: `/tmp/.../scratchpad/xcheck1.py`.

**One defect found and closed while sweeping.** `blob_index` filtered `git
ls-tree` to `blob` entries. A gitlink (`160000 commit`) would then be absent from
BOTH indexes, and `classify` reads a path absent from both as "both trees deleted
it" — IDENTICAL, a false pass on a real content change. This repository carries
no submodule today (`git ls-files -s | awk '$1=="160000"'` → 0), which is exactly
why it is pinned: a rule that is right only while a fact happens to hold is the
shape this whole batch is about.
`test_a_gitlink_the_target_does_not_carry_is_not_read_as_identical` builds the
pointer with `git update-index --cacheinfo` and is red without the fix.

**Wired**: `tools/gatekeeper-land-differential.sh`, `--claim work`, immediately
after the ancestry checks. This is not decoration — that file already refuses on
`BASE_SHA = HEAD_SHA`, and this repository squash-lands, so a branch whose
content already reached the trunk and was then rebased has a different HEAD and
identical bytes. Ancestry says there is a range; the blobs say there is nothing
in it, and four throwaway checkouts plus an hour of gates measure the base
against itself.

---

## 2. `generated_test_list_minimum_guard` → `programs/generated_test_list_min_guard.py`

**Existing program? No — two emptiness tests, and neither is a minimum.**

* `tools/gatekeeper-land.sh:912` — `[ ! -s "$sel" ]`, file non-empty.
* `tools/gatekeeper-land-differential.sh:369` — the same test, and it only
  PRINTED a warning and carried on.
* `tools/ci/trusted_test_selection.py:455` — `raise Refusal("trusted selection
  denominator is empty")`, plus a genuine per-path existence check
  ("selected path is absent from both commits") and mandatory negative controls.
  That is the strongest of the three and it is still emptiness, not a floor; it
  also covers only the merge-verify path.

**The rule.** Refuse unless the list holds at least `--min` **DISTINCT** entries
and every one of them exists under `--root`. Distinct, because a minimum written
over line count is satisfied by one path repeated nine hundred times — the first
failure wearing the second's clothes. The floor is an ARGUMENT: a guard that
derived its own floor from the file it is checking agrees with itself by
construction, which is `hygiene_shard_aggregate --expect`'s rule.

**Four arms + mutation** (`test_generated_test_list_min_guard.py`, 11 tests):

| arm | test | result |
|---|---|---|
| positive | `test_a_list_at_or_above_its_floor_with_every_path_present_passes` | rc 0, prints `5 distinct` |
| negative | `test_an_empty_list_is_refused`, `test_a_non_empty_list_far_below_its_floor_is_refused`, `test_duplicates_cannot_inflate_a_list_over_its_floor`, `test_one_unresolvable_path_refuses_the_whole_list` | rc 1; names the count seen vs required and the unresolvable path |
| VACUOUS | `test_an_unreadable_root_is_vacuous_and_says_so` | rc 2 + marker — existence could not be DECIDED |
| bad invocation | `test_a_missing_minimum_is_rc3_not_argparse_2`, `test_a_floor_of_zero_is_rejected_as_a_command_line`, `test_an_unreadable_list_is_rc3` | rc 3 + `USAGE_ERROR:` |
| **mutation** | `test_reverting_the_minimum_to_an_emptiness_test_lets_the_shrunken_list_pass` | `len(distinct) < args.minimum` → `not distinct`; the three-entry list refused above passes. That IS the shell script's rule, stated as an experiment. |

**CORPUS SWEEP.** The real selector, driven against 12 real bases (the last 12
commits of `origin/main`), each output handed to the guard with the floor the
wiring derives:

```
bases=12   PASS=12   REFUSED=0   VACUOUS=0
smallest distinct selection over the 12 = 151, against a derived floor of 18
```

Zero false refusals. The margin (151 vs 18) is the honest reading of what the
floor is worth: it is a FLOOR, not an expectation, and it catches the collapse —
the zero-byte list and the three-of-nine-hundred list — not a normal selection
that happens to be small.

A wider replay (60 bases) was started and stopped: a selector run against a base
deep in history takes ~170 s, so 60 of them is over two hours of wall clock for
the same answer. What is reported is what was measured, and 12 is the denominator.

The two failure MODES are proved by fixture rather than by corpus, because
neither has an instance in this tree — which is the point of shipping the guard:
`test_an_empty_list_is_refused`, `test_a_non_empty_list_far_below_its_floor_is_refused`,
`test_duplicates_cannot_inflate_a_list_over_its_floor`,
`test_one_unresolvable_path_refuses_the_whole_list`.

**Wired**: `tools/gatekeeper-land-differential.sh`, at the selector→runner seam,
replacing the warning. The floor is DERIVED, never typed: the selector's own
`SMOKE_BASENAMES` resolved against the candidate tree the way the selector
resolves it (a basename that does not exist is skipped), so it shrinks with the
tree and can never become a stale census pin. Measured here: 18 of 18 present.

---

## 3. `version_claim_sits_in_a_table_row` → `programs/doc_table_row_placement_check.py`

**Existing program? No, and the gate that looks closest is structurally unable
to see it.** `plugin_version_prose_sync_check` asks whether a stated version
EQUALS the shipped one, over three named documents and six claim FORMS. A claim
inserted in the wrong PLACE still equals it. `marketplace_version_sync_check`
guards the JSON manifests. `staged_version_claim_check`, `version_bump_monotonic_check`
answer other questions. None reads placement.

**The rule.** Every contiguous run of table-shaped lines must contain a GFM
delimiter row. Written the other way round — "a table row whose neighbours are
prose" — it would need a definition of prose and inherit every argument about
lists, block quotes and footnotes. It does not need one: without a delimiter row
the lines are not a table and never render as one, for any reader.

Fenced blocks are skipped; a pipe table drawn as an example inside a fence is not
a claim about anything. The finding carries the neighbours, because they are the
evidence — the halves of the sentence the paste replaced.

**Four arms + mutation** (`test_doc_table_row_placement_check.py`, 10 tests):

| arm | test | result |
|---|---|---|
| positive | `test_a_real_table_passes`, `test_the_shipped_corpus_is_clean`, `test_a_pipe_table_inside_a_fence_is_not_a_finding`, `test_a_single_dash_delimiter_is_a_real_table` | rc 0 |
| negative | `test_a_fragment_pasted_into_prose_is_refused`, `test_the_finding_carries_the_prose_it_displaced` | rc 1; names document, line, and both prose neighbours |
| VACUOUS | `test_examining_no_document_is_vacuous_and_says_so` | rc 2 + marker |
| bad invocation | `test_a_path_that_does_not_exist_is_rc3_not_rc2`, `test_an_unknown_flag_is_rc3_not_argparse_2` | rc 3 |
| **mutation** | `test_reverting_the_delimiter_rule_lets_the_fragment_pass` | `if not any(DELIMITER.fullmatch(...))` → `if False:`; the swallowed sentence passes |

**CORPUS SWEEP — three corpora, and the third is the proof.**

```
origin/main tracked markdown        318 documents   5953 table-shaped lines   0 findings
the second checkout's markdown      856 documents  13008 table-shaped lines   0 findings
                                   ----                -----
                                   1174 documents  18961 lines                0 findings
```

One false positive was found and REMOVED during development: an upstream
vendored document whose delimiter is `|-|-|-|`. A single dash per cell is legal
GFM; demanding two produced the finding. `test_a_single_dash_delimiter_is_a_real_table`
pins the repair.

**Replay over history — the rule finds the measured defect.** Running
`orphan_blocks` over the last 400 commits of `origin/main`, every distinct
tracked markdown blob:

```
commits=400   distinct markdown blobs examined=1370   orphan findings=25
   f842978a7e0d  vibe-ic-marketplace/README.md:43  | Plugin version | **1.11.42** |
   1c80e86e3ea6  vibe-ic-marketplace/README.md:43  | Plugin version | **1.11.41** |
   ... 23 more, the number advancing release by release ...
   748ca9dfca95  vibe-ic-marketplace/README.md:43  | Plugin version | **1.11.23** |
```

That is the recovery's measurement, reproduced by the program: a version claim
in a "table" that never rendered as one, with **twenty-five** subsequent bumps
faithfully advancing the number inside it. Every version gate looked at those
numbers and found them correct. It is repaired on HEAD, which is why the sweep is
clean; the guard is what stops it returning.

**Wired**: `tools/ci/repo_hygiene_gates.sh`, immediately after
`run "plugin version stated in prose"`, because it is that gate's blind spot.
**This is a PROTECTED path — see REQUESTS TO THE LANDER.**

---

## 4. `emitter_population_and_its_test_pin_move_together` → `programs/emitter_population_pin_check.py`

**Existing program? No.** `corpus_cardinality_pin_scan` finds tests pinned to a
corpus census and is a REPORTER (exits 0 whatever it finds); `derived_corpus_figure_check`
asks whether a figure in a DOCSTRING can be recomputed; `gate_discloses_denominator_check`
and `gate_zero_denominator_refuses_check` ask what a gate's OUTPUT said about its
own reach. None compares a printed population against the population it counts.

**The rule, in two checks.**

* **A — the emitter against itself.** An emitted script that increments a counter
  at K sites and states a LITERAL denominator for that counter (`$X >= D`,
  `$X == D`, `$X/D`, `$X of D`, `D >= 2`) is stating one population twice.
  Refuse when `D != K`. This is the half that catches the lane on the way in:
  add a fourth repair and `of 3` is wrong before any test runs.
* **B — the test pin against the emitter.** A test naming exactly one program,
  quoting a population phrase whose tail the emitter also states, must quote one
  of the emitter's own values for that tail.

**What was tried and rejected, with numbers**, because the narrowing is the
whole engineering content here:

| predicate | pins examined | "findings" | verdict |
|---|---|---|---|
| every `assert "<literal>" in <text>` matched verbatim against the named program's source | 6062 | 2345 | **rejected** — emitters TEMPLATE their output (`f"{n} of {m} failures"`), so the finished string is not, and must not be, a literal anywhere in the emitter |
| narrowed to population phrases (`of N <tail>`) | 40 | 34 | rejected — same cause |
| + require the emitter's denominator to be a HARD literal | 14 | 3 | rejected — all 3 false, all three a docstring narrative recounting what a number USED TO BE |
| + exclude docstrings and bare block strings on BOTH sides | 4 | **0** | shipped |

**Four arms + mutation** (`test_emitter_population_pin_check.py`, 10 tests):

| arm | test | result |
|---|---|---|
| positive | `test_an_emitter_that_agrees_with_itself_and_its_pin_passes`, `test_the_shipped_corpus_is_clean`, `test_a_docstring_narrative_is_not_a_pin`, `test_a_presence_test_is_not_a_population` | rc 0 |
| negative | `test_a_fourth_increment_without_moving_the_denominator_is_refused` (check A), `test_a_pin_naming_a_value_the_emitter_no_longer_states_is_refused` (check B) | rc 1; names the site count, the denominator, the test line and both values |
| VACUOUS | `test_a_tree_stating_no_population_twice_is_vacuous_and_says_so` | rc 2 + marker |
| bad invocation | `test_a_programs_directory_that_does_not_exist_is_rc3`, `test_an_unknown_flag_is_rc3_not_argparse_2` | rc 3 |
| **mutation** | `test_reverting_the_comparison_lets_the_disagreement_pass` | both `if value != sites:` and `if value not in emitted:` → `if False:`; the disagreeing fixture passes |

**CORPUS SWEEP.**

```
1232 programs and 1619 single-program test files enumerated
3 emitted counter denominator(s) and 1 test pin(s) examined      0 findings
```

**THE REACH IS SMALL AND THE PROGRAM PRINTS IT ON EVERY RUN.** Three of those
denominators are the measured site itself (`phase3_one_shot_runner`'s
`$_prr_refused`, stated as `>= 3`, `of 3 repairs refused` and `/3`, against three
`incr` sites). A verdict that did not state its reach would overstate itself, so
the count is in the PASS line and in the `--json` report. The narrow scope is the
price of zero false positives; the alternative measured 2345.

**Wired**: `tools/ci/repo_hygiene_gates.sh`, after
`run "stated corpus figures are derived, not typed"` — the third member of that
family. **PROTECTED path — see REQUESTS TO THE LANDER.**

---

## 5. `a_prepare_describes_the_tree_it_lands_on` — ALREADY A PROGRAM. No new gate.

**`tools/ci/protected_landing_transition.py`, `build_receipt()`, lines 510–538.**

```python
base_files = _observe_files(repo, base_commit, base_manifest["paths"], algorithm, oid_len)
...
if candidate_manifest["current"]["id"] != base_state_id:
    raise Refusal("PREPARE current state id does not name the live base")
if candidate_manifest["current"]["files"] != base_files:
    raise Refusal("PREPARE current tuple is not the exact live base tuple")
```

`_observe_files` re-hashes every path in the manifest's `paths` tuple against the
commit being landed on, AT VERIFICATION TIME. That is the rule verbatim: "at
landing, re-hash every path in the `current` tuple against the landing tree; any
mismatch refuses". The ACTIVATE branch is the same instrument —
`_match_state(candidate_files, base_manifest)` re-derives the state from observed
bytes and refuses "a rollback or unprepared move".

The recovery's `fix_action` — "re-render the manifest against that tree rather
than transcribe an older one" — is **also already a program**:
`tools/ci/protected_landing_manifest_author.py`, whose own docstring carries the
measurement that motivated it (three consecutive hand-authored manifests with
`current.id == next.id`, which `parse_manifest` refuses).

The manifest in the tree carries **47** protected paths, matching the recovery's
"forty-seven protected paths in its `current` tuple".

Writing a sixth program here would be duplication, and the skill measures that
roughly 63% of "extractable rules" already are programs. **One residual gap,
which is a message and not a rule** — see REQUESTS TO THE LANDER.

---

## 6. `attestation_gates_refuse_a_dirty_checkout_before_running` → `programs/attestation_preflight_check.py`

**Existing program? Partly, and the overlap is deliberate on the other side.**

* `landing_worktree_is_clean_check.py` covers TRACKED modifications under the
  shipped paths, with a fingerprint for the mid-run window. Its docstring states:
  *"UNTRACKED files are ignored on purpose"* — and untracked/ignored bytecode is
  exactly the class that bit us.
* `gate_host_independence_check.py` refuses `DIRTY_CHECKOUT` on tracked drift,
  and treats untracked + ignored paths as its STIMULUS (#539) — "No `--ignored`:
  `__pycache__` and `.pytest_cache` churn on every drive". Correct for that probe.
* `suite_write_guard` skips regenerable artefacts by design.

**So nothing sees the bytecode, and the drift instrument does.**
`_run_isolation.snapshot()` — taken on both sides of every `matrix_mutation_ledger`
replay — is `root.rglob("*")` over the FILESYSTEM and records every regular file,
`.pyc` included. `.pyc` is gitignored, so `git status` is silent. That asymmetry
is the measured 13-of-39.

**The rule.** Before the expensive run: (a) `PYTHONDONTWRITEBYTECODE` present in
the ENVIRONMENT — not `sys.dont_write_bytecode`, which is what `python3 -B` sets
for itself and is NOT inherited by the children an attestation spawns; (b) no
bytecode/cache residue under the DECLARED roots; (c) no tracked drift under them.
`--refuse-untracked` is opt-in, because turning it on by default would break #539.
At least one ROOT is required: the set of paths an attestation re-derives is a
property of that attestation and is never guessed.

**Four arms + mutation** (`test_attestation_preflight_check.py`, 11 tests):

| arm | test | result |
|---|---|---|
| positive | `test_a_clean_root_with_the_flag_set_is_attestable`, `test_the_shipped_tree_preflights_clean_under_the_prescribed_environment`, `test_untracked_files_are_the_stimulus_and_are_not_refused_by_default` | rc 0 |
| negative | `test_the_flag_is_read_from_the_environment_not_from_this_interpreter`, `test_a_gitignored_bytecode_artefact_is_a_refusal` (the fixture ASSERTS git cannot see it, or it would prove nothing), `test_a_tracked_edit_under_a_declared_root_is_a_refusal` | rc 1; each cause named |
| VACUOUS | `test_a_root_holding_no_file_is_vacuous_and_says_so` | rc 2 + marker |
| bad invocation | `test_no_root_is_rc3_because_the_snapshot_set_is_never_guessed`, `test_a_root_outside_the_repo_is_rc3_not_a_finding`, `test_an_unknown_flag_is_rc3_not_argparse_2` | rc 3 |
| **mutation** | `test_reverting_the_residue_walk_lets_the_stray_bytecode_pass` | both `RESIDUE_DIRS` / `RESIDUE_SUFFIXES` tests → `if False:`; the gitignored `.pyc` fixture passes |

**CORPUS SWEEP — both directions, on the real tree.**

```
clean committed tree, PYTHONDONTWRITEBYTECODE=1
  [PASS] 4168 file(s) under 1 declared root(s) — no residue, no tracked drift

the same tree mid-session (after a pytest run, with uncommitted edits)
  [FAIL] 1 bytecode/cache artefact ... programs/__pycache__
         2 TRACKED path(s) differ from HEAD: landing_noop_verdict_check.py,
                                            tests/test_landing_noop_verdict_check.py
```

The red arm is not a fixture. It is this session's own working tree, refused for
the three real reasons, before anything expensive ran — which is the whole of the
rule.

**Wired**: `tools/gatekeeper-land-differential.sh`, on the candidate worktree
right after `git worktree add`, together with `export PYTHONDONTWRITEBYTECODE=1`
at the top of that script. The export is the FIX; the preflight is what stops it
being a habit — remove the export and the preflight goes red.

*Why NOT `tools/ci/repo_hygiene_gates.sh`*: measured, that wiring is a BAN. The
hygiene script's own earlier gates import shipped modules without the token, so
`programs/__pycache__` exists by the time the preflight would run, and it would
refuse every landing. A gate that refuses every landing is a ban, and a ban is
what teaches an operator to route around it.

---

## Everything that was re-measured after the change

Run on the clean committed branch with `PYTHONDONTWRITEBYTECODE=1`:

| gate | candidate | base (`origin/main`, pristine worktree) |
|---|---|---|
| chip-AGNOSTIC source guard | PASS (1550 files) | — |
| shipped-path portability | PASS (4679 files) | — |
| programs index fresh | PASS (1164 indexed) | — |
| argparse help format | PASS | — |
| dead plugin path | PASS | — |
| gates disclose their denominator | PASS (59 of 88 probed) | — |
| a zero denominator refuses | PASS (569 probed) | — |
| gate skip routing | PASS | — |
| no gate is left neutered | PASS | — |
| derived corpus figures | PASS (4029 files) | — |
| **declared reports written atomically** | **PASS** (fixed: all five routed through `_atomic_artefact.write_json`) | — |
| silent remedy decline | PASS | — |
| plugin version stated in prose | PASS (6 claims / 3 documents, all 1.11.62) | — |
| NDA scan of the tracked tree | PASS (5815 blobs) | — |
| plugin full audit (D1/D2) | PASS (1238 programs) | — |
| **gates are wired** | FAIL: `closed_loop_edge_check`, `ppa_pr_scope_check`, `slot_pad_budget_check` | **FAIL: the same three, by name** |
| **checker execution wiring** | FAIL: the same three | **FAIL: the same three** |

The two reds are **identical on both arms, by test ID and not by count**. None of
the five new gates appears: all five are wired. The three named are pre-existing
and none is in the 59-entry `gate_is_wired_baseline.json`.

`gate_is_wired_check` also NOTES that the baseline shrank
(`analog_liberty_nonzero_delay_check` is now wired). That is pre-existing drift on
the base and it was **not** repaired here, because the repair is
`--write-baseline`, which the brief forbids.

## What was NOT done, and why

* No push to `main`. No plugin version bump. No `--write-baseline` anywhere.
* No edit to `tools/ci/protected_landing_transition.json`.
* `programs/INDEX.md` was regenerated with `tools/gen_programs_index.py` (1159 → 1164),
  because `run "programs index fresh"` would otherwise refuse the landing.
* Rule 5 got no program. See §5.

## Language / NDA

Every artefact added here is English-only and names no foundry, process node, SKU
or chip codename; `nda_tracked_tree_scan` PASSES over 5815 tracked blobs and the
chip-AGNOSTIC guard over 1550 plugin source files.

---

# REQUESTS TO THE LANDER

## R1 — a PREPARE for one protected path (BLOCKING for this branch)

This branch changes the bytes of exactly one of the 47 protected paths and does
**not** touch the manifest, so it is the ACTIVATE half and
`protected_landing_transition.build_receipt` will refuse it as "a rollback or
unprepared move" until a PREPARE is rendered against the base.

```
path     : tools/ci/repo_hygiene_gates.sh
mode     : 100755

  LIVE at origin/main 6dfe15a32        AFTER this branch
  blob_oid 7670045ab91c91d687278d81c71c6719bcce55d0
           786873ef33e92a0c0250669c80a4a34224927cdb
  sha256   c311b8d27416b22c292c2cb0289e2668a7f5859a43bb4480c3c6ce389d12b861
           70aa60929f4beead60d8a81678c711d98d4bf9cb8e33646af057a9ef0f765203
  size     113195
           114792
```

The other 46 protected paths are byte-identical to `origin/main` (verified with
`git diff --name-only origin/main HEAD -- <the 47>`, which names only this one).
The live tuple matches BOTH `manifest.current` (`eda-image-decouple-v1-next`) and
`manifest.next` (`activated-at-lane-parallel-window`) for this path, because the
lane-parallel-window transition moved three other paths and not this one.

Suggested: `protected_landing_manifest_author.py --next-file
tools/ci/repo_hygiene_gates.sh=<this branch's copy>`, so nothing is transcribed.

The change is two `run` lines plus their comments — the wiring for rules 3 and 4.

## R2 — `protected_landing_transition.py` refuses without naming the paths

Rule 5 is enforced, and its refusal is one sentence short of actionable:

```python
raise Refusal("PREPARE current tuple is not the exact live base tuple")
```

The measured recovery was "two of forty-seven protected paths no longer matched
the tree it would land on, **and neither is a path that transition moves**" —
which is the sentence a maintainer needs and the refusal does not print. The two
lists are both in scope at that line (`candidate_manifest["current"]["files"]`
and `base_files`), so this is a message change, not a rule change:

```python
if candidate_manifest["current"]["files"] != base_files:
    live = {r["path"]: r["sha256"] for r in base_files}
    drifted = sorted(r["path"] for r in candidate_manifest["current"]["files"]
                     if live.get(r["path"]) != r["sha256"])
    moved = {r["path"] for r in candidate_manifest["next"]["files"]} - ...
    raise Refusal("PREPARE current tuple is not the exact live base tuple; "
                  f"{len(drifted)} of {len(base_files)} path(s) drifted: "
                  + ", ".join(drifted[:6]))
```

I did not make this change: `tools/ci/protected_landing_transition.py` is itself
protected (role `authority`), and a second protected path in one landing doubles
the PREPARE. Say the word and it arrives as its own lane with its own numbers.

## R3 — two seams in the protected landing RUNTIME that I deliberately left alone

Both are already wired on the differential path, so nothing is unguarded; these
are the SAME holes in the files a merge-path landing uses, which are protected.

* `tools/gatekeeper-land.sh:912` — `if [ ! -s "$sel" ]` is the naked emptiness
  test rule 2 replaces, and it is the only one left in the tree. The differential
  path now derives the selector's own smoke floor and calls
  `generated_test_list_min_guard`; the same lines belong here.
* `tools/ci/trusted_test_selection.py:455` — the MERGE path does not have that
  hole: it builds the denominator through `trusted_test_selection`, which
  refuses an empty selection and refuses a path absent from BOTH commits. What it
  still has no notion of is a FLOOR — a selection that came back at 3 of an
  expected 900 is accepted. A `--min` there, derived from the same
  `SMOKE_BASENAMES` the differential path now uses, closes it.

Neither is in this branch, because each would be another protected-path ACTIVATE
(`tools/gatekeeper-land.sh` role `runtime`, `tools/ci/trusted_test_selection.py`
role `authority`). If you want them, say so and I will produce the bytes and the
sha256/size pairs the same way as R1.

## R4 — the batch lander itself is rule 1's real caller

`landing_noop_verdict_check` is wired to this repository's own landing gate, but
the failure it was distilled from happened in the FLEET batch lander — the thing
that logged `NOTHING TO LAND` for a lane that differed in four files. That tool is
not in this repository, so nothing here can wire it. The call it wants is:

```
landing_noop_verdict_check.py --repo <clone> --branch <lane> --target <trunk> \
    --claim noop --generated 'vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md' \
    --generated '<the 63x8 census files>' --json <report>
```

rc 1 means the no-op verdict is wrong and the paths are printed, split into
generated (re-run the generator on the merged tree) and not (apply the lane's
bytes).

## R5 — pre-existing reds this branch did not touch

`gate_is_wired_check` / `checker_execution_wiring_audit` are red on pristine
`origin/main` with `closed_loop_edge_check`, `ppa_pr_scope_check` and
`slot_pad_budget_check`, and `gate_is_wired_check` additionally NOTES that
`analog_liberty_nonzero_delay_check` is now wired and the baseline is stale. All
four want `--write-baseline`, which the brief forbids here. Flagging, not fixing.
