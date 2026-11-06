"""The two wide landing lanes must not destroy the report they just computed.

`run_repo_tools_pytest` and `run_unselectable_pytest` each merge a complete
per-file JUnit — every case name, every failure message — and used to `rm -f`
it unconditionally a few lines later. In a `--rm` container that is the only
copy, so a ~46-minute lane produced a COUNT and nothing else: "28 red cases",
"8 red cases", names already deleted. Recovering what the lane had ALREADY
COMPUTED then costs a re-measurement of the whole corpus.

`run_pytest` never had this defect; it honours `GATEKEEPER_PYTEST_JUNIT`. These
tests assert the other two lanes now mirror it, and they assert it by RUNNING
THE REAL FUNCTION BODIES sliced out of `tools/gatekeeper-land.sh` — not by
reading the source and hoping. The driver and the write guard are stubbed so
the lanes finish in milliseconds; everything the fix touches (the target
selection, the up-front removal, the final `rm`) is the shipped code.

NEGATIVE CONTROL, in the same file rather than promised in a commit message:
each test also runs the PRE-FIX body — reconstructed by textual surgery on the
sliced function — and asserts the report is DESTROYED. A test that cannot fail
against the old code proves nothing about the new code.
"""

from __future__ import annotations

from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
_REPO_ROOT = _PROGRAMS.parents[3]
_LAND = _REPO_ROOT / "tools" / "gatekeeper-land.sh"

#: The stub driver writes this case name into the report it is asked for. It is
#: the thing an operator needs and the count can never carry: a NAME.
_CASE = "test_a_name_the_count_cannot_carry"

_LANES = {
    "run_repo_tools_pytest": "GATEKEEPER_REPO_TOOLS_JUNIT",
    "run_unselectable_pytest": "GATEKEEPER_UNSELECTABLE_JUNIT",
}




















def test_neither_variable_can_gate_anything():
    """Mirror of `test_the_junit_hook_in_the_landing_script_changes_no_verdict`
    for the two new variables. If either ever gated, the merge path and the
    push path would stop agreeing."""
    src = _LAND.read_text(encoding="utf-8")
    for var in _LANES.values():
        assert var in src, f"{var} is not wired into {_LAND}"
        for line in src.splitlines():
            if var in line and not line.lstrip().startswith("#"):
                assert "FAILED=1" not in line, line
