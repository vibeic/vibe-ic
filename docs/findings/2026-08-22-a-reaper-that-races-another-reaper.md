# A reaper that races another reaper reports a false reason and leaves litter

Lane `next/reaper-races-another-reaper`, cut from `origin/main` (a4caccefe,
v1.11.69).

## Where this came from

The batchbig measurement report named one genuine intermittent and carried it
forward rather than fixing it:

> `test_a_SIGKILL_mid_probe_leaves_the_repository_byte_identical` is a genuine
> intermittent on BOTH arms. It will keep producing candidate differences for
> whoever measures next.

It cost that measurement three isolated re-runs per arm to rule out. This lane
root-causes it.

## It is not load, and it is not the kill

Measured, single variable, same commit and same worktree:

| | result |
|---|---|
| 5 SEQUENTIAL runs at load 16 | 5 passed |
| 6 CONCURRENT runs at load 16 | 3 passed, **3 failed** |

So the trigger is concurrency, not contention — which matters, because the
first explanation anyone reaches for is "the box was busy" and that explanation
is wrong.

## The mechanism, instrumented rather than argued

Each failing run's own scratch had a lock sidecar, and the lock was **not held**
(its owner had been SIGKILLed). `reap` nevertheless filed it as:

    kept: "no lock sidecar and only 0s old — it may be a peer between mkdtemp
           and lock"

That sentence is false about what happened. A **peer reaper** was part-way
through `shutil.rmtree` on that same directory, so the sidecar had already been
unlinked when this walk stat'ed it, and the unlocked branch read a half-removed
directory as a peer that is just starting up. Two `rmtree(..., ignore_errors=
True)` calls over one tree can also leave the directory itself standing.

The caller is then unable to tell *"kept because someone may be starting"* from
*"gone because someone else removed it"* — and a test that asks "is my scratch
gone?" fails for a reason that belongs to another process.

**Positive control, run before writing the fix:** the same six processes with
their `reap()` calls wrapped in one `flock` — 6 of 6 removed. That is what
identified the race, rather than a story about it.

## The fix

`reap` holds a per-`(root, prefix)` reaper lock around its walk.

- A re-entrant call through `remover` (caller code, and it may reach `reap`
  again) is detected by a per-process key set and does not self-deadlock.
- A root where the lock cannot be created walks **unserialised**, which is
  exactly what shipped before. Refusing to reap would trade a rare race for a
  certain leak.
- `flock` is released by the kernel when a process dies, so a crashed reaper
  cannot wedge the next one.

Measured after: 6 concurrent 6/6; 8 concurrent 8/8 twice; 10 concurrent 10/10
twice.

## The reds

| mutation | verdict |
|---|---|
| remove the reaper lock (walk unserialised, as shipped) | CAUGHT — `test_a_second_reaper_waits_for_the_first`, 1 failed / 15 passed |
| drop the re-entrancy guard | CAUGHT — `Timeout (>25.0s) from pytest-timeout`; it wedges on a lock this same process holds |

The first test holds the lock from a **subprocess** deliberately: `flock` is
per-open-file-description, so a same-process holder could re-take its own lock
and the test would prove nothing.

## The repository caught two things in this lane that review did not

**1. The reaper lock was itself litter.** `test_a_clean_run_leaves_no_scratch
_behind` went red:

    AssertionError: a clean run left scratch behind: {.../hostindep-.reap.lock}

Callers ask "what did this run leave behind" with `root.glob(prefix + "*")`, and
the lock was named `<prefix>.reap.lock`, so it answered that question — a module
adding a file to the very namespace it exists to keep clean. Fixed by renaming
to `.<prefix>.reap.lock`, **not** by teaching the test to ignore it. A lock is
not scratch OF that prefix and must not answer a glob that asks for scratch.

**2. A claim of mine had to be retracted.** The first commit called the
pid-identity change in `test_gate_cli_entry_survives_weakening` a "second,
independent defect". It is a real logical flaw — "a `gate_cli_probe_*` directory
that was not there before" is a guess, not an identity, and a concurrent peer's
scratch satisfies it — but I could **not** demonstrate that it produces a
failure once the reaper race is fixed:

    pid check OFF, reaper lock ON:   8 concurrent  → 8 passed
                                    10 concurrent → 10 passed
                                    10 concurrent → 10 passed

So it ships **without a red**, on a logical argument alone, and it is separable:
the whole of the measured defect is the reaper race. A reviewer who wants only
what is proven can drop that one hunk and the flake still does not reproduce.

## The regression

33 test files — every file under `programs/tests/` that touches
`_crash_safe_scratch`, `reap(`, the scratch-root guard, or the mutation probe —
on two same-depth checkouts.

| | base (a4caccefe) | head (this lane) |
|---|---|---|
| failed | 9 | 9 |
| passed | 477 | 479 |
| skipped | 15 | 15 |
| wall | 627 s | 576 s |

**NEW RED: none. FIXED: none.** The nine failures are the same nine ids on both
arms, all in `test_landing_merge_verdict.py`, and are pre-existing on main —
this lane neither causes nor cures them, and I did not investigate them because
they are not this lane's subject.

The +2 passed is this lane's own two tests.

An earlier head arm of this same 33-file set reported **one** new red. It was
the reaper-lock-as-litter defect above; it is fixed, and the arm was re-run on
the frozen tree rather than argued away.

## What this lane does not claim

- It does not change what any gate asserts.
- It does not touch a baseline, an exemption, or `gate_red_since.json`.
- It does not bump the plugin version.
- It is not folded into any assembly.
