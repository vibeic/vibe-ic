"""Unit tests for rom_init_lint.py.

Covers the IC-A FPGA BIST silent-failure class: `initial begin for (...)
mem[i] = ...` patterns that Quartus MAX10 cannot synthesize.

Tests:
  1. Broken pattern with integer declared at module scope  — FAIL
  2. Broken pattern with integer declared inside initial   — FAIL
  3. Safe: $readmemh init                                  — PASS
  4. Safe: per-index assignments without for-loop          — PASS
  5. Safe: no memory declarations                          — PASS
"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "rom_init_lint.py"
assert SCRIPT.exists(), f"rom_init_lint.py not found at {SCRIPT}"


def _run(*paths: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, paths)],
        capture_output=True,
        text=True,
    )


def _write(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text(body)
    return p


def test_broken_integer_at_module_scope(tmp_path):
    f = _write(tmp_path, "bad.v", """
module bad;
    reg [7:0] rom [0:31];
    integer i;
    initial begin
        for (i = 0; i < 32; i = i + 1) rom[i] = 8'h00;
        rom[0] = 8'h70;
    end
endmodule
""")
    r = _run(f)
    assert r.returncode == 1, f"expected fail, got {r.returncode}: {r.stderr}"
    assert "quartus-unsafe-rom-init" in r.stderr


def test_broken_integer_inside_initial(tmp_path):
    f = _write(tmp_path, "bad2.v", """
module bad2;
    reg [7:0] rom [0:7];
    initial begin
        integer i;
        for (i = 0; i < 8; i = i + 1) rom[i] = 8'hFF;
    end
endmodule
""")
    r = _run(f)
    assert r.returncode == 1, f"expected fail, got {r.returncode}: {r.stderr}"


def test_safe_readmemh(tmp_path):
    f = _write(tmp_path, "good1.v", """
module good1;
    reg [7:0] rom [0:31];
    initial $readmemh("rom.hex", rom);
endmodule
""")
    r = _run(f)
    assert r.returncode == 0, f"expected pass, got {r.returncode}: {r.stderr}"


def test_safe_per_index_no_loop(tmp_path):
    f = _write(tmp_path, "good2.v", """
module good2;
    reg [7:0] rom [0:3];
    initial begin
        rom[0] = 8'h01;
        rom[1] = 8'h02;
        rom[2] = 8'h03;
        rom[3] = 8'h04;
    end
endmodule
""")
    r = _run(f)
    assert r.returncode == 0, f"expected pass, got {r.returncode}: {r.stderr}"


def test_safe_no_memory(tmp_path):
    f = _write(tmp_path, "plain.v", """
module plain(input clk, output reg q);
    always @(posedge clk) q <= ~q;
endmodule
""")
    r = _run(f)
    assert r.returncode == 0


# ── the $readmem* exemption, and the two controls that keep it honest ──────────
# Measured on a real design: the gate fired on code that ALREADY implemented
# remediation (B) from its own fix_hint, and failed the whole cell for it. The
# exemption is keyed on the SAME memory, so a gate that merely stops firing would
# be caught by the two negative controls below.

_ZERO_THEN_READMEM = """\
module m;
  reg [7:0] mem [0:127];
  integer i;
  initial begin
    for (i = 0; i < 128; i = i + 1) mem[i] = 8'h00;
    $readmemh("rom.hex", mem);
  end
endmodule
"""

_ZERO_ONLY = """\
module n;
  reg [7:0] mem [0:127];
  integer i;
  initial begin
    for (i = 0; i < 128; i = i + 1) mem[i] = 8'h00;
  end
endmodule
"""

_ZERO_THEN_READMEM_OTHER_MEM = """\
module o;
  reg [7:0] mem [0:127];
  reg [7:0] other [0:127];
  integer i;
  initial begin
    for (i = 0; i < 128; i = i + 1) mem[i] = 8'h00;
    $readmemh("rom.hex", other);
  end
endmodule
"""


def _scan_src(tmp_path, src, name="d.v"):
    import rom_init_lint as R
    f = tmp_path / name
    f.write_text(src)
    return R.scan_file(f)


def test_zeroing_loop_followed_by_readmem_of_the_same_mem_is_not_a_defect(tmp_path):
    """The zeroing loop is a benign prologue; the array's contents come from the file."""
    assert _scan_src(tmp_path, _ZERO_THEN_READMEM) == []


def test_zeroing_loop_with_no_readmem_still_fires(tmp_path):
    """NEGATIVE CONTROL: distinguishes 'the exemption works' from 'the rule died'."""
    f = _scan_src(tmp_path, _ZERO_ONLY)
    assert len(f) == 1 and f[0].rule == "quartus-unsafe-rom-init"


def test_readmem_into_a_different_mem_still_fires(tmp_path):
    """NEGATIVE CONTROL: an exemption keyed on mere PRESENCE would leak here."""
    f = _scan_src(tmp_path, _ZERO_THEN_READMEM_OTHER_MEM)
    assert len(f) == 1 and f[0].rule == "quartus-unsafe-rom-init"
