"""ORGANIC #802 — rule_incomplete_sensitivity reported the VALUE TAIL of a based
numeric literal (4'b0000→b0000, 8'hFF→hFF, 20'd0→d0, 4'd3→d3) as a
missing-sensitivity signal → false block-eligible WARN rc=1 on correct
combinational RTL.

The read scan `re.findall(r'[A-Za-z_]\\w*', body)` ran over a body still
containing based literals; the sole literal guard `not re.match(r"^\\d", t)`
rejects only DIGIT-prefixed tokens, so the letter-leading value tail survived.
FIX: strip based numeric literals (anchored on the apostrophe) before the scan.

§4.05: a real missing signal beside a literal still flags; a signal merely NAMED
`d0` (read without an apostrophe) still flags. chip-AGNOSTIC.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402


def _missing(src):
    return sorted({f.symbol for f in H.rule_incomplete_sensitivity(src, "d.v")})


def test_802_based_literals_not_reported_missing():
    src = ("module m(input [3:0] a, output reg [7:0] y);\n"
           " always @(a) begin y = 8'hFF; if (a == 4'hF) y = 8'h00;"
           " y = 20'd0; end\nendmodule")
    miss = _missing(src)
    assert "hFF" not in miss and "h00" not in miss and "d0" not in miss, miss
    assert miss == [], miss


def test_802_noleak_real_missing_signal_beside_literal_still_flags():
    src = ("module m(input [3:0] a, input [7:0] b, output reg [7:0] y);\n"
           " always @(a) y = b & 8'hFF;\nendmodule")
    assert _missing(src) == ["b"]


def test_802_noleak_signal_named_d0_without_apostrophe_still_flags():
    # `d0` read as `q = d0;` (no apostrophe) is a genuine signal, not a literal.
    src = ("module m(input [3:0] a, input [3:0] d0, output reg [3:0] q);\n"
           " always @(a) q = d0;\nendmodule")
    assert _missing(src) == ["d0"]


def test_802_strip_helper_only_strips_apostrophe_anchored():
    import re
    strip = lambda b: re.sub(  # noqa: E731
        r"\b\d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_]+", " ", b)
    assert "hFF" not in strip("y = 8'hFF;")
    assert "d0" in strip("q = d0;")    # no apostrophe → preserved


# ── END-STATE: the real rtl_hygiene_lint program (default INFO severity) no
#    longer hard-blocks (rc=1) the based-literal combinational RTL. ─────────────
import subprocess  # noqa: E402


def test_802_endstate_program_no_longer_hard_blocks(tmp_path):
    rtl = ("module m(input [3:0] a, output reg [7:0] y);\n"
           " always @(a) begin y = 8'hFF; if (a == 4'hF) y = 8'h00;"
           " y = 20'd0; end\nendmodule")
    f = tmp_path / "m.v"
    f.write_text(rtl)
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "rtl_hygiene_lint.py"), str(f)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout       # was rc=1 (based-literal false WARN)
    assert "incomplete-sensitivity" not in r.stdout or "b0000" not in r.stdout


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
