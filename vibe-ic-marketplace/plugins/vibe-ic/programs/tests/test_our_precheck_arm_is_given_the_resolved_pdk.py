#!/usr/bin/env python3
"""Step 37.5ic's OWN arm was launched without the PDK it needs to decide.

THE DEFECT
----------
`general_precheck --pdk` exists so the ladder's density rung can be judged
against the PDK's OWN stated per-layer windows. Without it that delegate has no
windows, every metal layer comes back UNCHECKED, and `Checker.KLayoutDensity`
cannot reach a verdict — a WIRING gap, reported downstream as a property of the
die.

That forwarding was closed one level down — `general_precheck` ->
`metal_layer_density_check` — by
`tests/test_gf180_general_precheck_forwards_the_pdk.py`. It was left open one
level UP, at `tapeout_precheck`, which is the only caller of our arm and the
one place that has a resolved PDK to give: the argv it built named
`--json`, `--gds` and `--declaration`, and nothing else. So the chain was
proven from the middle onwards while its first link was never connected, and
the closed gate stayed shut on every real run.

MEASURED, 8HD-8, subservient x gf180mcuD, v1.17.22 frozen main:
`reports/phase3/tapeout_precheck.json` carries `Checker.KLayoutDensity`
NOT_DETERMINED on our own arm.

WHAT IS PINNED, BOTH DIRECTIONS
-------------------------------
D1  A resolvable PDK REACHES the arm, and the value forwarded is the SAME
    `pdk` the merged report publishes — not a second resolution that could
    disagree with the one the operator arm is selected by.
D2  An UNRESOLVED PDK forwards NOTHING. The flag is omitted exactly as before,
    the delegate says it had no windows, and an unknown process is never
    laundered into a clean density result. Without this half D1 would also pass
    against a program that appended `--pdk` unconditionally with an empty
    value, which is a different (and worse) defect.
"""
import json
import sys
from pathlib import Path
from typing import List

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import tapeout_precheck as TP              # noqa: E402
import general_precheck as GP              # noqa: E402

from test_tapeout_precheck_two_arms import (  # noqa: E402
    _project, _DIE_ANSWERS)
from test_general_precheck import _die_at_origin  # noqa: E402


def _capture_our_argv(proj: Path) -> List[List[str]]:
    """Run the merge with a runner that records every argv and writes a
    well-formed report, so the merge proceeds and the argv is the only thing
    under test."""
    seen: List[List[str]] = []

    def run(cmd, timeout):
        seen.append(list(cmd))
        out = Path(cmd[cmd.index("--json") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(
            {"verdict": GP.PASS, "reason": "stand-in", "steps": []}))
        return 0, "", ""

    rep = TP.evaluate(proj, runner=run)
    return [c for c in seen if any("general_precheck.py" in x for x in c)], rep


def _pdk_flag(argv: List[str]):
    return argv[argv.index("--pdk") + 1] if "--pdk" in argv else None


def test_d1_a_resolvable_pdk_reaches_our_own_arm(tmp_path):
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="ihp-sg13g2", slots=False)
    ours, rep = _capture_our_argv(proj)
    assert ours, "our arm was never launched"
    assert _pdk_flag(ours[0]) == "ihp-sg13g2", (
        "the density rung is judged against the PDK's own per-layer windows "
        "and cannot find them without --pdk; got argv "
        f"{ours[0]!r}")


def test_d1_the_value_forwarded_is_the_one_the_report_publishes(tmp_path):
    """One resolution, used by both arms. Two would let our ladder be judged
    against a different process from the one the operator arm was chosen by."""
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="gf180mcuD", slots=False)
    ours, rep = _capture_our_argv(proj)
    assert _pdk_flag(ours[0]) == rep.pdk, (
        f"forwarded {_pdk_flag(ours[0])!r} but published {rep.pdk!r}")
    assert rep.pdk, "the fixture was supposed to make the PDK resolvable"


def test_d2_an_unresolved_pdk_forwards_nothing(tmp_path):
    """THE FALSIFYING HALF. A program that always appended `--pdk` would pass
    D1 and fail here, and an unknown process would reach the delegate as an
    empty string it cannot refuse on."""
    proj = _project(tmp_path, _die_at_origin, _DIE_ANSWERS,
                    pdk="", slots=False)
    ours, rep = _capture_our_argv(proj)
    assert ours, "our arm was never launched"
    assert not rep.pdk, (
        "the fixture was supposed to leave the PDK unresolved; got "
        f"{rep.pdk!r}")
    assert _pdk_flag(ours[0]) is None, (
        "an unresolved PDK must be forwarded as ABSENCE, never as an empty "
        f"flag value; got argv {ours[0]!r}")
