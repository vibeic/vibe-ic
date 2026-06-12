"""ORGANIC #584 — bitwidth_consistency_check paired a signal's
declaration with index expressions across the whole FILE; sv2v emits one
.v per source .sv but each file routinely holds MULTIPLE modules, so two
modules using the same short signal name (a, b, q) at different widths
cross-matched: a module declaring `input wire [3:0] b` and legally
indexing `b[3:2]` was flagged against ANOTHER module's `[1:0] b`
declaration in the same file — 6 false errors on a live crypto-peripheral
project failed phase2 strict-structural despite clean yosys synth.

Fix: _module_regions() tracks module/endmodule boundaries and the
declaration→index pairing is scoped per module. NEGATIVE half: a
genuinely out-of-range index in the narrow module is still caught
(relaxation-verification doctrine).
"""
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import bitwidth_consistency_check as BW  # noqa: E402

# The issue's exact shape: same-name signals at different widths in two
# modules of one sv2v-style file; every index legal in its OWN module.
_TWO_MODULE_LEGAL = """\
module narrow_unit (b_in, y);
\tinput wire [1:0] b_in;
\toutput wire y;
\twire [1:0] b;
\tassign b = b_in;
\tassign y = b[1];
endmodule
module wide_unit (b_in, y);
\tinput wire [3:0] b_in;
\toutput wire [1:0] y;
\twire [3:0] b;
\tassign b = b_in;
\tassign y = b[3:2];
endmodule
"""

# NEGATIVE: the narrow module REALLY indexes out of range.
_TWO_MODULE_REAL_BUG = """\
module narrow_unit (b_in, y);
\tinput wire [1:0] b_in;
\toutput wire [2:0] y;
\twire [1:0] b;
\tassign b = b_in;
\tassign y = b[6:4];
endmodule
module wide_unit (b_in, y);
\tinput wire [7:0] b_in;
\toutput wire [2:0] y;
\twire [7:0] b;
\tassign b = b_in;
\tassign y = b[6:4];
endmodule
"""


def test_cross_module_same_name_not_flagged(tmp_path):
    """The issue's exact 現象: wide module's legal b[3:2] must not be
    flagged against the narrow module's [1:0] b declaration."""
    f = tmp_path / "two_mod.v"
    f.write_text(_TWO_MODULE_LEGAL)
    findings = BW.analyze_file(f)
    assert findings == [], [fd.message for fd in findings]


def test_real_out_of_range_still_caught_in_its_module(tmp_path):
    """NEGATIVE no-leak half: narrow module's b[6:4] against its own
    [1:0] b is still an error; wide module's identical b[6:4] against
    its own [7:0] b is legal."""
    f = tmp_path / "two_mod_bug.v"
    f.write_text(_TWO_MODULE_REAL_BUG)
    findings = BW.analyze_file(f)
    errs = [fd for fd in findings if fd.rule == "bitselect-out-of-range"]
    assert len(errs) == 1, [fd.message for fd in errs]
    # the finding must point INSIDE the narrow module (lines 1-7)
    assert errs[0].line <= 7, errs[0]


def test_single_module_regression(tmp_path):
    """The checker's original motivating bug (5-bit reg indexed [6:0])
    keeps firing in a single-module file."""
    f = tmp_path / "single.v"
    f.write_text(
        "module m (input wire clk, output wire [6:0] o);\n"
        "  reg [4:0] resp_data_idx;\n"
        "  assign o = resp_data_idx[6:0];\n"
        "endmodule\n"
    )
    findings = BW.analyze_file(f)
    assert any(fd.rule == "bitselect-out-of-range" for fd in findings)


def test_module_regions_parser():
    regions = BW._module_regions(_TWO_MODULE_LEGAL)
    assert [r[2] for r in regions] == ["narrow_unit", "wide_unit"]
    # regions must not overlap
    assert regions[0][1] <= regions[1][0]


def test_cli_end_state_on_issue_shape(tmp_path):
    """End-state via the real program CLI: the issue's multi-module file
    must exit 0 / PASS (pre-fix: 6 false bitselect-out-of-range errors,
    rc 1)."""
    f = tmp_path / "sv2v_shaped.v"
    f.write_text(_TWO_MODULE_LEGAL)
    result = subprocess.run(
        [sys.executable, str(PROG / "bitwidth_consistency_check.py"),
         str(f)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout
    assert "Result: PASS" in result.stdout
