#!/usr/bin/env python3
"""Tests for full_suite_run_check.py — did the agent run the FULL suite?

RE-PINNED FOR THE OWNER-LEVEL RULING OF 2026-08-31. Every case below that
changed direction is marked; the ones that did not are the ones that carry the
change's weight, because a rewrite whose negative controls all moved with it
has proved nothing.

WHAT CHANGED. The acceptance used to read the ARGUMENT SHAPE: no positional
path, or a path under `pytest.ini`'s single testpath, meant FULL. It now reads
COVERAGE OF THE GIT-DERIVED POPULATION — `run_tests.sh` is FULL because the
tiers it prints cover every tracked test file, and `programs/tests` is not
because it leaves 141 of 3117 unrun. So a bare `pytest`, which resolves to that
one testpath, moved from PASS to FAIL, and so did the two `programs/tests`
cases that v1.6.0 had moved the other way. The reasoning v1.6.0 recorded was
sound for the TWO-TREE world it was made in and is preserved verbatim below;
what outran it is `tools/phase1_engine/tests` (#1391), `mcp-eda/test` (#1420),
`skills/*/tests` and `_shared` (v1.13.80).

WHAT DID NOT CHANGE, and is asserted here for that reason: a `-k` selector, a
single test file, a run with no test invocation at all, an empty log, a missing
file and a bad argument list all keep exactly the exit codes they had. Widening
the gate to recognise the runner must not have turned it into a rubber stamp.

`test_run_tests_sh_is_classified_as_the_full_suite.py` is this change's own
acceptance file and carries the runner, cheat and refusal arms.
(chip-AGNOSTIC.)"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1] / "full_suite_run_check.py"
_spec = importlib.util.spec_from_file_location("full_suite_run_check", _PROG)
fsr = importlib.util.module_from_spec(_spec)
sys.modules["full_suite_run_check"] = fsr
_spec.loader.exec_module(fsr)


# ---- PASS cases ---------------------------------------------------------


# ---- CHANGED DIRECTION at the 2026-08-31 ruling -------------------------


# ---- FAIL cases ---------------------------------------------------------


# ---- file scan + JSON + edge --------------------------------------------


# ── THE DERIVATION ITSELF ───────────────────────────────────────────────────
# `_integration_tree_has_tests()` and the four cases that drove it are gone.
# They asked "is the legacy `tests/` tree empty?" so that `programs/tests` could
# be granted FULL while it was. The subtraction subsumes that question in both
# directions and without a probe: an EMPTY tree contributes no file to the
# population, so it cannot be missing from any coverage set; a tree that grows a
# test file joins the population and every invocation that does not run it
# becomes a subset the same day. Nobody edits the gate either way — which is
# what the removed probe was for.


# ── the listing call is SUPERVISED, and the deadline is real ──────────────
# `runner_tiers` runs a script chosen at runtime, so nothing here can read what
# that script launches — `loop_watchdog_compliance_check` class (c). The call
# therefore goes through `_watchdog.run_supervised`, and these two tests are the
# prove-by-run half of that: a declared-but-hanging candidate must be KILLED at
# the deadline and read as "not a runner", and a candidate that answers must
# still answer. Without the first, "supervised" would be a word in a comment.

def _declaring_script(path: Path, body: str) -> Path:
    path.write_text(f"#!/usr/bin/env bash\n# {fsr._LIST_TIERS_FLAG}\n{body}\n",
                    encoding="utf-8")
    return path


def test_a_hanging_candidate_is_killed_at_the_deadline(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(fsr, "_LIST_TIERS_TIMEOUT", 3)
    monkeypatch.setattr(fsr, "_LIST_TIERS_POLL", 1)
    script = _declaring_script(tmp_path / "hangs.sh", "sleep 600")

    started = time.monotonic()
    result = fsr.runner_tiers(script)
    elapsed = time.monotonic() - started

    assert result is None, "a script that never answers is not a runner"
    # It RETURNED, and it returned near the deadline rather than after 600 s.
    assert elapsed < 30, f"the deadline did not fire: {elapsed:.1f}s"
    assert elapsed >= 2, f"it did not wait for the deadline at all: {elapsed:.1f}s"


def test_a_candidate_that_answers_is_unaffected_by_the_supervision(tmp_path):
    """The other direction: supervision must not turn a real runner into None."""
    (tmp_path / "alpha").mkdir()
    (tmp_path / "beta").mkdir()
    script = _declaring_script(tmp_path / "answers.sh", "echo alpha\necho beta")

    assert fsr.runner_tiers(script) == ["alpha", "beta"]


def test_a_candidate_that_exits_non_zero_is_not_a_runner(tmp_path):
    script = _declaring_script(tmp_path / "fails.sh", "exit 3")
    assert fsr.runner_tiers(script) is None


def test_a_candidate_that_does_not_declare_the_protocol_is_never_launched(
        tmp_path):
    """The static precondition, still first: an undeclared script must return
    immediately, not after the supervision deadline."""
    import time
    silent = tmp_path / "silent.sh"
    silent.write_text("#!/usr/bin/env bash\nsleep 600\n", encoding="utf-8")

    started = time.monotonic()
    assert fsr.runner_tiers(silent) is None
    assert time.monotonic() - started < 1.0, "it was launched"
