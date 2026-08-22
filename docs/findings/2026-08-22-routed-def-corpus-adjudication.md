# The routed-DEF corpus is empty because it was emptied, and the gate should stay BLOCKING

Adjudication of the one NOT CHECKED row on `origin/main` that carries no exemption:

```
NOT CHECKED (rc 2, BLOCKING; no exemption):
corpus "published cells carrying a routed DEF" is EMPTY — nothing was checked over it
[population: producer rc 0, 0 items]
```

Measured 2026-08-22 on a clean worktree of `origin/main` @ `81cd5321b`
(`git clean` tree, `PYTHONDONTWRITEBYTECODE=1`).

## Verdict

**The corpus is legitimately empty right now.** The producer is correct, its path
is correct, and it is asking the right question of the right repository. It
returns zero because **every artefact that used to answer it was withdrawn on
purpose two days ago.**

Not "the producer is wrong" and not "the artefacts are under another name". Both
were checked against the artefacts, not against the producer's intent.

**CORRECTED 2026-08-22, later the same day.** The verdict above stands and the
withdrawal is real, but it was only *half* the reason the population is zero, and
the half it missed is the one that mattered. This document originally claimed the
gate was "satisfied again by one publication … with nothing in this repository
changed." That was never measured, and it is false: `benchmark_evidence_publish.py`
— the program that publishes a cell — does not stage `phase3/stage3/` at all, so
**no cell it has ever produced could be a member of this corpus.** The one member
the corpus ever held was hand-staged. See
[Correction: the satisfaction condition was unreachable](#correction-the-satisfaction-condition-was-unreachable),
which supersedes the paragraphs marked below.

## What was measured

### 1. The producer resolves the right tree, and the tree is real

`tools/ci/routed_def_corpus.py` resolves through `_corpus_location.resolve()`,
which follows `$VIBE_IC_BENCHMARK_DATA` to a clone of the published-corpus
repository. That repository is the one `routed_def_corpus._ORIGIN` names,
`https://github.com/vibeic/benchmark-data.git`, and a clone of it is present on
this host at the same default path the landing verifier uses
(`tools/gatekeeper-verify-merge.sh:prepare_benchmark_snapshots` →
`$HOME/_matrix_benchmark_data`). Its `origin` remote is that exact URL.

### 2. Pointed at the real corpus, the answer is still zero

```
$ VIBE_IC_BENCHMARK_DATA=<clone> python3 tools/ci/routed_def_corpus.py --repo <repo>
[routed-def corpus] note: VIBE_IC_BENCHMARK_DATA overrides <repo>/benchmark-data/ic -> <clone>/ic
rc=0, 0 items
```

Against the corpus repository's own tip, freshly fetched on 2026-08-22
(`origin/main` = `3b58ccd42`):

| query | result |
|---|---|
| `git ls-tree -r --name-only origin/main \| grep -c 'routed\.def'` | **0** |
| `git ls-tree -r --name-only origin/main -- ic/ \| grep -c 'phase3/'` | **0** |
| `v<version>_<PDK>` published cell directories under `ic/` | **0** |
| what remains under `ic/<design>/` | `input/` only |

So the population is zero at the published tip, not merely zero in this checkout.

### 3. It was not always zero, and it was emptied deliberately

At `bcf2f94^` the corpus contained exactly one member:

```
ic/spm/v1.5.58_ihp-sg13g2/phase3/stage3/pnr/routed.def
```

Relative to the `ic/` prefix that is `spm/v1.5.58_ihp-sg13g2/phase3/stage3/pnr/routed.def`
— six components, with `parts[2:] == ("phase3", "stage3", "pnr", "routed.def")`,
which is **exactly** the shape `routed_def_corpus._index_paths` matches. The
producer's query was matching this artefact until it stopped existing.

It stopped existing in the published-corpus repository at commit `bcf2f94`,
2026-08-20 19:28 +0800, *withdraw all four published cells, and write down what
may be published here*, whose first line is an owner instruction dated
2026-08-20: remove the current `ic` results, none of them is a pass. That commit
removed 1387 files and recorded, per cell, the measurement it was removed on —
two of the four carried a passing verdict over an audit in which none of 246
registered gates had run.

`ic/<design>/input/` was left in place on the stated ground that a design input
is not a result. That is why `ic/spm/` still exists while the population is zero.

### 4. The gate has therefore been unable to check anything since 2026-08-20

The wiring that makes an empty population a blocking dispatcher-owned refusal —
`routed_def_corpus.py`, `GATE_DISPATCH_ATTEST_POPULATION=1` at the wiring site,
and the `nunexempted` exit-2 branch in `_gate_dispatch.sh` — all arrived
together on 2026-08-18 in v1.10.69 (`7c376e348`). The corpus was withdrawn on
2026-08-20. The window in which this gate could have examined a cell was those
two days, and only for a run that had the corpus pointer bound.

## What would have to exist for this gate to check anything

One file, published into the corpus repository:

```
ic/<design>/v<plugin-version>_<PDK>/phase3/stage3/pnr/routed.def
```

with the rest of that cell beside it — the same shape `spm/v1.5.58_ihp-sg13g2`
had. Concretely, all of:

1. A run that reaches an independently re-derived Overall `PASS` or
   `PASS_WITH_WAIVERS`, staged by `benchmark_evidence_publish.py`, which
   refuses to stage a non-converged run.
2. Exactly one completion audit per cell, at `reports/audit/…` — the withdrawal
   commit named a second audit one directory too deep, reading FAIL 3.5 s before
   the PASS the public page displayed.
3. A non-zero `passed_gate_count`: a verdict is not evidence. Two of the four
   withdrawn cells carried a passing verdict over 0 gates actually run.
4. The cell committed under `v<plugin-version>_<PDK>`, validated by
   `benchmark_evidence_structure_check.py`.

The moment one such cell lands in the corpus repository and the pointer is
bound, this loop expands to a real population and the four per-cell gates
(`macro OBS not crossed`, `DRC PASS is not vacuous`, `inner FAILs reach the
verdict`, `new tool diagnostic id`) become live verdicts.

> **SUPERSEDED — the two paragraphs that stood here claimed this happened "with
> nothing in this repository changed", and that the gate was "satisfied again by
> one publication". Neither was measured and both are false. Read
> [the correction](#correction-the-satisfaction-condition-was-unreachable)
> instead; list items 1-4 above are still necessary, they were just not
> sufficient.**

## Decision: BLOCKING stays, and it buys no exemption

Neither of the two instruments is the right one.

**Not an exemption.** `uncheckable_until` exists to buy a dated tolerance for a
gate that reports NOT_CHECKED. Attaching one here is refused by construction —
`_dispatch` mode 2 raises a wiring error, *"a dispatcher-owned population
refusal … cannot consume an uncheckable exemption — an unknown denominator must
remain blocking"* — and that refusal is right for the reason
`repo_hygiene_gates.sh` already records against this exact corpus: the last time
these four gates were absorbed under exemptions, all four stated reasons were
FALSE, and the empty-population refusal was the only thing left that could
notice. An exemption dated into 2027 would restore precisely that silence.

**Not a declaration change.** This row is now the only statement anywhere on
`main` that post-route geometry is checked over nothing at all. Downgrading it
to advisory would let the project ship with zero published post-route evidence
and no signal saying so — and, worse, would still be advisory on the day the
corpus refills, i.e. it would stop blocking exactly when it regains the ability
to find something.

So the honest declaration is the one already there. The row is true, it is the
correct verdict for a zero population, and it should stay red until a cell is
published. What was missing is not a change to the gate; it is this record of
*why* it is zero, which existed nowhere in this repository. A reader who hits
the row today is told `EMPTY` and has no way to learn that the population was
withdrawn by instruction on 2026-08-20 or what would restore it.

This agrees with the adjudication already written into `gatekeeper_review.py`
(2026-08-20), which rejected softening the empty-corpus refusal on cited
evidence and resolved the corpus in the review arm instead. That note predates
the withdrawal by a few hours and so does not record it; this one does.

## Two things this adjudication does not do, and why

**It does not change the declaration or the producer.** `routed_def_corpus.py`,
`repo_hygiene_gates.sh`, `_gate_dispatch.sh` and `_corpus_location.py` are all
inside `REQUIRED_AUTHORITY_PATHS` in `tools/ci/protected_landing_transition.py`.
The merge verifier reads that manifest from the BASE commit and refuses a
candidate whose protected bytes BASE does not already authorise, so both
instruments the question offers are unavailable to any candidate commit: they
can only move through a base-authorised PREPARE/ACTIVATE transition. That is not
an obstacle to route around — it is the reason a single agent cannot quietly
retune the landing runtime, and it applies to this agent too.

**It does not publish anything to make the corpus non-empty.** Making this row
green by putting a routed DEF where the producer would find it, without a
converged run behind it, is the exact defect the withdrawal commit removed four
cells for.

## One defect found while proving the above, filed not fixed

`routed_def_corpus.main()` hardcodes `may_be_absent=True` when it calls
`_corpus_location.refuse()`. That module's own contract says the opposite, in
its docstring: *"THE OPT-IN IS A FLAG THE CALL SITE PASSES, NEVER A DEFAULT …
an rc 0 for a scan that did not happen is the false certificate this whole gate
suite exists to remove, and the only thing keeping it from becoming the general
answer is that somebody has to type it."* Every sibling consumer takes it as a
CLI flag — `gatekeeper-land.sh` passes `--corpus-may-be-absent` to
`benchmark_evidence_structure_check.py` explicitly.

The consequence is that two of the four outcomes `_corpus_location` exists to
keep apart reach the dispatcher as the same bytes, rc 0 with zero items:

| situation | producer stdout/rc | row the reader sees |
|---|---|---|
| corpus supplied, measured, contains no routed DEF | rc 0, 0 items | `is EMPTY — nothing was checked over it` |
| no corpus supplied, nothing scanned at all | rc 0, 0 items | `is EMPTY — nothing was checked over it` |

Both were reproduced above. In the second row that sentence asserts a
measurement that was never taken; the producer says so on **stderr**
(`NO_CORPUS: … point VIBE_IC_BENCHMARK_DATA at a clone to make this gate check
something`) and the roll-up does not carry it. Today, on `origin/main` with no
pointer set, the one blocking row on the board states the wrong reason for its
own redness — which is why this reads as a publishing question when it is first
a configuration question.

The fix is to give the producer the flag its own module contract requires,
default `False`, and decline it at the hygiene wiring site. Then an unconfigured
checkout is rc 2 with the missing input named, and `EMPTY` is only ever printed
over a corpus that was actually read. **It moves rc 0 to rc 2 — strictly harder
to satisfy, never a pass** — but it edits two protected authority files, so it
belongs to a base-authorised transition and not to this commit.

## A second defect, found by writing the guard this adjudication rests on

The argument above leans on one structural fact: an `uncheckable_until` armed in
front of an attested-population loop **cannot** be consumed by the population
refusal, because `_dispatch` mode 2 rejects it. That fact was **unpinned** —
every existing empty-corpus test drives the loop with no exemption armed
(`test_empty_corpus_gate_keeps_the_array_invariant`,
`test_issue1025_empty_corpus_sweep_blocks`, `test_issue1075_...`), so deleting
the branch that rejects it changes none of their verdicts.

Stated precisely, because the two halves were measured separately. In place on
this branch those three files are green (24 passed, 1 xfailed, together with the
new one). Against the mutated dispatcher they are **verdict-identical to the
control**: repointed at the mutant, 4 failed / 17 passed; repointed at an
unmutated copy, the same 4 failed / 17 passed. Those four failures are the
repointing harness, not the mutation — the files build their own repo scaffold
and an absolute dispatcher path breaks it — which is exactly why the control arm
was run before believing the mutant arm. The mutation moves nothing in them.

`test_population_refusal_cannot_be_bought_off.py` pins it. Measured by deleting
that one `elif` from a **copy** of the dispatcher (the tracked file was not
touched; `sha256 bc52987b…` unchanged before and after):

| | guard present | `elif` deleted |
|---|---|---|
| exit code | **2** | **0** |
| `wiring_errors` | 1 entry | `[]` |
| roll-up says | `NOT a pass` | `(exempt until 2999-01-01)` |
| `not_checked_unexempted` | `[]` | `[]` |
| row `exempt_until` | `2999-01-01` | `2999-01-01` |

One deleted `elif` turns the only blocking row on the board into a silent
exit-0 pass with a date on it.

**And look at the bottom two rows: they are identical in both columns.** The
dispatcher raises the wiring error and then appends the date to `GATE_EX_UNTIL`
anyway, so even in the guarded run the record states the *refused* exemption as
a *granted* one — `exempt_until: "2999-01-01"`, `exemption_expired: false`, and
`not_checked_unexempted: []` for the row it had just declared unexemptable. The
printed line for that same row says `BLOCKING; no exemption`. The console and
the record give opposite answers about the same gate.

Nothing is unsafe today only because `gatekeeper_review`, `repo_hygiene_parallel`
and `hygiene_finding_delta` each independently refuse on `wiring_errors`. But
`not_checked_unexempted` is the field NAMED for this question, and
`gatekeeper_review`'s own comment documents it as the **fail-safe** derivation —
"every NOT_CHECKED in it reads as UNEXEMPTED and refuses … the opposite default
would make 'hand a record in the old format' the way to buy silence". Here it
fails the other way: a date that was never granted defeats the fail-safe, and
the whole refusal rests on one unrelated field staying fatal in every consumer
forever.

The fix is one line — append `""` instead of `$ex_until` on the refused branch,
which is strictly tightening and cannot turn any red green. `_gate_dispatch.sh`
is a protected authority file, so it is **filed, not fixed**, and pinned as a
`strict` xfail that will go RED (XPASS) the day it is repaired.

## Correction: the satisfaction condition was unreachable

Everything above this heading was written without asking the one question that
decides whether the row is honestly BLOCKING: **can the supported publishing path
actually produce a member of this corpus?** It cannot, and could not on any day
in the gate's history.

### What the producer selects on

`tools/ci/routed_def_corpus.py` builds the entire population from one path shape
inside the published tree — `_index_paths` matches a path of exactly six
components under `ic/` whose tail is `("phase3", "stage3", "pnr", "routed.def")`:

```
ic/<design>/<version>/phase3/stage3/pnr/routed.def
```

### What the publisher stages

`benchmark_evidence_publish.py` is the program `PUBLISHING.md` names as the one
that stages a converged run into a cell ("You do **not** hand-assemble an evidence
folder"). Its `_COPY_SUBTREES` is:

```python
("phase1", "phase2", Path("phase3") / "reports", Path("phase3") / "analog", "reports")
```

`phase3/stage3` is not in it and never was. Its own docstring said so and named
the consequence without connecting it to this gate:

> Raw PnR scratch under phase3/stage3 is still not staged … NOTE that the three
> hand-staged reference cells DO carry `phase3/stage3/pnr/routed.def` … so on that
> subtree this program still publishes less than they do.

### Measured, not read

A synthetic converged run, published through the supported path with no flags,
carrying a routed DEF of 38 bytes — six orders of magnitude under the 50 MB
`_SIZE_CEILING`:

```
SOURCE   routed.def exists: True  38 bytes
PUBLISHED routed.def exists: False
any .def anywhere in the published cell: []
phase3/ subtree actually staged: ['reports', 'stage4']

LAYOUT_ROUTING.txt:
phase3/stage3/pnr/routed.def  38B  sha256:fee7400…  NOT_PUBLISHED  source-run-only
phase3/stage4/gds/top.gds    704B  sha256:b987ad6…  STAGED         in-cell
```

`NOT_PUBLISHED source-run-only` — not `ROUTED_AWAY`. It is not a size decision:
the size rule never saw the file, because the directory it lives in is not
published at any size. The GDS beside it, 704 bytes, staged.

### So the corpus had exactly one member and it could not have had a second

`ic/spm/v1.5.58_ihp-sg13g2/phase3/stage3/pnr/routed.def` entered the published
repository in its initial `snapshot: vibe-ic benchmark results, no history`
import — a hand-staged legacy cell, from before the publishing program — and left
in `bcf2f94`. Across the whole history of that repository, `git log --all
--diff-filter=A -- '*.def'` returns that one path and nothing else. No cell
`benchmark_evidence_publish.py` has ever produced was a member, and none ever
could have been.

That is the brief's option (3) after all, arrived at from the publishing side
rather than the producing side: **the artefacts exist under a path the supported
publisher does not write.** The producer is asking the right question of the right
repository — the writer was never able to answer it.

### What this changes about the adjudication, and what it does not

**It does not change the decision.** BLOCKING stays and it still buys no
exemption, for every reason in the section above. Nothing here makes the gate
pass: the corpus is still empty, the row is still `rc 2 NOT CHECKED`, and it still
blocks.

**It changes what the row is a statement about.** Before the repair, "NOT CHECKED,
BLOCKING, no exemption" was a permanent verdict wearing a temporary one's clothes.
Every list item in *What would have to exist* was necessary and none of them was
sufficient, so a reader following that list to the letter — publish a converged
cell, structure-check it, land it — would have produced a cell, bound the pointer,
and watched the row stay `EMPTY`, with nothing in the record to say why.

### The repair, and its exact boundary

`_ROUTED_DEF_RELPATH` in `benchmark_evidence_publish.py` stages
`phase3/stage3/pnr/routed.def`, size-routed exactly like the GDS. This is the same
omission the GDS block already carries its own comment about, one artefact over:

> `phase3/stage4` is not a copy subtree, so until this existed the GDS was omitted
> at EVERY size — the size routing could not reach the one artefact the manifest
> is actually about.

**One artefact, not the subtree.** `placed.def`, `floorplan.def`, `post_cts.def`,
the stage's `.tcl` and `phase3/stage3/extracted/*.spef` all stay `NOT_PUBLISHED`.
Widening published scope to raw PnR scratch remains the evidence-policy call the
docstring defers, and it is still deferred. A routed DEF over the ceiling is still
`ROUTED_AWAY`, because the guard that blocks the commit is a size rule and a cell
that ignored it would not land.

It is a restoration rather than a new policy: the hand-staged reference cells
carry this file, and on the rest of that subtree the program still publishes less
than they do.

### Pinned

`programs/tests/test_routed_def_corpus_is_reachable_by_publishing.py`, four arms,
all four RED before the repair:

| arm | subject | before |
|---|---|---|
| A | the DEF reaches the cell at the path the producer selects on | cell held `[]` `.def` files |
| B | CONTROL — an oversize DEF is `ROUTED_AWAY`, not staged | recorded `NOT_PUBLISHED`; the ceiling never saw it |
| C | CONTROL — the rest of the PnR scratch stays unpublished | staged `.def` set was `[]`, not `['routed.def']` |
| D | `routed_def_corpus.py` itself COUNTS the published cell | producer rc 0, stdout `[]` |

ARM D is the load-bearing one, and the reason this is not a file-copying test: it
runs the gate's own producer over a real git checkout of the published tree. A
file at a path is not a population member until the producer says it is.

### The condition, restated so it is now true

One converged cell, meeting items 1-4 of *What would have to exist*, **published
by a `benchmark_evidence_publish.py` that carries this repair**, with its routed
DEF under the 50 MB ceiling. Cells published before it will not become members
retroactively; the artefact was never staged, so there is nothing in them to find.
