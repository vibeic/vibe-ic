# Four tests write into the shipped tree, and the guard cannot see a killed session

Measured 2026-08-20 on `int/two-paths-all` @ `c67efd4543`, in the pinned EDA
image (`ghcr.io/vibeic/vibeic-eda@sha256:66c33ff…0d01ff`), via `docker run --skip`.

## The population

Four tests plant a **new `.py` file into the shipped `programs/` directory** —
not into `tmp_path` — and rely on teardown to remove it:

| test | file it plants |
|---|---|
| `programs/tests/test_issue559_drift_check_rule_b_blindspot.py:196` | `brand_new_hand_rolled_check.py` |
| `programs/tests/test_gate_discloses_denominator.py:40` | `_probe_<name>.py` |
| `programs/tests/test_phase2a_gate_contract_check.py:49` | `__fake_gate_for_test__.py` |
| `programs/tests/test_gate_skip_routing_check.py:83` | `_i528_report_only_disclosure_check.py` |

Each is legitimate in intent: all four need a gate that does not already exist,
and the registry they exercise is keyed on a file being present in `programs/`.
All four clean up in a `finally` / teardown.

## What actually defeats the guard — and what does NOT

`suite_write_guard` is a **pytest plugin** (registered by `pytest_plugins` in
`vibe-ic-marketplace/plugins/vibe-ic/conftest.py:66`), implementing
`pytest_runtest_teardown` and `pytest_sessionfinish`
(`programs/suite_write_guard.py:477,491`).

**`--maxfail` does NOT defeat it.** Controlled A/B, same worktree, same
selection, counting `suite_write_guard` / `WRITE_GUARD_NOT_CHECKED` lines:

    pytest -q --maxfail=1 …   -> 1  ([PASS] suite_write_guard: … wrote nothing)
    pytest -q …               -> 1  ([PASS] suite_write_guard: … wrote nothing)

A `--maxfail` stop is a normal session end: completed tests have already run
their `finally`, and `pytest_sessionfinish` still fires. Any claim that
truncation lets these writes survive unnoticed is wrong, and it matters that it
is wrong — it points remediation at the wrong mechanism.

**A KILLED session defeats it, completely.** Deterministic demonstration: a test
that plants a file into `programs/` and then `os.kill(os.getpid(), SIGKILL)`:

    guard lines emitted:                     0
    git status --porcelain afterwards:  ?? vibe-ic-marketplace/plugins/vibe-ic/programs/_killdemo_planted_check.py

No `pytest_runtest_teardown`, no `pytest_sessionfinish`, no `finally` — so no
cleanup and no report. The debris is left in the shipped tree, and the run that
left it emitted no verdict at all, which is the state most easily mistaken for
"nothing happened".

This is not hypothetical: it is how `brand_new_hand_rolled_check.py` came to sit
untracked in a working tree during this session, after a `docker kill` of a
long-running arm.

## Why it is worth fixing rather than remembering

The guard's own contract is that a run cannot lie about what it wrote. Against a
kill it does not report a failure — it reports *nothing*, and silence is
indistinguishable from a clean run in a scrollback. Three things follow:

1. **A killed run must not be read as evidence of anything**, including of a
   clean tree. Confirm the summary line before believing a result.
2. **`git status --porcelain` on the worktree is the cheap independent check**
   after any run that did not print its own summary.
3. **The durable fix is to stop needing teardown**: these four tests want a
   `programs/` directory they can plant into, not *the shipped* `programs/`
   directory. A copied tree, or a registry root injected via the option the
   guard already understands, removes the whole class — including the cases
   where the process dies for reasons no `finally` can catch.
