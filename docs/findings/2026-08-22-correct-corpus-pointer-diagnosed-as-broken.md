# A correct pointer at the published corpus was diagnosed as a broken one, and
# it takes the landing test arm's collection with it

Continuation of the routed-DEF corpus adjudication. That record reached verdict
(2) — the corpus is legitimately empty — and named two things it deliberately
did NOT take. **This takes the second one**, and measuring it moved it from
"an operator who follows the printed advice gets a confusing error" to
"every ingredient of a landing-arm collection outage is present and measured".

Measured 2026-08-22 on a clean worktree of `origin/main` @ `a4caccefe`
(v1.11.69), `PYTHONDONTWRITEBYTECODE=1`.

## The defect

`programs/tests/_published_corpus.corpus_root` names THREE causes for "you set
`VIBE_IC_BENCHMARK_DATA` and there are no cells", and refuses:

> They named a corpus. The name is wrong, or the clone failed, or the CI step
> that was meant to fetch it did nothing.

On 2026-08-20 a fourth appeared that is none of the three: the pointer is right,
the clone succeeded, the fetch worked, and `vibeic/benchmark-data` genuinely
publishes zero cells because the publisher withdrew all four of them. The
refusal then closes by advising the reader to

> point it at a clone of vibeic/benchmark-data.

**The remedy it prints is the action that produced it.**

This is the same defect `tools/ci/routed_def_corpus.py` separates into rc 0 (an
index was read and holds none) and rc 3 (nothing was opened) — vibe-ic#1764 —
surviving one layer down in the test helper, where nobody looked for it.

## The corpus, measured at the publisher

`git clone --filter=blob:none --single-branch --branch main` of
`https://github.com/vibeic/benchmark-data`, HEAD `3b58ccd42`:

| query | result |
|---|---|
| blobs in the whole repository | 6929 |
| designs under `ic/` | 9 |
| cell directories `ic/*/v*` | **0** |
| blobs named `routed.def` | **0** |
| blobs ending `.def`, any path | **0** |
| `PUBLISHING.md` at the root | present |

## The reach, and it is the landing path

Each link measured separately rather than inferred from the one before it.

1. **The landing TEST arms bind the pointer.**
   `tools/ci/hermetic_candidate_runner.py` sets
   `_TEST_PROCESS_ENV = {"VIBE_IC_BENCHMARK_DATA": CORPUS_PATH}` and
   `_fixed_process_env` applies it to every arm that is not `A2`/`B2` — i.e.
   to `A1`/`B1`, the test arms. `CORPUS_PATH` is `/corpus`.

2. **`/corpus` is the publisher, and the runner asserts it.**
   `tools/ci/benchmark_data_landing_checkout.py` pins
   `CANONICAL_ORIGIN = "https://github.com/vibeic/benchmark-data.git"` and
   refuses a checkout whose `git remote get-url --all origin` is anything else.

3. **The cron-owned checkout on this fleet is that zero-cell tree.**
   `_checkout_arg` defaults to `~/_matrix_benchmark_data`. On this host it is a
   real clone of the canonical origin at
   `bcf2f94 "withdraw all four published cells, and write down what may be
   published here"`, carrying `PUBLISHING.md` and **0** `ic/*/v*` directories.

4. **Bound at that exact directory, collection dies.** The 55 modules that
   import the helper, `--collect-only`, same file list both sides:

   | tree | pointer | collected | collection errors |
   |---|---|---|---|
   | `origin/main` @ `a4caccefe` | `~/_matrix_benchmark_data` | **52** | **52** |
   | this branch | `~/_matrix_benchmark_data` | **1357** | **0** |

   52 of the 55 modules die AT IMPORT — `needs_corpus` is built at module scope,
   so the exception escapes collection and pytest never reaches a test. Most of
   the ~1300 tests lost that way have no published cell as their subject; they
   are collateral of where the marker is evaluated.

   Cross-check, taken independently against a synthetic corpus carrying one
   cell: 1345 collected, 0 errors. 1357 − 12 new cases in this branch = 1345.
   Two different corpora, same denominator.

5. **And they RUN, not merely collect.** Collection is not execution, so ten of
   the `needs_corpus` modules were executed rather than counted, pointer bound
   at the same real landing checkout:

   ```
   196 passed, 20 skipped, 4 xfailed in 59.32s   (loadavg 18.16, nproc 32)
   ```

   On `main` those same ten modules yield zero executed tests: they are
   collection errors. The 20 skips carry the new sentence verbatim —

   > `VIBE_IC_BENCHMARK_DATA` names the published benchmark corpus and it was
   > READ — it publishes 0 cells under `ic/<design>/v<version>_<PDK>/`, so this
   > check has no published cell to examine. This is a MEASUREMENT of zero, not
   > 'I could not look', and it is not a pass: nothing was verified about any
   > cell. The pointer is correct; the corpus is empty.

   — which is the point: 196 tests that have nothing to do with a published cell
   now run, and the 20 that do are skipped over a **counted zero** rather than
   erroring over a configuration that was never broken.

### Targeted regression, both pointer states

| tree | pointer | result |
|---|---|---|
| `origin/main` | unset | 20 passed, 1 skipped |
| this branch | unset | 32 passed, 1 skipped |
| this branch | real landing corpus | 32 passed, 1 skipped |

20 + the 12 new cases = 32, and the skip count does not move. The default
no-pointer path — the one every developer and the current landing pytest run use
— is byte-for-byte the behaviour it had.

**THE LIMIT OF THIS CLAIM, stated rather than left for a reader to assume.** The
hermetic image was NOT run. What is measured is that every ingredient is
present: the arm binds the pointer, the pointer resolves to the canonical
publisher, the publisher has no cells, and that combination kills collection on
`main`. Whether the arm is red *today* depends on the arm's own mount and
selection, which this record did not exercise. It is an unlit fuse that has been
traced end to end, not an observed fire.

## The fix, and why it is not the loosening this module forbids

The obvious edit — return `None` whenever there are no cells — is precisely the
exploit `_published_corpus` was written to prevent, measured once as
`VIBE_IC_BENCHMARK_DATA=<empty dir> pytest -> 29 passed, 2 skipped`: a whole
corpus suite switched off by a mistyped path. **It is not taken.**

What is taken is a POSITIVE identification of the tree as the published corpus,
which no accident produces — the publishing contract at its root AND the `ic/`
root that cells live under:

```
set + not a corpus (missing path, empty dir, dead clone) -> raise.  UNCHANGED
set + IS the corpus + it carries cells                   -> the path. UNCHANGED
set + IS the corpus + its cell population is 0           -> skip, SAYING SO. NEW
```

The new row carries its own sentence, `MEASURED_EMPTY_REASON`, which states the
count and states that it is not a pass. It never borrows `SKIP_REASON`'s
"could not look", because the corpus *was* looked at. Both non-running states
remain non-running: **a skip is not a pass, and nothing is verified about any
cell either way.**

Git is deliberately NOT required. This helper walks the filesystem rather than
an index — unlike `programs/_corpus_location.not_a_checkout_reason`, whose
callers read `git ls-files` and must refuse a loose directory — so an archive
export of the corpus is readable here and refusing it would be wrong.

### What can still reach the refusal, asserted

Each of these is a test in
`test_measured_empty_corpus_is_not_a_broken_pointer.py`, and four of the twelve
are GREEN on unfixed `main` **by design**: they are the anti-loosening guards,
and a future widening of the new row is what turns them red.

| tree | outcome |
|---|---|
| path does not exist | raise |
| empty directory | raise |
| a real tree that is not the publisher (`datasets/`, `runs/`, a README) | raise |
| the contract, but no `ic/` root | raise |
| an `ic/` root, but no contract | raise |
| contract + `ic/`, zero cells | MEASURED_EMPTY, skip |
| contract + `ic/`, one cell | PRESENT, the path |

"Contract but no `ic/`" refusing is the honest outcome rather than a gap: a cell
is *defined* as `ic/<design>/v<version>_<PDK>/`, so a tree with no `ic/` cannot
be measured for cells at all, and calling it measured-empty would be a
manufactured measurement in the opposite direction.

## The red, and why an earlier draft's red was worthless

The headline test calls `corpus_root()` — which exists both before and after
this repair — so on unfixed `main` it fails with the real refusal:

```
E  Failed: a correct pointer at the published corpus was diagnosed as a broken
   pointer -- the remedy it prints is the action that produced it:
   VIBE_IC_BENCHMARK_DATA=... names a corpus with no published cell under
   ic/<design>/v<version>_<PDK>/ ...
```

The first draft built its fixtures from `C.CORPUS_CONTRACT` and went red on all
11 cases with `AttributeError: module '_published_corpus' has no attribute
'CORPUS_CONTRACT'`. That red proves only that a constant is new — it is the
"checker validates the thing NEXT to the claim" shape. The fixtures now
hand-spell `"PUBLISHING.md"` and one test ties the two spellings together.

Verified green: 20 passed on the fixed tree — the 12 new cases plus all 8
pre-existing guarantees in `test_published_corpus_helper.py`, none of which
moved.

## What this deliberately does not do

- **It does not touch the routed-DEF verdict.** That corpus is still empty, the
  gate still reports NOT CHECKED, and nothing here publishes anything to make it
  non-empty. An empty corpus stays rc 2 / NOT CHECKED and never becomes a pass.
- **It does not take the other named-and-not-taken item.** Over a corpus with
  zero published cells, `benchmark_evidence_structure_check --tree` prints
  `9/9 conformant, 0 nonconformant` and the cell count appears nowhere in that
  line. It is a disclosure defect, not a false verdict. The summary string is
  parsed by `tools/gatekeeper-land.sh` and `tools/gatekeeper-verify-merge.sh`
  and read by tests under `programs/tests/`; changing a string the landing path
  parses, without running the landing path, is how a fix becomes an outage. It
  stays measured, named and left — see the routed-DEF restoration-condition
  record for its reproduction.
- **`benchmark evidence structure` reports NOT CHECKED on this branch's
  pre-push, and it does so identically on clean `main`.** Run on a clean
  `a4caccefe` worktree with the same arguments the hook uses, it prints
  `UNDETERMINED: --tree benchmark-data is not a directory`. The batch did not
  introduce it; the tree simply has no `benchmark-data/` since v1.10.56. Binding
  `VIBE_IC_BENCHMARK_DATA` at a clone — the action the gate's own message asks
  for — is what lets the push proceed, and that is also the configuration this
  record repairs the test helper for.
