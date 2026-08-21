# Full test coverage for the two tape-out paths, IC and IP

Branch `test/pathsteps-ic-ip-matrix`, cut from `origin/main` **8a9c5ad9e**
(`[v1.11.51]`, fetched 2026-08-21 18:07). Worktree at cut: 5658 tracked files,
`git status --porcelain` empty.

### What changed

```
A  vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_path_step_matrix_ic_and_ip.py
       the matrix. 129 collected node ids.

M  vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_tapeout_readiness_check.py
       finding F6 — a pre-existing red ON step 37.5ic, repaired.

M  vibe-ic-marketplace/plugins/vibe-ic/programs/PROGRAM_INVENTORY.json
M  vibe-ic-marketplace/README.md
M  vibe-ic-marketplace/plugins/vibe-ic/README.md
       derived counts, regenerated because the tree grew by one test file.
       See the A/B section.

A  RESULT.md
```

**No flow yaml byte changed**, no shipped program changed, no version bump, no
`--write-baseline` on any gate, no protected path touched, and nothing was
pushed to `main`.

---

## 1. What was built

A **design class x path step** matrix. Seven classes, five steps, every cell's
state asserted explicitly, and every cell decided by driving **the flow's own
predicates over a real project tree** — `flow_compliance_check._check_condition`
and `flow_compliance_check.check_step` — never by reading the yaml and
asserting what it appears to say.

That distinction is not stylistic. The pre-existing
`test_pad_and_seal_ring_on_the_chip_path.py:242` asserts the condition's TEXT
and pins 15.5ic's spelling to 26.5ic's and to 37.5ic's. All three can be
spelled identically and still be wrong for a class of design; only running them
on a tree of that class can say.

### The classes

Five from the brief, plus two the flow can distinguish that the brief did not
name:

| class | tree | why it exists |
|---|---|---|
| `self_tapeout_pdk_ships_no_shuttle` | `SELF_TAPEOUT.txt`, `ihp-sg13g2` | the registry names no shuttle |
| `self_tapeout_pdk_ships_a_shuttle` | `SELF_TAPEOUT.txt`, `gf180mcuD` | the registry names a LIVE one |
| `shuttle_chip_template_fetched` | `slots/1x1.yaml`, `gf180mcuD` | the operator's geometry is here |
| `shuttle_chip_template_not_fetched` | `SELF_TAPEOUT.txt`, `gf180mcuD` | see finding F1 — same tree as the row above |
| `ip_hardmacro` | `NO_TEMPLATE.txt` | the 37.5ip terminal |
| **`no_router_file_step_0_5ic_never_ran`** | no router artefact at all | **added.** The "someone forgot" class. Four step comments rest on the claim that 0.5ic's gate reports it; nothing tested that claim. |
| **`two_router_files_at_once`** | `SELF_TAPEOUT.txt` + `NO_TEMPLATE.txt` | **added.** Three steps justify their `any_of` with "no tree ever holds both". A tree that does makes every terminal run at once. |

### The three layers

**Condition layer** (35 cells) — `_check_condition` over each class tree.
RUNS / SKIPPED-CONDITION / MISSING, one stated expectation per cell, no default
and no wildcard: a cell nobody wrote is a `KeyError`, not a silent pass.

**Verdict layer** (35 cells) — `check_step` over a BARE tree. A cell that RUNS
must land on `MISSING`, never on a skip. This is the original defect stood on
its head: 15.5ic on a self tape-out used to report SKIPPED-CONDITION (nothing
to see) and must now report MISSING (a pad ring is owed and is not there).

**Gate layer** — two halves:
* *vacuous-pass guard*, per cell: no gate of a running step exits 0 on a tree
  carrying only a router file. rc 1 (a finding) and rc 2 (`[CANNOT CHECK]`) are
  both answers; rc 0 is not an answer at all.
* *red reachability*, per step: each of the five gates reaches **rc 1** on a
  constructed refusal. A gate stuck on rc 2 is a step stuck on SKIP one layer
  down — which is exactly how `pad_ring_gen` could only ever take its SKIP
  branch for a year.

**MISSING never reads as SKIPPED-CONDITION.** `_state()` returns MISSING for a
step id the flow does not carry at all, and the retired `37.5self` is the
standing control that proves the resolver keeps the two apart.

---

## 2. Findings

### F1 — a self tape-out on a shuttle-served PDK cannot pass 37.5ic. REPORTED, not fixed.

`tapeout_precheck.operator_arm_applicability` decides the operator arm from two
facts — the PDK's registry entry, and whether slot geometry was fetched — and
never from the **router file**. So a die taping ITSELF out on `gf180mcuD`
lands on `NOT_DETERMINED` ("the template was never fetched") for a template it
was never going to fetch, and `NOT_DETERMINED` exits 1.

The flow has the answer and this arm does not ask for it:
`_tapeout_declaration.route_of` is the canonical three-way router, and
`tapeout_declaration_gen` writes into `SELF_TAPEOUT.txt`, verbatim, that *"the
operator's own container is the arm it does not get, because there is no
operator."*

**Why I did not fix it.** Reading the router file would close this, and would
also make a design that genuinely INTENDED the shuttle and forgot to fetch read
as "one fewer arm" — a silence, which is the disease. The flow cannot tell the
two apart because there is no declared submission target (finding F2). The
honest remedy is structural.

Pinned by `test_a_self_tapeout_on_a_shuttle_pdk_is_refused_at_37_5ic` (our arm
stubbed ALL GREEN, so the refusal is attributable to the missing arm and
nothing else) and by
`test_the_route_predicate_exists_and_the_operator_arm_does_not_consult_it`,
which goes red the moment the arm starts consulting the route.

### F2 — the flow cannot distinguish two of the brief's five classes.

The brief names "self tape-out, PDK ships one" and "shuttle chip, template NOT
fetched" as separate classes. Their trees are **byte-identical**: a chip with no
ingested slot geometry gets `SELF_TAPEOUT.txt` whatever it intended, because
`route_of` reads `has_slots` and the declared `deliverable`, and the 18-question
declaration has no submission-target question. Both rows are kept, and
`test_the_flow_cannot_tell_a_self_tapeout_from_an_unfetched_shuttle` asserts the
declaration has no `submission_target` — so if one is ever added, the test goes
red and the two rows become genuinely different classes.

### F3 — step 38 is a SIXTH path-specific step, and it has no condition. REPORTED, not fixed.

The five steps carry the path in their id spelling, and nothing makes that
authoritative. Asking the question the other way round — *after the step the
flow itself calls "the cell/IP path TERMINAL", which later steps does an IP
still owe?* — returns exactly two, and one of them has no way out:

```
38  Foundry Handoff      no condition, no escape hatch
39  FPGA final sign-off  no condition, but --skip-hardware already waives it
                         (_FPGA_BOARD_STEP_IDS = {6, 39}); measured WAIVED
```

Everything else (M1..M4, 40..44) falls away on a condition of its own.

Measured on a **COMPLETE** IP deliverable — the streamed GDS plus all four
views — step 38 reports `MISSING` with all five kit members named. An IP has no
reticle, no wafer and no dicing street; step 38's own notes say the kit exists
because otherwise *"the foundry cannot accept the GDS for fab"*, which is a
statement about a die. Neither `foundry_handoff_package_check` nor
`foundry_handoff_pack_gen` contains any hardmacro or route branch — the gate
speaks only of *"the chip-named GDS deliverable"*.

**Why I did not fix it.** The remedy NARROWS a sign-off step's applicability,
and getting that wrong lets a die skip foundry handoff — the opposite and worse
failure. Recorded as `xfail(strict=True)` with the evidence, so it XPASSes and
forces the waiver's removal the moment it lands.

### F4 — three producers a path step declares are invoked by nothing. REPORTED, not fixed. **This is the headline.**

Dimension 1 of the 63x8 matrix asks whether a step's **gate** is wired, and
answers it by running `_evaluate_gate` for real. All five path steps pass.
Nobody asks the other half: a step also declares the programs that **produce**
its `required_outputs`, and a step whose producer nothing dispatches reports
MISSING for every design forever — which every reader charges to the design.

Measured by AST over every `programs/*.py` (string constants and imports,
docstrings excluded), plus the flow's own gate clauses as a second channel:

| step | producer | invoker |
|---|---|---|
| 0.5ic | `submission_template_ingest` | **NONE** |
| 0.5ic | `tapeout_declaration_gen` | **NONE** |
| 15.5ic | `pad_assignment_gen` | its own gate clause |
| 15.5ic | `pad_ring_gen` | **NONE** |
| 26.5ic | `die_finishing_gen` | `phase3_one_shot_runner.py:23340` |
| 37.5ic | `tapeout_docs_gen` | its own gate clause |
| 37.5ip | `digital_hardmacro_gen` | `phase3_one_shot_runner.py:31738` |

The one-shot runners hardcode their steps; `phase3_one_shot_runner` does not
load the flow yaml at all, so there is no dynamic dispatcher that a name scan
would miss. Nothing under `commands/`, `skills/`, `agents/`, `hooks/`,
`mcp-eda/`, `benchmark/`, `config/` or `_shared/` mentions any of the three.

**The consequence is the whole point.** `tapeout_declaration_gen` and
`submission_template_ingest` are the ONLY things in this flow that write a
router file, and every other path step conditions on one. So **no run of this
flow reaches a router file by running one**, which puts every design in this
matrix's `no_router_file` row — where 15.5ic, 26.5ic, 37.5ic and 37.5ip ALL
report SKIPPED-CONDITION. That is the same silent skip the chip-path work
(v1.11.38) landed to close, still live one layer up: the condition was repaired
and the thing that satisfies it was never dispatched.

The docstring exclusion is load-bearing and was measured, not assumed:
`pad_assignment_gen`'s docstring contains the line
`programs/pad_ring_gen.py    reader`, and a text scan counts that as an
invocation of the one producer in the list that has none.

**Why I did not fix it.** Wiring a producer into a one-shot runner changes what
a real run does and blocks on. The repo's own gates call that the flow owner's
call, and the `flow-change-acceptance` standard for it — bidirectional negative
control, corpus sweep with zero false positives, an explicit
BLOCKING-vs-ADVISORY declaration, prove-by-run — is more than a test branch
should decide unilaterally.

### F6 — a pre-existing test on 37.5ic stopped describing the flow. FIXED.

`test_tapeout_readiness_check.py::test_the_flow_declares_this_gate_with_the_path_this_program_writes`
is red on `origin/main` and is on the exact step this campaign covers, so it was
repaired rather than reported.

It asserted `"program_exit_zero" in gate` — a ONE-LEVEL lookup — which stopped
being true the moment 37.5ic took an `all_of` container to hold both arms in one
clause, the shape the step's own comment argues for at length. It also expected
the step to name `tapeout_readiness_check` directly and to declare exactly one
required output; since `37.5self` was retired the flow declares `tapeout_precheck`
(the merge) and the step has five outputs.

**The guarantee is kept and is now stronger**, because the repair follows the
real chain instead of assuming a one-hop one:

```
the flow declares -> tapeout_precheck         (the BLOCKING slot)
which invokes     -> tapeout_readiness_check
which writes      -> reports/phase3/shuttle_precheck.json
which the step declares as a required output
```

The gate is walked with the executor's own walker, and the delegation is read
out of `tapeout_precheck`'s source rather than restated, so a merge that quietly
stopped delegating cannot keep the test green. 37 passed 1 failed -> 38 passed.
Three mutation arms, M13-M15 below.

### F5 — minor: the flow names a step that does not exist.

`flow/phase1_phase2_phase3.yaml:668`, inside 0.5ic's comment, says in the
present tense that `SELF_TAPEOUT.txt` is *"read by step 37.5self"*. `37.5self`
was retired into 37.5ic as an ARM on 2026-08-20. Comment-only, no behaviour.
Not edited: the yaml is contended by the matrix-dimension lane and a one-line
comment is not worth an adjacency conflict. `programs/tapeout_precheck.py:22`
carries the same stale route table, but its surrounding prose is explicitly
historical.

---

## 3. Mutation arms

Every guard was mutated and the reddened node ids recorded. The deliverable is
tests, so the arm proves each guard reddens against the defect it guards.
Run serially in a dedicated worktree; the tree is `git checkout -- .` between
mutations and ends `porcelain=0`.

Base for every arm: `08d398576` (this branch's head at the time), reddening
against a clean 116 passed / 11 skipped / 2 xfailed.

| # | mutation | reddens | node ids |
|---|---|---|---|
| M1 | revert 15.5ic's condition to the pre-v1.11.38 operator-only form | 8 failed, 108 passed, 11 skipped, 2 xfailed in 40.94s | `test_condition_layer_cell[self_tapeout_pdk_ships_no_shuttle::15.5ic]`<br>`test_condition_layer_cell[self_tapeout_pdk_ships_a_shuttle::15.5ic]`<br>`test_condition_layer_cell[shuttle_chip_template_not_fetched::15.5ic]`<br>`test_condition_layer_cell[two_router_files_at_once::15.5ic]`<br>…and 4 more |
| M2 | the same, on 26.5ic | 8 failed, 108 passed, 11 skipped, 2 xfailed in 41.66s | `test_condition_layer_cell[self_tapeout_pdk_ships_no_shuttle::26.5ic]`<br>`test_condition_layer_cell[self_tapeout_pdk_ships_a_shuttle::26.5ic]`<br>`test_condition_layer_cell[shuttle_chip_template_not_fetched::26.5ic]`<br>`test_condition_layer_cell[two_router_files_at_once::26.5ic]`<br>…and 4 more |
| M3 | the same, on 37.5ic | 8 failed, 108 passed, 11 skipped, 2 xfailed in 41.85s | `test_condition_layer_cell[self_tapeout_pdk_ships_no_shuttle::37.5ic]`<br>`test_condition_layer_cell[self_tapeout_pdk_ships_a_shuttle::37.5ic]`<br>`test_condition_layer_cell[shuttle_chip_template_not_fetched::37.5ic]`<br>`test_condition_layer_cell[two_router_files_at_once::37.5ic]`<br>…and 4 more |
| M4 | delete step 37.5ip from the flow | 23 failed, 93 passed, 11 skipped, 2 xfailed in 39.18s | `test_the_matrix_covers_every_path_step_the_flow_declares`<br>`test_condition_layer_cell[self_tapeout_pdk_ships_no_shuttle::37.5ip]`<br>`test_condition_layer_cell[self_tapeout_pdk_ships_a_shuttle::37.5ip]`<br>`test_condition_layer_cell[shuttle_chip_template_fetched::37.5ip]`<br>…and 19 more |
| M5 | re-add `37.5self` as a step (the retired third route) | 2 failed, 114 passed, 11 skipped, 2 xfailed in 40.91s | `test_the_matrix_covers_every_path_step_the_flow_declares`<br>`test_a_step_the_flow_does_not_carry_reads_MISSING_and_never_a_skip` |
| M6 | make `die_finishing_check` exit 0 unconditionally | 6 failed, 110 passed, 11 skipped, 2 xfailed in 40.27s | `test_no_gate_of_a_running_path_step_passes_on_an_empty_tree[self_tapeout_pdk_ships_no_shuttle::26.5ic]`<br>`test_no_gate_of_a_running_path_step_passes_on_an_empty_tree[self_tapeout_pdk_ships_a_shuttle::26.5ic]`<br>`test_no_gate_of_a_running_path_step_passes_on_an_empty_tree[shuttle_chip_template_fetched::26.5ic]`<br>`test_no_gate_of_a_running_path_step_passes_on_an_empty_tree[shuttle_chip_template_not_fetched::26.5ic]`<br>…and 2 more |
| M7 | make `digital_hardmacro_check` exit 2 unconditionally (it can only ever say CANNOT CHECK) | 1 failed, 115 passed, 11 skipped, 2 xfailed in 40.30s | `test_the_gate_of_every_path_step_can_reach_a_RED_verdict[37.5ip]` |
| M8 | give 0.5ic a `condition`, so the unconditioned router can skip | 13 failed, 103 passed, 11 skipped, 2 xfailed in 41.31s | `test_condition_layer_cell[self_tapeout_pdk_ships_no_shuttle::0.5ic]`<br>`test_condition_layer_cell[self_tapeout_pdk_ships_a_shuttle::0.5ic]`<br>`test_condition_layer_cell[shuttle_chip_template_not_fetched::0.5ic]`<br>`test_condition_layer_cell[ip_hardmacro::0.5ic]`<br>…and 9 more |
| M9b | make the two-router contradiction UNDETECTABLE (`_routers_present` sees one where there are two) | 1 failed, 115 passed, 11 skipped, 2 xfailed in 41.47s | `test_two_router_files_at_once_are_refused_and_the_control_is_not` |
| M10 | give step 38 the chip-path condition — i.e. LAND the F3 remedy | 4 failed, 113 passed, 11 skipped, 1 xfailed in 64.67s (0:01:04) | `test_the_matrix_covers_every_path_step_the_flow_declares`<br>`test_exactly_one_step_after_the_IP_terminal_has_no_way_to_not_apply`<br>`test_an_IP_does_not_owe_the_foundry_handoff_kit`<br>`test_the_producer_wiring_of_every_path_step_is_what_it_was_measured_to_be` |
| M11 | wire an unwired producer up (`pad_ring_gen` into phase3_one_shot_runner) | 1 failed, 115 passed, 11 skipped, 2 xfailed in 41.03s | `test_the_producer_wiring_of_every_path_step_is_what_it_was_measured_to_be` |
| M12 | take a wired producer dark (`digital_hardmacro_gen`'s dispatch target renamed) | 1 failed, 115 passed, 11 skipped, 2 xfailed in 41.23s | `test_the_producer_wiring_of_every_path_step_is_what_it_was_measured_to_be` |

### Arms for the F6 repair

Base `0cf908c56`, reddening against a clean 38 passed. Each mutates the THING
the repaired test guards, never the test.

| # | mutation | reddens |
|---|---|---|
| M13 | delete `tapeout_precheck` from 37.5ic's gate | 1 failed, 37 passed — `test_the_flow_declares_this_gate_with_the_path_this_program_writes` |
| M14 | the merge stops delegating (`"tapeout_readiness_check.py"` renamed) | same, 1 failed |
| M15 | the operator arm is written where the flow does not look (`THEIR_ARM_ARTEFACT` changed) | same, 1 failed |

### The arm that found a real weakness in my own test

**M5 reddened nothing on the first pass.** `_path_steps()` derived the path
steps from the `ic`/`ip` id suffix; `37.5self` ends in neither, so re-adding it
— the exact three-route defect this campaign closed — was invisible, and
`test_a_step_the_flow_does_not_carry_reads_MISSING_and_never_a_skip` was
asserting something trivially true. A predicate that cannot fail is worthless.

Fixed in `08d398576`: a step is on a path because its **condition reads a
router artefact**; the suffix is a naming convention and a convention cannot be
what a guard rests on. Both discriminators are kept. `_state()` now resolves
against the WHOLE flow, so MISSING means "the flow does not carry it" rather
than "the subset did not match it".

**M9 was a bad mutation, not a weak test.** Renaming
`RULE_ROUTER_CONTRADICTION` renames both sides of a comparison that reads the
constant — correct behaviour, since pinning the string literal would be worse.
Replaced by M9b, which makes the contradiction **undetectable** rather than
renamed.

---

## 4. A/B against the base, by test id

Both arms run **serially, per file**, in two separate worktrees — the base at
`8a9c5ad9e`, the head at this branch — and re-run from scratch after the
inventory repair below, so neither arm measures a moving tree. Nothing was run
under `-n`.

**Selection.** The delta is ONE new file under `programs/tests/`, so the arm is
the 93 pre-existing modules that could see it: every module that globs
`programs/**.py`, iterates a directory, or names `PROGRAM_INVENTORY` /
`INDEX.md`, plus the ten suites neighbouring the five path steps. The 154
modules that read the flow yaml are NOT in the arm — no flow yaml byte changed.

```
selection                        93 modules
base node ids                  2118
head node ids                  2118
only in base                      0
only in head                      0
OUTCOME CHANGED                   0
base   FAILED 17  PASSED 1977  SKIPPED 124
head   FAILED 17  PASSED 1977  SKIPPED 124
RED SETS IDENTICAL             True
```

The new module itself is additive: **129 node ids**, none of which exist on the
base. Final state `116 passed, 11 skipped, 2 xfailed` — the two xfails are
findings F3 and F4, both `strict=True`.

### The one red this A/B caught, and what was done about it

The FIRST pass of the arm was per-file, and it found:

```
programs/tests/test_program_inventory_no_drift.py
   base: 23 passed
   head: 5 failed 18 passed
```

on a branch that adds exactly one file. Two derived populations stopped being
true — `programs_tree_all_py` 3999 -> 4000 and `test_files` 2708 -> 2709 — and
five stated counts bound to them drifted with them.

Every one of those numbers is GENERATED and the checker names its own repair,
so the repair is to re-run the generator and read the population back, never to
relax the assertion. `gen_program_inventory.py` rewrote
`PROGRAM_INVENTORY.json`; the six bound prose counts have no `--fix` and were
edited line by line from the population it wrote
(`vibe-ic-marketplace/README.md:23,561,565` and
`plugins/vibe-ic/README.md:9,232,246`).
`gen_program_inventory.py --check` now exits 0. **No baseline was written.**

### The 17 reds are pre-existing and identical in both arms

```
  programs/tests/test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged
  programs/tests/test_landing_merge_verdict.py::test_end_to_end_a_green_test_cannot_move_b1_to_another_commit
  programs/tests/test_landing_merge_verdict.py::test_end_to_end_b2_corpus_mutation_is_post_attested_and_norecord
  programs/tests/test_landing_merge_verdict.py::test_end_to_end_candidate_wave_precedes_parallel_isolated_base_wave
  programs/tests/test_landing_merge_verdict.py::test_end_to_end_index_flags_cannot_hide_changed_b1_bytes
  programs/tests/test_landing_merge_verdict.py::test_end_to_end_relinked_parent_selection_is_norecord
  programs/tests/test_landing_merge_verdict.py::test_end_to_end_replace_refs_cannot_redefine_the_verified_tree
  programs/tests/test_landing_merge_verdict.py::test_end_to_end_trusted_verifier_supplies_the_one_bootstrap_evidence
  programs/tests/test_landing_merge_verdict.py::test_interruption_kills_a_term_ignoring_parallel_arm_and_removes_worktrees
  programs/tests/test_landing_merge_verdict.py::test_pid_only_term_kills_a_term_ignoring_b2_and_removes_worktrees
  programs/tests/test_matrix_63x8_census_freshness.py::test_the_census_block_is_fresh
  programs/tests/test_matrix_63x8_census_freshness.py::test_the_generator_cli_can_go_red_and_green
  programs/tests/test_matrix_63x8_census_freshness.py::test_the_published_total_equals_the_live_census
  programs/tests/test_matrix_63x8_ledger.py::test_output_entries_classify_into_the_four_kinds
  programs/tests/test_orphan_scan_reads_the_landing_gate_runner.py::test_the_shipped_audit_no_longer_calls_the_coordinator_unreachable
  programs/tests/test_pytest_per_file_junit.py::test_nested_validated_progress_is_relayed_to_the_outer_session
  programs/tests/test_tapeout_readiness_check.py::test_the_flow_declares_this_gate_with_the_path_this_program_writes
```

Two are worth a sentence.
`test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged` is a
HOST artefact, not a defect: it asserts the refusal "NO \`PIN\` block" and gets
"magic did not complete: watchdog reported launch_error after 0s" — `magic` is
not on this host's PATH. Worth noting that a tool absence renders as FAIL where
this repo's own contract would make it rc=2 / `[CANNOT CHECK]`.

`test_tapeout_readiness_check.py::test_the_flow_declares_this_gate_with_the_path_this_program_writes`
was ON the step this campaign covers, so it was **repaired** (`0cf908c56`) —
see finding F6. It is the one red in the list above that is green at head; the
table is the measurement taken BEFORE that repair, kept because it is what the
A/B actually recorded.

---

## 5. What I could NOT settle

* **F1's correct remedy.** Reading the router file in
  `operator_arm_applicability` closes the self-tape-out case and opens the
  forgot-to-fetch case. I could not find a third reading that closes both with
  the artefacts the flow has today, and I am not confident enough in either
  direction to change a step whose whole value is that its verdict is not one
  we wrote.

* **Whether step 38 should skip or should have an IP-shaped kit of its own.**
  I established that an IP cannot satisfy it and that nothing in the step knows
  the IP path exists. I did not establish which of the two remedies the owner
  wants, and they are not the same change.

* **The blast radius of wiring the three producers (F4).** I measured that they
  are unwired and what follows from it. I did not measure what wiring them
  would do to existing runs, because that needs the corpus, and
  `benchmark-data` is not in this tree (the pre-push benchmark-evidence gate
  reports `--tree benchmark-data is not a directory`).

* **`test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged`**
  fails on **base** and at head identically. It is a host artefact, not a
  defect: the test asserts the refusal message "NO \`PIN\` block" and gets
  "magic did not complete: watchdog reported launch_error after 0s" — `magic`
  is not on this host's PATH. Worth noting that a tool-absence renders as FAIL
  where the repo's own contract would make it rc=2 / `[CANNOT CHECK]`, but that
  is not this branch's scope.

---

## REQUESTS TO THE LANDER

1. **F4 is the one that matters.** Three producers — `submission_template_ingest`,
   `tapeout_declaration_gen`, `pad_ring_gen` — are declared by a step and
   invoked by nothing. The first two write the router file every other path
   step conditions on, so the chip-path repair that landed as v1.11.38 cannot
   fire on any real run. Please decide who wires them and to which runner. The
   strict xfail
   `test_no_path_step_declares_a_producer_that_nothing_can_invoke` XPASSes and
   forces its own removal the moment they are.

2. **Dimension 1 of the 63x8 matrix covers gates only.** Whatever is decided
   about F4, the general gap is that no dimension asks whether a step's
   declared PRODUCERS are dispatchable. That is a matrix-dimension question
   and belongs to the lane that owns it, not here.

3. **F3 — the proposed edit for step 38, if you want it.** LOCAL to step 38's
   block, and it is 37.5ic's chip-path marker verbatim:

   ```yaml
     - id: 38
       condition:
         any_of: true
         files_exist:
           - "input/submission_template/slots/*.yaml"
           - "input/submission_template/SELF_TAPEOUT.txt"
       condition_kind: design_dependent
       name: "Foundry Handoff (mask spec + WAT plan + scribe layout + corner test kit)"
   ```

   Verified as mutation M10. With it applied the xfail XPASSes — the anti-rot
   fires — and **three other tests go red, all of them correctly**, because
   step 38 becomes a path step by this matrix's own derivation:
   `test_the_matrix_covers_every_path_step_the_flow_declares` (38 is not in
   `DECLARED_PATH_STEPS`), `test_exactly_one_step_after_the_IP_terminal_has_no_way_to_not_apply`
   (the owed set becomes `{39}`) and
   `test_the_producer_wiring_of_every_path_step_is_what_it_was_measured_to_be`
   (`foundry_handoff_package_check` enters the producer set). Landing the edit
   means updating those three expectations in the same commit; they are data,
   not logic. **Do not land it without deciding F3's open question first** —
   an IP might deserve an IP-shaped handoff kit rather than a skip.

4. **F1 — a 19th declaration question.** A declared submission target would let
   37.5ic's operator arm tell "there is no operator to ask" from "we never went
   and asked", and would make the brief's two shuttle classes genuinely
   distinct. Structural, so I did not make it.

5. **No protected path is touched.** The branch adds one file under
   `programs/tests/` and edits nothing else, so
   `tools/ci/protected_landing_transition.json` needs no change and I have no
   sha256 to hand you.

6. **`git push` needs the tracked hook on this host.** `.git/hooks/pre-push`
   symlinks to the main checkout's copy, which was 646 commits behind
   `origin/main` and still runs the benchmark-evidence gate that moved to
   `gatekeeper-land.sh`. Pushed with
   `git -c core.hooksPath=tools/git-hooks push`; the tracked hook passes.
