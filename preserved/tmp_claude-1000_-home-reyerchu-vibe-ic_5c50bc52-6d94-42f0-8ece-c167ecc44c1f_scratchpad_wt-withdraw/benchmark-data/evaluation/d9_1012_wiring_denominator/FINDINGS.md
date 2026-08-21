# vibe-ic#1012 — the D9 denominator, before and after the wiring test got honest

`tools/d9_corpus_baseline.py::discover_checkers` decided "the flow already
drives this program" with a bare substring test over the flow-YAML **text**.
That test defines the **denominator** of the published D9 baseline, so anything
that put a program's name anywhere in that file removed the program from the
measured population.

This directory is the re-measurement. Both sweeps were run **this turn**, on the
**same corpus**, at the same repo state, with the only difference being the
wiring test:

| | rule | command |
|---|---|---|
| BEFORE | `p.stem in flow_yaml.read_text()` | `origin/main` @ `080bf6d0` |
| AFTER | first token of each gate-clause command string | this branch |

```
python3 tools/d9_corpus_baseline.py --out <dir> --jobs 16
```

Both sweeps ended with the corpus tripwire green — `benchmark-data is pristine
across 17493 tracked file(s)`. Nothing here repaired a checker, wired anything
into `flow/phase1_phase2_phase3.yaml`, or changed a verdict.

---

## 1. THE HEADLINE, RESTATED. It got worse.

|  | BEFORE | AFTER |
|---|--:|--:|
| published run dirs | 107 | 107 |
| checkers (measurable + not) | 72 + 1 = **73** | 86 + 1 = **87** |
| cells | 7704 | 9202 |
| CLEAN | 2070 | 2358 |
| FINDING | 706 | 891 |
| NO-INPUT | 4604 | 4872 |
| ERROR | 324 | 1081 |
| **RED (FINDING + ERROR)** | **1030 / 7704 = 13.37 %** | **1972 / 9202 = 21.43 %** |

**The published D9 baseline's would-redden rate rises from 13.37 % to 21.43 %
of cells, and the checker population from 73 to 87.**

Nothing got worse in the corpus. The ruler got honest. Fourteen checkers that
the flow does not gate had been silently deleted from the population by a
substring hit, and twelve of them are red on published runs. Stating the smaller
number was never a measurement of safety; it was a measurement of which program
names happened to appear in a YAML comment.

### The decomposition, so nobody reads ERROR as "found something"

|  | BEFORE | AFTER |
|---|--:|--:|
| ERROR (could-not-measure) | 324 = 4.21 % | 1081 = **11.75 %** |
| content-derived cells (CLEAN + FINDING) | 2776 | 3249 |
| FINDING / content-derived | 25.43 % | **27.42 %** |

Two thirds of the RED increase (757 of 942 new red cells) is **ERROR**, not
FINDING — mostly programs whose CLI refuses a run-dir positional (§3). Those
belong in the denominator by this instrument's own rule (*"a checker that cannot
run in this environment is reported as ERROR with its reason and stays in the
denominator"*), and each one is a standing invitation to add a bespoke arg-shape
entry so it can be measured for real. The **content-derived** finding rate,
which is the number that is actually about the designs, moves 25.43 % → 27.42 %.

---

## 2. POPULATION DIFF, BOTH DIRECTIONS

```
BEFORE 73  ->  AFTER 87        ENTER 14        LEAVE 0
```

**LEAVE = 0.** Not one checker drops out. The correction is purely additive, so
every AFTER number is the BEFORE number plus the fourteen entrants — no
re-attribution, no offsetting movement.

**And measured, not assumed:** of the 72 checkers measured in *both* sweeps,
**72 / 72 have byte-identical per-bucket tallies.** The two sweeps disagree
about nothing except which checkers exist. (This is the property unconditional
per-cell isolation is supposed to buy, tested here as a side effect.)

Full populations: `population_diff.json` → `before.population`,
`after.population`. Rendered tables: `corpus_baseline_BEFORE.md`,
`corpus_baseline.md`.

### Against the *published* `d9_corpus_baseline.md` (78 checkers)

The published table predates PR #1006/#1013, so it is a third point, not the
BEFORE arm:

* **enters (12)** — the same 14 minus `l20_dft_scan_topology_actionable_check`
  and `lec_run`, which the published table already had (the comment that hid
  them did not exist yet).
* **leaves (3)** — `l6_fsm_scaffold_actionable_check`,
  `l9_submodule_conformance_check`, `step_internal_fail_bubble_up_check`. All
  three were genuinely wired by #1006/#1013 in the interval. Correct departures.

**Cross-check, unplanned and load-bearing.** Where the corrected instrument and
the pre-#1006 published table overlap on a checker the comment later hid, the
cells are *identical*:

| checker | published (pre-#1006) | this turn (corrected) | identical |
|---|---|---|---|
| `l20_dft_scan_topology_actionable_check` | 55 FINDING / 3 CLEAN / 49 NO-INPUT | 55 / 3 / 49 | ✅ |
| `lec_run` | 107 ERROR | 107 ERROR | ✅ |

So the fix restores exactly what the comment removed, and adds nothing to those
rows.

---

## 3. THE FOURTEEN ENTRANTS — cells, and why each was excluded

RED = FINDING + ERROR. Out of 107 published runs each.

| checker | RED | FINDING | ERROR | CLEAN | NO-INPUT | why the substring test hid it |
|---|--:|--:|--:|--:|--:|---|
| `design_one_shot_runner` | 107 | 100 | 7 | 0 | 0 | comments only (8 lines) |
| `fault_atpg_run` | 107 | 0 | 107 | 0 | 0 | `programs:` roster + substring of `transition_/path_delay_fault_atpg_run` |
| `lec_run` | 107 | 0 | 107 | 0 | 0 | one comment (line 4255) |
| `path_delay_fault_atpg_run` | 107 | 0 | 107 | 0 | 0 | `programs:` roster (line 2885) |
| `phase3_one_shot_runner` | 107 | 0 | 107 | 0 | 0 | comments + a `notes:` block (23 lines) |
| `si_mcf_sta` | 107 | 0 | 107 | 0 | 0 | **prefix** of the wired `si_mcf_sta_check`; also a path arg |
| `signoff_audit` | 107 | 0 | 107 | 0 | 0 | **path argument** `reports/analog/mixed_signal/signoff_audit.json` |
| `transition_fault_atpg_run` | 107 | 0 | 107 | 0 | 0 | `programs:` roster (line 1693) |
| `l20_dft_scan_topology_actionable_check` | **55** | 55 | 0 | 3 | 49 | **the reported defect** — one comment (line 4294) |
| `phase1_doc_one_shot_runner` | 17 | 17 | 0 | 5 | 85 | comments only (lines 158, 1821) |
| `formal_property_run` | 13 | 13 | 0 | 0 | 94 | `programs:` roster (line 954) |
| `sdc_gen` | 1 | 0 | 1 | 83 | 23 | comments only (lines 304, 413) |
| `analog_hardmacro_gds_emit` | 0 | 0 | 0 | 90 | 17 | `programs:` roster (line 2113) |
| `phase1_structured_field_substance_check` | 0 | 0 | 0 | 107 | 0 | one comment (line 387) |
| **total (14 × 107 = 1498 cells)** | **942** | **185** | **757** | **288** | **268** | |

Every one of the fourteen was adjudicated by hand against the YAML: **not one is
the first token of any gate-clause command string.** Six distinct
non-wiring shapes were found, of which only the first was reported:

1. **a comment** — #1012's own shape, and 9 of the 14;
2. a `notes:` prose block;
3. a step-level `programs:` roster entry (5 of the 14 — see §5);
4. a **path argument** inside an otherwise-wired command
   (`mixed_signal_signoff_check . --json reports/…/signoff_audit.json`);
5. a **prefix** of a wired program name (`si_mcf_sta` ⊂ `si_mcf_sta_check`);
6. a **substring of another roster entry** (`fault_atpg_run` ⊂
   `transition_fault_atpg_run`).

### The ERROR reasons, stated rather than counted

* 6 checkers × 107 = 642 cells: **argparse refuses the run-dir positional**
  (`fault_atpg_run`, `lec_run`, `path_delay_fault_atpg_run`, `si_mcf_sta`,
  `signoff_audit`, `transition_fault_atpg_run`). Each carries argparse's own
  message. These are the bespoke-arg-shape table's next entries.
* `phase3_one_shot_runner` × 107: `rc 4 — phase3 PDK resolution REFUSED —
  silent wrong-PDK fallback`. A refusal, not a crash, but rc 4 is outside the
  instrument's tier map, so it lands in ERROR with its reason.
* `design_one_shot_runner` × 7: timed out at 120 s.

---

## 4. THE PAIRED GUARD

The #1006 comment block that names the held checker **also** names
`l6_fsm_scaffold_actionable_check` and `l9_submodule_conformance_check`. Under
the defect all three were excluded because their names appeared in text; for l6
and l9 that happened to be the right answer, because both are *also* genuinely
wired.

After the fix both are **still** excluded — now because
`advisory_program_exit_zero: "l6_fsm_scaffold_actionable_check ."` (line 340) and
`advisory_program_exit_zero: "l9_submodule_conformance_check ."` (line 686)
really do invoke them. Asserted in
`tools/test_d9_corpus_baseline.py::TestWiringIsStructuralNotTextual::test_genuinely_wired_neighbours_stay_wired`,
which anchors on a **non-empty** population so it cannot be satisfied by a
predicate that stops counting real clauses too.

---

## 5. THE ONE JUDGEMENT CALL, STATED

Five of the fourteen entrants are named in a step-level `programs:` roster and
nowhere else. A roster entry is structural, not prose — so excluding it is a
*second* decision, separate from "a mention is not a wiring", and it moves the
population by 5.

**It is not wiring, and the reason is this instrument's own output column:**
"would redden **if promoted to BLOCKING**". A roster declares what a step runs;
it is not a gate that can fail. A program named only there is exactly a checker
the flow does not enforce — the population this baseline exists to size.

It is also not a new *class* of entrant. Producers already populate the
published baseline (`lec_run`, `qsf_gen`, `analog_mc_yield_run`,
`l21_to_upf_emit`, `spec_declaration_emit`, `waiver_template_gen`,
`ip_catalog_pull`, `signoff_ladder_run`, `regmap_transaction_tb_gen`,
`benchmark_run_manifest`). Keeping the roster-only five is consistent with that,
not an expansion of scope.

Measured both ways, so the cost of the call is on the record and not hidden:

| rule | population |
|---|--:|
| substring over text (BEFORE) | 73 |
| gate clauses only (**AFTER, adopted**) | **87** |
| gate clauses + `programs:` rosters | 82 |

The adopted rule is the one that makes the denominator **larger**. It was not
chosen because it flatters anything.

---

## 6. WHAT THE CORRECTION EXPOSED IN THE INSTRUMENT ITSELF

The first sweep over the corrected population **died at cell 8500 of 9202**:

```
OSError: [Errno 39] Directory not empty: 'reports'
```

raised out of `TemporaryDirectory.__exit__` inside a worker.
`subprocess.run(timeout=…)` kills the direct child and nothing below it — which
was survivable only while the substring test was excluding every runner-class
program in the directory. The writer census says the same thing from the other
side: checkers observed writing into the run they judge went from **8 → 15**,
and all seven new writers are entrants.

Fixed at three layers (root cause: own process group, signalled as a group;
containment: cleanup returns a reason instead of raising; blast radius: a worker
exception is one ERROR cell, not a dead sweep). The re-run completed 9202/9202
with **0 leaked scratch copies** and the corpus tripwire green.

---

## 7. Regenerate

```
python3 tools/d9_corpus_baseline.py \
    --out benchmark-data/evaluation/d9_1012_wiring_denominator --jobs 16
```

Every figure above is derived from `corpus_baseline.json` (this sweep) and the
BEFORE sweep's own JSON; none is typed from memory. The BEFORE column is a
record of what `origin/main` @ `080bf6d0` measured and is deliberately **not**
maintained — re-deriving it later would destroy the record of what was measured
here.
