# SIXRED — six ENFORCED-CONTRADICTED cells on the deps_correct row

Status: IN PROGRESS (started 2026-08-31)
Host: 192.168.1.114
Findings written here incrementally.

## Step 0 — orientation

- main = 781d24727 [v1.14.22]; throwaway worktree /home/reyerchu/_sixred/main
- Row = **d5 `deps_correct`** ("Is blocks_on the true upstream set — no missing and no phantom edge?")
- README generated census (matrix_63x8/README.md:334,352): d5 row = own 0 / subst 0 / undeclared 61 / **CONTRADICTED 6** / NA-measured 0 / WAIVED 1 / NA 0
- Predicate module: programs/tests/test_matrix_d5_deps_correct.py
- Next: identify WHICH 6 steps are red.

## Step 1 — the 6 red cells REPRODUCED (3.0s, main 781d24727)

```
cd vibe-ic-marketplace/plugins/vibe-ic
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest programs/tests/test_matrix_d5_deps_correct.py -q -p no:randomly
=> 6 failed, 74 passed, 1 xfailed
```
Failing cells: **steps 2, 7, 14, 15, 37, 39** — all in
`test_d5_blocks_on_covers_the_real_dependency_graph`, all `D5-MISSING-EDGE`.

7 defect rows, from exactly TWO evidence sources:

| # | consumer step | artefact | producer | evidence gate program |
|---|---|---|---|---|
| A1 | 2  | phase3/stage5_manufacturing/packaging_log.json | 42 | stage_on_pass_review.py |
| A2 | 7  | same | 42 | stage_on_pass_review.py |
| A3 | 14 | same | 42 | stage_on_pass_review.py |
| A4 | 15 | same | 42 | stage_on_pass_review.py |
| A5 | 37 | same | 42 | stage_on_pass_review.py |
| A6 | 39 | same | 42 | stage_on_pass_review.py |
| B1 | 2  | reports/phase2/coverage/coverage_actual.json | 4 | flow_compliance_check.py |
| B2 | 14 | same | 4 | flow_compliance_check.py |

**ONE ROOT CAUSE candidate**: source A covers all 6 cells. `stage_on_pass_review.py`
is the on-pass review program moved to step 39 in v1.13.78 and attached as a gate to
6 steps; the layer-2 basename anchor sees `'packaging_log.json'` as a standalone string
constant inside it and charges every step that has it as a gate with reading step 42's
artefact. Source B is a second, smaller cause on 2 of the same cells.
Next: read stage_on_pass_review.py to decide kind (a)/(b)/(c) per the brief.

## Step 2 — mechanism of cause A (all 6 cells)

`programs/stage_on_pass_review.py` is ONE program used as the gate of 6 steps, each
invoked with a different `--stage`:

```
yaml:1522  stage_on_pass_review . --stage stage_phase1 ...
yaml:2551  ... --stage stage1 ...
yaml:3991  ... --stage stage_analog ...
yaml:4096  ... --stage stage2 ...
yaml:7114  ... --stage stage3 ...
yaml:7799  ... --stage stage4 ...
```

`packaging_log.json` is named ONLY inside `rule_package_cannot_bond_design` (R5) and
its module constant `_PACKAGING_LOG` (stage_on_pass_review.py:3022, 3166). R5 is
registered at line 4349 as:

```python
register(stage="stage5_manufacturing", rule_id="R5_PACKAGE_CANNOT_BOND_DESIGN",
         rule=rule_package_cannot_bond_design, ..., enabled=False,
         not_enabled_reason="no run has ever produced a stage-5 artefact: MEASURED
         2026-08-30, 0 of 105 published run roots carry phase3/stage5_manufacturing/ ...")
```

`enabled=False` -> `_DECLARED_NOT_ENABLED`, never `_RULES` (register(), line 3979-3981).
`review()` iterates `_RULES` only (line 4039); `main()` touches `_DECLARED_NOT_ENABLED`
only to PRINT the rule id + reason and return rc=2 (lines 4544-4560). **The body of R5
is never executed.** And no gate invocation passes `--stage stage5_manufacturing`.

So: the phantom edge X -> 42 for X in {2,7,14,15,37,39} is charged because the layer-2
basename anchor (`program_string_constants`, test file lines 340-397) counts a string
constant inside a function the program can never call, in a stage no step selects.
That is **kind (b): the PREDICATE is wrong.** The edge cannot be declared (42 is the
last step, and would be a forward/circular edge), so kind (a) is unavailable by
construction.

## Step 3 — mechanism of cause B (cells 2 and 14 only)

`programs/flow_compliance_check.py:9582` `_COVERAGE_SELFSKIP_ARTIFACT = "coverage_actual.json"`,
used at exactly one site (line 9597):

```python
if Path(artifact_rel).name != _COVERAGE_SELFSKIP_ARTIFACT:
    return False
```

`artifact_rel` iterates `result.evidence` — the required_outputs of the step BEING
CHECKED. The constant is a DISCRIMINATOR on the current step's own artefact list; no
path is ever constructed from it and step 4's file is never opened on behalf of step 2
or 14. Also kind (b).

## Step 4 — WHEN each cause appeared (bisect by commit, d5 module only)

| tree | d5 result |
|---|---|
| `3348b1d12^` (just before v1.13.27 / PR #1853) | **80 passed, 1 xfailed — row GREEN** |
| `93235bdf3^` (just before v1.13.78) | 6 failed: {2, 7, 14, 15, 37, **40**} — cause A only (7 defect rows) |
| `781d24727` main v1.14.22 | 6 failed: {2, 7, 14, 15, 37, **39**} — causes A+B (9 defect rows) |

**This corrects the brief's hypothesis.** The row did NOT go red because v1.13.78 moved
the on-pass reviews. It went red at **v1.13.27 (PR #1853, `3348b1d12`)**, which added the
DECLARED-NOT-ENABLED rule R5 and with it the bare constant `"packaging_log.json"` to a
gate program shared by 6 steps. v1.13.78 only (i) moved one member of the set from step 40
to step 39 and (ii) added `flow_compliance_check` as a gate to steps 2 and 14, which
introduced cause B on top — the count stayed 6 because B lands on two cells A already had.

Also visible in the full sweep: step 12 carries a 10th defect row (`netlist.v` -> 14); that
is the PINNED waiver `12/d5`, working as designed, and is not part of the six.

## Step 5 — the ONE root cause, stated

`program_string_constants()` (test_matrix_d5_deps_correct.py:340-397) counts a bare
basename constant as a READ wherever it appears in executable code. Both live causes are
occurrences in **MATCH position** — the program is testing a path it was ALREADY GIVEN
against a name, never constructing a path to open:

* A: `stage_on_pass_review.py:3166` — `if r.endswith("packaging_log.json")`, selecting
  from `decl["artefact"]`. (The genuine path construction two lines later uses the
  FULL-path constant `_PACKAGING_LOG`, a different string that the basename anchor does
  not match — so this single `endswith` is the entire charge behind 6 cells.)
* B: `flow_compliance_check.py:9597` — `Path(artifact_rel).name != _COVERAGE_SELFSKIP_ARTIFACT`,
  over `result.evidence`, i.e. the checked step's OWN declared outputs.

Layer 2 already excludes two provably-not-a-read positions (docstrings; `not in` container
elements). Match position is the same class, and `not in` is a strict subset of it.
Kind = **(b) the PREDICATE is wrong**. Kind (a) is impossible here (42 is the last step;
the repair the finding asks for is a forward/circular edge) and (c) would hide a live
question behind an advisory_reason rather than remove a false charge.

## Step 6 — arm measured BEFORE authoring (monkeypatched probe, no tree edit)

Probe: `/home/reyerchu/_sixred/measure_arm.py` — recompute `derived_dependencies()` for
all 63 steps under BASE and under the ARM predicate.

```
BASE steps 23 pairs 37 rows 92
ARM  steps 23 pairs 29 rows 78
```

Pairs removed — EXACTLY the eight defect pairs, nothing else:
```
('2','4') ('2','42') ('7','42') ('14','4') ('14','42') ('15','42') ('37','42') ('39','42')
```
Collateral on other pairs: **0**. `('12','14')` (the pinned `12/d5` waiver) survives.

NOTE (separate honesty defect, found on the way): the module docstring and the three
anti-starvation floors say `12 steps / 16 pairs / 32 rows`; **live on main is 23/37/92**.
The floors are `>=`, so they never reddened while drifting 11 pairs / 60 rows behind.
Since this fix SHRINKS the denominator, the module's own rule ("name the removed read
and why it is not a dependency ... then re-derive this floor") applies: floors go to the
post-fix live baseline 23/29/78 and the docstring states the removal.
- CONFIRMED by two independent instruments at 781d24727 [v1.14.22]:
  - `pytest programs/tests/test_matrix_d5_deps_correct.py` -> **6 failed, 74 passed, 1 xfailed** (5.9 s)
  - `test_matrix_63x8_coverage.enforcement_census()` -> dim=5 ENFORCED-CONTRADICTED on exactly
    steps **2, 7, 14, 15, 37, 39** (and 12/d5 WAIVED, as pinned).

## Step 1 — what the six reds actually say

8 defect rows over 6 cells, from **two** string constants, both via LAYER 2
(the gate-program basename anchor), never layer 1 or 3:

| rows | consumer steps | artefact | producer | named in |
|---|---|---|---|---|
| 6 | 2, 7, 14, 15, 37, 39 | `phase3/stage5_manufacturing/packaging_log.json` | step 42 | `stage_on_pass_review.py` |
| 2 | 2, 14 | `reports/phase2/coverage/coverage_actual.json` | step 4 | `flow_compliance_check.py` |

The six steps are EXACTLY the six steps whose gate names `stage_on_pass_review`,
each under a DIFFERENT `--stage` selector:
2=`stage_phase1`, 7=`stage1`, 14=`stage_analog`, 15=`stage2`, 37=`stage3`, 39=`stage4`.

## Step 2 — the finding is already published, and the disposition was deferred TO HERE

`ec36f917b` [v1.14.10, 2026-08-31 11:03] published it and said so in its own message:

> Six cells of dimension 5 (deps_correct) have been RED since `da6fcd7fe3` [v1.13.63] and
> the page a reader quotes said 0. ... NOT FIXED HERE, and that is the point of publishing
> it. The disposition is a flow-graph ruling or a change to how d5 attributes a shared
> program's constants; both are flow-level changes with their own acceptance standard and
> an owner.

Independently re-derived here, and it holds: at `ab2dae680` [v1.13.26] the whole d5 module
is **80 passed, 1 xfailed, 0 failed**; the six steps carry NO `stage_on_pass_review` clause
there (`gate_programs(2)` = 17 tokens vs 19 at main). Census ENFORCED 532->526 / CONTRADICTED 0->6.

**One row the published finding does not name:** the two `coverage_actual.json` rows on
steps 2 and 14. The published text names only `packaging_log.json`. So the disposition has
to cover a second shared program as well, and `flow_compliance_check` is a gate of 64 steps.

## Step 3 — why every one of the 8 rows is a PHANTOM, mechanically

`packaging_log.json` (6 rows). The only code in `stage_on_pass_review.py` that opens it is
`rule_package_cannot_bond_design` (R5), registered at line 4349 as
`register(stage="stage5_manufacturing", rule_id="R5_PACKAGE_CANNOT_BOND_DESIGN", ..., enabled=False)`.
`enabled=False` puts it in `_DECLARED_NOT_ENABLED`, never `_RULES`, and it is keyed under
`stage5_manufacturing` — a stage NONE of the six gate commands passes. Two independent
reasons it is unreachable from every one of the six invocations. Its own docstring:
"It is not reachable from `main` while stage5 stays out of `_RULES`".

`coverage_actual.json` (2 rows). The constant is `_COVERAGE_SELFSKIP_ARTIFACT`, used at
`flow_compliance_check.py:9597` as `if Path(artifact_rel).name != _COVERAGE_SELFSKIP_ARTIFACT: return False`
— a BASENAME CLASSIFIER over the artefact the step under review declared as its own evidence,
not a path the program opens. Step 2 runs it as `--stage-id stage_phase1`, step 14 as
`--stage-id stage_analog`; neither stage declares step 4's coverage artefact.

So d5's message "the real dependency is CIRCULAR and one side of it is wrong" is, for these
8 rows, the derivation refuting ITSELF: 5 of 6 are circular and the 6th is a forward edge.

## Step 7 — the fix (authored, NOT landed)

Branch `fix/d5-match-position-constants-are-not-reads`, worktree `/home/reyerchu/_sixred/fix`.

One file: `programs/tests/test_matrix_d5_deps_correct.py`.
`program_string_constants()` becomes a thin wrapper over a new pure
`read_position_constants(source, origin)` (so the exclusions are drivable from source
text by their own tests), and layer 2 gains two exclusions beside the existing two:

3. the BINDING SITE of a module-level `NAME = "literal"` alias is not a use (its uses are
   counted, each in its own position);
4. a constant occurring ONLY in MATCH position — an operand of any `ast.Compare`, an
   element of a container being compared, or the literal argument of
   `.endswith(...)` / `.startswith(...)` — is a classifier, not a read. This SUPERSEDES
   the old `not in`-container rule (same idea, one operator wide).

A constant that occurs even once OUTSIDE those positions still counts.

RESULT on `fix`:
```
programs/tests/test_matrix_d5_deps_correct.py .... 80 passed, 1 xfailed in 3.39s
```
(base at the same commit: 6 failed, 74 passed.)

## Step 8 — CORRECTION: the `endswith` half of the fix was wrong; the control caught it

`test_d5_match_position_exclusion_is_not_a_blanket` (the anti-over-suppression control I
wrote alongside the fix) went RED:

```
AssertionError: stage_on_pass_review.py no longer registers a read of ['L5_ADI_SPEC.json']
```

Why: `stage_on_pass_review.py:1744` uses the SAME idiom as the packaging_log site —
`l5 = next((project / r for r in intent_rel if r.endswith("L5_ADI_SPEC.json")), None)`
— and then `l5.read_text()`. **`endswith` here selects a path that IS then opened.**
So "a literal argument of `.endswith()` is not a read" is FALSE in this tree, and the
identical shape at the packaging_log site is not what makes that one harmless.

The pair-level probe in Step 6 could not see this: `L5_ADI_SPEC.json` is produced by D1,
and D1 is in every step's closure, so losing the read changed no pair. Only the
per-program anchor control saw it. Retained as the standing reason this exclusion class
must be measured at the ANCHOR level, not the pair level.

`_MATCH_METHODS` withdrawn. The Compare-operand + alias-binding half is unaffected and
still fixes cause B.

## Step 9 — the correct mechanism for cause A: the flow declares it, per stage

`stage_on_pass_review` reads ONLY `decl["intent"]` and `decl["artefact"]`, and the flow
declares those per stage in the stage's own `on_pass_review:` block:

| stage | on_pass_review.intent | on_pass_review.artefact |
|---|---|---|
| stage_phase1 | input/docs/, phase1/input_doc/, input_doc/, phase1/input_prompt/, input/phase1_prompt.md, input/phase1_structured.yaml | phase1/generated_docs/ |
| stage1 | phase1/generated_docs/L9_INTEGRATION_SPEC.json | phase2/stage1/rtl/, reports/phase2/ |
| stage2 | phase1/generated_docs/L9_INTEGRATION_SPEC.json | phase2/stage2/synth/netlist.v |
| stage_analog | phase1/generated_docs/L5_ADI_SPEC.json | phase3/analog/, phase1/analog/ |
| stage3 | phase1/generated_docs/L8_TIMING_WAVEFORM.json, L9_INTEGRATION_SPEC.json | phase3/stage3/pnr/constraint.sdc, phase3/stage3/cts/, phase3/stage3/sta/, reports/phase3/ |
| stage4 | phase1/generated_docs/L9_INTEGRATION_SPEC.json | phase3/stage4/gds/, phase3/analog/hardmacro/ |
| **stage5_manufacturing** | phase1/generated_docs/L1_DATASHEET.json | **phase3/stage5_manufacturing/packaging_log.json** |

Each of the 6 red steps dispatches `stage_on_pass_review . --stage <X>` for exactly one X,
and **no gate command in the flow passes `--stage stage5_manufacturing`** — which is why
R5 is registered `enabled=False`. So `packaging_log.json` is declared, by the flow itself,
as a read of a stage no step selects.

The repair is therefore not a syntactic heuristic over the program's AST at all: it is
that **where the flow DECLARES what a gate program reads at this step, that declaration is
the answer, and the whole-program basename union must not add to it.** Same move layer 3
already made with `required_inputs: [{from: X}]`.

## Step 10 — final fix shape, MEASURED (base 781d24727 vs branch)

Two parts, one file (`programs/tests/test_matrix_d5_deps_correct.py`):

**Part 1 — read-position analysis** (`read_position_constants`, extracted from
`program_string_constants` so tests can drive it from source text). Adds two exclusions
to the existing docstring rule:
 * the BINDING SITE of a module-level `NAME = "literal"` alias is not a use;
 * a constant occurring ONLY as an `ast.Compare` operand (or an element of a container
   being compared) is a classifier. This supersedes the old `not in`-container rule.
 `.endswith`/`.startswith` arguments are explicitly NOT excluded — measured, see Step 8.
 Fixes cause B.

**Part 2 — layer 2b, `_FLOW_DECLARED_READ_PROGRAMS`.** For a gate program the flow
DISPATCHES (`stage_on_pass_review . --stage <X>`), the basename anchor is intersected
with the paths the flow declares for that invocation (`<stage X>.on_pass_review.intent`
+ `.artefact`), instead of the union over all seven stages. Fixes cause A.

### Delta, whole flow

|  | base | branch |
|---|---|---|
| steps with a derived cross-step dep | 23 | 23 |
| distinct (consumer, producer) pairs | 37 | **29** |
| evidence rows | 92 | **70** |
| (gate program, anchored artefact) anchors | 112 | **111** |

Pairs removed — exactly the eight defect pairs, nothing else:
`(2,4) (2,42) (7,42) (14,4) (14,42) (15,42) (37,42) (39,42)`

Program-level anchors removed: exactly one — `(flow_compliance_check, coverage_actual.json)`.
`(stage_on_pass_review, packaging_log.json)` is STILL an anchor of the program; it is
simply no longer attributed to steps whose stage does not declare it.

Evidence rows lost on SURVIVING pairs (precision gain, disclosed because the row floor
exists to make it visible): `(7,D1) 6->3`, `(14,D1) 8->5`, `(15,D1) 5->2`,
`(37,D1) 4->2`, `(39,D1) 4->1`. Each is an L-doc that a DIFFERENT stage's review reads;
e.g. step 7 is stage1, whose `intent:` is L9 alone, and it was being charged with reading
L1/L5/L8 because some other stage's rule does.

`test_matrix_d5_deps_correct.py`: **80 passed, 1 xfailed** (base at same commit: 6 failed).

## Step 11 — bidirectional negative control (the arm must be able to fail on base)

Base worktree `/home/reyerchu/_sixred/neg` at 781d24727, with ONLY the new register +
its test ported in (no fix):

```
FAILED test_d5_the_narrowing_register_names_live_subjects
  step 2/7/14/15/37/39 charged with reading .../packaging_log.json again
  step 2/14        charged with reading reports/phase2/coverage/coverage_actual.json again
1 failed, 81 deselected
```
All 8 charges named. On the branch the same test passes.

Source-driven fixtures run through the BASE extractor (F.program_path monkeypatched to a
temp file, nothing written into the repo):

| fixture literal | expected | BASE | branch |
|---|---|---|---|
| docstring_only.json | excluded | absent | absent |
| alias_compared.json | excluded | **present** | absent |
| eq_only.json | excluded | **present** | absent |
| not_in_only.json | excluded | absent | absent |
| in_only.json | excluded | **present** | absent |
| alias_opened.json | retained | present | present |
| built_only.json | retained | present | present |
| suffix_selected.json | retained | present | present |
| rebound_one/two.json | retained | present | present |
| compare-only `x.json` | excluded | **present** | absent |

So both source-driven controls fail on base and pass on the branch; every RETAIN case is
unchanged by the fix, which is what makes the pass meaningful.

## Step 12 — docstring, floors, LAND.md

* Module docstring: layer-2 exclusion list rewritten (compare-position supersedes the
  `not in` rule; alias binding site added; the `endswith` retraction recorded with its
  worked example), new LAYER 2b section, and the shrink disclosure 37/92 -> 29/70 with
  every removed pair and every row lost on a surviving pair named.
* Floors re-derived 12/16/32 -> **23/29/70** (they were `>=` guards sitting ~3x below live;
  disclosed as a second, latent defect found on the way).
* `LAND.md` written at the repo root of the branch worktree (179 lines).
* d5 module: **85 passed, 1 xfailed**.
* `test_matrix_d5_deps_correct.py` is NOT one of the 52 protected_landing_transition
  paths (checked `tools/ci/protected_landing_transition.json`); the two protected matrix
  files, `test_matrix_63x8_coverage.py` and `test_matrix_63x8_census_freshness.py`, are
  NOT touched.

## Step 13 — census REGENERATED on the branch: d5 CONTRADICTED = 0

`python3 tools/gen_matrix_63x8_census.py` (rc=0, ~4 min):

```
wrote .../matrix_63x8/README.md: ENFORCED own=18 substituted=116 undeclared=397;
CONTRADICTED=1 NOT-MEASURED=53 WAIVED=8 NA=19; 612 cells (612/612 accounted).
```

| dim | before | after |
|---|---|---|
| **5 deps_correct** | undeclared 61, **CONTRADICTED 6**, WAIVED 1 | undeclared 67, **CONTRADICTED 0**, WAIVED 1 |
| 7 outputs_list_complete | undeclared 63, CONTRADICTED 0 | undeclared 62, **CONTRADICTED 1** |
| total | 526 ENFORCED / 6 CONTRADICTED | 531 ENFORCED / **1** CONTRADICTED |

**The six are gone from the row, not hidden**: they moved into ENFORCED (61 -> 67), the
census was regenerated by its own generator, and nothing in the census was hand-edited.

**The d7 CONTRADICTED=1 is NOT mine and is under investigation.** `test_matrix_d7_outputs_
list_complete.py` does not import anything from the d5 module (checked its imports), and
the branch touches only the d5 test file plus the generated README block. The census run
happened at load average 8.3; d7 drives subprocesses, tempdirs and wall-clock. Running d7
on the BASE worktree now to establish whether it is a live main red the committed README
is stale about, or load flake. Result below.

### d7 CONTRADICTED=1 is a PRE-EXISTING main red, not a regression from this branch

Measured on the BASE worktree (`/home/reyerchu/_sixred/main`, 781d24727, unmodified):

```
FAILED test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step25]
  step 25: required_outputs is INCOMPLETE — 1 load-bearing artefact it never declares.
  declared (3): reports/phase3/em.rpt, em.json, em_signoff.json
  * [W1:gate_output_read_elsewhere] 'reports/phase3/em_current_authority.json'
    (written by em_peak_current_authority_check; read by program:phase3_one_shot_runner)
1 failed, 100 passed, 1 skipped, 4 xfailed in 48.32s
```

So on this checkout main carries a **7th** live matrix red that the committed census does
not show. Note the d7 predicate's own skip clause is conditioned on `corpus_root()` and
`R.observed_writes()` — the committed census block was very likely generated with the
published corpus bound, where this cell skips. Stated as measured HERE, corpus-unbound;
it is a separate item from the six and is NOT touched by this branch.

* d7 on the BRANCH: `1 failed, 100 passed, 1 skipped, 4 xfailed` — byte-identical outcome
  set to base. **Zero delta.**

## Step 14 — collateral

Everything that references the d5 module or the census, on the branch:

```
programs/tests/test_matrix_63x8_ledger.py
programs/tests/test_matrix_write_record_scope.py
programs/tests/test_submission_template_check.py
programs/tests/test_matrix_63x8_census_freshness.py
=> 138 passed in 311.84s   RC=0
```

`test_matrix_63x8_census_freshness.py` passing is the important one: it re-derives the
census and diffs it against the committed block, so the regenerated table is FRESH, not
just written.

The full matrix was also driven end-to-end by the census generator itself (that is how it
computes cell states): the only CONTRADICTED cell left in the whole 612 is the
pre-existing d7/step25, reproduced identically on base.

## Step 15 — committed (NOT landed, NOT pushed)

```
branch  fix/d5-match-position-constants-are-not-reads
commit  452a2da37
base    781d24727 [v1.14.22]
files   LAND.md (new, 179 lines)
        programs/tests/matrix_63x8/README.md      (+6/-6, generated block only)
        programs/tests/test_matrix_d5_deps_correct.py (+604/-44)
```
No version assigned. Not pushed. `LAND.md` is at the branch worktree root
(`/home/reyerchu/_sixred/fix/LAND.md`).

* `test_matrix_63x8_census_freshness.py` re-run on the CLEAN committed tree:
  **6 passed in 302s, RC=0.** The regenerated census block is fresh.

---

# SUMMARY

**All six ENFORCED-CONTRADICTED cells on the `deps_correct` row are one root cause, kind (b).**

They are steps 2, 7, 14, 15, 37, 39. Every one was charged with a `blocks_on` edge to
step 42 (or, on two of them, also to step 4) whose only possible repair is a forward or
circular edge — step 42 is the last step in the flow. Layer 2 of the d5 predicate counted
a bare basename constant as a READ in code that the step's own gate invocation can never
execute:

* `stage_on_pass_review` is one program gating six steps, dispatched `--stage <X>`; its
  `packaging_log.json` constant belongs to R5, a rule the flow declares under
  `stage5_manufacturing` — a stage no gate command selects, and which is registered
  `enabled=False` for exactly that reason. The whole-program anchor charged every step
  with the union over all seven stages.
* `flow_compliance_check` name-tests `coverage_actual.json` against the declared outputs
  of the step it is checking. It classifies a path it already holds; it opens nothing.

The row went red at **v1.13.27** (PR #1853), not at v1.13.78. v1.13.78 moved one member
of the set from step 40 to 39 and added the second cause to two cells that already had
the first, which is why the count stayed 6 across the move.

**Fix** (branch `fix/d5-match-position-constants-are-not-reads`, commit `452a2da37`, base
`781d24727`, NOT landed, no version): a read-position rule (compare-operand and
alias-binding-site are not reads, superseding the old `not in` rule) and a layer 2b that
intersects the anchor with what the flow declares for THIS invocation. Removes exactly
the eight defect pairs and no others; one program-level anchor lost. Five controls, all
falsified against base. Anti-starvation floors re-derived 12/16/32 -> 23/29/70 (they had
drifted ~3x slack).

**Result**: d5 module 6 failed -> 85 passed / 1 xfailed. Regenerated census d5 row
CONTRADICTED **6 -> 0**, undeclared 61 -> 67. Total matrix CONTRADICTED 6 -> 1.

**Two things this branch does NOT fix, both found on the way and both stated rather than
absorbed:**
1. **d7/step25 is a 7th live main red** on this (corpus-unbound) checkout, reproduced
   identically on base and on the branch: step 25 never declares
   `reports/phase3/em_current_authority.json`, which `phase3_one_shot_runner` reads. The
   committed census showed d7 CONTRADICTED=0, so main's published census under-reports by
   one; the cell's own skip clause is conditioned on `corpus_root()`, so the committed
   block was probably generated corpus-bound.
2. **The d5 anti-starvation floors had gone slack by nearly 3x** (12/16/32 declared vs
   23/37/92 live) and never reddened, because they are `>=` guards. Re-derived on this
   branch; the same failure mode is worth checking on the other seven dimensions.

**A correction to the brief's hypothesis**: the flow moves are not the cause. The row was
green at `3348b1d12^` and red at `93235bdf3^` with the same six cells.

---

# ROUND 2 — d7/step25, the two findings in LAND.md, and the floor family sweep

Owner directive: fix d7/step25; give each finding its own sentence in LAND.md; CHECK the
other seven dimensions' floors (a family is never one instance); push as one ref with the
arms; do not land.

## Step 16 — d7/step25, the live red

The finding is CORRECT and is kind **(a) the DECLARATION is stale**:

* step 25's gate clause `program_exit_zero: "em_peak_current_authority_check . --json
  reports/phase3/em_current_authority.json"` DESIGNATES that output (yaml:5314);
* `phase3_one_shot_runner` READS it by name — `phase3_one_shot_runner.py:34516` (existence
  probe), `:42366` and `:42377` (opens it and cites it as `em_cat["evidence"]`);
* step 25's `required_outputs` names only `reports/phase3/em.rpt`, `em.json`,
  `em_signoff.json`.

Written by one thing, read by another, declared by nothing = W1 exactly.

TWO DOCUMENTED PRECEDENTS for closing this rule by DECLARING the path, both on step 31,
both recorded in `test_matrix_63x8_ledger.py`:
* `reports/phase3/magic_illegal_overlap.json` (2026-08-20 R9, 152 -> 153)
* `reports/phase3/perc_sweep.json` (`2ffa7a594` [v1.12.10], 165 -> 166)

The second one names every PAIRED change the declaring commit must carry, and says the
declaring commit for `perc_sweep.json` did NOT carry them:
1. the ledger entry-count pin (total + FILE/GLOB/ANY_OF split) with a dated note;
2. the d3 evidence manifest (`test_d3_manifest_declaration_parity`,
   `test_flow_manifest_declaration_parity`);
3. the anchored figures `figure:required_output_entries` and `figure:required_outputs_file`
   — `gen_matrix_63x8_census.py --check-figures` was red on all of them.

### The declaration

`flow/phase1_phase2_phase3.yaml`, step 25 `required_outputs`, after `em_signoff.json`
(which was declared for the SAME rule on the SAME step, and whose note is the template):

```yaml
      - "reports/phase3/em_current_authority.json"
```

with a note recording: the designating clause, the three runner read sites, and the proof
that declaring it cannot manufacture a MISSING — `em_peak_current_authority_check.main`
writes the `--json` target BEFORE it branches on the verdict
(`em_peak_current_authority_check.py:435-436`, ahead of the FAIL / PASS / INCOMPLETE
returns), so the file exists on every path where the clause actually ran; the only earlier
returns are argument errors, which fail `program_exit_zero` anyway.

**d7 after: `101 passed, 1 skipped, 4 xfailed` (RC=0).** Was `1 failed, 100 passed`.

d5 is unaffected — measured, not assumed: no GATE program names `em_current_authority.json`
(only `phase3_one_shot_runner`, which is not a gate program — d5's own known gap 2), so
the new anchor charges nobody. Live d5 stays **23 steps / 29 pairs / 70 rows**.

### The paired ratchets the declaration trips — all three, derived not typed

The ledger's own note on the `perc_sweep.json` precedent records that ITS declaring commit
carried none of them. This one carries all three.

**1. `test_matrix_63x8_ledger.py` entry-count pin.** Went red exactly as predicted:
`assert 183 == 182`, `Counter({'FILE': 131, 'GLOB': 28, 'ANY_OF': 24})`.
RE-DERIVED by the method the pin itself prescribes, not incremented — `flowref` driven at
the pre-edit yaml via `VIBE_IC_MATRIX_FLOW_YAML` and at the tip, (step, entry) SETs diffed:

```
before 182  after 183
ADDED  : [('25', 'reports/phase3/em_current_authority.json')]
REMOVED: []
```
A plain FILE, so GLOB (28) and ANY_OF (24) are untouched — which is what makes the
attribution checkable. Pin moved to 183 / FILE 131 with a dated derivation note.

**2. Anchored figures.** `gen_matrix_63x8_census.py --check-figures` named four:
```
[FAIL] matrix_63x8/README.md:156  {figure:required_output_entries} states 182; the tree says 183
[FAIL] matrix_63x8/flowref.py:72  {figure:required_output_entries} states 182; the tree says 183
[FAIL] matrix_63x8/flowref.py:76  {figure:required_outputs_file}   states 130; the tree says 131
[FAIL] matrix_63x8/flowref.py:88  {figure:required_output_entries} states 182; the tree says 183
```
Repaired by the generator (`--fix`), never by hand.

**3. d3 evidence manifest — and it was ALREADY RED ON BASE.**
`d3_manifest_declaration_parity_check` reported **7** uncovered paths, of which only ONE is
mine:
```
step 2:      reports/phase1/gates/stage_phase1_compliance.json
step 14:     reports/analog/stage_analog_compliance.json
step 15:     reports/phase2/gates/stage2_compliance.json
step 25:     reports/phase3/em_current_authority.json     <- mine
step 37:     reports/phase3/gates/stage3_compliance.json
step 37.5ip: reports/phase3/digital_hardmacro.json
step 39:     reports/phase3/gates/stage4_compliance.json
```
The other six were declared by `29e9c72796` [v1.13.96], which moved the yaml without the
manifest — the fourth instance of the pattern the ledger note already complains about.
Measured on the UNMODIFIED base worktree:
`test_d3_manifest_declaration_parity.py: 2 failed, 21 passed` — so this was a
**pre-existing main red** before I touched anything.

All 7 recorded **UNPROVEN**, with notes. UNPROVEN is the honest status, not a convenience:
no admissible run root is present in this checkout (all 15 in the manifest's `run_roots`
are absent — benchmark-data is an unpopulated submodule), the gates that write these files
postdate every published cell, and the copies of `em_current_authority.json` and
`digital_hardmacro.json` that DO exist on this host live in agent scratch trees, which the
manifest's `_admissibility` clause excludes by construction. Same outcome the precedent
records for step 31's `magic_illegal_overlap.json`: the finding moves from d7 to d3, and
the cell reports it unevidenced wherever a corpus is offered.

```
d3 declaration parity: 183 declared required_outputs path(s) across 66 step(s) with
outputs; 0 not covered by the manifest, 0 covered by an entry that records no usable
status                                                                        RC=0
```

## Step 17 — THE FLOOR FAMILY: all seven other dimensions swept

Method: AST sweep of every `assert <expr> >= <int|FLOOR_NAME>` and `> <int>` in all nine
dimension modules plus the four `test_matrix_63x8_*` modules — **34 sites** — then the live
LHS measured for each substantive one, and each site's own words read to decide what KIND
of bound it is. A "ratchet that cannot see loosening" is only a defect where the module
DECLARES the number to be the live baseline; a bound that says of itself that it is rough
is doing its job at 3x.

### Class A — live-baseline ratchets. THREE instances, all drifted, all re-derived.

| site | words that make it Class A | declared | live | slack |
|---|---|---|---|---|
| `d5 _DERIVED_DEP_STEPS/PAIRS/ROWS_FLOOR` | "the floor is the live baseline" | 12 / 16 / 32 | 23 / 37 / 92 | 1.9x / 2.3x / 2.9x |
| `d5 _DECLARED_DEP_STEPS/PAIRS_FLOOR` | "Live floors, same idiom as the layer-1+2 trio above" | 54 / 69 | 58 / 76 | 1.07x / 1.10x |
| `d6 _FLOW_DECLARED_OUTPUT_FLOOR` | "the denominator is pinned as a FLOOR and stated out loud" | 162 | 213 | 1.31x |

Re-derived to 23/29/70 (post-fix), 58/76, and 214 respectively, each with a dated note
saying what drifted and why a `>=` guard cannot see it. **Attribution measured, not
assumed**: at base `781d24727` the d6 figure is 213 and the d5 declared-dep figures are
58/76 — so all of that drift is PRE-EXISTING. This branch adds exactly +1 to the d6
denominator (step 25's new entry) and 0 to the d5 declared-dep pair, which reads
`required_inputs` while the declaration change touched `required_outputs`.

### Class B — deliberately rough collapse detectors. Correctly left alone.

Each says so in its own words, so re-deriving them to live would misread them AND make
them brittle:

| site | live vs bound | its own words |
|---|---|---|
| `d7:416 len(write_index()) >= 100` | 295 (2.95x) | "Index sizes: **a rough floor**, so a scan that collapses to a handful of entries fails here" |
| `d7:420 len(lit) >= 500` | 885 (1.77x) | same comment; "literal index **collapsed** to ..." |
| `d7:1545 len(limit) > 60` | 2144 (35.7x) | a prose-length non-triviality check, not a population |
| `d6:1985 len(l3) >= 40` | — | "L3 ... has **nearly no subject left**" |
| `d6:2343 len(audited) >= 60` | — | "its subject **has collapsed**" |
| `d6:1057 len(chain) >= 3000` | — | an exact semantic bound: the region must not be SHORTER than the 3000-byte window it replaces |
| `d1:1441 len(total) >= 50` | — | secondary; the load-bearing line above it is `total == declared`, an EQUALITY, which cannot go slack |
| `d1:1451 len(biggest) >= 100` | — | "the P0 umbrella is **supposed to carry** the structural gate set" |
| `d5:1457 len(prod) >= 150` | 214 | test is named `..._is_live_and_non_empty`; the message prints the live figures |
| 20 further `> 0` / `>= 1` / `>= 2` / `>= 3` sites | — | non-emptiness guards, not baselines |

**The family is three, not one — and it is confined to d5 and d6.** d1, d2, d3, d4, d7, d8,
d9 and the four `test_matrix_63x8_*` modules carry no live-baseline floor at all; every
one-sided bound they hold declares itself rough. That is the answer to "a family is never
one instance": the instance count is 3, and the reason the other seven are clean is that
they never made the claim, not that nobody checked.

## Step 18 — census REGENERATED on a quiet, clean tree: CONTRADICTED = 0

Two earlier regeneration attempts were VOID and are recorded rather than dropped: both
tripped the generator's inner `suite_write_guard` — "this pytest session WROTE INTO THE
TREE" — because the tree was edited while the generator's own pytest run was in flight
(the `--fix` run rewrote the anchored figures under itself; the next run caught my floor
edits). Re-run on a committed, untouched tree:

```
[PASS] 63x8 derived figures fresh: 57 anchored figure(s) re-derived across 36 corpus file(s).
wrote .../matrix_63x8/README.md: ENFORCED own=18 substituted=116 undeclared=398;
CONTRADICTED=0 NOT-MEASURED=53 WAIVED=8 NA=19; 612 cells (612/612 accounted).   RC=0
```

**612 cells: 532 ENFORCED, 0 ENFORCED-CONTRADICTED, 8 WAIVED, 19 NA, 6 NOT_MEASURED,
45 ENFORCED-SKIPPED, 2 WAIVED-SKIPPED.**

| dim | main 781d24727 | this branch |
|---|---|---|
| 5 `deps_correct` | undeclared 61, **CONTRADICTED 6** | undeclared 67, **0** |
| 7 `outputs_list_complete` | undeclared 63, CONTRADICTED 0 (published) / **1** (measured live) | undeclared 63, **0** |
| total | 526 ENFORCED / 6 CONTRADICTED | 532 ENFORCED / **0** |

## Step 19 — final verification, clean committed tree, one run

```
test_matrix_63x8_census_freshness.py
test_matrix_d5_deps_correct.py
test_matrix_d6_skip_discipline.py
test_matrix_d7_outputs_list_complete.py
test_d3_manifest_declaration_parity.py
test_matrix_63x8_ledger.py
test_matrix_write_record_scope.py
test_submission_template_check.py
=> 429 passed, 1 skipped, 6 xfailed in 523.66s   RC=0
[PASS] suite_write_guard: this pytest session wrote nothing `git status --porcelain` would show.
```

The census FRESHNESS gate passing is the load-bearing one: it re-derives the whole census
and diffs it against the committed block, so `CONTRADICTED=0` is a regenerated fact, not a
written number.
