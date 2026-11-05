#!/usr/bin/env python3
"""antenna.rpt and density.rpt must say WHOSE design they are about.

THE FINDING, MEASURED (vibe-ic#1119, attack A3_CROSS_DESIGN)
============================================================
Copying `sha256/clean_run_v1427_20260715`'s same-named artefacts over
`spm/v1.9.96_gf180mcuD` — a different design on a different PDK — and re-running
that cell's own sign-off gates left two of them green:

    antenna_report_check    rc 0 -> 0    SUCCEEDED
    erc_density_check       rc 0 -> 0    SUCCEEDED

Eleven sibling findings closed by teaching the GATE to read the design its
evidence declares. These two could not: their evidence declares nothing.

    reports/phase3/antenna.rpt   sha256 7c614562baacec12...  <- the cell
    reports/phase3/antenna.rpt   sha256 7c614562baacec12...  <- the donor

BYTE-IDENTICAL between two designs. 487 bytes of "0 net violations, 0 pin
violations", no name in it anywhere, citing `phase3/stage3/pnr/openroad.log` as
its source — a path typed as a constant, and a file the published cell does not
contain. `reports/density.{rpt,json}` were the same shape: real numbers, no
identifier. No gate-side rule can bind evidence that carries no distinguishing
byte, so the fix is at the PRODUCER, and this file guards the producer end.

WHAT A STAMP IS NOT
===================
It makes a report ATTRIBUTABLE. It does not make it a MEASUREMENT, and the two
must not merge — a stamped empty report is still an empty report.
`test_a_stamp_does_not_make_an_absent_or_empty_report_a_pass` holds that line
for both gates, including the case that matters most: a report carrying a
CORRECT stamp and no result at all.

WHY FIXTURES AND NOT THE PUBLISHED CELL
=======================================
The cells that produced the measurement above are not in this repository — they
moved to vibeic/benchmark-data — so a test over them runs on one host and skips
everywhere else. The property is not corpus-shaped: "two designs must not
produce the same report bytes" is expressible in two tmp directories, and it
fails on every host.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

#: The PnR log shape the in-session antenna path keys on. `ANTENNA_POSTROUTE_DONE`
#: selects the authoritative post-repair branch, which needs no container.
_PNR_LOG = ("[INFO ODB-0128] Design: {top}\n"
            "ANTENNA_POSTROUTE_DONE\n"
            "Found 0 net violations\n"
            "Found 0 pin violations\n")

_FILL_LOG = ("Placed 1234 filler instances\n"
             "Design area 1000 um^2 27% utilization\n"
             "ROW_UTILIZATION_PCT 99.5\n")




def _rtl(root: Path, top: str) -> None:
    (root / "rtl").mkdir(parents=True, exist_ok=True)
    (root / "rtl" / f"{top}.v").write_text(
        f"module {top} (input wire clk, output wire q);\n"
        f"  assign q = clk;\nendmodule\n", encoding="utf-8")










def _gate(prog: str, root: Path, extra=()) -> dict:
    """The gate's own CLI and exit code — the flow reads exit codes."""
    r = _pr.run([sys.executable, str(_PROGRAMS / prog), ".", *extra],
                       cwd=str(root), capture_output=True, text=True)
    try:
        doc = json.loads(r.stdout)
    except ValueError:
        doc = {"program": "unparseable", "stdout": r.stdout[:2000]}
    doc["rc"] = r.returncode
    return doc


# ===========================================================================
# THE PRODUCERS
# ===========================================================================










# ===========================================================================
# THE GATES — the finding closes here
# ===========================================================================








# ===========================================================================
# ATTRIBUTABLE IS NOT MEASURED
# ===========================================================================
_STAMP_ONLY = (
    "measured_design: my_top\n"
    "measured_from: phase3/stage3/pnr/my_top.def sha256:"
    "5a60299f693ceb0e8f501d2b79093a676cba36fde5043a97fdcc68d5e818de69\n")


@pytest.mark.parametrize("body,label", [
    (None, "absent"), ("", "empty"), (_STAMP_ONLY, "stamp only, no result"),
])
def test_a_stamp_does_not_make_an_absent_or_empty_report_a_pass(
        tmp_path, body, label):
    """The failure mode this change could have introduced, held shut.

    The third case is the one that matters: a report whose stamp is present and
    CORRECT, and which measured nothing. Identity is not substance.
    """
    for prog, extra, sub, name in (
            ("antenna_report_check.py", ("--mode", "antenna"),
             "reports/phase3", "antenna.rpt"),
            ("erc_density_check.py", (), "reports", "density.rpt")):
        root = tmp_path / f"{prog}-{label}"
        (root / sub).mkdir(parents=True, exist_ok=True)
        _rtl(root, "my_top")
        if body is not None:
            (root / sub / name).write_text(body, encoding="utf-8")
        got = _gate(prog, root, extra)
        assert got["rc"] != 0, (
            f"{prog} PASSED on a {label} report. A stamp makes a report "
            f"attributable, never a measurement:\n{json.dumps(got, indent=2)}")
