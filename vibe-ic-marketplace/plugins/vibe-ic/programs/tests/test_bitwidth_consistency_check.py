"""Unit tests for bitwidth_consistency_check.py."""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bitwidth_consistency_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import bitwidth_consistency_check as chk  # noqa: E402


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


def test_oversized_bitselect_fails(tmp_path):
    content = """\
module m;
    reg [4:0] idx;
    wire [7:0] addr;
    assign addr = 8'h00 + idx[6:0];
endmodule
"""
    p = _write(tmp_path, "m.v", content)
    findings = chk.analyze_file(p)
    errors = [f for f in findings if f.severity == "error"]
    assert errors
    assert "bitselect-out-of-range" in errors[0].rule


def test_in_range_bitselect_passes(tmp_path):
    content = """\
module m;
    reg [7:0] data;
    wire [3:0] low_nibble;
    assign low_nibble = data[3:0];
endmodule
"""
    p = _write(tmp_path, "m.v", content)
    findings = chk.analyze_file(p)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors


def test_concat_widening_passes(tmp_path):
    content = """\
module m;
    reg [4:0] idx;
    wire [7:0] addr;
    assign addr = {3'b0, idx};
endmodule
"""
    p = _write(tmp_path, "m.v", content)
    findings = chk.analyze_file(p)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors


def test_full_range_match_passes(tmp_path):
    content = """\
module m;
    reg [7:0] data;
    wire [7:0] copy;
    assign copy = data[7:0];
endmodule
"""
    p = _write(tmp_path, "m.v", content)
    findings = chk.analyze_file(p)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors
