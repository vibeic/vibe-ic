"""A report's claimed stage must be the stage its own session measured.

WHY
===
MEASURED: a power report headed post-layout whose session linked the pre-layout
netlist and loaded no parasitics published 0.306 mW against the post-route
session's 0.573 mW — 46.6 % understated — and reported the entire CLOCK GROUP as
0.000 mW where the real measurement puts 33.7 % of total power there. An absent
input read as a measured zero.

THE SESSION IS GROUND TRUTH
===========================
The reds below are built the way the defect was: the header keeps its
post-layout claim while `read_spef` is removed. Only the session changes, and
the verdict must follow the session, not the label.

ONE READER, NOT A SIXTH COPY
============================
`_sta_basis.declared_basis` is imported rather than re-implemented; that module
records five copies of the stamp reader disagreeing on 7 of a 24-stamp corpus.
`test_the_stamp_is_read_through_the_one_reader` pins the import.

chip-AGNOSTIC: flow-stage vocabulary. `/foss/pdks/sky130A` is an open kit root.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "declared_basis_matches_the_session_inputs.py"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location("dbmtsi", _TOOL)
dbmtsi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dbmtsi)

_POST = (
    'read_liberty /foss/pdks/sky130A/libs.ref/a/lib/a__tt_025C_1v80.lib\n'
    'read_verilog design_pnr.v\n'
    'link_design top\n'
    'read_spef design.spef\n'
    'read_sdc constraint.sdc\n'
    'report_power\n')
_RPT_STAMPED_POST = "# STA_BASIS: POST_ROUTE_SPEF\nTotal 5.73e-04\n"
_RPT_STAMPED_PRE = "# STA_BASIS: PRE_LAYOUT_ESTIMATE\nTotal 3.06e-04\n"



def _count_in(text: str, phrase: str) -> bool:
    """`phrase` (which begins with a count) appears with NO digit before it.

    MEASURED: `assert "1 inexpressible" in out` is satisfied by an output saying
    `21 inexpressible`, and `"0 key(s) observed"` by `10 key(s) observed`. A
    substring assertion on a count is not a pin — every one of these tests would
    have passed against a tenfold-wrong number. Taken from the census lane's
    "a substring assertion on a count is not a pin — parse the number".
    """
    return re.search(r"(?<!\d)" + re.escape(phrase), text) is not None


def test_the_count_anchor_actually_fires():
    """PROVE THE PIN FIRES. `_count_in` exists because a substring assertion on a
    count is not a pin — `"1 inexpressible" in out` is satisfied by an output
    saying `21 inexpressible`. A helper that silently never rejects anything would
    reinstate exactly the defect it was added to remove, and nothing else in this
    file would notice, because every other use of it asserts the TRUE case.

    So: the true case passes, and a preceding digit is refused.
    """
    assert _count_in("examined 1 thing", "1 thing")
    assert not _count_in("examined 21 thing", "1 thing"), (
        "the anchor did not fire: a tenfold-wrong count still satisfies the pin")
    assert not _count_in("examined 10 thing", "0 thing")
    assert _count_in("a, 0 thing", "0 thing")





# ------------------------------------------------------------------ unit













# ------------------------------------------------------------ red control









# -------------------------------------------------------------- verdicts
