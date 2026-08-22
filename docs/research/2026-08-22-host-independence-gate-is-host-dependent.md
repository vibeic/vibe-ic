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

---

## MEASURED: ANCHORING ALONE IS NOT A FIX — IT MAKES THE GATES VACUOUS

Remedy (2) above said "anchor the corpus walk on the repository … removes it".
That was reasoned, not measured. Measured now, in a throwaway checkout of
`81cd5321b` with the walk replaced by the repo-relative default — which is
exactly what `benchmark_evidence_index` does — same host, `$HOME` still holding
a `benchmark-data` clone, environment unset:

    walk intact (climbs into $HOME)   l_doc rc 2 UNDETERMINED
                                      evidence rc 1 FAIL, scanning
                                      /home/reyerchu/benchmark-data/ic
    anchored on the repository        l_doc rc 0 NO_CORPUS
                                      evidence rc 0 NO_CORPUS

Both become **rc 0 — a PASS that scanned nothing**. So anchoring makes the
verdict host-independent by making it constant: the corpus is never inside this
repository any more, so a repo-anchored gate finds nothing on every host.

**That is the vacuous direction, and it is worse than the defect it removes.**
A gate that is red on one host and green on another is at least red somewhere; a
gate that is green everywhere without looking is the shape this repo removes one
gate at a time.

### SO THE OPTIONS ARE THREE PARTS, NOT TWO ALTERNATIVES

1. **Anchor the walk** — so the verdict does not depend on what sits above the
   checkout. Necessary, not sufficient.
2. **Bind the corpus on the landing path** (`VIBE_IC_BENCHMARK_DATA`), so an
   anchored gate has something to scan. Without this, (1) is a silence.
3. **Decide what an unbound corpus means.** `--corpus-may-be-absent` is what
   turns "nothing anywhere" into rc 0; without the flag the same state is rc 2
   UNDETERMINED. Today every one of these gates carries the flag AND is
   dispatched with a plain blocking `run` — so an absent corpus is a PASS and a
   present-but-unreadable one is a FAIL, which is the two halves the wrong way
   round.

And (4), from the addendum above: `L-doc field producer` currently returns rc 2
UNDETERMINED and is recorded FAIL because its dispatch is a plain `run`. It wants
`run_tolerating_uncheckable` with a dated `uncheckable_until`.

None of the four is made here. Two touch `repo_hygiene_gates.sh`, a PROTECTED
path; all four change what main reports; and (3) in particular is a policy
decision about whether a landing host must carry a corpus at all — which is the
owner's, with the measurements now in front of them rather than an assertion.

---

## RE-CONFIRMED AT `a4caccefe` (v1.11.69), AND THE PART THAT MAKES IT INVISIBLE

Re-ran `gate_host_independence_check . --jobs 8` on main today. Unchanged, and
now over a larger probe set:

    main a4caccefe, working checkout under $HOME
      rc=1  [FAIL] 3 of 87 probed corpus gate(s) (96 declared) did not give one
            reproducible verdict across two trees: 3 HOST_DEPENDENT_VERDICT
              tracked-symlink portability
              L-doc field producer
              evidence citation resolves

The same run on `agent/jrows-on-batchbig` gives the identical rc and the
identical three, so this is main's property and the branch is neutral to it.

The gate's own diagnosis of the mechanism is worth quoting, because it is right
about the symptom and wrong about the cause:

    the same commit gives different answers in a working checkout and a fresh
    worktree, and does so on BOTH rounds, so the gate is reading something that
    is not in the commit — almost always untracked run leftovers

It is not leftovers here. The two arms differ because the working checkout sits
under `/home/reyerchu`, whose ancestor walk finds `~/benchmark-data/ic`, and the
fresh worktree does not:

    checkout: rc=2 UNDETERMINED: /home/reyerchu/benchmark-data/ic is a directory
              but holds no L-doc this gate can read
    worktree: rc=0 NO_CORPUS: nothing at benchmark-data/ic ... NOTHING WAS
              SCANNED

### WHY CI NEVER SEES IT

Run the same checker from a checkout OUTSIDE `$HOME` — a clean tree, which is
what CI has — and it does not pass. It refuses:

    rc=2  NO_STIMULUS: host-independence was NOT checked — the checkout carried
          no untracked and no ignored path, so it and the fresh worktree held
          the same bytes and all 87 probed gate(s) agreed by construction. A
          comparison with nothing on one side that is not on the other cannot
          detect a gate reading local state. This is not a pass. Run it in the
          working tree the leftovers accumulate in.

That is exactly the right answer and the gate deserves credit for it: it never
claims a pass it did not earn. But `repo_hygiene_gates.sh:1828` dispatches it
with `run_tolerating_uncheckable` under an `uncheckable_until 2027-02-28`, and
rc 2 is precisely what that tolerates. So:

    clean host (CI)        rc 2 NO_STIMULUS  -> tolerated, nothing learned
    working checkout       rc 1 FAIL         -> blocks, and rc 1 is NOT exempt

The finding is real, the instrument is honest, and the arrangement that can see
it is the one nobody runs in CI. Anyone running a full hygiene sweep in their
working tree today gets the red; the pipeline never does.

### AND THE SCALE OF (3), NOW MEASURED

The "two halves the wrong way round" above is not two gates. All **10** gates
invoked with `--corpus-may-be-absent`, run from outside `$HOME`:

    RECORDED PASS WHILE REPORTING NOTHING SCANNED: 10 of 10
    roll-up: declared 93  ran 10  decided 10  passed 10  failed 0
             "all 93 gate(s) passed"

A ninth of the declared set, each counted by `PROCESS_STATES` among the gates
that "actually ran".
