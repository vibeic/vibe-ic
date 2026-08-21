# jrunner2 — the Phase-3 runner's three honesty defects, and the duplicated timing row

Branch: `agent/jrunner2-phase3-runner-honesty`
Base: `origin/main` @ `e36d81c0a` (v1.11.33), fetched at the start of this lane.
Design under measurement: the `spm` run trees left by the `jppae2e` lane
(`run/baseline` + `run/trials/t000..t059`, sky130A). Nothing in those trees was
written to; every re-measurement wrote into this lane's own `proof/` directory.

Five commits, four fixes and two generated-file regenerations:

```
95afe941e  F-7   power sign-off links the routed netlist
175b52e39  F-6   both multi-corner sign-off reports stamp STA_BASIS
a60b545ac  F-14  the emitted power deck is run-root-relative + the guard
c79e8575b  F-10  declared-mirror collapse in the timing reader
9a5e1045f  chore PROGRAM_INVENTORY.json regenerated once, on the final tree
<index>    chore programs/INDEX.md regenerated for the new program
```

---

## F-7 — the power number was computed on the PRE-PnR netlist

### What was wrong

`_emit_power_report` served two callers from ONE body that linked
`<top>_synth.v` unconditionally:

* the Step-10 pre-layout power PREVIEW, for which that is correct;
* the Step-33 SIGN-OFF report, whose generated header said
  *"values reflect the post-PnR netlist"*.

```
$ grep -E 'read_verilog|read_spef' run/baseline/reports/phase3/power_spm.tcl
read_verilog /…/run/baseline/phase2/stage2/synth/spm_synth.v
(no read_spef)
```

### What I changed, and why it is the session and not the header

The sign-off call site passes `basis="post_pnr"`; the session then links
`<top>_pnr.v` and reads `phase3/stage3/extracted/<top>.spef`. Every line of the
header — `netlist:`, `spef:`, `basis:`, and the Substance paragraph — is now
DERIVED from what the session opened. Editing the header to say "pre-PnR"
instead would have made the document honest and the measurement useless.

The report also carries its own stamp, in the vocabulary `_sta_basis` already
normalises, so no consumer needs a second table:

```
POWER_BASIS: POST_ROUTE_SPEF | POST_ROUTE_NO_SPEF | PRE_LAYOUT_ESTIMATE
POWER_BASIS_NETLIST: <name>
POWER_BASIS_SPEF: <name or "none (netlist-only)">
```

Degrades loudly: `post_pnr` asked for with no routed netlist on disk falls back
to the synth netlist, stamps `PRE_LAYOUT_ESTIMATE`, notes the fallback, and
puts no post-route claim anywhere in the header.

### The proof — it moves, and the clock stops being zero

Driven with the runner's OWN emitter, in the runner's own container, over the
same 60 place-and-route configurations. Commands:

```
$ python3 proof/drive_power.py <plugin>/programs $(ls -d run/trials/t0*) proof/fixed_arm.json
$ md5sum run/trials/t0*/reports/phase3/power.rpt | awk '{print $1}' | sort | uniq -c
```

| | shipped `power.rpt` (pre-fix) | re-measured with the fix |
|---|---|---|
| distinct report digests over 60 configs | **1 of 60** | **60 of 60** |
| total power | 0.306 mW, invariant | 0.546 – 0.616 mW, **39 distinct values**, 12.8 % spread |
| clock group | **0.000 mW (0.0 %)** on all 60 | 0.184 – 0.222 mW; **rows reading exactly zero: 0** |
| baseline tree, total | 0.306 mW | 0.573 mW → **1.873×** |

For the record, the input side: over the same 60 trials the routed netlists are
60 distinct files and the SPEFs are 60 distinct files, while the synth netlist
is **1**. That is why no PnR knob could move the published figure.

### Mutation arm

`programs/tests/test_phase3_power_signoff_links_the_routed_netlist.py`, 9 tests.

* on this branch: **9 passed**
* on `origin/main` (`e36d81c0a`), same file: **7 failed, 2 passed**

The two that pass are the reverse controls — the pre-layout preview still links
the synth netlist and reads no SPEF — and they are supposed to pass on both
arms. The helper passes `basis` only when the emitter accepts it, deliberately:
otherwise every test would redden with `TypeError: unexpected keyword argument`
and prove that the signature changed rather than that the measurement was
wrong. The pre-fix failures are on the measurement:

```
AssertionError: the SIGN-OFF power session must link the netlist that was routed.
  It linked: …/phase2/stage2/synth/dut_synth.v
AssertionError: the Substance paragraph must be DERIVED from the linked inputs,
  not a literal claim that survives a change of netlist
AssertionError: two place-and-route configurations produced the same measurement
  input, so no PnR knob can move this number
```

---

## F-6 — the two multi-corner sign-off reports carried no `STA_BASIS`

Checked first, as the brief asked: `git log origin/main -- …/phase3_one_shot_runner.py`
shows the most recent touch is `0b1e2029a` (v1.11.30) and no lane had stamped
these emitters. The grep on `e36d81c0a` reproduced the finding exactly.

### What I changed

Both emitters stamp **per stanza**, not per file:

* `_emit_corner_spef_sta` → `sta_spef_multicorner.rpt` (RC corners)
* `_emit_mcorner_ocv_sta` → `sta_mcorner_ocv.rpt` (PROCESS corners)

Per stanza is not a detail. The process-corner report's SETUP stanza reads the
SLOW liberty and its HOLD stanza reads the FAST one, so a file-level stamp
copied from the single-corner emitter would be wrong for one of them. Each
stanza names its own `STA_BASIS`, `STA_BASIS_LIBERTY`, `STA_BASIS_NETLIST` and
`STA_BASIS_SPEF`, all derived: `PRE_LAYOUT_ESTIMATE` when the routed netlist is
absent, `POST_ROUTE_NO_SPEF` when that stanza issues no `read_spef`. All three
values already exist in `_ppa/timing._STAGE_BY_STAMP`.

`_ppa/timing._stage_for`'s docstring quoted the pre-fix grep as current. Its
behaviour is unchanged and should be — an unstamped report must still degrade
loudly — but the quote is now history and the docstring says so.

### The proof — measured downstream, on the real tree

`_ppa/timing.py <tree> --json` over a copy of `run/baseline`:

| arm | rows | `scope.stage = null` | staged |
|---|---|---|---|
| `origin/main` | 56 | **48** | 8 `post_route_extracted` |
| + F-10 only | 28 | 24 | 4 |
| + F-10 + F-6 | 28 | **0** | 28 `post_route_extracted` |

48-of-56 is exactly the number the finding reports. **Scaffolding disclosed:**
re-running place-and-route to regenerate stamped reports is a 40-minute job, so
for this measurement the four stamp lines were injected into a COPY of the two
reports using the emitters' own f-string output and nothing else was edited.
The emitters themselves are covered by the test below, which reads the TCL they
actually write.

### Mutation arm

`programs/tests/test_multicorner_signoff_reports_declare_their_stage.py`, 6 tests.

* on this branch: **6 passed**
* on `origin/main`: **6 failed**

Including `test_the_one_shipped_reader_resolves_both_reports_to_a_stage`, which
runs the emitted stanza payloads through `_sta_basis.declared_basis` — the ONE
shipped reader — and gets `POST_ROUTE` instead of `None`.

No regression in the neighbourhood: `test_multi_corner_sta_basis.py`,
`test_tapeout_signoff_p1_multicorner.py`,
`test_multi_corner_sta_unlinked_is_not_clean.py`,
`test_spef_sta_times_the_setup_signoff_corner.py`,
`test_ppa_runner_extraction_ledger.py` → 37 passed.

---

## F-14 — absolute host paths in the emitted analysis scripts

### The measured population, and what I did and did not convert

```
$ python3 programs/emitted_script_portability_check.py run/baseline
[FAIL] 26 of 30 emitted script(s) hard-code a path inside the run root
```

I converted **one**: `reports/phase3/power_<top>.tcl`, the analysis
configuration the finding names and the one this lane already owns after F-7.
The other 25 are listed under REQUESTS TO THE LANDER. Converting them means
editing two dozen emitters spread through a 41,000-line file that several lanes
are editing today, and the brief's own caution says a large edit does not
rebase silently. I would rather hand over a working mechanism plus an honest
census than a branch that cannot land.

### The mechanism

```tcl
set RUN_ROOT [file normalize [file join [file dirname [info script]] .. ..]]
read_verilog $RUN_ROOT/phase3/stage3/pnr/spm_pnr.v
read_spef    $RUN_ROOT/phase3/stage3/extracted/spm.spef
read_liberty /foss/pdks/…/sky130_fd_sc_hd__tt_025C_1v80.lib      # untouched
```

`info script` is set by the `source` that `sta -no_init -exit <file>` performs
— verified directly in the pinned image before writing any of this — so the
same deck resolves under an identity bind-mount and under a canonical one.
The `..` count is computed from where the deck is written, never assumed.

**The rule the checker enforces:** an absolute path INSIDE the run root is a
finding; one OUTSIDE it is not. A path inside names something this run produced
and the run tree moves. A path outside names the environment and is already
portable across every host running the same image — flagging it would make the
check unpassable and therefore ignored.

**One predicate, two consumers.** `emitted_script_portability_check.host_paths_in`
is the only definition; the CLI sweeps a tree with it and the emitter calls it
on the deck it just wrote, noting loudly in the run if a run path ever returns.

### The proof — it re-runs elsewhere, and the old one did not

```
$ sha256sum treeA/reports/phase3/power_spm.tcl treeB/reports/phase3/power_spm.tcl
cc00aed3…  treeA/…      cc00aed3…  treeB/…          # byte-identical
```

Tree B is a copy of the same run whose routed netlist was then replaced with a
different one from the same run. Same deck, run in both places:

| | Clock leakage | which tree it actually read |
|---|---|---|
| portable deck sitting in tree B | 1.59e-10 | **tree B** — correct |
| hard-coded deck sitting in tree B | 6.32e-09 | **tree A** — the original |
| tree A reference | 6.32e-09 | tree A |

The hard-coded deck did not error. It produced a full report of the wrong tree.

### Positive / negative / vacuous / bad invocation

| exit | meaning | pinned by |
|---|---|---|
| 0 | every deck in scope is portable | `test_a_portable_deck_passes`, `test_a_pdk_path_outside_the_run_root_is_not_a_finding` |
| 1 | a deck hard-codes a path inside the run root | `test_the_real_defect_goes_red`, `test_one_bad_deck_among_good_ones_is_still_a_finding` |
| 2 | `[CANNOT CHECK]` — nothing in scope | `test_no_script_in_scope_refuses_rather_than_passing`, `test_staged_inputs_are_not_in_scope_and_alone_are_vacuous` |
| 3 | bad invocation | `test_a_project_that_is_not_a_directory_is_rc3`, `test_an_under_scope_that_does_not_exist_is_rc3_not_a_pass` |

### Mutation arm

`programs/tests/test_emitted_script_portability_check.py`, 13 tests.

* on this branch: **13 passed**
* on this branch with **only F-14 reverted** (`175b52e39` + the new files):
  **2 failed, 11 passed** — `test_the_power_deck_spells_in_tree_paths_against_run_root`
  and `test_a_run_path_reaching_the_deck_is_noted_loudly`.

The per-commit arm is the honest one: measured against plain `origin/main` a
third test also reddens, but for F-7's reason (the pre-fix deck links the synth
netlist), which would over-credit this fix.

### Declared BLOCKING or ADVISORY

**Neither yet, and that is deliberate.** The checker is a standalone program
with real exit codes and the emitter self-checks the one deck it owns. It is
NOT wired as a flow gate, because a gate that reports 25 findings on every run
is a gate people learn to skip. Wiring it belongs with the conversion of the
remaining 25 — see REQUESTS TO THE LANDER.

---

## F-10 — every timing row emitted twice, from byte-identical files

### Where it is fixed, and why

**Not in the emitter.** Both locations are load-bearing. Five shipped checkers
read the `reports/phase3/` copy —

```
achieved_period_recorded_check.py:79-81
sta_corner_record_completeness_check.py:212,217,222
drv_promotion_corroboration_check.py:63
post_route_signoff_corner_check.py:147
eco_status_gen.py:96
```

— and the step writes the `phase3/stage3/sta/` one. Dropping either breaks a
consumer. (`test_matrix_d7_outputs_list_complete.py:402` separately pins that
the mirror is declared by no STEP, which is consistent: it is a publication,
not a step output.)

**Not by content hash either**, and this is the constraint the brief sets. A
genuine second measurement that happens to agree to the byte is a real reading
of a real artefact; collapsing it by digest would erase evidence — the same
silence this whole lane exists to remove. Identical bytes are not proof of a
copy.

**So: the run declares its own copies.** The step making the copy is the only
thing that knows it is a copy. `_publish_artefact_mirror` writes the copy
byte-exactly and records it:

```json
{"schema": "vibeic.artefact_mirrors.v1",
 "mirrors": [{"mirror": "reports/phase3/sta_spef_based.rpt",
              "of": "phase3/stage3/sta/sta_spef_based.rpt",
              "sha256": "sha256:baa1a53d…",
              "declared_by": "_emit_spef_sta"}]}
```

`_ppa/timing.collapse_declared_mirrors` collapses a pair ONLY when the run
declared it AND both files still match the digest recorded at copy time. Two
byte-identical artefacts nobody declared still produce two sets of rows.

Degrades loudly and unchanged-by-default: no manifest → nothing collapsed, so
an older run tree keeps exactly today's answer; a mirror that has diverged from
its source → not collapsed, with a note saying they are two contents and
therefore two facts.

### The proof, on the real tree

```
$ python3 programs/_ppa/timing.py <copy of run/baseline> --json out.json
```

| | rows | measured | (metric, scope) groups | groups with >1 record |
|---|---|---|---|---|
| pre-fix | 56 | 44 | 20 | **20** |
| post-fix | 28 | 22 | 20 | **4** |

The residual 4 are **F-10b**, a different finding: `worst_path_slack_ns` emitted
once per reported PATH under one scope — measured here as exactly three values
per view, e.g. `[5.20, 5.32, 5.36]` for `process=tt, rc_corner=max`. No mirror
collapse can or should touch it; it needs the scope to name the path.

### Mutation arm

`programs/tests/test_declared_mirrors_are_not_a_second_measurement.py`, 9 tests.

* on this branch: **9 passed**
* on this branch with **only F-10 reverted** (`a60b545ac`): **7 failed, 2 passed**

The 2 that pass are exactly the controls that must hold on both arms:
`test_two_identical_artefacts_that_are_not_declared_mirrors_both_count` (the
rule a hash-based collapse fails) and `test_without_a_manifest_nothing_is_collapsed`
(an old run tree keeps its answer).

---

## The by-TEST-ID A/B against the base

Selection: the 80 shipped test modules that name any symbol this branch
touches (`_emit_power_report`, `_emit_corner_spef_sta`, `_emit_mcorner_ocv_sta`,
`_emit_spef_sta`, `STA_BASIS`, the three report basenames,
`pre_pnr_power_preview`, `artefact_mirrors`, `PROGRAM_INVENTORY`, `_ppa`,
`_publish_artefact_mirror`, `_run_root_tcl_path`,
`emitted_script_portability`). This branch's four NEW modules are excluded —
they are the mutation arms, reported above.

Run SERIALLY (`-p no:randomly`, no `-n`, `--timeout=600`), one arm after the
other on an idle host (load 0.39, 115 GB available, 32 cores), because a red
produced under `-n` by a tree-mutating test racing a tree-reading one is not
a red.

```
base  /home/reyerchu/_jrunner2/mut  @ e36d81c0a   7 failed, 1863 passed, 10 skipped, 6 xfailed   147.86s
head  /home/reyerchu/_jrunner2/wt   @ this branch 7 failed, 1863 passed, 10 skipped, 6 xfailed   149.78s

$ diff <(grep ^FAILED base.log|sort) <(grep ^FAILED head2.log|sort)
IDENTICAL RED SET
```

Collected node IDs compared as sets, not counts:

```
$ diff base.nodes head.nodes      # 1886 each
NODE ID SETS IDENTICAL
```

The 7 reds, all present on clean `origin/main` before this branch existed:

```
test_matrix_d2_falsifiable.py::test_d2_gate_has_a_reachable_fail[step1.6x]
test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step31]
test_matrix_d7_outputs_list_complete.py::test_every_cell_lands_in_exactly_one_state
test_program_inventory_no_drift.py::test_stated_counts_in_the_documents_match_the_tree
test_program_inventory_no_drift.py::test_check_mode_exits_zero_on_the_committed_tree
test_program_inventory_no_drift.py::test_clean_tree_reports_no_failure
test_program_inventory_no_drift.py::test_declared_non_counts_are_still_present[and all 56 EDA/device tools]
```

The four `test_program_inventory_no_drift` reds are README.md count drift
(`states 1208 for programs_top_level, tree has 1224`, `states 2644 for
test_files, tree has 2689`) that predates this branch. I did not fix them: they
are somebody's stated counts across `README.md`, and sweeping them in would put
another lane's drift in this diff.

**One red this branch DID introduce, and fixed:**
`test_program_inventory_no_drift.py::test_catalogued_agrees_with_the_shipped_index`
— INDEX.md said 1150 catalogued programs and the tree held 1151. Regenerated
with `tools/gen_programs_index.py`; the delta is one row plus the two counters
that follow from it.

`programs/plugin_full_audit.py .` on this branch: **D1 PASS** (1224 programs;
44 synth overlay-covered), **D2 PASS**.
`programs/tests/test_checker_execution_wiring_audit.py`: 40 passed.

Both generated files were regenerated by their generators, never hand-edited,
and each is regenerated exactly once on the final tree — the collateral-revert
pre-push gate caught my first attempt, which regenerated `PROGRAM_INVENTORY.json`
in two commits of one push, and it was right to.

---

## What I could NOT settle

1. **The other 25 emitted scripts still carry host paths.** Named below.
   Measured, not estimated, and not converted for the rebase-safety reason
   above.

2. **F-14's checker is not wired into the flow.** It has exit codes, tests and
   a real defect it goes red on, but no step calls it. Wiring it before the 25
   are converted produces a gate that is red on every run.

3. **F-10b is untouched** — `worst_path_slack_ns`, three values per view under
   one scope. It is a distinct finding with a distinct remedy (the scope must
   name the path) and it is not in this brief.

4. **F-6's downstream effect was measured with hand-injected stamps** on a copy
   of a pre-fix run tree, because regenerating stamped reports needs a full
   place-and-route. The strings injected are the emitters' own output; the
   emitters are covered by tests that read the TCL they write. A full re-run
   would upgrade this from "the reader stages 28 of 28 rows given these
   stamps" to "the flow produces these stamps end to end".

5. **`_emit_power_report`'s two ratchets, checked but not exercised end to
   end.** The new module-level helpers (`_publish_artefact_mirror`,
   `_emitted_script_root_tcl`, `_norm_abs`, `_path_is_under`,
   `_run_root_tcl_path`) carry no PPA vocabulary token, so
   `test_ppa_runner_extraction_ledger` needed no ledger entry — verified by
   running it (37 passed in the neighbourhood run), not by reading the rule.

---

## REQUESTS TO THE LANDER

1. **No protected path was touched.** `tools/ci/repo_hygiene_gates.sh` and the
   rest of `protected_landing_transition.json` are untouched by this branch;
   `git diff --name-only origin/main..HEAD` is six files, all under
   `vibe-ic-marketplace/plugins/vibe-ic/programs/` plus this RESULT.md.

2. **Two generated files are in the diff** — `programs/PROGRAM_INVENTORY.json`
   and `programs/INDEX.md`. Both are the generators' own output on this tree
   (`gen_program_inventory.py`, `tools/gen_programs_index.py`). If this branch
   is batched with another that also adds programs or tests, **re-run both
   generators on the merged tree and take their output** rather than resolving
   either conflict by hand — neither side's counters will be right.

3. **The 25 unconverted emitted scripts**, measured on `run/baseline`:

   ```
   phase3/stage3/eco/eco_timing_repair.tcl                    12
   phase3/stage3/extracted/extract_<top>.tcl                   2
   phase3/stage3/extracted/si_mcf/si_mcf_sta_mcf_hold.tcl      3
   phase3/stage3/extracted/si_mcf/si_mcf_sta_mcf_setup.tcl     3
   phase3/stage3/extracted/si_mcf/si_mcf_sta_nominal.tcl       3
   phase3/stage3/extracted/si_mcf/si_mcf_windows.tcl           4
   phase3/stage3/extracted/si_timing_<top>.tcl                 5
   phase3/stage3/extracted/spef_corners/extract_corners_*.tcl  4
   phase3/stage3/pnr/metal_fill_<top>.tcl                      2
   phase3/stage3/pnr/pnr.tcl                                  39
   phase3/stage3/pnr/signoff_spef_repair.tcl                  10
   phase3/stage3/sim_postlayout/sdf_<top>.tcl                  4
   phase3/stage3/sta/per_corner/sta_{FF,SS,TT}.tcl             6 each
   phase3/stage3/sta/power_<top>.tcl                           2
   phase3/stage3/sta/sta_mcorner_ocv_{hold,setup}.tcl         12 each
   phase3/stage3/sta/sta_spef_based.tcl                       12
   phase3/stage3/sta/sta_spef_{setup,hold}.tcl             13 / 12
   reports/phase3/aging_sta_<top>.tcl                          3
   reports/phase3/dynamic_ir_transient.tcl                     2
   reports/phase3/erc_<top>.tcl                                1
   reports/phase3/ir_em_<top>.tcl                              2
   ```

   The mechanism is in place and each conversion is the same three-line change
   (`_emitted_script_root_tcl` in the prologue, `_run_root_tcl_path` for the
   in-tree paths, the post-write `_esp.host_paths_in` note). It is a good
   candidate for a dedicated lane that owns the whole file for one pass; done
   piecemeal across lanes it will conflict with everything.

4. **Wire `emitted_script_portability_check` once the 25 are converted**, and
   declare it BLOCKING then. Until then it is a program you can run by hand;
   I have deliberately not made it a gate that is red on every run.

5. **`test_program_inventory_no_drift` has 4 pre-existing reds on main**
   (README.md stated counts vs the tree, and one retired "not a count"
   sentence). Not mine, not fixed here, and they will still be red after this
   lands. They are a one-line regeneration plus a `_NOT_A_POPULATION_COUNT`
   decision that belongs to whoever owns README.md's counts.
