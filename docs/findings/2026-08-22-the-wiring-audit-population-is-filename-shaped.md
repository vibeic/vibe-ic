# "Is every checker wired?" cannot be answered: the audit's population is filename-shaped

_Measured 2026-08-22 on host `8hd-3` against `jdistmat/matrix-distil` at
`facc28860` (main `a4caccefe` merged in, so every figure below is also a figure
about main). Repository tooling only: no design, PDK, vendor or part identifier
appears._

## Why this was measured

A landing owner has to decide whether to wire twenty new instruments. Neither
`gate_is_wired_check` nor `checker_execution_wiring_audit` reports them as
unwired — and the reason is not that they are wired. It is that neither can see
them.

## The population

`checker_execution_wiring_audit.py:178`

    _CHECKER_SUFFIXES = ("*_check.py", "*_audit.py", "*_guard.py", "*_lint.py",
                         "*_gate.py")

    top-level programs                        1260
    inside the filename-shaped population      624
    outside it                                 636

The audit that asks whether a checker is wired examines **less than half** the
top-level programs, and membership is decided by how a file is NAMED.

That is the defect this branch's own
`layer_membership_is_declared_not_inferred_from_a_filename_prefix` refuses, in
the tool whose job is to notice unwired checkers.

## It has been hit before, and was answered by lengthening the list

The audit's own docstring records it:

> Until 2026-08-03 the population was `*_check.py` + `*_audit.py` — 533 of the
> …

The response was to add `*_guard.py`, `*_lint.py` and `*_gate.py`. That is a
FIX, not a RULE: it repairs the instances someone noticed and leaves the method
— membership by filename — exactly as it was. The next program named outside
the list is invisible again, which is what happened.

## How many are invisible, honestly bounded

A program "behaves like a checker" if it emits a verdict and can refuse. Two
predicates, deliberately reported as a RANGE rather than as one number:

| predicate | outside the population | this branch's | pre-existing on main |
|---|---:|---:|---:|
| emits `[PASS]`/`[FAIL]`, has a `__main__` | 46 | 17 | **29** |
| that, AND a literal `return 1` / `sys.exit(1)` | 23 | 8 | **15** |

**The strict figure UNDER-counts, and this branch's own instruments prove it:**
it finds 8 of the 20, though all 20 refuse — because they assign `rc = 1` and
then `return rc`, which no literal match sees. The true count is above 23 and at
most 46. It is left as a range on purpose: a single number here would be a
literal-match artefact, which is the error this whole capture exists to remove.

What is not in doubt is the direction. **At least fifteen verdict-emitting,
refusing programs already on `main` are outside the population of the audit
that asks whether checkers are wired.** They are not reported as unwired; they
are not reported at all.

## What this means for the twenty

Wiring them has exactly two honest routes:

1. **Rename them to a suffix** — `*_check.py` and so on. This makes them
   visible by making them conform to a NAME, which is the practice
   `layer_membership_is_declared_not_inferred_from_a_filename_prefix` and
   `invocation_proved_by_parse_not_by_text` both refuse. It also fixes twenty
   instances and leaves the 15+ pre-existing ones invisible.
2. **Give the audit a structural population** — every top-level program that
   emits a verdict and has a refusing exit path, with the filename suffixes
   kept as ONE contributor and asserted to be a subset. This is the same remedy
   the layer gate proposes for `ppa_*.py`, and it covers the pre-existing 15
   in the same move.

The second is the one that stops the question recurring. Both are the owner's
call; this document does not take it, and no code here is changed.

## Reproducing it

    python3 - <<'PY'
    import pathlib
    P = pathlib.Path("vibe-ic-marketplace/plugins/vibe-ic/programs")
    sufs = ["*_check.py","*_audit.py","*_guard.py","*_lint.py","*_gate.py"]
    pop = set()
    for s in sufs: pop |= {f.name for f in P.glob(s)}
    allp = {f.name for f in P.glob("*.py")}
    print(len(allp), len(pop), len(allp - pop))
    PY

## The numbers above decay; a census does not

Every figure in this document is a measurement taken at one sha, which is the
failure mode this whole capture exists to remove. It is therefore also shipped
as a program:

    programs/checker_population_is_structural_not_filename_shaped_census.py

A CENSUS, not a gate: it reports and exits 0, `--strict` restores a refusal, and
its docstring names the refusing instrument for the class. It reads the audit's
`_CHECKER_SUFFIXES` tuple FROM THE AUDIT'S SOURCE rather than re-typing it, so
widening that tuple shrinks the census with no edit here -- pinned by a test.

Run on this tree it reports 1261 / 624 / 637, **47** verdict-emitting programs
outside the population (**43** of them with a literal banner inside a `print()`)
and **35** that also refuse. That 35 sits inside the
23-to-46 range this document predicted, and is above the literal-only 23 for
exactly the stated reason: the census counts `rc = 1; return rc`, which a
literal match never sees. The range was honest; the census narrows it.

## The wiring decision is COUPLED to the protected-tuple repair

_Measured 2026-08-22 against `origin/main` at `ae78abb28`._

Wiring a gate here means adding a `python3 "$PG/<name>.py"` line to
`tools/ci/repo_hygiene_gates.sh` — the invocations are a hand-maintained
enumeration, 1834 lines of them. That file is:

    a PINNED authority path in protected_landing_transition.json   yes
    its live state on main                                         NEITHER
    declared to move by the open transition                        no

So it is one of the eight paths in group B of the drift finding: already
mismatched, and moved by something the transition never authorised.

**Editing it to wire anything adds a further unauthorised change to a protected
path that is already in a refusing state.** That is not a reason never to wire;
it is a reason the two decisions cannot be taken separately. Whoever wires these
either repairs the tuple first, or knowingly adds a ninth unauthorised move to
group B while the receipt machinery is already unable to answer.

This is why no wiring change is prepared on this branch. It would look helpful,
it would be one line per gate, and it would quietly make the harder problem
worse. The measurement that wiring the 17 green instruments costs main nothing
still stands — it is the ONLY part of that decision that is free.
