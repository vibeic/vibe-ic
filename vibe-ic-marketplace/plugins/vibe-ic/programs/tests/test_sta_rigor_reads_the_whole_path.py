#!/usr/bin/env python3
"""A recovery violation was dropped for being far from its Endpoint line.

THE DEFECT, REPRODUCED. `_check_types_violations` looked for a path's
`slack (VIOLATED)` line inside a 2000-CHARACTER window after the Endpoint that
names the recovery/removal check. In OpenSTA output that slack line comes AFTER
the whole path detail, so the distance is a function of PATH LENGTH — and a
sign-off path routinely runs to dozens or hundreds of lines.

MEASURED on a synthetic recovery path whose only variable is the number of
detail lines. The violation is present and identical in every one:

     10 detail lines   slack   481 bytes after the Endpoint   -> reported
     60 detail lines   slack  2681 bytes after                -> MISSED
    200 detail lines   slack  8941 bytes after                -> MISSED

So this check reported a CLEAN result over a report containing a genuine
recovery/removal violation, and the longer the path the more certain it was to
miss it. A false clean is the one direction a sign-off rigor check must never
fail in.

THE FIX IS NOT A BIGGER WINDOW. The right boundary was already in the code: the
scope of a path ends where the NEXT `Startpoint:` begins, and the function
already computed that. The byte window was redundant and lossy — it truncated
before the structural bound could apply. The MPW loop in the same function has
always done this correctly, bounding on its own structural stoppers with no byte
count, which is what makes the 2000 an oversight rather than a considered bound.

WHY A TEST RATHER THAN JUST A FIX: nothing about a dropped violation is visible.
The report still parses, the check still returns, and the verdict is clean. Only
a test that puts a violation FAR from its Endpoint can tell the two apart.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent


def _mod():
    saved = list(sys.path)
    sys.path.insert(0, str(_PROGRAMS))
    try:
        spec = importlib.util.spec_from_file_location(
            "_sta_rigor_t", _PROGRAMS / "sta_signoff_rigor_check.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        return m
    finally:
        sys.path[:] = saved


def _path(detail_lines: int, violated: bool = True, tail: str = "") -> str:
    """One OpenSTA recovery path whose only variable is its LENGTH."""
    detail = "\n".join(
        f"   0.42   1.13 ^ u_reg_{i}/CLK (cell_1)" for i in range(detail_lines))
    slack = "  -0.83   slack (VIOLATED)" if violated else "   0.83   slack (MET)"
    return ("Startpoint: u_a/CLK (rising edge-triggered flip-flop)\n"
            "Endpoint: u_b/RESET_B (recovery check against rising-edge clock clk)\n"
            "Path Group: asynchronous\nPath Type: min\n"
            f"{detail}\n{slack}\n\n" + tail)


@pytest.mark.parametrize("lines", [10, 60, 200, 1000])
def test_a_violation_is_found_however_long_the_path_is(lines):
    """THE REGRESSION. The violation is identical in every one of these; only
    the distance from the Endpoint changes. A check whose answer depends on how
    many cells a path happens to traverse is not checking the design."""
    found = _mod()._check_types_violations(_path(lines))
    assert found, (
        f"a recovery violation {lines} detail lines from its Endpoint was not "
        f"reported. The scope is bounded by a byte count again, so a long path "
        f"hides its own violation — a FALSE CLEAN on sign-off")
    # The function reports the ENDPOINT that owns the violated path, not the
    # slack line itself — checked here so this test cannot pass on some future
    # finding that happens to be truthy for an unrelated reason.
    assert any("recovery check" in f.lower() for f in found), found


def test_a_met_path_is_not_reported_however_long_it_is():
    """The other direction, so "finds it at any length" is not satisfied by a
    check that reports every path. A path that MET must stay silent."""
    assert _mod()._check_types_violations(_path(200, violated=False)) == []


def test_a_later_paths_violation_does_not_leak_back_into_a_clean_one():
    """THE BOUND THE WINDOW WAS DOING BY ACCIDENT, now done on purpose.

    Removing the byte cap means the look-ahead runs to the next `Startpoint:`.
    If that bound were wrong, a CLEAN path followed by a violating one would be
    reported as violating — trading a false clean for a false alarm, which is
    not a fix. The clean path here is followed by a violating path, and only
    the violating one may be reported."""
    m = _mod()
    clean_then_dirty = _path(200, violated=False, tail=_path(200, violated=True))
    found = m._check_types_violations(clean_then_dirty)
    assert len(found) == 1, (
        f"expected exactly the second path's violation, got {found}")


def test_the_scope_is_not_bounded_by_a_byte_count_any_more():
    """Read from the source, because the two failure modes are indistinguishable
    from the outside once a fixture is short enough to fit whatever the bound
    is. A future edit that reintroduces a window would pass every test above
    with a large enough number and fail the design the day a path got longer."""
    src = (_PROGRAMS / "sta_signoff_rigor_check.py").read_text()
    # PRESENCE of the marker, stated as presence. `len(src.split(m, 1)) == 2`
    # says the same thing, and reads to `population_pin_without_its_member_set`
    # as a SIZE pinned over a live population (2 via read_text) with no member
    # set beside it -- which is exactly the shape that rule refuses.
    marker = "_RECOVERY_REMOVAL_ENDPOINT_RE.finditer"
    assert marker in src, "the recovery/removal scan has moved; re-derive this"
    fn = src.split(marker, 1)
    # To the end of the loop, not a fixed slice. The first draft of THIS
    # assertion took `[:1200]` and failed because the explanatory comment above
    # the code is longer than that — a byte window truncating a scan, which is
    # the very defect the file under test was fixed for. Bounded structurally:
    # the loop ends where the next top-level `def` begins.
    seg = fn[1].split("\ndef ", 1)[0]
    assert "m.end() + " not in seg, (
        "the recovery/removal look-ahead is bounded by a byte offset again; "
        "the path's slack line sits past any fixed window on a long path")
    assert 'find("Startpoint:")' in seg, (
        "the structural bound is gone, so the scan now runs into the NEXT "
        "path and would report its violation against this endpoint")


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))
