# The scratch-root rule for this agent's runners

MEASURED 2026-08-21, and it cost a false finding.

    TMPDIR=/home/reyerchu/_ptmo_priv/tmp1166t/image   (96 chars) -> test FAILED
    TMPDIR=/tmp/ptmo_short                            (16 chars) -> test PASSED

`test_flow_compliance_check_gate::test_a_real_verdict_is_not_mistaken_for_a_crash`
asserts a marker is present in a FIXED-SIZE evidence window. A long scratch path
fills that window with path and pushes the marker out, so the length of the
directory I chose decided the verdict.

THE RULE, and it has two clauses because the two traps are different:

  1. SHORT.  The scratch root must be short — `/tmp/ps` class, not a descriptive
     path that encodes the run, the version and the lane. Descriptive names are
     for the OUTPUT directory, which no test reads.
  2. OUTSIDE $HOME.  `tools/ci/hermetic_candidate_runner.py:426` refuses any
     subject or corpus under `$HOME` ("would expose the host HOME to the
     candidate"). A scratch root under `$HOME` produces a whole file of reds
     that are about the operator's home directory.

`/tmp/ps` satisfies both. `/home/reyerchu/_ptmo_priv/tmp<version><lane>`
satisfies neither, and I used it for most of this job.

Both traps share one shape: the measurement environment leaked into the verdict,
and in both cases the tell was in the TEXT of the failure — a snippet starting
mid-path; a refusal naming HOME — never in its colour.
