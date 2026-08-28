"""#559 — `output reg[7:0] q` made every instantiation of that port a mismatch.

`module_port_audit`'s port pattern required whitespace after the net type:

    r'(?:(?:wire|reg|logic|signed|unsigned)\\s+)*'

`output reg[7:0] q` is legal Verilog and common in real RTL — the width bracket
binds to the type without a space. With `\\s+` the whole ANCHORED match fails,
the port vanishes from the module's declared set, and every instantiation
connecting it reports

    Port '.q' … does not exist in module 'inner' port declarations

MINIMAL PAIR, the same file with one space moved:

    output  reg[7:0] data_out   -> ERROR mismatch
    output reg [7:0] data_out   -> clean

CORPUS, over the 107 tracked rtl directories driven with `--rtl-dir`:

    before   rc=1 on 7 of 107
    after    rc=1 on 5 of 107

The 2 that clear are this shape. The remaining 5 were a DIFFERENT parser limit —
a `` `ifdef`` / `` `endif`` block inside the port list (ibex_core.sv:101), after
which the parser stopped seeing ports — fixed below by `strip_preproc_directives`
after this file's first version pinned it as still-open. Both are parser limits
rather than design defects: `fetch_enable_i` IS declared at ibex_core.sv:104,
and `data_out` IS declared at hamming_tx.sv:41.

⚠ THESE COUNTS ARE OVER A 107-DIRECTORY POPULATION and do not chain onto the
figures in `test_module_port_audit_header_shapes.py`, which sweeps the 101
directories matching `benchmark-data/**/phase2/stage1/rtl/*.{v,sv}`. Two further
shapes (a module-line `import`, multi-dimensional packed ranges) took that
population to rc=1 on 0 of 101, re-measuring BOTH arms rather than carrying a
number across denominators.

WHY THIS MATTERS BEYOND ONE GATE. `module_port_audit` is one of the 12 gates
#559 still has to triage for umbrella invocability, and it is the only one the
umbrella can already drive (`--rtl-dir` is a value the umbrella computes). Under
#492's bar a conversion needs no new corpus FAILs; at 7 it failed that bar on
its own parser. It now clears that bar, on a corpus swept to zero and with the
zero shown to be a real clean rather than an accept-everything parser.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "module_port_audit.py"

_TIGHT = """\
module inner(
    input  wire       clk,
    output  reg[7:0]  data_out
);
endmodule
module outer(input wire clk, output wire [7:0] o);
    inner u(.clk(clk), .data_out(o));
endmodule
"""

_SPACED = _TIGHT.replace("output  reg[7:0]  data_out",
                         "output reg [7:0]  data_out")

#: Non-ANSI form, which the same pattern guards at the second call site.
_NON_ANSI = """\
module inner(clk, data_out);
    input clk;
    output reg[7:0] data_out;
endmodule
module outer(input wire clk, output wire [7:0] o);
    inner u(.clk(clk), .data_out(o));
endmodule
"""


def _run(tmp_path, src, name="a.v"):
    (tmp_path / name).write_text(src, encoding="utf-8")
    return _pr.run([sys.executable, str(PROG), "--rtl-dir", str(tmp_path)],
                          capture_output=True, text=True)


def test_a_width_bound_to_the_net_type_is_parsed(tmp_path):
    """The defect: `reg[7:0]` with no space."""
    r = _run(tmp_path, _TIGHT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "does not exist" not in r.stdout, r.stdout


def test_the_spaced_form_still_works(tmp_path):
    """The accept case. Widening the pattern must not break what parsed
    before — a change that traded one form for the other would satisfy the
    test above and fix nothing."""
    r = _run(tmp_path, _SPACED)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_non_ansi_call_site_is_fixed_too(tmp_path):
    """The same pattern appears twice — ANSI and non-ANSI headers. Fixing one
    leaves the other, and the second is the older style this corpus still
    carries."""
    r = _run(tmp_path, _NON_ANSI)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "does not exist" not in r.stdout, r.stdout


def test_a_genuine_mismatch_still_reports(tmp_path):
    """Load-bearing. A pattern loose enough to accept anything would pass every
    test above while making the gate incapable of finding a real defect."""
    src = """\
module inner(input wire clk, output reg[7:0] data_out);
endmodule
module outer(input wire clk, output wire [7:0] o);
    inner u(.clk(clk), .no_such_port(o));
endmodule
"""
    r = _run(tmp_path, src)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "no_such_port" in r.stdout


def test_the_pattern_is_fixed_at_both_sites():
    """Read from source: the two occurrences must both be `\\s*`.

    Asserted structurally because the non-ANSI path is easy to miss — the
    behavioural test above covers it, and this says WHY it passes.
    """
    src = PROG.read_text(encoding="utf-8")
    tight = src.count(r"(?:(?:wire|reg|logic|signed|unsigned)\s*)*")
    loose = src.count(r"(?:(?:wire|reg|logic|signed|unsigned)\s+)*")
    assert tight == 2, f"expected both sites relaxed, found {tight}"
    assert loose == 0, f"{loose} site(s) still require whitespace after the type"


def test_an_ifdef_inside_the_port_list_no_longer_hides_ports(tmp_path):
    """The SECOND cause, now fixed.

    This test asserted the limit was still OPEN when the whitespace fix landed,
    precisely so that fixing it would go RED and force the corpus number to be
    re-measured instead of drifting. It did, and the number moved:

        original                        rc=1 on 7 of 107
        after the whitespace fix        rc=1 on 5 of 107
        after `strip_preproc_directives` rc=1 on 1 of 107

    A conditional block inside the port list took part in the comma split and
    every port after it vanished. `ibex_core.sv` opens one at line 101 and the
    header parsed to ONE port (`clk`); it now parses to 53, with
    `fetch_enable_i` — declared at line 104 — among them.

    The CONDITIONAL ports are kept, not dropped: they are real ports under some
    configuration, this audit compares NAMES rather than an active config, and
    evaluating the conditions would need a define set the program does not have
    and must not invent.
    """
    src = """\
module inner(
    input  wire  clk,
`ifdef SOMETHING
    output wire  dbg,
`endif
    output reg[7:0] data_out
);
endmodule
module outer(input wire clk, output wire [7:0] o);
    inner u(.clk(clk), .data_out(o));
endmodule
"""
    r = _run(tmp_path, src)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "does not exist" not in r.stdout, r.stdout


def test_the_conditional_port_is_kept_not_dropped(tmp_path):
    """Blanking the directive must not blank the ports it guards — dropping
    them would trade a false 'does not exist' for a different one."""
    src = """\
module inner(
    input  wire  clk,
`ifdef SOMETHING
    output wire  dbg,
`endif
    output reg[7:0] data_out
);
endmodule
module outer(input wire clk, output wire dbg2, output wire [7:0] o);
    inner u(.clk(clk), .dbg(dbg2), .data_out(o));
endmodule
"""
    r = _run(tmp_path, src)
    assert r.returncode == 0, (
        "the conditional port was dropped, so connecting it reads as a "
        "mismatch: " + r.stdout)
