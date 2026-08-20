#!/usr/bin/env python3
"""`reports/phase3/power.json` has to carry the NUMBER, not only a verdict.

MEASURED 2026-08-21 on a complete phase-3 run: OpenSTA `report_power` computed
`Total ... 3.06e-04` into `reports/phase3/power.rpt`, and `power.json` — the
structured companion the runner writes one line later, from that very file —
carried `tool`, `source`, `analysis_mode`, `verdict` and `evidence` and NO
measurement. So every consumer that wanted "what does this design draw" had
nowhere structured to look, and a PPA objective could not be computed at all.

The fix declares `total_power_w` at that same site. These tests pin the two
properties that make the declaration trustworthy rather than merely present:

  * the figure is read from OpenSTA's own five-column `report_power` TABLE, and
    the LAST `Total` row wins — a report appended to twice describes the later
    run, and taking the first (or averaging) would make two runs read alike;

  * a figure it CANNOT read comes back as `None` WITH A REASON, never as 0.0.
    Zero is a legitimate power measurement, so a parse failure that returned it
    would be indistinguishable from a real one — the exact substitution that
    makes "we did not look" and "we looked and it was fine" the same artefact
    (header rule 9).

Tool-shape-specific by necessity (it names the OpenSTA table it reads) and
otherwise chip-, PDK- and vendor-AGNOSTIC: no design, process or part literal.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent


def _power_total_watts_impl():
    """Load ONLY the helper out of the 39k-line runner. Importing the whole
    module drags in the container/PDK machinery, which this unit has nothing to
    do with — and a test that needs the world to start is a test nobody runs."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    start = src.index("def _power_total_watts")
    end = src.index("def _emit_power_report")
    ns = {"Tuple": Tuple, "Optional": Optional}
    exec(compile(src[start:end], "phase3_one_shot_runner", "exec"), ns)
    return ns["_power_total_watts"]


# A real OpenSTA `report_power` tail, shape-identical to the one measured.
REPORT = """\
Group                  Internal  Switching    Leakage      Total
                          Power      Power      Power      Power (Watts)
----------------------------------------------------------------
Sequential             2.74e-04   8.71e-06   5.28e-10   2.82e-04  92.2%
Combinational          1.47e-05   9.16e-06   5.16e-10   2.39e-05   7.8%
Clock                  0.00e+00   0.00e+00   0.00e+00   0.00e+00   0.0%
Macro                  0.00e+00   0.00e+00   0.00e+00   0.00e+00   0.0%
Pad                    0.00e+00   0.00e+00   0.00e+00   0.00e+00   0.0%
----------------------------------------------------------------
Total                  2.88e-04   1.79e-05   1.04e-09   3.06e-04 100.0%
                          94.2%       5.8%       0.0%
"""


def test_the_total_is_read_from_the_table():
    watts, reason = _power_total_watts_impl()(REPORT)
    assert watts == pytest.approx(3.06e-04)
    assert reason is None


def test_the_last_total_row_wins():
    doubled = REPORT + REPORT.replace("3.06e-04", "9.99e-04")
    watts, reason = _power_total_watts_impl()(doubled)
    assert watts == pytest.approx(9.99e-04), (
        "a report appended to twice describes the LATER run")
    assert reason is None


def test_zero_watts_is_a_measurement_and_survives_as_one():
    zeroed = REPORT.replace("3.06e-04 100.0%", "0.0 100.0%")
    watts, reason = _power_total_watts_impl()(zeroed)
    assert watts == 0.0
    assert reason is None, (
        "0 W is a legitimate measurement; it must not be reported as a failure")


@pytest.mark.parametrize("text,fragment", [
    ("", "empty"),
    ("Group Internal\nSequential 1 2 3 4 5\n", "no `Total` row"),
    ("Total 1 2\n", "fewer than the five"),
    ("Total a b c d e\n", "not a number"),
])
def test_an_unreadable_report_yields_a_reason_never_a_zero(text, fragment):
    watts, reason = _power_total_watts_impl()(text)
    assert watts is None, (
        "a figure that could not be read must not arrive as 0.0 — zero is a "
        "real measurement and the two would be indistinguishable")
    assert fragment in reason


def test_the_emission_site_declares_the_number_and_its_basis():
    """The helper alone proves nothing if `power.json` never carries what it
    returns. Pin the emission site itself."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    site = src[src.index('_aa.write_text(rpt_phase3 / "power.json"'):]
    site = site[:site.index("written.append")]
    for field in ("total_power_w", "total_power_measured",
                  "total_power_basis", "total_power_unmeasured_reason"):
        assert field in site, (
            f"`power.json` must declare `{field}`; a verdict without the "
            "number is what this change exists to remove")
