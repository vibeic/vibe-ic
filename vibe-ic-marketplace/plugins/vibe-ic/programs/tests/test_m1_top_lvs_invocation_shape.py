#!/usr/bin/env python3
"""M1's netgen call must match netgen's own two-element contract.

netgen's `lvs` takes a TWO-element `{filename cellname}` list per side, and its
source says what happens otherwise: when `llength` is not 2 it treats the WHOLE
string as one filename.

This site used to join every schematic file into one space-separated string and
append the top cell name, handing netgen four or more elements. netgen then
looked for a file literally named

    "<netlist>.v <macro1>.v <macro2>.v <top>"

failed to open it, and never loaded the schematic side. The program published
`verdict: FAIL, reason: "... real compare ran on the merged GDS;
design/extraction defect"` anyway -- attributing to the design a comparison that
never started, and naming a report file it had not written.

The schematic side is ALWAYS the gate netlist plus one `.v` per analog macro,
so it is always >= 2 files: M1 could not pass for any design with an analog
hardmacro, which is the only kind of design M1 exists for.

These tests read the Tcl that netgen would actually consume, rather than
grepping the Python that emits it -- source text proves a line exists, not that
the artefact it builds is well formed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

from mixed_signal_top_lvs_run import (  # noqa: E402
    netgen_lvs_script, lvs_failure_verdict)

# The real shape: a gate netlist plus one stub per analog hardmacro.
_SCH = ["/w/chip_top_synth.v", "/w/delta_sigma.v", "/w/ldo.v"]
_LAYOUT = "/w/merged.spice"


def _script(sch=None):
    return netgen_lvs_script(sch or _SCH, _LAYOUT, "chip_top_flat", "chip_top",
                             "/pdk/setup.tcl", "/w/reports/top_lvs.rpt")


def _lvs_line(script):
    return [l for l in script.splitlines() if l.startswith("lvs ")][0]


def _lvs_args(script):
    """The `lvs` arguments, in order, with Tcl braces stripped.

    Hand-parsed rather than shlex'd: the schematic side is a `[list ...]`
    substitution, which POSIX quoting rules do not model.
    """
    rest = _lvs_line(script)[len("lvs "):]
    args, i = [], 0
    while i < len(rest):
        if rest[i] == " ":
            i += 1
            continue
        if rest[i] == "{":
            j = rest.index("}", i)
            args.append(rest[i + 1:j])
            i = j + 1
        elif rest[i] == "[":
            j = rest.index("]", i)
            args.append(rest[i:j + 1])
            i = j + 1
        else:
            j = rest.find(" ", i)
            j = len(rest) if j == -1 else j
            args.append(rest[i:j])
            i = j
    return args


# ---------------------------------------------------------------------------
# The invocation shape
# ---------------------------------------------------------------------------
def test_every_schematic_file_is_read():
    script = _script()
    for p in _SCH:
        assert p in script, f"{p} never reaches netgen"


def test_extra_schematic_files_join_the_first_ones_netlist():
    """`readnet <fmt> <file> <fnum>` forces the file into the netlist held in
    fnum. Without the trailing fnum each file becomes its own netlist and only
    one of them is ever compared."""
    lines = _script().splitlines()
    assert lines[0].startswith("set fnum [readnet verilog "), lines[0]
    for ln in lines[1:len(_SCH)]:
        assert ln.endswith("$fnum"), (
            f"{ln!r} starts a separate netlist instead of joining fnum")


def test_the_schematic_side_names_the_netlist_it_was_read_into():
    """`{<fnum> <cell>}` -- an integer file number then the cell.

    NOT a bare cell name. A bare name is ambiguous exactly when LVS is doing its
    job: both sides normally hold a cell of the same name, and `lay_top`
    defaults to `top` whenever the layout has no `_flat` subckt. Measured
    against netgen 1.5.323, the bare name resolved to the LAYOUT's copy and
    netgen refused with "Both cells are in the same netlist: Cannot compare!"
    """
    args = _lvs_args(_script())
    sch = args[1]
    assert sch.startswith("[list $fnum"), (
        f"schematic side is {sch!r}; it must name the netlist the schematic "
        f"files were read into, or netgen resolves it against the layout")
    assert "chip_top" in sch


def test_the_layout_side_is_the_two_element_pair_netgen_documents():
    args = _lvs_args(_script())
    assert args[0].split() == [_LAYOUT, "chip_top_flat"], args[0]


def test_no_lvs_argument_smuggles_a_file_list():
    """The regression, stated as a property: no argument may carry a path
    separator AND a space, which is what a flattened file list looks like.
    The layout pair is the one legitimate `<path> <cell>` and is excluded."""
    for a in _lvs_args(_script())[1:]:
        assert not ("/" in a and " " in a), (
            f"argument {a!r} looks like several paths flattened into one")


def test_a_single_schematic_file_still_works():
    """The degenerate case must not regress: one file, still read into its own
    netlist, still named by that netlist."""
    script = _script(sch=["/w/only.v"])
    assert script.splitlines()[0] == "set fnum [readnet verilog {/w/only.v}]"
    assert _lvs_args(script)[1].startswith("[list $fnum")


def test_paths_with_spaces_survive_as_one_word():
    """Braces, not shell quoting: a Tcl script is not a shell command line."""
    script = netgen_lvs_script(["/a b/net.v", "/a b/mac.v"], "/a b/lay.spice",
                               "top_flat", "top", "/a b/setup.tcl",
                               "/a b/rpt.txt")
    assert "{/a b/net.v}" in script
    assert "{/a b/setup.tcl}" in script


# ---------------------------------------------------------------------------
# A comparison that never ran is not a verdict about the design
# ---------------------------------------------------------------------------
_READ_ABORT = (
    "Reading netlist file /w/a.v /w/b.v chip_top\n"
    "ReadNetlist: unable to find file '/w/a.v /w/b.v chip_top'\n-1\n")


def test_a_run_that_never_compared_is_not_called_a_design_defect():
    """netgen writes its report only after loading both sides and comparing, so
    a missing report means nothing was compared. The FAIL stands -- an
    unrunnable LVS is not a pass -- but the reason must not blame the design."""
    v = lvs_failure_verdict(report_written=False, rc=-1,
                            transcript=_READ_ABORT)
    assert v["verdict"] == "FAIL", "an LVS that cannot run is not a pass"
    assert v["compared"] is False
    assert "design/extraction defect" not in v["reason"], v["reason"]
    assert "NOT a design" in v["reason"]


def test_the_no_comparison_verdict_hands_over_the_tool_output():
    """The old reason pointed at an LVS report that, in this case, was never
    written -- so the reader was left with nothing to look at."""
    v = lvs_failure_verdict(report_written=False, rc=-1,
                            transcript=_READ_ABORT)
    assert "ReadNetlist" in v["transcript_tail"]


def test_a_real_mismatch_is_still_attributed_to_the_design():
    """The tightening must not swallow the case the old message was right
    about: netgen ran, compared, and the design did not match."""
    v = lvs_failure_verdict(report_written=True, rc=1,
                            transcript="Circuits do not match\n")
    assert v["verdict"] == "FAIL"
    assert v["compared"] is True
    assert "design/extraction defect" in v["reason"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
