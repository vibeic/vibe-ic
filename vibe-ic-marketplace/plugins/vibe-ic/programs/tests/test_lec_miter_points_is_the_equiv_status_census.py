"""The LEC denominator must be the equiv_status CENSUS, not a mid-flight residual.

MEASURED, opentitan_aes x chip_top (v1.17.22 canonical LEC run,
reports/lec.rpt): the Yosys log carried

    Found 3396 unproven $equiv cells (3396 groups) in equiv:     <- equiv_simple ENTRY
    ...
    Found 4072 $equiv cells in equiv:                            <- equiv_status CENSUS
      Of those cells 830 are proven and 3242 are unproven.

`parse_equiv_output` read the ENTRY line as the total and published
`miter_points=3396` beside `proven=830` / `unproven=3242`, whose sum is 4072.
That decomposition does not add up, and the narrower denominator makes the
proven ratio read 24.4% where the run earned 20.4%.

The equiv_simple entry line counts the points still UNPROVEN when that pass
STARTED. It equals the population only when nothing had been proven yet.

Both directions: each test names the pre-fix value it must not return.
"""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "lec_run.py"
sys.path.insert(0, str(SCRIPT.parent))
import lec_run  # noqa: E402


# Shape-faithful reduction of the measured log: an earlier pass discharges
# some points, so the equiv_simple entry residual is SMALLER than the census.
_LOG_CENSUS_LARGER = """
12. Executing EQUIV_SIMPLE pass.
Found 3396 unproven $equiv cells (3396 groups) in equiv:
Proved 137 previously unproven $equiv cells.

23. Executing EQUIV_INDUCT pass.
Found 3242 unproven $equiv cells in module equiv:
  Proof for base case failed. Circuit inherently diverges!
Proved 0 previously unproven $equiv cells.

24. Executing EQUIV_STATUS pass.
Found 4072 $equiv cells in equiv:
  Of those cells 830 are proven and 3242 are unproven.
"""


def test_total_is_the_equiv_status_census_not_the_simple_entry_residual():
    p = lec_run.parse_equiv_output(_LOG_CENSUS_LARGER)
    assert p["proven"] == 830
    assert p["unproven"] == 3242
    # Pre-fix this was 3396 — the equiv_simple entry residual.
    assert p["total"] == 4072, (
        "miter_points must be the equiv_status census (4072), not the "
        f"equiv_simple entry residual (3396); got {p['total']}")


def test_the_published_decomposition_adds_up():
    p = lec_run.parse_equiv_output(_LOG_CENSUS_LARGER)
    assert p["proven"] + p["unproven"] == p["total"], (
        f"proven({p['proven']}) + unproven({p['unproven']}) must equal "
        f"total({p['total']}) — a census that does not add up is a parser "
        "bug, not a property of the design")


def test_denominator_never_narrows_below_the_summary_sum():
    # No equiv_status census line at all: the only total available is the
    # entry residual, which is SMALLER than proven+unproven. The guard must
    # widen to the sum rather than publish an impossible ratio.
    text = """
Found 100 unproven $equiv cells (100 groups) in equiv:
Proved 10 previously unproven $equiv cells.
  Of those cells 40 are proven and 90 are unproven.
"""
    p = lec_run.parse_equiv_output(text)
    assert p["proven"] == 40 and p["unproven"] == 90
    # Pre-fix this was 100, which is less than 40+90.
    assert p["total"] == 130, (
        f"a denominator must never be narrower than the summary it is "
        f"published beside; got {p['total']}")


def test_single_pass_run_is_unchanged():
    # The common small case the entry-line reading was written for: nothing
    # proven before equiv_simple, so entry residual == census. This must not
    # move, in either direction.
    text = """
Found 71 unproven $equiv cells (71 groups) in equiv:
Proved 71 previously unproven $equiv cells.
Found 71 $equiv cells in equiv:
  Of those cells 71 are proven and 0 are unproven.
"""
    p = lec_run.parse_equiv_output(text)
    assert (p["proven"], p["unproven"], p["total"]) == (71, 0, 71)
    assert p["equivalent"] is True
