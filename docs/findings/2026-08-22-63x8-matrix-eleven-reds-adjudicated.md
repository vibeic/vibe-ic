# The eleven 63x8 reds: ONE cause for six of them, and it is already pinned in the module

_Measured 2026-08-22 on host `8hd-3`, against `origin/main` at `a4caccefe`
[v1.11.69], in a fresh detached worktree at `/tmp/jrm`, `PYTHONDONTWRITEBYTECODE=1`,
one pytest process per measurement, each with its own `--basetemp`. No design, PDK,
vendor or part identifier appears; `sky130A`, `gf180mcuD` and `ihp-sg13g2` are open
PDKs._

**Nothing here is a fix.** Every one of the eleven ids is still red on this base, and
this file states, per id, what it is red FOR, which of the two measurement lanes it is
red in, and which of its remedies were run rather than reasoned about. Three decisions
that only the operator can take are stated at the end with their measured costs.

## The eleven, and the two lanes they were measured in

Two lanes, because the answer differs between them and the difference is the story.
`tools/ci/hermetic_candidate_runner.py:99-102` sets `VIBE_IC_BENCHMARK_DATA=/corpus`
for the landing test process, so the LANDING lane runs corpus-BOUND. The enumeration
that produced the 57-red list ran with the pointer UNSET
(`tools/ci/J63B_63X8_RED_SET.md:1528`), i.e. BLIND.

| # | id | UNBOUND | BOUND |
|---|----|---------|-------|
| 1-6 | `test_matrix_d3_outputs_produced::test_d3_required_outputs_are_produced[15,17,19,20,30,32]` | RED | RED |
| 7-8 | `test_matrix_mutation_ledger::test_every_enforced_cell_carries_a_named_mutation[0.5ic,1.6x]` | RED | RED |
| 9 | `test_matrix_mutation_ledger::test_the_coverage_is_complete_and_the_count_is_stated` | RED | RED |
| 10 | `test_matrix_63x8_coverage::test_every_na_cell_asserts_a_live_precondition` | RED | RED |
| 11 | `test_matrix_63x8_coverage::test_no_cell_is_counted_enforced_while_its_predicate_is_red` | RED | RED (different mechanism — NORECORD, below) |

The BOUND arm used `/tmp/jrm_corpus/benchmark-data` — a detached worktree of this same
repository at `9167b162e`, a branch commit that still carries the pre-split
`benchmark-data/` subtree (17210 tracked files). It is NOT a clone of
`vibeic/benchmark-data`; it is the youngest real corpus reachable on this host, and
`run_roots()` discovers **10 admissible run roots** in it, so the BOUND arm is a real
measurement and not a fixture.

Whole-file counts, same base, same host:

```
UNBOUND   test_matrix_d3_outputs_produced.py     6 failed,  52 passed, 61 skipped
BOUND     ...::test_d3_required_outputs_are_produced   9 failed, 58 passed, 2 xfailed
UNBOUND   test_matrix_mutation_ledger.py         3 failed, 121 passed,  2 skipped
BOUND     test_matrix_mutation_ledger.py         3 failed, 123 passed
```

**Binding a corpus closes none of the eleven and reveals three more d3 cells**
(`0.5ic`, `1.6x`, `31`). The blind lane reports those three as skips. So the 57-red
census on main is computed over a population where **61 of 69 dimension-3 cells
declined to look**, and three of them are red when they do.

## Reds 1-6 — ONE cause, and the module already names it

All six fail on the same clause. Quoted red, `step15`, UNBOUND:

```
E  AssertionError: step 15 (Floorplan + PDN): 1 declared output(s) cite a run root
E  NO corpus can supply, so the corpus-absent skip must not cover them:
E    'phase3/stage3/pnr/floorplan.def': NOT DETERMINED — the record wants
E    'phase3/stage3/pnr/floorplan.def' from run root
E    'campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721' (kind 'home'), which
E    this dimension searches on no host
```

BOUND, the same six fail through the other branch, and there the module says the
cause outright — the REMEDY CHECK clause fires on **exactly six entries, in exactly
these six steps, and on no other failing cell**:

```
step   missing entries   entries carrying REMEDY CHECK
0.5ic        4                     0
1.6x         1                     0
15           1                     1
17           1                     1
19           1                     1
20           1                     1
30           2                     1
31           1                     0
32           1                     1
                            total  6
```

> REMEDY CHECK (vibe-ic#1349): the run-tree half of that choice is NOT AVAILABLE for
> this entry. No alternative of it lands inside the scope `benchmark_evidence_publish`
> stages … Staged scope: `['phase1', 'phase2', 'phase3/analog', 'phase3/reports',
> 'phase3/stage4/gds', 'reports']` + files `['RESULT.md', 'provenance.jsonl']`.

**The cause in one sentence: every one of the six entries lives under
`phase3/stage3/`, the one subtree `benchmark_evidence_publish` deliberately does not
stage, so no cell that program publishes can ever carry it.** The publisher says so in
its own docstring (`benchmark_evidence_publish.py:82-86`), and names four of the six
paths while doing it:

> Raw PnR scratch under phase3/stage3 is still not staged: that is a decision about
> what counts as evidence … Widening it is an evidence-policy call, not a size call,
> and is deliberately left alone here.

This is not a discovery. The module carries the population as a shipped, tested pin,
`UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT`
(`test_matrix_d3_outputs_produced.py:4597`), and its guard
`test_d3_the_run_tree_remedy_is_withdrawn_where_the_publisher_cannot_stage_it` is
`@needs_corpus`, so on the blind lane it never runs. **The six brief ids ARE that
pin.**

### The partition is caused by the publish scope and nothing else — perturbed

`publishable()` called directly, same base, corpus bound:

```
as declared   'phase3/stage3/pnr/floorplan.def'                        -> False
+ ' OR reports/floorplan.def'   (an IN-scope alternative)              -> True
+ ' OR steps/floorplan.def'     (an OUT-of-scope alternative)          -> False
```

Adding an in-scope alternative flips it; adding an out-of-scope one does not. Nothing
else in the entry changed.

### The other two remedies were RUN, not reasoned about

* **Re-point the record at a root that carries the artefact.** The two cited roots are
  `campaign_pdk/spm/pdk_portability_ihp-sg13g2_20260721` and
  `AI_IC_design/4th_benchmark/{cv32e40p,ibex}_e2e`, both `kind: home`. Neither exists
  on this host. Searched every `benchmark-data` tree reachable from `$HOME` — **20 of
  them** — for the seven cited artefacts (`floorplan.def`, `placed.def`,
  `post_cts.def`, `post_hold.def`, `eco_trigger_decision.json`, `critical_path.sp`,
  `correlation.json`): **0 hits in 0 trees.** The artefacts exist in quantity in agent
  scratch trees, which the manifest's own `_admissibility` note excludes by name.
* **Waive.** Refused, for the reason `matrix_63x8/waivers.py` gives: a waiver admits a
  cell is not enforceable. These cells are enforceable and the module decides them
  correctly; it is the RECORD that is wrong. A waiver retires only when the predicate
  passes, which needs the publish decision anyway, so waiving removes the prompt and
  keeps the debt.

### A LATENT red the pin does not cover, found while checking it

The pin is a snapshot of what is UNEVIDENCED, which depends on which corpus is
bound — that is why its guard is `@needs_corpus`. Being UNPUBLISHABLE depends on
neither: it is the flow declaration against the publish scope. Measured over the whole
flow with the pointer unset, `publishable()` is False for **40** declared entries, of
which **24 sit in cells dimension 3 ENFORCES** (the other 16 are in dormant NA cells).

Each of the 24 run through `check_entry` with the corpus bound:

```
16  PRODUCED [LIVE]
 6  NOT PRODUCED [FIXTURE]   <- exactly UNEVIDENCED_OUTSIDE_THE_PUBLISH_CONTRACT
 2  NOT PRODUCED [LIVE]      <- step 0.5ic, recorded UNPROVEN, so the FIXTURE
                                branch never applies and the other pin cannot
                                see them however the corpus moves
```

The sixteen resolve against tracked artefacts under prefixes the publisher does not
stage — exactly what `_PUBLISH_GAP` warns of: *"the tracked artefacts under this
prefix all come from pre-program hand-staged trees."* **Re-publishing those cells with
the program instead of by hand takes sixteen entries from evidenced to unevidenced in
one commit, and the eight not-produced become twenty-four.**

_Correction: an earlier revision of this section said nine and three. Those were
arithmetic off the failing-cell list rather than off the entries; the numbers above are
per-entry measurements._

## Red 10 — a doctrine collision, bisected to one commit

```
E  AssertionError: 2 NA problem(s):
E    - dimension 3: cell test test_d3_required_outputs_are_produced: pytest.skip()
E      at line 2309. A cell test may not skip: the three states are ENFORCED,
E      WAIVED (strict xfail) and NA (asserted precondition)
E    - dimension 7: cell test test_d7_required_outputs_list_is_complete: pytest.skip()
E      at line 375. …
```

Bisected against the commit that introduced the skip, two worktrees, same host:

```
0f8350003  "test: a check over an absent corpus must SKIP, not FAIL"   1 passed in 9.17s
c8c2ab0f7  "test: apply the corpus-absent skip only where it is
            MEASURED to be needed"                                     1 failed in 8.50s
```

`c8c2ab0f7` (2026-08-16) applied one shipped doctrine — *a check over an absent corpus
must SKIP, not FAIL* — **inside two 63x8 CELL tests**, and that is the one place a
second shipped doctrine forbids it. The ban is not incidental: the coverage module
states it twice, once as this test's check (3) and once as an assertion on the state
vocabulary itself —

> `test_matrix_63x8_coverage.py:695`: *"A fourth state is exactly the escape hatch the
> three-state rule forbids"*

so there is no in-vocabulary state for "this checkout carries nothing to read".

### The obvious revert was RUN, and it costs 49 confident-wrong reds

Throwaway worktree, both `pytest.skip(SKIP_REASON)` calls replaced by a fall-through
so the predicate runs:

```
before   test_matrix_d3_outputs_produced.py + test_matrix_d7_outputs_list_complete.py
           6 failed
after    55 failed, 147 passed, 15 skipped, 6 xfailed
```

The 49 new reds each assert *"N required_outputs are NOT produced"* over `0 admissible
run roots searched: []` — the failure mode `run_roots()`'s own docstring already
records at `ee849c19e` and calls *"not a stricter answer, it is a confident wrong
one"*. **Reverting is worse than the defect.**

## Red 11 — the union of the other ten, and it conflates two populations

```
E  Failed: 55 of 621 cells are reported in a state their own live predicate
E  contradicts (6 measured red, 49 not measured):
E  MEASURED RED — the predicate ran and contradicted the state (6). These are repo defects:
E    15/d3, 17/d3, 19/d3, 20/d3, 30/d3, 32/d3   … the live run says failed
E  NOT MEASURED — the predicate never returned a verdict (49). NOT evidence of
E  enforcement either, but a missing dependency or a collection error is a HOST
E  problem, not a repo defect. …
E  STATE-ONLY census (what used to be published): {'ENFORCED': 591, 'WAIVED': 11, 'NA': 19}
E  TWO-AXIS census (what is true): {'ENFORCED': 539, 'WAIVED': 8, 'NA': 19,
E                                   'ENFORCED-SKIPPED': 46, 'WAIVED-SKIPPED': 3,
E                                   'ENFORCED-CONTRADICTED': 6}
```

Its 6 MEASURED RED are reds 1-6. Its 49 NOT MEASURED are red 10's two skips seen from
the other side. It has no cause of its own. It does, however, block on a population
its own message says is not a repo defect — see decision 3.

## Reds 7-9 — not waiting on a corpus, and both offered remedies are unavailable

```
E  AssertionError: step 1.6x: 1 cell(s) enforce nothing anyone has shown can fail:
E    - 1.6x/d3:outputs_produced is ENFORCED and NO mutation in
E      matrix_mutation_ledger.MUTATIONS was measured to redden it. A green cell with
E      no reachable red is a certificate, not a measurement.
E  AssertionError: 2 ENFORCED cell(s) carry no measured mutation: ['0.5ic/d3', '1.6x/d3']
```

Identical bound and unbound (`3 failed, 123 passed` / `3 failed, 121 passed`), so they
are not evidence-starved. What the BOUND arm adds, and it changes the reading: **with a
corpus bound, `0.5ic/d3` and `1.6x/d3` are RED** — their cells fail, every entry
`UNPROVEN` and resolving nowhere. A cell that is already red does not need a mutation
to prove it can go red; it needs its own defect closed. Their entries ARE publishable
(`reports/phase1/*.json`, `reports/crosslayer/rewrite_equivalence_check.json` all
return `publishable=True`), so unlike reds 1-6 these two are closable by a published
run — `1.6x` is simply a step no published run predates.

`applies_to` may not be widened without a measured green-to-red transition (LOCK 3),
and no such transition is producible: replay is `ALREADY_RED` with a corpus and
`NOT_REPLAYABLE` without one.

## Two reds that ONLY the bound lane can see — and one of them is a real defect

`test_no_cell_is_counted_enforced_while_its_predicate_is_red` does not even reach its
census when the corpus is bound. It refuses first:

```
E  AssertionError: the nested outcome run produced red test report(s) outside the
E  matrix cell join. Its rc=1 is not completely represented by the cell census, so
E  this run is NORECORD:
E    test_d3_evidence_is_live_wherever_the_run_root_exists            failed
E    test_d3_the_compliance_audit_does_not_create_declared_outputs    failed
```

Both are `@needs_corpus` guards, so the blind lane never runs them. Run alone, bound:

```
E  AssertionError: 157 of 164 declared entries were verified live; 134 are backed by
E  run trees committed to this repo and that number is host-independent by
E  construction (#527). More than 134 means evidence is coming from outside the
E  commit again.   assert 157 == 134
```

— a pin whose own text says the number is host-independent while the number it pins
depends on WHICH corpus is bound. It is not a finding about the tree, and it is
reported here as a pin that has gone dark rather than as a defect.

```
E  AssertionError: the set of declared required_outputs that a COMPLIANCE AUDIT
E  creates in the tree it audits changed.
E    measured: {'benchmark-data/ic/spm/v1.9.96_gf180mcuD':
E                  ('31::reports/phase3/magic_illegal_overlap.json',), …}
E    pinned:   {'benchmark-data/ic/spm/v1.9.96_gf180mcuD': (), …}
E  Newly self-certified: {'…v1.9.96_gf180mcuD': ['31::reports/phase3/magic_illegal_overlap.json']}
E  A gate clause is now producing an artefact the same audit then reports as present.
```

**That one IS a defect, and it is invisible to every lane that runs blind.** Step 31's
gate clause writes `reports/phase3/magic_illegal_overlap.json` into the tree the same
audit then measures — self-certification, the exact failure the guard exists to catch.
Step 31 is also one of the three cells that go red only when the corpus is bound. This
is filed as a ledger row here rather than fixed: it is outside the eleven ids this work
was scoped to, and closing it means moving a producer out of a gate clause into the
runner that owns the step.

Caveat, stated because it bounds both rows: the bound arm used a worktree of THIS
repository at `9167b162e`, not a clone of `vibeic/benchmark-data`. The corpus worktree
was checked after every run and is byte-clean (`git status --porcelain` -> 0 lines), so
nothing here was measured against a tree these runs had modified.

## What was NOT done, and why

No test was made green. No assertion was weakened, no case deleted, no exemption added
or re-dated, no baseline written. No fix is claimed, so no break-the-fix control is
offered — instead every classification above carries the run that produced it, and the
one causal claim (publish scope decides the partition) carries a two-directional
perturbation.

