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

## SETTLED: all three numbers reproduced, on main's own commit tree

One directory carrying uncommitted work — `vibe-ic-marketplace/plugins/vibe-ic/
tools/phase1_engine/` — reproduces the landing's three numbers exactly, with the
commit tree unmoved:

```
$ git rev-parse HEAD^{tree}                 954bc27704cb…   (= main's tree, unchanged)
$ echo >> …/tools/phase1_engine/cli.py                      # edited, NOT committed
$ git add …/tools/phase1_engine/tests/test_zzz_landing_probe.py   # staged, NOT committed
$ git rev-parse HEAD^{tree}                 954bc27704cb…   (STILL main's tree)

  unselectable census        133      (was 132)
  repo tools (find tools)     50      (unmoved)
  targeted selection         225      (was 221) — "from 18 changed path(s)"
```

Each number moves for its own reason, and the reasons are all in the same tree:

* **census 132 → 133.** `git ls-files` reads the INDEX, so the staged test file
  counts. It is under the PLUGIN's `tools/`, not the repo root's, and the
  census's `tools/` subtrahend is the repo-root one (`run_repo_tools_pytest`'s
  `find tools …` runs from `$ROOT`) — so it lands in the complement. This is not
  a corner: the plugin's `tools/phase1_engine/tests/` already supplies **8 of
  the 132** existing members.
* **repo tools 50, unmoved.** Same reason from the other side: that `find` never
  descends into the plugin, so a plugin-`tools/` test file is invisible to it.
  This is the observation that pins the file's location — any file that moved
  the census by living under the REPO-ROOT `tools/` would have moved this to 51.
* **targeted 221 → 225.** `git diff --name-only <base>` sees the edited
  `cli.py`, so the changed-path population goes 16 → 18. `cli.py` is under a
  `tools/` dir, so rule 6 keys it by its BASENAME — no uniqueness test on that
  path — and selects every test file that names `cli.py`. Measured over the
  whole `tools/` basename space, exactly one basename selects exactly four tests
  the rest of this diff had not already selected, and it is this one:

      programs/tests/test_die_finishing_step_265ic.py
      programs/tests/test_l_doc_generator_stamp.py
      programs/tests/test_v0_2_55_phase1_flat_generated_docs.py
      programs/tests/test_v0_2_58_phase1_engine_bundle.py

  221 + 4 = 225.

### The hypothesis was half right, and the half it got wrong is the useful half

"One extra tracked test file outside `programs/tests` and `tools/`" accounts for
the census and **cannot** account for the targeted count. Measured over all 132
existing members of that species, driving each through the real selector's
three-hop rule 7: **131 add zero selected tests and one adds one. None adds
four.** A newly-created test file is, by construction, named by nothing, so its
selection delta is zero — the census and the selection are moved by *different
files in the same tree*, not by one file.

### What the landing worktree was carrying

Uncommitted work in the plugin's `tools/phase1_engine/`: at least an edit to
`cli.py` and at least one new test under its `tests/`. Neither is in any commit
on either side of `d1f9885f0440..ae5cc4dbf` — checked with `--diff-filter=AD`,
which reports no test file added or deleted outside `programs/tests` and
`tools/` in that range — so no artefact in this repository records it and the
worktree that held it is gone. The mechanism, the tree, and the exact selection
delta are named; the individual bytes are not recoverable and are not claimed.

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
