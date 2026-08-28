"""A disclosure token must not be able to buy a green cell.

The gate under test closes the half of matrix dimension D6 that D6 does not
ask. Measured on the 68x9 matrix (plugin v1.12.33): mutating a gate so it
stops working and says NOTHING reddens D6 hard; mutating the SAME gate so it
stops working and says ``VACUOUS_PASS`` leaves D6 byte-identical to the clean
tree -- 80 passed / 1 xfailed -- while a project with an empty clock plan
moves from ``status='FAIL'`` to ``status='VACUOUS_PASS'``.

Both arms are asserted here at the same denominator: the mutation the probe
actually ran must be REPORTED, and the shapes the repo legitimately contains
must not be.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import vacuous_disclosure_needs_a_runtime_condition_check as G

_PROGRAMS = Path(G.__file__).resolve().parent
_ROOT = _PROGRAMS.parents[3]


def _findings(src: str):
    found, reason = G.audit_source(src, "sample_check.py")
    assert reason is None, reason
    return found


# ---------------------------------------------------------------- can FAIL --
def test_the_measured_mutation_is_reported():
    """M1: the gate stops working and announces itself vacuous instead."""
    src = (
        "import sys\n"
        "def main():\n"
        "    print('VACUOUS_PASS: clock plan not evaluated')\n"
        "    return 0\n"
    )
    found = _findings(src)
    assert len(found) == 1, found
    assert "VACUOUS_PASS" in found[0]["sentinel"]


def test_an_unconditional_rc2_is_reported():
    """rc 2 is read as VACUOUS by the consumer whatever the text says."""
    src = "import sys\ndef main():\n    sys.exit(2)\n"
    assert len(_findings(src)) == 1


def test_a_helper_no_conditioned_caller_reaches_is_reported():
    """Being in a helper is not itself a condition -- the CALL must be one."""
    src = (
        "def _skip():\n"
        "    print('SKIPPED-CONDITION: nothing to do')\n"
        "def main():\n"
        "    _skip()\n"
    )
    assert len(_findings(src)) == 1


# ---------------------------------------------------------------- can PASS --
def test_a_skip_conditioned_on_a_runtime_fact_is_clean():
    src = (
        "from pathlib import Path\n"
        "def main(p):\n"
        "    if not Path(p).exists():\n"
        "        print('VACUOUS_PASS: no clock plan on disk')\n"
        "        return 0\n"
    )
    assert _findings(src) == []


def test_a_helper_a_conditioned_caller_reaches_is_clean():
    """`lec_equivalence_check`'s shape: the tail of a dedicated helper."""
    src = (
        "def _inconclusive(reason):\n"
        "    print(f'PASS_WITH_WAIVERS: LEC not decided ({reason})')\n"
        "    return 3\n"
        "def main(result):\n"
        "    if result is None:\n"
        "        return _inconclusive('LEC_INCONCLUSIVE')\n"
        "    return 0\n"
    )
    assert _findings(src) == []


def test_prose_naming_a_sentinel_is_not_a_disclosure():
    """A docstring that DISCUSSES VACUOUS_PASS is prose, not the gate speaking."""
    src = (
        '"""This gate never emits VACUOUS_PASS; see SKIPPED-CONDITION."""\n'
        "SENTINELS = ('VACUOUS_PASS', 'NOT_RUN')\n"
        "def main():\n"
        "    return 0\n"
    )
    assert _findings(src) == []


def test_a_sentinel_counted_in_a_summary_line_is_not_a_disclosure():
    """`flow_step_executor_coverage_check`'s shape: a LABEL, not a verdict.

    The consumer reads a sentinel only at line START, so a count printed
    mid-line cannot be read as this run's verdict.
    """
    src = (
        "def main(rows, disclosed):\n"
        "    print(f'steps={len(rows)}  DISCLOSED-SKIP={len(disclosed)}')\n"
    )
    assert _findings(src) == []


# ------------------------------------------------------------- fail-safe ----
def test_an_unparseable_module_is_unanalysable_not_clean():
    found, reason = G.audit_source("def main(:\n", "broken_check.py")
    assert found == []
    assert reason and "unparseable" in reason


# ------------------------------------------------------------ corpus sweep --
def test_the_repo_sweeps_clean():
    """A guard that fires on the state it ships with is a bug, not a guard."""
    rc = subprocess.run(
        [sys.executable, str(_PROGRAMS / G.__name__) + ".py",
         "--root", str(_ROOT), "--strict"],
        capture_output=True, text=True)
    assert rc.returncode == 0, rc.stdout[-3000:]
