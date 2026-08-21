"""The landing review has a budget, and running out of it BLOCKS.

Owner ruling, 2026-08-21: a landing may spend up to four minutes on
`gatekeeper_review`, and "if the review cannot decide inside that, it must
return rc=2 UNDETERMINED and BLOCK, never rc=0".

The function is EXTRACTED FROM THE REAL SCRIPT rather than restated here. A
copy of the case statement in a test would go on passing after the script's own
copy was edited, which is the drift this repo removes from gates one at a time;
`_extract` fails loudly if the function is renamed or reshaped.
"""
from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LANDER = ROOT / "tools" / "gatekeeper-land.sh"


def _extract(name: str) -> str:
    src = LANDER.read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(name)}\(\) \{{\n(.*?)^\}}\n",
                  src, re.S | re.M)
    assert m, f"{name}() is not in {LANDER.name} in the shape this test drives"
    return f"{name}() {{\n{m.group(1)}}}\n"


def _drive(tmp_path, stub_body: str, budget: str = "240"):
    """Run the REAL function against a stub `gatekeeper_review.py`."""
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / "gatekeeper_review.py").write_text(
        textwrap.dedent(stub_body), encoding="utf-8")
    script = tmp_path / "drive.sh"
    script.write_text(
        "set -u\n"
        f'PROGRAMS="{programs}"\nROOT="{tmp_path}"\nBASE="origin/main"\n'
        f'GK_HYG_RECORD="{tmp_path}/rec.json"\nGK_HYG_RC=0\n'
        f'GK_REVIEW_BUDGET_S="{budget}"\n'
        + _extract("run_gatekeeper_review")
        + 'run_gatekeeper_review; echo "RC=$?"\n',
        encoding="utf-8")
    r = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                       timeout=120)
    rc = int(re.search(r"RC=(-?\d+)", r.stdout).group(1))
    return rc, r.stdout


def test_a_review_that_says_merge_ok_passes(tmp_path):
    rc, out = _drive(tmp_path, """
        import sys
        print("VERDICT: MERGE_OK")
        sys.exit(0)
        """)
    assert rc == 0, out


def test_a_review_that_requests_changes_blocks(tmp_path):
    rc, out = _drive(tmp_path, """
        import sys
        print("VERDICT: REQUEST_CHANGES")
        sys.exit(1)
        """)
    assert rc == 1, out


def test_a_review_that_runs_out_of_budget_is_rc_2_and_blocks(tmp_path):
    """THE RULING'S CASE. Not rc 0, and not the 124 `timeout` really returns —
    a landing must be able to tell 'undecided' from 'decided nothing is wrong',
    and 124 reaching a caller that only special-cases 0 and 1 is how the first
    becomes the second."""
    rc, out = _drive(tmp_path, """
        import time
        time.sleep(30)
        """, budget="1")
    assert rc == 2, out
    assert "UNDETERMINED" in out
    assert "did not decide within 1s" in out


def test_an_unexpected_exit_status_is_rc_2_and_blocks(tmp_path):
    """A crash, an import error, a python that is not there. None of them are
    MERGE_OK and none of them are REQUEST_CHANGES, so none of them may be
    resolved by guessing which one they resemble."""
    rc, out = _drive(tmp_path, """
        raise SystemExit(9)
        """)
    assert rc == 2, out
    assert "UNDETERMINED" in out and "exited 9" in out


def test_a_review_killed_outright_is_rc_2_and_blocks(tmp_path):
    rc, out = _drive(tmp_path, """
        import os, signal
        os.kill(os.getpid(), signal.SIGKILL)
        """)
    assert rc == 2, out
    assert "UNDETERMINED" in out


@pytest.mark.parametrize("stub,expect", [
    ("import sys; sys.exit(0)", 0),
    ("import sys; sys.exit(1)", 1),
    ("import sys; sys.exit(2)", 2),
    ("import sys; sys.exit(3)", 2),
])
def test_no_status_other_than_zero_reaches_a_caller_as_a_pass(
        tmp_path, stub, expect):
    rc, out = _drive(tmp_path, stub)
    assert rc == expect, out
    if expect != 0:
        assert rc != 0


# --- the wiring itself, so it cannot quietly come undone -------------------

def test_the_lander_actually_calls_the_review():
    src = LANDER.read_text(encoding="utf-8")
    assert 'run "full:gatekeeper-review"' in src, (
        "the review is defined but never invoked — which is the exact state "
        "this wiring exists to end")


def test_the_review_is_a_declared_landing_unit():
    """`landing_completion_record.finish` refuses unless the emitted labels
    equal the complete tuple, so a unit the lander emits and the tuple does not
    declare would refuse every landing — and one the tuple declares and the
    lander never emits would do the same."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_lcr", ROOT / "tools" / "ci" / "landing_completion_record.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    units = list(mod.LANDING_PROGRESS_UNITS)
    assert "full:gatekeeper-review" in units
    # AFTER the hygiene run whose record it reads, and BEFORE the closing tree
    # gates, which is the only position where its input exists and its own
    # writes are still covered.
    assert units.index("full:repo-hygiene") < units.index("full:gatekeeper-review")
    assert units.index("full:gatekeeper-review") < units.index("full:write-guard-final")


def test_the_hygiene_record_is_written_unconditionally():
    """With no record the review can only report `skipped — 0 gate state(s)
    examined`, which is a deadline that never comes due."""
    src = LANDER.read_text(encoding="utf-8")
    assert 'GK_HYG=(--summary-json "$GK_HYG_RECORD")' in src
    assert re.search(r'GK_HYG_RECORD="\$\{GATEKEEPER_HYGIENE_REPORT:-', src)
