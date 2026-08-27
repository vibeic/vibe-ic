# The landing gate's 225/50/133 and the reproduction's 221/50/132

*Measured 2026-08-28 on 8HD-6, against live `main` `ae5cc4dbf` (tree
`954bc2770`), base `d1f9885f0440` — the base the landing declared.*

## The question

The `batch96-landing-v1-11-96` gate reported

```
  PASS  targeted tests (225 file(s))
  PASS  repo tools tests (50 file(s))
        unselectable corpus: 133 file(s)
```

An independent reproduction on the **same declared base** got **221 / 50 / 132**.
Established before this note, and not re-litigated here:

* no base in that history yields 225 — `d1f9885f0440` → 221, later bases 156–159,
  the full cadence 2875, the smoke floor 18;
* the unselectable corpus is base-independent and **member-identical** between
  `d1f9885f0440` and the candidate — 132 on both sides, empty symmetric
  difference.

So 133 cannot come from a base/candidate difference, and 225 cannot come from a
different base. The working hypothesis was "the gate measured a tree carrying
one extra tracked test file outside `programs/tests` and `tools/`".

## The answer: neither counter measures a COMMIT. Both measure the INDEX.

The hypothesis is right about the *shape* and wrong about where such a file
could hide. It does not have to be in any commit, on either side, for either
counter to see it — because **neither counter reads a commit tree**.

`landing_unselectable_pytest_corpus.tracked_test_files` enumerates with
`git ls-files`:

```python
    ["git", "-C", str(repo), "ls-files", "-z"],
```

`git ls-files` reads **the index**, not `HEAD` and not the candidate. Its own
docstring says why it was chosen — "so that an untracked scratch file in
somebody's worktree cannot change what a landing runs" — which is true of an
*untracked* file and says nothing about a *staged* one.

`ci_targeted_test_select._git_changed_files` takes the **union of two diffs**,
and the second one has no commit on its right-hand side at all:

```python
    for args in ([f"{base}..HEAD"], [base]):
```

The second form is `git diff --name-only <base>` — base against the **working
tree, staged and unstaged**. That is deliberate and documented: the merge queue
"stages a squash (so `HEAD == base`, diff empty) and then asks which tests the
change needs", and before the union existed the answer was the smoke floor.

Both counters therefore describe **the landing worktree at the moment the gate
ran**, and a landing runs on exactly the tree where that distinction is
maximal: `HEAD` is the base and the candidate is *staged*.

## Measured, on a tree whose commit is byte-identical to main's

One extra test file, `git add`-ed and never committed, outside `programs/tests`
and outside `tools/`:

```
$ git rev-parse HEAD^{tree}                      954bc27704cb7d12cf7ba5c0fc4a348b6898ec3b
$ landing_unselectable_pytest_corpus.py | wc -l  132

$ git add …/skills/rtl-review/tests/test_zzz_landing_probe.py
$ git rev-parse HEAD^{tree}                      954bc27704cb7d12cf7ba5c0fc4a348b6898ec3b   <- UNCHANGED
$ landing_unselectable_pytest_corpus.py | wc -l  133                                        <- MOVED
$ find tools … | wc -l                            50                                        <- unmoved
$ ci_targeted_test_select.py --base d1f9885f0440
  … selected 221 test file(s) from 17 changed path(s)                                       <- 16 -> 17
```

Three of the four observations are the landing's own numbers, reproduced
exactly: the census moves 132 → 133, the repo-tools count does not move (it is a
`find` over `tools/`, and the file is not under `tools/`), and the selector's
changed-path population moves 16 → 17 while the commit tree does not move at
all.

The fourth — the targeted count — moved by 0 for *this* stimulus, because the
selector's delta for a path no rule maps is not 1. It is rule 7: the path is
keyed by the most specific suffix of itself that is unique in the tree, and the
key selects the tests that NAME it, through three hops (a test names it, a
`programs/tests` helper names it, a program opens it as a live string literal).
A probe file nothing mentions selects nothing. **A file that four tests mention
selects four**, and 221 + 4 = 225.

## What this settles

* **The two counts move together because they read the same thing** — the
  landing worktree's index — and they move independently of every commit on
  either side. That is why the reproduction could not reach 225/133 from any
  base: it was replaying commits against a question neither counter asks.
* **The file cannot be named from `main`.** It was never committed on either
  side; `d1f9885f0440..ae5cc4dbf` adds and deletes no test file outside
  `programs/tests` and `tools/` (checked with `--diff-filter=AD`), so no
  artefact in this repository records it. Naming it needs the landing worktree,
  which no longer exists. What CAN be named is its shape, and it is tightly
  constrained by the two numbers: a **tracked-in-the-index** file, matching
  pytest's collection patterns, **outside** `programs/tests` and `tools/`, not in
  the census's declared exclusions, and named by exactly **four** test files
  under `programs/tests` that the rest of the diff did not already select.
* **This is not exotic.** The census's own 132 members include three files of
  precisely that species — two under `_jcapsha_notes/candidate_tests/` and one
  under `docs/capture/2026-08-21-jcap-ppa/` — test files that reached the tree
  as somebody's scratch and stayed. A landing that stages its assembly with a
  broad `git add` puts a 133rd in the index for the length of one gate run.

## What is worth changing, and what is not

Not the selector's union: it exists because the merge queue's staged squash
makes `<base>..HEAD` empty, and removing it would restore a measured defect.

What is worth doing is **disclosure**. Both numbers are printed as though they
were properties of the candidate, and neither says which tree it measured. The
lander already prints its base; it does not print whether the index it measured
matched any commit. One line — `git status --porcelain` non-empty, or
`git write-tree` differing from `HEAD^{tree}` — beside the two counts would have
made this a five-minute answer instead of a night's.

`gate_host_independence_check` already refuses exactly this state for its own
question (`DIRTY_CHECKOUT: … 2 TRACKED path(s) modified/staged; parallel workers
would compare them with HEAD rather than with this tree`). The two counters have
the same exposure and no such sentence.
