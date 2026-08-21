"""Step 5's .sby must not read an include-hub aggregator next to its siblings.

An INCLUDE-HUB AGGREGATOR is a source whose body ```include``s SIBLING sources
that are ALSO staged standalone (the ChipFoundry/eFabless ``uprj_netlists.v``
shape is the canonical one). Handing both to one ``read_verilog`` elaborates
every included module twice and yosys ABORTS::

    ERROR: Re-definition of module `\\user_proj_example'!

sby then reports ``rc=16`` / "engine_0 did not return a status" for every task,
NO proof engine ever runs, and the flow self-reports a FORMAL-VERIFICATION
capability gap it does not actually have.

Measured on caravel_user_project x sky130A: the unpatched runner produced
``verdict=INCONCLUSIVE, proved=0`` with that yosys error in the sby log; with
the aggregator dropped from the read list the SAME harness and the SAME design
gave ``verdict=PASS, proved=2`` (``abc pdr`` unbounded + ``abc bmc3`` depth 12,
both "returned PASS").

These tests exercise the SHIPPED emitter end-to-end through
``formal_property_run.run()`` and assert the PROPERTY (what ends up on the
``read_verilog`` line), never a source literal. The proof itself is not run
here - sby is not assumed present - so the tests stay hermetic; the executed
two-tree proof is the acceptance evidence for the change.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import formal_property_run as fpr  # noqa: E402


HUB_BODY = """\
`include "defines.v"
`ifdef GL
    `include "gl/leaf_a.v"
`else
    `include "leaf_a.v"
`endif
"""

LEAF_A = """\
`default_nettype none
module leaf_a (input wire clk, input wire rst, output reg q);
    always @(posedge clk) if (rst) q <= 1'b0; else q <= ~q;
endmodule
`default_nettype wire
"""

HARNESS = """\
`default_nettype none
module formal_leaf_a (input wire clk);
    (* anyseq *) wire rst;
    wire q;
    leaf_a dut (.clk(clk), .rst(rst), .q(q));
    reg f_past_valid = 1'b0;
    always @(posedge clk) f_past_valid <= 1'b1;
    reg rst_q = 1'b0;
    always @(posedge clk) rst_q <= rst;
    a_reset: assert property (@(posedge clk) (f_past_valid && rst_q) |-> (q == 1'b0));
endmodule
`default_nettype wire
"""

# A macro-only header: including it is ordinary composition, NOT an aggregator
# signal. Dropping it would strand a real source list.
DEFINES = "`ifndef DEFS\n`define DEFS 1\n`endif\n"


def _stage(tmp_path: Path, files: dict) -> tuple[Path, Path, list[Path]]:
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    formal = proj / "phase2" / "stage1" / "formal"
    rtl.mkdir(parents=True)
    formal.mkdir(parents=True)
    for name, body in files.items():
        (rtl / name).write_text(body)
    harness = formal / "formal_leaf_a.sv"
    harness.write_text(HARNESS)
    return proj, harness, sorted(rtl.glob("*.v"))


def _read_line(sby_text: str) -> str:
    for line in sby_text.splitlines():
        if "read_verilog" in line:
            return line
    raise AssertionError("no read_verilog line in the emitted .sby:\n" + sby_text)


def _emit(tmp_path: Path, files: dict) -> str:
    proj, harness, rtl = _stage(tmp_path, files)
    # `run` needs no tool to reach the emit: it writes the .sby, then fails to
    # find sby/docker. We only read the artefact it wrote.
    try:
        fpr.run(project=proj, harness=harness, rtl=rtl, top="formal_leaf_a",
                container=None)
    except Exception:  # pragma: no cover - tool absence is not the subject
        pass
    sbys = sorted((proj / "phase2" / "stage1" / "formal").glob("*.sby"))
    assert sbys, "the runner emitted no .sby at all"
    return sbys[0].read_text()


def test_aggregator_is_dropped_from_the_read_list(tmp_path):
    """The hub is excluded; every module-declaring sibling is kept."""
    text = _emit(tmp_path, {"defines.v": DEFINES,
                            "leaf_a.v": LEAF_A,
                            "uprj_netlists.v": HUB_BODY})
    line = _read_line(text)
    assert "uprj_netlists.v" not in line, (
        "the include-hub aggregator is still on the read_verilog line, so "
        "leaf_a is elaborated twice and yosys aborts before any engine runs:\n"
        + line)
    assert "leaf_a.v" in line
    assert "defines.v" in line


def test_macro_only_header_is_never_dropped(tmp_path):
    """Including a module-less macro header is normal composition.

    Negative direction: a source list with no aggregator at all must come
    through untouched, or a real design loses a source and synth dies.
    """
    leaf_with_header = '`include "defines.v"\n' + LEAF_A
    text = _emit(tmp_path, {"defines.v": DEFINES,
                            "leaf_a.v": leaf_with_header})
    line = _read_line(text)
    assert "leaf_a.v" in line, line
    assert "defines.v" in line, line


def test_filter_never_empties_the_read_list(tmp_path):
    """Fail-open: if everything looks like a hub, keep the unfiltered list.

    Reading a redundant file is recoverable; reading nothing is not.
    """
    mutual_a = '`include "b.v"\nmodule a (input wire c); endmodule\n'
    mutual_b = '`include "a.v"\nmodule b (input wire c); endmodule\n'
    proj, harness, rtl = _stage(tmp_path, {"a.v": mutual_a, "b.v": mutual_b})
    try:
        fpr.run(project=proj, harness=harness, rtl=rtl, top="formal_leaf_a",
                container=None)
    except Exception:  # pragma: no cover
        pass
    sbys = sorted((proj / "phase2" / "stage1" / "formal").glob("*.sby"))
    assert sbys
    line = _read_line(sbys[0].read_text())
    srcs = [t for t in line.split() if t.endswith(".v")]
    assert srcs, "the read_verilog line lost every design source: " + line


def test_files_block_matches_the_read_list(tmp_path):
    """Whatever is read must also be staged, or sby cannot resolve it."""
    text = _emit(tmp_path, {"defines.v": DEFINES,
                            "leaf_a.v": LEAF_A,
                            "uprj_netlists.v": HUB_BODY})
    line = _read_line(text)
    read_srcs = {t for t in line.split() if t.endswith((".v", ".sv"))}
    block = text.split("[files]", 1)[1]
    listed = {ln.strip() for ln in block.splitlines() if ln.strip()}
    missing = read_srcs - listed
    assert not missing, f"read but not staged under [files]: {sorted(missing)}"
