# `reports/spare_cell_coverage.json` — the declaring producer

- **Date**: 2026-08-22
- **Base**: `origin/main` `ae78abb28` (v1.11.70). Authored on `a4caccefe` (v1.11.69)
  and rebased when the batch in flight landed 673 commits. Neither of the two upstream
  commits touching a file this change edits goes near it: `bef9ee4e7` edits comments
  elsewhere in `flow/phase1_phase2_phase3.yaml` and leaves step 18's declaration
  untouched, `9e7f738cf` edits `phase3_one_shot_runner.py` outside the spare block.
  The rebase was clean and every figure below was re-measured on `ae78abb28`.
- **Ledger row**: `only_the_declaring_step_writes_its_output` — a live FAIL, deliberately
  recorded rather than repaired, because "fixing the clobber ALONE would turn the cell
  green while leaving the real gap invisible."

## Decision

**`spare_cell_coverage_check` is the declaring producer of
`reports/spare_cell_coverage.json`. `phase3_one_shot_runner`'s write of that path is
removed.**

This is shape 1 of the three that were open. It is **not** shape 3: the two writers were
checked first, on real runs, and they do not carry two different measurements — every
field the runner's payload held is already in `phase3/stage3/pnr/spare_cells.json`, the
runner's own declared artefact. The name is not the defect. The second write is.

Paired with it, and inseparable from it:

**`spare_cell_coverage_check` no longer reads the path it writes.** Its
`actual_density` now comes only from `spare_cells.json`.

The two halves land together because the second one is only reachable once the first
lands. That is what the ledger row was protecting.

## Why the checker, and not the runner

Four independent things name the checker for this path, and nothing names the runner.

**1. The flow declares it.** Step 18 of `flow/phase1_phase2_phase3.yaml`:

```yaml
  - id: 18
    name: "Spare-cell + ECO-prep insertion (Design-for-ECO)"
    programs:
      - spare_cell_coverage_check
    required_outputs:
      - "phase3/stage3/pnr/spare_cells.json"
      - "reports/spare_cell_coverage.json"
```

One step, two declared outputs, one declared program. The runner produces the first;
the checker is the only program declared for the second.

**2. The release-gating tier reads it under that name, and reads one field.**
`benchmark_verify_report` Pillar 6:

```python
cov = _load_json(project / "reports" / "spare_cell_coverage.json")
cov_pass = bool(cov) and str(cov.get("status", "")).upper() == "PASS"
```

and its own header says the path is *"from `spare_cell_coverage_check.py`, readiness"*.
It grades `status` and nothing else, so it cannot tell the two writers apart. With two
writers the sign-off was whichever ran last.

**3. The corpus already settled it, silently.** (`benchmark-data/` left this repository
in v1.10.56, #1723 — *"benchmark-data, benchmark_external and IP move to their own
repositories"* — so it is in neither the `a4caccefe` nor the `ae78abb28` tree. The figures below were measured
against the published corpus as it stands in this checkout, which is that same tree at
its last in-repo commit, `24ff95307`. Every count here is reproducible against the
benchmark-data repository; none of it is reproducible from the base tree alone.)
**30 of 30** published copies of
`spare_cell_coverage.json` under `benchmark-data/` — 14 at a
`reports/spare_cell_coverage.json` path, 14 under `reports/phase2/gates/`, 2 filed
under a step folder — carry `"program": "spare_cell_coverage_check"`. The runner
payload's marker string, `"spare_cell_coverage (runner-emit)"`, occurred in **no artefact
anywhere in the repository** — only in the source line that produced it, which this
change removes. The runner's write never survived a run.

The two published runs that carry a `write_ledger.json` say why, and say it about the
path rather than about the payload:

| run | `spare_cells.json` mtime | `spare_cell_coverage.json` mtime | Δ | producer |
|---|---|---|---|---|
| `spm/v1.10.18_sky130A` | 1786273818.075 | 1786273866.399 | **+48.3 s** | `null`, `unwitnessed` |
| `spm/v1.9.96_gf180mcuD` | 1786043783.649 | 1786043869.865 | **+86.2 s** | `null`, `unwitnessed` |

The runner writes both files inside one `try` block, microseconds apart. A coverage file
48 and 86 seconds later is not the runner's; it is the gate running afterwards. Both
ledgers file the path as a D5 finding — *"declared output exists but its mtime falls
inside no logged tool invocation window"* — with `producer: null`.

That finding carries its own caveat and it is worth stating: *"a real tool run that was
never wrapped produces this signal too."* On its own the `unwitnessed` label proves only
that provenance did not cover the write. It is the three together — the payload is the
checker's, the mtime is tens of seconds after the runner's own artefact, and the ledger
cannot name a producer — that make the clobber a measurement rather than a reading of
the source.

**4. The runner's verdict was strictly weaker.** Not a different measurement — the same
question, answered with looser thresholds:

| | runner-emit | `spare_cell_coverage_check` |
|---|---|---|
| density floor | the **run's own** `spare_dens` | fixed `--target-density`, default **0.02** |
| distribution | `count <= 1 or distinct > 1` | `distinct >= max(2, ceil(0.5 * count))` |
| empty set | no rule | `count == 0` is a hard FAIL |

Both wrote `status`, so both were a sign-off. Measured, three plans, all three PASS at
the runner and FAIL at the gate:

```
run configured at a laxer self-target (0.005) and met it
   runner-emit = PASS | checker = FAIL  ['actual_density 0.005 < target_density 0.02']
200 spares clustered on 2 positions
   runner-emit = PASS | checker = FAIL  ['spares clustered: only 2 distinct position(s) for 200 spare(s)']
zero spares inserted, self-target 0.0
   runner-emit = PASS | checker = FAIL  ['actual_density 0 < target_density 0.02',
                                         'spares clustered: only 0 distinct position(s) for 0 spare(s)',
                                         'no spare cells inserted (count == 0)']
```

The last row is the one that matters for what spares are *for*. A design with zero
spare cells has no metal-only ECO budget at all: after tape-out there is nothing to
re-wire, and any functional fix is a base-layer re-spin. The runner's file would have
signed that off as `status: PASS`, and Pillar 6 would have read it.

## What happens to the other writer

`phase3_one_shot_runner` keeps `phase3/stage3/pnr/spare_cells.json` — step 18's other
declared output, and its own. Nothing is lost by dropping its coverage summary, because
the summary was derived from that artefact in the first place: `count`,
`placed_cells_est`, `target_density`, `actual_density`, `tied_off` and the measured
`tie_off` evidence are all in the plan. The runner's grid-spread count survives as a
step **detail line** — a log note, never an artefact and never a verdict.

To make the removal cost a reader nothing, the checker now carries the runner's
measurement through into the one file at the declared path: `placed_cells_est`, the
measured `tie_off` dict (so a FAIL says which of *raised*, *never ran* or *partial*
happened), and `plan_target_density` — the run's own target, kept under a **distinct
key** from the gate floor, because publishing a self-target under the key the floor uses
is precisely what the runner's summary did.

**No spare or ECO cell is touched by any of this.** The insertion path, the tie-off, the
`keep`/`dont_touch` attributes and the fill exclusion are unchanged. What is removed is
one JSON write.

## The second gap: single-writered is not the same as produced

Found in verification, after the removal had already landed, and fixed on the same
branch. It is recorded here rather than quietly patched because it is the exact
failure mode this decision is about, arriving from the other direction.

Removing the runner's write left `spare_cell_coverage_check` as the sole writer of
`reports/spare_cell_coverage.json`, invoked by step 18's gate clause. But
`phase3_one_shot_runner` also runs `flow_compliance_check --strict` on its own output
before it returns, and that grades `required_outputs` **by presence**, not by whether
the gate passed. On a **runner-only** invocation — the runner called directly, with no
orchestrator gate pass — nobody produced the file.

Measured on a published run tree carrying a real spare plan
(`benchmark-data/ic/sha256`), the report being the only difference between the two
trees:

```
with reports/spare_cell_coverage.json
  ⊘ [PASS-VOIDED      ] Step 18: Spare-cell + ECO-prep insertion (Design-for-ECO)

without it
  · [MISSING          ] Step 18: Spare-cell + ECO-prep insertion (Design-for-ECO)
       └─ required_outputs missing: ['reports/spare_cell_coverage.json']
          (satisfied: 1/2 — the gate passed, but every declared output must be
           produced, not just one)
```

A path with exactly one permitted writer that nothing ever runs is single-writered and
absent. The gate passed; the declared output simply had no producer on that path.

**The fix is the shape this file already uses one step earlier.** The runner now
*invokes the declaring producer* instead of formatting a rival payload:

```python
if (out_dir / "spare_cells.json").is_file():
    subprocess.run([sys.executable,
                    str(PROGRAMS_DIR / "spare_cell_coverage_check.py"),
                    str(project)], capture_output=True, text=True, timeout=120)
```

which is step 8's `sdc_syntax_check` pattern verbatim in intent — *"emitting here makes
the required_outputs gate (file presence) pass without depending on the gate's
invocation order"* — and is what the removed convenience summary should have been all
along. It is not a relapse:

* **The single-writer property is untouched.** The only program that ever *formats*
  this path is still `spare_cell_coverage_check`. The ast guard stays green by
  construction, not by exemption, and `test_exactly_one_program_writes_the_declared_report`
  still reddens on a real second writer.
* **Running it twice is safe, and only because of the other half of this decision.**
  The checker reads only `spare_cells.json`, never the path it writes, so the runner's
  invocation and the gate's later one compute the same verdict from the same artefact.
  Under the old self-reading checker, invoking it twice would have fed the second
  invocation the first one's output. Idempotence is what the read removal bought.
* **The verdict is not swallowed.** The checker's `rc=1` is a genuine readiness FAIL
  and is deliberately not propagated: producing the declared report is the runner's
  job, acting on the verdict is the gate's.

End to end, on the tree above: coverage absent → step 18 MISSING; runner invokes the
producer → file present carrying `"program": "spare_cell_coverage_check"`; step 18
back to PASS-VOIDED, its voiding an unrelated upstream `MISSING` that is identical on
both sides.

Two guard legs cover it, `test_every_declared_output_of_step_18_is_produced_on_a_runner_only_run`
and its paired control. The first asks a question `L1` structurally cannot: for every
path step 18 declares, does anything the runner actually runs produce it.

## The real gap, which removing the clobber alone would have hidden

`spare_cell_coverage_check.audit()` read `reports/spare_cell_coverage.json` as *"the
runner's coverage summary"* and **preferred** its `actual_density` over the
`spare_cells.json` in front of it:

```python
for src in (coverage_summary or {}, spare_plan):   # summary FIRST
```

That path is the checker's own output. The runner's clobber was the only thing keeping
the read fresh: with the runner writing first each run, the checker read a current
number and the bug was invisible. Remove the runner's write on its own and the checker
reads its **own previous verdict**, on every re-run, with no writer left to correct it.

Measured on one project directory, before the fix:

```
RUN 1  spare_cells.json count=203 actual=0.020022  ->  rc=0  PASS  actual_density=0.020022
RUN 2  spare_cells.json count=5   actual=0.000493  ->  rc=0  PASS  actual_density=0.020022
RUN 2, report deleted first                        ->  rc=1  FAIL  actual_density=0.000493
```

RUN 2 is a spare pool 40× under the readiness floor, exiting 0 and publishing
`"verdict": "PASS"` on a density from the previous run, with the contradicting
`"count": 5` in the same file. The shipped artefacts record the shape in their own
field: every published report carries
`"coverage_summary_json": "reports/spare_cell_coverage.json"` — a pointer, in the file,
to the file. Anyone following it to find the measurement behind the verdict finds the
verdict.

After the fix, the same three invocations:

```
RUN 1  ->  rc=0  PASS  actual_density=0.020022
RUN 2  ->  rc=1  FAIL  actual_density=0.000493
RUN 2, report deleted first  ->  rc=1  FAIL  actual_density=0.000493
```

## Blast radius

**Targeted suite, in the image, branch vs base.** Re-measured on `ae78abb28` over the
12 files that cover this change — the checker, the runner's spare path, tie-cell
discovery, preservation, Pillar 6, flow declaration parity, flow condition reachability
and the D3 output matrix:

```
base    ae78abb28   6 failed, 218 passed, 64 skipped
branch              6 failed, 230 passed, 64 skipped
```

Diffed by test ID: **NEW RED — NONE. FIXED — NONE.** The six are
`test_d3_required_outputs_are_produced[step15/17/19/20/30/32]`, identical on both sides.
Step 18 is GREEN on both. The twelve extra passing cases are exactly this change's guard,
which does not exist on the base.

The wider selection below was measured on `a4caccefe` in the authoring session and is
kept because it covers far more ground than the 12-file batch:

The selection `ci_targeted_test_select.py --base a4caccefe` produces 141 files; both
trees were run through `pytest_per_file_junit.py --aggregate-check`, one session each.

```
branch  7 failed, 2409 passed, 102 skipped, 6 xfailed   (2524 cases, 920.30s)
base    7 failed, 2400 passed, 102 skipped, 6 xfailed   (2515 cases, 921.09s)
```

Diffed by test ID, not by count: **NEW RED — NONE. FIXED — NONE.** The seven reds are
`test_matrix_d3_outputs_produced.py` (six `test_d3_required_outputs_are_produced`
parametrisations and `test_d3_waived_unproven_entries_have_no_committed_artefact`),
identical on both sides and already red on the base. The nine extra cases on the
branch are this change's guard. (It has ten legs; the tenth was added after the branch
session had collected, and is green on its own — `10 passed` in the same image.)

**Published corpus.**

The fixed checker was replayed over every published run that carries both a
`spare_cells.json` and a sibling verdict: **7 pairs, 7 identical** on
`verdict`, `actual_density`, `count`, `distribution_ok` and `tie_off_ok`. **No published
run changes colour.** The other 7 reports at that path have no sibling plan in the
published tree and could not be replayed; that is a limit of the corpus, not a clean
result.

## The change

| file | change |
|---|---|
| `programs/phase3_one_shot_runner.py` | the `reports/spare_cell_coverage.json` write and its `coverage_payload` are removed; the grid-spread count becomes a detail-line note; the runner now INVOKES `spare_cell_coverage_check` so the declared output is produced on a runner-only run, and lists it in `pnr_outputs` |
| `programs/spare_cell_coverage_check.py` | `_resolve_paths` → `_resolve_spare_json` (one path, not two); `evaluate_coverage` loses its `coverage_summary` parameter; the verdict gains `plan_target_density`, `placed_cells_est`, `tie_off`; `version` 1.0.0 → 1.1.0; the dead `coverage_summary_json` key is gone |
| `programs/tests/test_spare_cell_design_for_eco.py` | four call sites drop the removed positional `None` |
| `programs/tests/test_declared_report_has_one_writer.py` | **new** — the guard |

`flow/phase1_phase2_phase3.yaml` is **unchanged**. The flow was right.

## The guard, and its reds

`programs/tests/test_declared_report_has_one_writer.py`, 12 legs. It parses every
non-test program in the plugin with `ast` and reports which of them *write* this path —
discovered, not listed, so a helper added tomorrow is in scope the day it lands. Reads
are not writes, which keeps `benchmark_verify_report`, a legitimate consumer, out of the
set.

All three halves of the decision were re-broken and the reds captured, in the image
(`ghcr.io/vibeic/vibeic-eda:0.3.16`, `--skip` first), each by restoring the base
version of one file into the branch tree (re-run on `ae78abb28`).

Second writer put back in the runner (the base's `phase3_one_shot_runner.py`):

```
E  AssertionError: reports/spare_cell_coverage.json is step 18's declared
   required_output and only spare_cell_coverage_check may write it; found writers
   ['phase3_one_shot_runner', 'spare_cell_coverage_check']
3 failed, 9 passed
```

Three, not one: reverting that file restores the rival write *and* removes the producer
invocation, so the L4 pair reddens with L1. That is the correct reading — the pre-change
runner fails this module on both counts.

Self-read put back in the checker (the base's `spare_cell_coverage_check.py`):

```
E  AssertionError: the checker took actual_density from a file it wrote itself:
   0.020022 is the PREVIOUS run's number
E  assert 0.020022 == 0.000493
...
E  AssertionError: assert (0, 'PASS', 0.99) == (1, 'FAIL', 0.000493)
...
E  KeyError: 'placed_cells_est'
3 failed, 9 passed
```

The producer invocation removed from the runner (the second gap above):

```
E  AssertionError: step 18 declares reports/spare_cell_coverage.json but nothing the
   runner runs produces it: its writers are ['spare_cell_coverage_check'], and the
   runner neither writes it nor invokes any of them. A runner-only invocation leaves
   that declared output MISSING.
E  AssertionError: phase3_one_shot_runner no longer invokes spare_cell_coverage_check
   by name — the leg above is asserting over a shape that is gone
2 failed, 10 passed
```

Clean tree: `12 passed`.

Four legs exist so the single-writer assertion cannot pass over an empty set: one
asserts the scanner finds the writer that is certainly there; three feed it write
shapes it must catch — the removed runner block verbatim, the atomic-artefact helper,
and the builtin `open(p, "w")` — with the last also asserting that `open(p)` is still a
read, so the mode discrimination is not achieved by calling everything a write.

## What was deliberately not done

**No general rule** that no path declared by one step may be written by another step's
program. That rule is right and it is a different row: its blast radius over the flow's
67 output-declaring steps has not been measured, and a rule that reddens paths nobody
has decided about would be a worse artefact than the one red cell this replaces. The
scanner in the guard is general; only this one path is asserted on.

**No exemption, no waiver, no re-dating**, and no `--write-baseline` on any hygiene
gate. The row is answered, not silenced.
