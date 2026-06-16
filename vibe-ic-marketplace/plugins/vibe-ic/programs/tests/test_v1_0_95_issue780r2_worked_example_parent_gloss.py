"""ORGANIC #780 round-2 (field reopen) — the v1.0.93 worked_example fix was
INCOMPLETE on the REAL binary_to_BCD_0010: the spec lists the per-digit steps
SEPARATELY ("MSD 0010 -> 2, Middle 0101 -> 5, LSD 0111 -> 7") with no grouped
binary literal in the SPEC, so the extraction-time `we_structural_artifact`
(spec-only grouped-source check) missed it and `0101 -> 5` still hard-blocked
(rc=1) — even though the TESTBENCH drives the full parent input
`bcd_in = 0010_0101_0111` and asserts the one output.

Fix (run()-time, has the TB): a binary-nibble notational gloss (LHS bits == RHS
value) that is a NIBBLE-ALIGNED slice of a larger grouped binary value present in
the spec OR the testbench (the parent example input the TB stimulates) is an
intermediate algorithm step → NO_CORROBORATION → advisory.

§4.05 no-leak: a GENUINE standalone binary->decimal example the TB never drives a
CONTAINING parent for still BLOCKS; a coincidental non-nibble-aligned substring
match in an unrelated wide TB literal does NOT downgrade it.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import spec_coverage_check as SC  # noqa: E402

_SPEC_COV = _PROGRAMS / "spec_coverage_check.py"

# the REAL discriminating shape (Step-2.6: per-digit steps listed SEPARATELY, no
# grouped literal in the spec; verbatim arrow-gloss form the field agent showed).
_BCD_SPEC = (
    "# binary_to_BCD converter\n"
    "Convert packed-BCD bcd_in to binary_out.\n"
    "Worked example digits: MSD 0010 -> 2, Middle 0101 -> 5, LSD 0111 -> 7; "
    "combine to binary_out = 257.\n")
_BCD_RTL = (
    "module binary_to_BCD(input [11:0] bcd_in, output [8:0] binary_out);\n"
    "  assign binary_out = bcd_in[11:8]*100 + bcd_in[7:4]*10 + bcd_in[3:0];\n"
    "endmodule\n")
# the TB drives the full grouped PARENT input (and asserts the one output).
_BCD_TB = (
    "module tb; reg [11:0] bcd_in; wire [8:0] binary_out;\n"
    "  binary_to_BCD u(.bcd_in(bcd_in), .binary_out(binary_out));\n"
    "  initial begin bcd_in = 12'b0010_0101_0111; #10;\n"
    "    if (binary_out == 257) $display(\"PASS\"); $finish; end\nendmodule\n")


def _run(tmp_path, spec, rtl, tb):
    (tmp_path / "s.md").write_text(spec)
    (tmp_path / "r.sv").write_text(rtl)
    (tmp_path / "tb.sv").write_text(tb)
    return subprocess.run(
        [sys.executable, str(_SPEC_COV), "--prompt", str(tmp_path / "s.md"),
         "--rtl", str(tmp_path / "r.sv"), "--tb", str(tmp_path / "tb.sv"),
         "--strict"], capture_output=True, text=True)


# ── NEW-PATH: the reopen case — per-digit gloss advisory, rc=0 ───────────────
def test_780r2_per_digit_gloss_with_tb_parent_is_advisory(tmp_path):
    r = _run(tmp_path, _BCD_SPEC, _BCD_RTL, _BCD_TB)
    assert r.returncode == 0, r.stdout
    assert "0101 -> 5" in r.stdout and "ADVISORY" in r.stdout


# ── §4.05 NO-LEAK: a genuine standalone example the TB never drives a parent
# for still BLOCKs ───────────────────────────────────────────────────────────
_DEC_SPEC = ("# bin2dec decoder\nThe decoder maps a 4-bit binary input to its "
             "decimal value. Example: 0101 -> 5.\n")
_DEC_RTL = "module bin2dec(input [3:0] b, output [3:0] d); assign d = b; endmodule\n"


def test_780r2_noleak_standalone_decoder_example_blocks(tmp_path):
    tb = ("module tb; reg [3:0] b; wire [3:0] d; bin2dec u(.b(b), .d(d));\n"
          "  initial begin b = 4'b0011; #10; b = 4'b1001; #10; $finish; end\n"
          "endmodule\n")
    assert _run(tmp_path, _DEC_SPEC, _DEC_RTL, tb).returncode == 1


def test_780r2_noleak_coincidental_substring_does_not_downgrade(tmp_path):
    # genuine 0101->5 the TB never covers; TB drives an unrelated 8'b11010110
    # which CONTAINS '0101' but at a NON-nibble-aligned offset (3) → must NOT
    # be treated as a parent → still BLOCKs.
    tb = ("module tb; reg [3:0] b; wire [3:0] d; bin2dec u(.b(b), .d(d));\n"
          "  reg [7:0] junk;\n"
          "  initial begin junk = 8'b11010110; b = 4'b0011; #10; b = 4'b1001; "
          "#10; $finish; end\nendmodule\n")
    assert _run(tmp_path, _DEC_SPEC, _DEC_RTL, tb).returncode == 1


# ── the helpers ──────────────────────────────────────────────────────────────
def test_780r2_grouped_source_requires_nibble_alignment():
    # the real per-digit parent (nibble-aligned) is a grouped source ...
    assert SC._binary_nibble_has_grouped_source("bcd_in = 0010_0101_0111", "0101")
    # ... a coincidental non-aligned substring (offset 3 in 11010110) is NOT.
    assert not SC._binary_nibble_has_grouped_source("8'b11010110", "0101")


def test_780r2_parent_gloss_helper_needs_grouped_parent():
    # gloss tokens + a grouped parent in the combined text → True.
    assert SC._worked_example_is_covered_parent_gloss(
        ["0101", "5"], "tb drives bcd_in = 0010_0101_0111")
    # gloss tokens with NO grouped parent anywhere → False (keeps blocking).
    assert not SC._worked_example_is_covered_parent_gloss(
        ["0101", "5"], "the decoder maps 0101 to 5")
    # a non-gloss genuine pair (bin 0011 = 3 != 1010) → False regardless.
    assert not SC._worked_example_is_covered_parent_gloss(
        ["0011", "1010"], "0011_1010_0011 grouped")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
