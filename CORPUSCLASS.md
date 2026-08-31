# CORPUSCLASS — committed artefacts whose value depends on which corpus was mounted

Brief: sweep the CLASS behind SIXRED.md Finding 1. For every census/generator that keys on
`corpus_root()` (or otherwise reads the mounted corpus) while writing a COMMITTED artefact:
either (a) the artefact should be corpus-independent -> fix the generator, or (b) it is
legitimately corpus-relative -> the freshness test must SAY WHICH corpus, recorded in the
artefact, so two hosts cannot silently publish different truths.
Two-tree falsified. One ref. LAND.md. Do not land.

Host 192.168.1.114. Base: main @ v1.14.29.
Status: IN PROGRESS.

## Step 0 — orientation

Worktree: `/home/reyerchu/_corpus/wt` @ 272734ef6 [v1.14.29].

TWO corpus seams exist, and they answer different questions — both are in scope:
* `programs/tests/_hostpaths.corpus_root()` — `$VIBEIC_CORPUS_ROOT`, or None.
* `programs/tests/_published_corpus.corpus_root()` / `.corpus_tree()` — resolves the
  published-cell corpus, with states NOT_OFFERED / MEASURED_EMPTY / PRESENT.

Candidate population = generators that write a file TRACKED IN THIS REPO (not a run tree).
Sources: the 7 `*freshness*` tests, `tools/gen_*.py`, `tools/*census*.py`.

## Step 1 — candidate generators

## Step 2 — STOP: the premise of the sweep needs checking first

Source-grepping the candidate generators for corpus tokens gives:

| generator | corpus tokens in its own source | has `--check` |
|---|---|---|
| gen_matrix_63x8_census.py | **0** | yes |
| gen_programs_index.py | 0 | yes |
| gen_flow_gate_d9_section.py | 9 | yes |
| gen_flow_gate_header.py | 0 | yes |
| gen_adversarial_findings.py | 4 | no |
| gen_engineering_evidence.py | 1 | yes |
| gen_all_steps_pdf.py / gen_summary_pdf.py | 0 | no |
| d9_content_census.py | 0 | no |
| liar_census.py | 11 | no |
| vacuous_exit_corpus_census.py | 2 | no |
| d9_corpus_baseline.py | 5 | no |
| d9_flow_gate_reality.py | 8 | no |

`gen_matrix_63x8_census.py` — the generator my own Finding 1 named as the member —
scores **0**. Its corpus dependence, if any, is INHERITED through the pytest subprocess it
drives, not visible in its source. So a textual detector would have missed the one member
I already had, and the detector has to be BEHAVIOURAL: run the generator twice, corpus
bound and unbound, and diff the committed artefact.

Before building that, the premise itself has to be re-checked, because re-reading the d7
skip clause contradicts what I published:

```python
if (not findings and _waiver_for(sid) is not None
        and not R.observed_writes() and corpus_root() is None):
    pytest.skip(SKIP_REASON)
```

**`not findings` is the FIRST conjunct.** Step 25 HAD a finding, so this branch could never
have fired for it, with or without a corpus. My Finding 1 attributed main's published
`d7 CONTRADICTED 0` to corpus binding via this clause. That attribution cannot be right.
Measuring the alternative — that the committed block was simply STALE and the census
freshness gate was RED on main — before going any further.

## Step 3 — CORRECTION. My Finding 1 named the wrong mechanism.

Measured on the UNMODIFIED base worktree `781d24727` [v1.14.22]:

```
programs/tests/test_matrix_63x8_census_freshness.py
FAILED ::test_the_census_block_is_fresh
FAILED ::test_the_published_total_equals_the_live_census
2 failed, 4 passed in 305.75s          RC=1

E  AssertionError: the census in .../matrix_63x8/README.md is stale —
E    committed:    **612 cells: 526 ENFORCED, 6 ENFORCED-CONTRADICTED, ...**
E    re-derived:   **612 cells: 525 ENFORCED, 7 ENFORCED-CONTRADICTED, ...**
```

So the committed census block on main was **STALE**, and the gate that exists to catch
staleness — `test_matrix_63x8_census_freshness.py` — was itself RED on main and unattended.
That is the whole explanation of "published 0, measured 1" for the d7 row. No corpus
binding is involved: the skip clause I cited requires `not findings` as its FIRST
conjunct, and step 25 HAD a finding, so that branch could not fire for it under any
corpus.

**Finding 1 as I published it is wrong and is withdrawn.** The true statement is stronger,
not weaker: main was publishing a census whose freshness gate was red, so every figure in
that block was unverified, not just the d7 one. The gate is green again on `272734ef6`
[v1.14.29] only because this campaign happened to regenerate the block.

This correction has to reach `LAND.md` and `SIXRED.md`, both of which are now on main
carrying the wrong mechanism.

## Step 4 — the CLASS question is still open, and needs a BEHAVIOURAL detector

The owner's question survives my mis-attribution: does any committed artefact's value
depend on which corpus was mounted when it was generated? A source grep cannot answer it
(the census generator scores 0 corpus tokens and drives a pytest subprocess), so the
detector is: generate each committed artefact TWICE — corpus unbound, then bound — and
diff. Two trees, same commit, different mount.

## Step 5 — the population, resolved

A member must satisfy BOTH: (i) its output is TRACKED in this repo, and (ii) its value can
depend on the mounted corpus. Resolving trackedness with `git ls-files`:

| generator | writes | tracked? | corpus tokens |
|---|---|---|---|
| `tools/gen_matrix_63x8_census.py` | `matrix_63x8/README.md` census block + 57 anchored figures in 36 files | **yes** | 0 in source, inherited via a pytest subprocess |
| `tools/gen_programs_index.py` | `programs/INDEX.md` | **yes** | 0 |
| `tools/d9_flow_gate_reality.py` | `tools/d9_reality/d9_reality.json` | **yes** | 8 |
| `tools/gen_adversarial_findings.py` | `programs/adversarial_findings.json` | **yes** | 4 |
| `tools/gen_flow_gate_d9_section.py` | a `--page` the caller supplies | no fixed target | 9 |
| `tools/gen_flow_gate_header.py` | a `--page` the caller supplies | no fixed target | 0 |
| `tools/gen_engineering_evidence.py` | `docs/ENGINEERING_EVIDENCE.md` | **untracked** | 1 |
| `tools/liar_census.py`, `d9_content_census.py`, `vacuous_exit_corpus_census.py`, `d9_corpus_baseline.py` | `--out` reports | no fixed tracked target | 11 / 0 / 2 / 5 |
| `tools/gen_all_steps_pdf.py`, `gen_summary_pdf.py` | PDFs | untracked | 0 |

So **four** candidates go to the two-tree detector, and two of them
(`d9_flow_gate_reality`, `gen_adversarial_findings`) read the corpus in their own source
while writing a file that is committed — the shape the brief describes, found without
needing the census at all.

## Step 6 — the two-tree harness

Two worktrees at the same commit `272734ef6`, differing ONLY in the mount:

* arm **U** — unbound: no `VIBE_IC_BENCHMARK_DATA`, no `VIBEIC_CORPUS_ROOT`.
* arm **B** — bound: both pointed at a synthetic published corpus at
  `/home/reyerchu/_corpus/synth`, built to the publishing contract
  (`PUBLISHING.md` + `ic/<IC>/v<version>_<PDK>/`) and verified to resolve:
  `corpus_state() -> ('present', /home/reyerchu/_corpus/synth)`.

Then regenerate every tracked derived artefact in each arm and diff arm-to-arm. A file
that differs is a committed artefact whose published value depends on which corpus was
mounted — the class, caught behaviourally rather than by grep.

## Step 7 — member 1: `tools/d9_reality/d9_reality.json` — case (b), UNSATISFIED

Generator `tools/d9_flow_gate_reality.py`, artefact TRACKED, 8 corpus references in its own
source. It reads the corpus at a HARD-CODED path, `BENCH = REPO / "benchmark-data"`.

The good half: when that path is absent it **refuses honestly** —

```
CANNOT CHECK: .../benchmark-data is not present. `benchmark-data/` was exported to its
own repository at v1.10.56 (e23d0be5e, 2026-08-17); it is not a missing directory in a
broken checkout. This program reads the corpus from that fixed path and has no option to
point it elsewhere, so it cannot run in this repository at all. NOT a pass.   rc=2
```

So it cannot silently publish a *second* truth. The defect is the other half:

* the committed artefact records `"corpus": {"runs": 107, "how": "git ls-files
  benchmark-data | dirs containing phase1/generated_docs/", "tech_lef_runs": 0}` — a
  cardinality and a method, but **no corpus IDENTITY**: no repository, no commit, no
  pointer. Two different benchmark-data revisions can both yield 107;
* since v1.10.56 the corpus is not at that path in any checkout, and the program "has no
  option to point it elsewhere", so **the artefact can no longer be regenerated at all** in
  this repository. It is frozen evidence about a corpus nobody can name;
* **nothing freshness-checks it** — no `--check` mode, no test diffs it against a
  regeneration. So the staleness that bit the census here cannot even be detected.

## Step 8 — member 2: `programs/adversarial_findings.json` — case (b), ALREADY SATISFIED

Generator `tools/gen_adversarial_findings.py`, artefact TRACKED, reads the corpus through
the correct seam (`from _published_corpus import CORPUS_ENV, corpus_root`) and refuses with
a message naming `$VIBE_IC_BENCHMARK_DATA` when it is unset.

**This is the model the brief describes, already implemented.** The artefact records the
corpus identity in its own body:

```json
"measured_on": "e0e86134",
"cell":        "spm/v1.9.96_gf180mcuD",
"donor":       "sha256/clean_run_v1427_20260715",
"older_run":   "sha256/clean_run_v1422_20260715",
```

— a corpus COMMIT plus the exact cells used. And it is ratcheted in both directions by
`test_adversarial_agent.py`, with a third state that is the whole point:

> a listed pair that goes UNAVAILABLE -> the cell it needed is gone. The finding is
> UNPROVEN, not fixed, and must not read as progress. [...] without it a corpus prune would
> silently 'close' every finding and the ratchet would measure the publication schedule
> instead of the gates.

plus a dedicated `test_the_adversarial_ratchet_follows_the_corpus_pointer.py`.

So the repair for member 1 is not invention: it is copying what member 2 already does.

## Step 9 — the pointer seam already refuses a corpus that cannot name itself

The first arm-B attempt failed, and the refusal is evidence FOR the repo, not against it:

```
AssertionError: VIBE_IC_BENCHMARK_DATA='/home/reyerchu/_corpus/synth' is not a git
checkout, so this module cannot ask which of its files the corpus COMMIT carries. Every
artefact under it would read as 'not tracked at HEAD — a local build product, not
evidence' and every cell would report its declared outputs NOT PRODUCED, which is a
confident wrong answer, not a strict one (#527, #1348). Point VIBE_IC_BENCHMARK_DATA at a
clone of vibeic/benchmark-data rather than at an unpacked copy of one.        rc=1
```

So the corpus seam ALREADY enforces half of the brief's option (b) at the pointer: a corpus
must be a git checkout, because the identity that matters is the corpus COMMIT. The
synthetic corpus was re-made as a real git checkout (`f2c7867`) and the arm re-run.

## Step 10 — two-tree result

| artefact | arm U (unbound) | arm B (corpus bound, git-backed synthetic) | arm-to-arm |
|---|---|---|---|
| `matrix_63x8/README.md` census block | `no change (612 cells)` — the committed block IS fresh unbound | **REFUSED**: `NORECORD` — 8 `test_matrix_d3_outputs_produced` tests went red outside the matrix cell join, so the run's rc=1 is not represented by the cell census and NOTHING was written | generator does not publish a second truth; it refuses |
| `programs/INDEX.md` | regenerated, **differs from the committed file** | regenerated, **byte-identical to arm U** | **corpus-INDEPENDENT** |

Two things fall out.

**(1) `gen_matrix_63x8_census.py` does not silently publish two truths.** Handed a corpus it
cannot use it declares the run NORECORD and writes nothing. That is the correct refusal and
it means the census is NOT a member in the "silently different" sense. What remains is the
narrower hazard: a corpus real enough to keep d3 green but different enough to move the
numbers. That case is not constructible on this host — the real `benchmark-data` is not
here — and the block records nothing about which corpus produced it, so it would be
invisible. Case **(b)**: the block should carry the corpus state it was generated under.

**(2) `programs/INDEX.md` is corpus-independent — and STALE ON MAIN.** Not a member of the
corpus class; a member of the disease my corrected Finding 1 actually names:

```
programs/tests/test_programs_index_freshness.py
FAILED ::test_index_is_fresh
FAILED ::test_index_lists_every_non_helper_program
  INDEX.md missing 1 program(s): ['transition_manifest_describes_its_tree_check']
  committed 1236 programs / 1229 `any`; live 1238 / 1229+2
2 failed, 9 passed
```

So **a second committed derived artefact on main is stale with its own freshness gate red
and unattended** — the same shape as the census block was at v1.14.22. Two of the repo's
seven freshness gates were red on main at the same time.

## Step 11 — the other five freshness gates are green

```
test_signoff_artifact_freshness.py  test_m1_top_lvs_freshness.py
test_clock_plan_freshness.py        test_synth_netlist_cache_rtl_freshness.py
test_phase3_signoff_regen_covers_psm_and_si.py
=> 60 passed in 3.57s   RC=0
```
So exactly **2 of the 7** were red on main: the census (repaired by the previous campaign)
and `programs/INDEX.md` (still red).

## Step 12 — member 1's number cannot be reproduced from ANY state of this repository

`d9_reality.json` claims `corpus.runs: 107`, derived by
`git ls-files benchmark-data | dirs containing phase1/generated_docs/`. That method is
INDEX-based, so it should be reproducible from history alone. Measured:

```
e23d0be5e  chore: benchmark-data ... move to their own repositories [v1.10.56]
at e23d0be5e^ (the last commit carrying benchmark-data as a real tree):
    tracked paths under benchmark-data : 527
    dirs containing phase1/generated_docs/ : 0
at e23d0be5e : 0 (exported)
at HEAD      : benchmark-data absent from the tree entirely
```

So the corpus had already been thinned to zero run dirs BEFORE the export. `107` is not
reproducible at the export boundary. Searching history for a commit where it IS.

Run-dir count at EVERY commit that touched `benchmark-data` (46 of them):

```
e23d0be5e 2026-08-17    0   <- export
c5d7f2d00 2026-08-16    0   <- published results moved to vibeic/benchmark-data
253216631 2026-08-15  105
e73601fec 2026-08-12  105
ae800cb70 2026-08-12  107   <- LAST commit at which the artefact's figure is true
cdc54d32f 2026-08-02  107   <- first
cf66e7916 2026-08-02  106
cb8e4c2c0 2026-07-30  106
```

So `corpus.runs: 107` IS reproducible — but only inside the window
`cdc54d32f .. ae800cb70` (2026-08-02 .. 2026-08-12), and the artefact names no commit.

And the sharpest fact of the whole sweep:

```
d9_reality.json was committed at c45c502ce, 2026-08-18 [v1.10.70]
run-dir count at c45c502ce: 0
```

**The artefact was published two days AFTER its corpus left the repository**, into a tree
where its own generator returns `CANNOT CHECK` and where re-deriving its headline figure
gives 0, not 107. It is evidence carried forward from an earlier, unnamed measurement and
landed after its subject was gone. That is the class in its purest form: not two hosts
publishing different truths, but one host publishing a truth no tree can check.

## Step 13 — the fix for member 1, and why it is checkable TODAY

Rewiring `d9_flow_gate_reality.py` to the corpus pointer is NOT attempted: `tracked_files`
and the imported `discover_runs` key every row on the literal prefix `benchmark-data/`, so
re-pointing it is a path-handling refactor I cannot validate without the real corpus, and
an unvalidated refactor of a corpus reader is how this class got here.

What IS deliverable and falsifiable is exactly what the brief asks for in case (b): the
artefact must SAY WHICH corpus, and something must enforce it. The identity that can be
verified with no corpus checkout at all is the REPO COMMIT at which the artefact's own
method reproduces its own figure — `git ls-tree -r <commit> -- benchmark-data`, index-based
and offline. So:

* record `corpus.identity` in `d9_reality.json`: the commit, the window, the method, and
  the fact that it does NOT reproduce at the commit that published it;
* add a gate that re-derives the figure at the recorded commit and refuses a mismatch.

Two-tree falsification for that gate: at the recorded commit the method yields 107 (pass);
at the artefact's own publishing commit `c45c502ce` it yields 0 (must be refused).

## Step 14 — F1 and F2 landed on the branch, F2 two-tree falsified

Branch `fix/committed-artefacts-name-their-corpus`, worktree `/home/reyerchu/_corpus/fix`,
base `272734ef6`.

**F1 — `programs/INDEX.md`, case (a).** Corpus-independent (proved byte-identical across
arms U and B), so the only defect is staleness. Regenerated by its own generator:
1236 -> 1238 programs, `any` 1227 -> 1229, one changed docstring line, and
`transition_manifest_describes_its_tree_check` added.

**F2 — `d9_reality.json`, case (b).** `corpus.identity` recorded, naming the commit at
which the artefact's own method reproduces its own figure, the window it holds over, the
method, and the fact that it yields 0 at the artefact's own publishing commit. New gate
`tools/tests/test_d9_reality_names_its_corpus.py`, 4 tests, which runs offline from git
history and needs no corpus checkout — the reason the identity is expressed as a commit.

Two-tree falsification of the gate:

| arm | artefact | result |
|---|---|---|
| 1 | the artefact AS IT IS ON MAIN (no `corpus.identity`) | **3 failed**, 1 passed |
| 2 | identity present but naming `c45c502ce`, the publishing commit | **1 failed** — `test_the_named_commit_actually_reproduces_the_figure` |
| 3 | the branch's artefact | 4 passed |

Arm 2 is the one that matters: a present-but-false identity is refused, so the gate checks
the NAME, not merely its presence. The fourth test is a self-limiting clause — it reddens
if the generator ever gains the corpus pointer, which is the signal to regenerate against a
real named corpus and delete the reconstructed identity.

## Step 15 — F3: the census block now names its corpus

`render()` gains one line, emitted right after the CONTRADICTED sentence. Unit-level
two-tree, before any regeneration:

```
UNBOUND : Corpus at generation: NOT_OFFERED — no published cell was read.
          Every figure below is a function of this commit alone.
BOUND   : Corpus at generation: PRESENT @ f2c7867 (synth). Figures whose predicate
          consults the corpus are a function of THAT tree as well as of this commit.
```

It is NOT a timestamp — the generator's own `WHAT IT REFUSES` rules those out because they
make `--check` meaningless. This changes only when the MOUNT changes, which is exactly the
drift `--check` could not previously see. The protected
`test_matrix_63x8_census_freshness.py` needs no edit: it calls the generator's own
`census_rows()` / `render()` and inherits the line.

Regenerated on the branch (RC=0, figures fresh), and the committed block now reads:

```
**612 cells: 532 ENFORCED, 0 ENFORCED-CONTRADICTED, 8 WAIVED, 19 NA, ...**
The 0 CONTRADICTED cells are ...
Corpus at generation: NOT_OFFERED — no published cell was read. Every figure below is a
function of this commit alone.
```

## Step 16 — verification, clean committed tree

```
test_matrix_63x8_census_freshness.py   (PROTECTED, unedited — inherits the new line)
test_programs_index_freshness.py       (was RED on main)
tools/tests/test_d9_reality_names_its_corpus.py   (new)
test_matrix_d5_deps_correct.py
test_matrix_d7_outputs_list_complete.py
=> 207 passed, 1 skipped, 5 xfailed in 365.00s   RC=0
[PASS] suite_write_guard: this pytest session wrote nothing `git status --porcelain` would show.
```

---

# SUMMARY

**The class has four members, and my own Finding 1 was not one of them.**

| member | verdict |
|---|---|
| `programs/adversarial_findings.json` | **(b) already satisfied** — records `measured_on` (corpus commit) + `cell`/`donor`/`older_run`, ratcheted both ways, with a corpus-pointer test. The model. |
| `tools/d9_reality/d9_reality.json` | **(b) unsatisfied -> fixed.** States `corpus.runs: 107`, names no corpus, unregenerable since v1.10.56, nothing freshness-checks it. Now carries a derived, verifiable `corpus.identity` and a 4-test gate that re-derives the figure at the commit it names. |
| `matrix_63x8/README.md` census block | **(b) -> fixed.** Never published two truths (arm B REFUSES with NORECORD rather than writing), but recorded nothing about the mount. Now names the corpus state and, when mounted, the corpus's own HEAD. |
| `programs/INDEX.md` | **(a).** Byte-identical across arms -> corpus-independent. Its only defect was staleness, with its freshness gate red on main. Regenerated. |

Eight further generators were examined and are NOT members: they write a `--page` or
`--out` the caller supplies, or an untracked doc — no fixed tracked target.

**Withdrawn:** the census block was never corpus-bound. It was STALE, and
`test_matrix_63x8_census_freshness.py` was RED on main and unattended. Two of the repo's
seven freshness gates were red at the same time; the other five are green.

**The finding the sweep actually produced**, which is sharper than the one it was chartered
to chase: `d9_reality.json` was committed at `c45c502ce` (2026-08-18), **two days after its
corpus left the repository at `c5d7f2d00`**, into a tree where its own method yields 0
instead of 107 and its generator returns `CANNOT CHECK`. Not two hosts publishing different
truths — one host publishing a truth no tree can check.
