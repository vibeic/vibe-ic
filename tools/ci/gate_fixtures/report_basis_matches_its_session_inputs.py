"""`report basis matches its session inputs` — a published number claiming a
stage its own session never measured.

THE MUTATION IS THE MEASURED DEFECT ITSELF. The gate's docstring records one
case in full: a power report headed post-layout whose session linked a
287-instance PRE-LAYOUT netlist and loaded NO extracted parasitics, against
3373 routed instances. It published 0.306 mW where the post-route session
publishes 0.573 mW — 46.6 % understated — and reported the whole CLOCK GROUP
as 0.000 mW where the real measurement puts 33.7 % of total power.

So the mutation is exactly that: the report keeps its `STA_BASIS: POST_ROUTE`
stamp, keeps its numbers, keeps its place beside its session — and the session
loses its `read_spef`. Nothing else moves. The gate derives the stage from the
INPUTS the tool actually read, never from the label, which is the whole point
of the rule, so removing the parasitics read is what changes the ANSWER.

THE DENOMINATOR IS THE SAME IN BOTH ARMS
========================================
Both subjects carry the same one `(session, report)` pair in the same
directory, and the gate prints its denominators on every run:

    (session, report) pairs examined:  1   (both arms)
    pairs that declare a stage:        1   (both arms)
    pairs declaring none:              0   (both arms)

Nothing is added to the corpus and nothing is removed from it. The pair is
still read, the claim is still declared, and the session is still an analysis
session that publishes a number (`report_power` is present in both). What moves
is whether the claim and the session agree.

WHY THE PAIR IS SHAPED THIS WAY
===============================
`_pairs()` matches a `.tcl` and a `.rpt` sharing a STEM in ONE directory, and
only counts the pair when the script actually publishes a number
(`report_power` / `report_checks` / `report_timing`). Both are present in both
arms; take either away and the pair leaves the population, which would prove
the gate can notice an empty corpus rather than a false claim. The claim itself
is read through `_sta_basis.declared_basis` — THE one stamp reader in the tree
— so the fixture writes the stamp in the emitter's own spelling
(`POST_ROUTE_SPEF`, which that reader normalises by PREFIX).

chip-AGNOSTIC: no IC, vendor, SKU or process appears here.
"""
from pathlib import Path

GATE = "report basis matches its session inputs"

#: Where a real campaign puts them — one analysis deck beside its report.
_DIR = "diag"
_STEM = "power_postroute"

#: The report. Its stamp claims POST_ROUTE in both arms; only the session moves.
_REPORT = """\
# STA_BASIS: POST_ROUTE_SPEF
# Power Report
Group                  Internal  Switching    Leakage      Total
Sequential             1.02e-04   3.31e-05   1.10e-09   1.35e-04
Combinational          2.11e-04   1.90e-04   4.40e-09   4.01e-04
Clock                  1.71e-04   2.20e-05   9.00e-10   1.93e-04
Total                  4.84e-04   2.45e-04   6.40e-09   7.29e-04
"""

#: The session, minus the one line that decides which side of PnR it measured.
_SESSION_HEAD = """\
read_liberty stdcells.lib
read_verilog routed.v
link_design chip_top
read_sdc chip_top.sdc
"""
_READ_SPEF = "read_spef routed.spef\n"
_SESSION_TAIL = """\
report_power
exit
"""


def _tree(work: Path, parasitics: bool) -> Path:
    root = work / "subject"
    d = root / _DIR
    d.mkdir(parents=True)
    (d / f"{_STEM}.rpt").write_text(_REPORT, encoding="utf-8")
    (d / f"{_STEM}.tcl").write_text(
        _SESSION_HEAD + (_READ_SPEF if parasitics else "") + _SESSION_TAIL,
        encoding="utf-8")
    return root


def can_pass(work: Path) -> Path:
    """The report claims POST_ROUTE and its session read the parasitics."""
    return _tree(work, parasitics=True)


def can_fail(work: Path):
    """The same pair, the same stamp, the same numbers — and a session that
    loaded no extracted parasitics, so the number cannot move when the layout
    moves."""
    return (_tree(work, parasitics=False),
            "claims POST_ROUTE")
