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
from _hostpaths import require_repo  # noqa: E402

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


# ── ORGANIC #584 round-2 — function-local decls must not shadow the
# module port for module-body indexes. Fixture quotes the REAL
# discriminating lines VERBATIM from the reopen's named artifact
# (aes_sbox_canright_masked.v: module port `input wire [7:0] a;` +
# sv2v-inlined package function local `reg [1:0] a;` + module-body
# `assign a1 = a[7:4];`) — per Step-2.6 doctrine, never a same-shape
# paraphrase.
_REAL_FUNC_LOCAL_SHADOW = """\
module aes_masked_inverse_gf2p8 (
\ta,
\tm,
\tb
);
\tinput wire [7:0] a;
\tinput wire [7:0] m;
\toutput wire [7:0] b;
\tfunction automatic [3:0] aes_sbox_canright_pkg_aes_mul_gf2p4;
\t\tinput reg [3:0] gamma;
\t\tinput reg [3:0] delta;
\t\treg [3:0] theta;
\t\treg [1:0] a;
\t\treg [1:0] b;
\t\treg [1:0] c;
\t\tbegin
\t\t\ta = aes_sbox_canright_pkg_aes_mul_gf2p2(gamma[3:2], delta[3:2]);
\t\t\taes_sbox_canright_pkg_aes_mul_gf2p4 = {a, c};
\t\tend
\tendfunction
\twire [3:0] a1;
\twire [3:0] a0;
\tassign a1 = a[7:4];
\tassign a0 = a[3:0];
\tassign b = {a1, a0};
endmodule
"""


def test_function_local_does_not_shadow_module_port(tmp_path):
    """The round-2 reopen's exact 現象: `assign a1 = a[7:4];` in the
    module body is legal against the module port `input wire [7:0] a;`
    even though an sv2v-inlined function declares `reg [1:0] a;`."""
    f = tmp_path / "aes_sbox_canright_masked.v"
    f.write_text(_REAL_FUNC_LOCAL_SHADOW)
    findings = BW.analyze_file(f)
    assert findings == [], [fd.message for fd in findings]


def test_function_local_index_checked_against_local_decl(tmp_path):
    """NEGATIVE no-leak: an out-of-range index INSIDE the function against
    the function-local `reg [1:0] a;` must still be caught."""
    bad = _REAL_FUNC_LOCAL_SHADOW.replace(
        "\t\t\taes_sbox_canright_pkg_aes_mul_gf2p4 = {a, c};",
        "\t\t\taes_sbox_canright_pkg_aes_mul_gf2p4 = a[3:0];")
    f = tmp_path / "bad_func_local.v"
    f.write_text(bad)
    findings = BW.analyze_file(f)
    errs = [fd for fd in findings if fd.rule == "bitselect-out-of-range"]
    assert len(errs) == 1, [fd.message for fd in errs]
    assert "[1:0]" in errs[0].message


def test_real_artifact_clean_when_present():
    """Content-gated on-host check (live-corpus doctrine): when the
    reopen's named artifact still carries the discriminating shape, the
    checker must PASS on it."""
    import pytest
    art = require_repo("benchmark_ic/5th__opentitan_aes_v0338/phase2/"
                       "stage1/rtl/aes_sbox_canright_masked.v")
    if not art.is_file() or "input wire [7:0] a;" not in art.read_text(
            errors="replace"):
        pytest.skip("named artifact absent or reshaped (live corpus)")
    findings = BW.analyze_file(art)
    errs = [fd for fd in findings if fd.rule == "bitselect-out-of-range"]
    assert errs == [], [fd.message for fd in errs]


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
