# The gate that catches host-dependence has a host-dependent verdict

Measured 2026-08-22 at `a00f53f20` (v1.11.66). Same tree, same commit, same
gate, `--jobs 8`. The only variable is `TMPDIR`:

    TMPDIR=/tmp                       [FAIL] 3 of 79 probed corpus gate(s)
                                      did not give one reproducible verdict
                                      across two trees: 3 HOST_DEPENDENT_VERDICT
                                      rc=1

    TMPDIR=/home/reyerchu/_jrows/tmp  [PASS] all 79 probed corpus-scanning
                                      gate(s) give the same verdict in a working
                                      checkout and a fresh worktree
                                      rc=0

The three it finds, and only in the first arrangement:

    tracked-symlink portability
    L-doc field producer
    evidence citation resolves

## WHY

`gate_host_independence_check` compares a working checkout (Arm A) against a
fresh `git worktree` (Arm B). Arm B is created by `_crash_safe_scratch.reserve`
with `root=tmp_root`, and `tmp_root` defaults to `tempfile.gettempdir()` — that
is, to `$TMPDIR`.

The three gates it is looking for resolve the published corpus by walking the
**program's** parent directories:

    named = next((b / "benchmark-data/ic" for b in here.parents
                  if (b / "benchmark-data/ic").is_dir()), …)

`here` is the program file, so the walk climbs out of the repository. On this
host it reaches `/home/reyerchu`, where a `benchmark-data` clone lives.

So when `$TMPDIR` is **under `$HOME`**, Arm B has the same `benchmark-data`
above it that Arm A does. Both arms resolve the same corpus, both give the same
verdict, and the gate reports that all 79 are reproducible. When `$TMPDIR` is
`/tmp`, Arm B has no corpus above it, the two arms differ, and the gate finds
exactly the class it exists for.

**Nothing is wrong with the comparison.** What is wrong is that the second tree
is placed somewhere that can share the first tree's `$HOME`, and `$HOME` is the
thing the walk reaches into.

## WHY IT IS EASY TO BE ON THE BLIND SIDE

`scratch_root_guard` requires the scratch root to sit outside any git work tree,
and a directory under `$HOME` satisfies that. Every run in this session used
`TMPDIR=/home/reyerchu/_jrows/tmp` for exactly that reason. So the arrangement
that hides the class is the one the repo's own guidance leads you to.

## WHAT THIS CONFIRMS, INDEPENDENTLY

Two of the three are two of the eight rows in `tools/ci/gate_red_since.json`.
They were annotated earlier the same day as stating a CONDITION rather than a
deadline, after measuring by hand that they are `rc 1` in a checkout under
`/home/reyerchu` and `rc 0` in one under `/tmp`. This is the repo's own
instrument reaching the same conclusion from the other direction, and it is why
those two rows do not carry a commit-dated deadline the way the other six do.

## REMEDIES, NOT TAKEN HERE

Either would change what main reports, so both are the owner's:

1. **Place Arm B outside `$HOME`.** Cheapest and it makes the existing gate do
   what it says. It turns three gates red on any host with a reachable corpus.
2. **Anchor the corpus walk on the repository** instead of on the program's
   parents, in the eight programs that do it —
   `grep -l 'in here.parents' programs/*.py`. `benchmark_evidence_index` already
   anchors on `repo_root / IC_SUBDIR` and is host-independent because of it.

(1) makes the problem visible; (2) removes it. They are not alternatives —
(1) without (2) reddens main, and (2) without (1) leaves the detector blind to
the next program that walks.
