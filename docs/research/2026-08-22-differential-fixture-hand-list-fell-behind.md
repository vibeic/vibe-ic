# 16 reds no arm sees, and why the obvious fix makes it worse

Measured 2026-08-22 at `origin/main` `a4caccefe` (v1.11.69).

## THEY ARE INVISIBLE TO TARGETED SELECTION

`ci_targeted_test_select --base origin/main` routes **0 of the 20**
`tools/test_*.py` files. There are 20 of them and no branch's two-arm
measurement has ever included one. Run by hand, both arms:

    base a4caccefe            17 failed, 485 passed
    agent/jrows-on-batchbig   16 failed, 486 passed
      NEW      0
      FIXED    1   tools/test_liar_census.py (the 181 -> 182 pin)
      CARRIED 16   all in tools/test_gatekeeper_land_differential.py

So main carries 16 reds in one file that the selector cannot reach.

## THE PROXIMATE CAUSE IS NAMED

The synthetic-repo fixture copies a HAND-LIST of programs into the stub:

    for mod in ("hygiene_finding_delta.py", "_atomic_artefact.py",
                "gate_process_attestation.py"):

`tools/gatekeeper-land-differential.sh` invokes **eight**:

    attestation_preflight_check      generated_test_list_min_guard
    ci_targeted_test_select          landing_merge_verdict
    hygiene_finding_delta            landing_noop_verdict_check
    landing_worktree_is_clean_check  pytest_per_file_junit

The missing ones make the stub answer `can't open file ...` or
`ModuleNotFoundError`, so each case refuses for THAT reason instead of the one
it is about — e.g. `assert "protected landing transition: STEADY" in out`
against output whose only content is a traceback.

## AND WHY "JUST ADD THEM" IS NOT THE FIX — MEASURED, NOT ARGUED

Adding them one layer at a time only moves the error:

    + landing_noop_verdict_check.py            still 16 (now _gate_usage_exit)
    + its transitive imports (3)               still 16 (now
                                               attestation_preflight_check)

The full closure of all eight is **148 modules**, which would make the
"synthetic" repo a copy of the real one. Per root:

    pytest_per_file_junit            139
    attestation_preflight_check        3
    generated_test_list_min_guard      3
    landing_noop_verdict_check         3
    landing_merge_verdict              2
    hygiene_finding_delta              1
    ci_targeted_test_select            0
    landing_worktree_is_clean_check    0

`pytest_per_file_junit` alone is the outlier. Excluding it leaves a practical
7 modules — so I added those seven and re-ran:

    17 failed, 11 passed

**One WORSE than before.** That is the answer: the fixture's minimality is
deliberate, and putting real programs into the stub changes the behaviour the
test exists to isolate. The experiment was reverted; nothing here is applied to
any branch.

## WHAT IS ACTUALLY BEING DECIDED

The fix is a design choice about how the stub repo is built, and it is not
mine to make:

  * compute the closure at RUNTIME instead of hand-listing it (and accept that
    the stub stops being minimal), or
  * make `gatekeeper-land-differential.sh` TOLERATE an invoked program being
    absent, and say so in its output, or
  * stub the invoked programs rather than copy them, so the differential is
    isolated on purpose rather than by omission.

Whichever is chosen, the hand-list is the thing that rotted: it must follow the
lander's invocation set, and today nothing checks that it does. That is the
same shape as the `liar census` shrink-pin and the `waivers.py` FILE:LINE
citations — a list that has to be updated by hand, with no gate asserting it
was.
