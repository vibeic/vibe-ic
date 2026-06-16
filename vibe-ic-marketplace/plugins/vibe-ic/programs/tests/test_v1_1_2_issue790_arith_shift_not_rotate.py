"""ORGANIC #790 — the #784 `shift-implemented-as-rotate` emit-block FALSE-BLOCKED
a sign-extending arithmetic right shift `{q[MSB], q[MSB:1]}` (the spec-faithful
arithmetic-shift idiom) as a wrap-around ROTATE.

Root cause: `_rtl_rotate_signatures` flagged ANY same-vector 2-part concat
`{x[..], x[..]}` as a rotate without checking the wrap is BIJECTIVE. A genuine
rotate PARTITIONS the index range [0..W-1] (disjoint + gap-free); a sign-extend
DUPLICATES the MSB (overlap) and DROPS the LSB (gap).

Fix: a same-vector concat counts as a rotate ONLY when its two bit-selects
partition the full index range. §4.05: every genuine rotate form (right / left /
rotate-by-k) still BLOCKs under a shift spec; the sign-extend / overlap / gap /
literal-fill forms are correctly silent.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_P = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_P))
import spec_conformance_check as SC  # noqa: E402

_PC = _P / "spec_conformance_check.py"
_SHIFT_SPEC = ("A 64-bit arithmetic shift register. On each clock perform an "
               "arithmetic right shift by one bit; the arithmetic right shift "
               "replicates the sign bit (MSB).\n")
_LOGICAL_SPEC = ("A barrel shifter performing a logical shift right of the input "
                 "by the control amount.\n")


def _conf(tmp_path, rtl, spec=_SHIFT_SPEC):
    d = tmp_path
    (d / "d.sv").write_text(rtl)
    (d / "spec.txt").write_text(spec)
    return subprocess.run(
        [sys.executable, str(_PC), "--rtl-dir", str(d), "--spec",
         str(d / "spec.txt"), "--top", "top"], capture_output=True, text=True)


_ASR = ("module top(input clk, input load, input [63:0] data, "
        "output reg [63:0] q);\n"
        "  always @(posedge clk) if (load) q <= data; else q <= {q[63], q[63:1]};\n"
        "endmodule\n")


# ── NEW-PATH: sign-extending arithmetic shift is NOT a rotate (no false-block) ─
def test_790_arith_shift_concat_not_blocked(tmp_path):
    r = _conf(tmp_path, _ASR)
    assert r.returncode == 0, r.stdout
    assert "shift-implemented-as-rotate" not in r.stdout


# ── §4.05 NO-LEAK: every genuine rotate form still BLOCKs under a shift spec ──
@pytest.mark.parametrize("body,desc", [
    ("q <= {q[0], q[63:1]};", "right-rotate-1"),
    ("q <= {q[62:0], q[63]};", "left-rotate-1"),
    ("q <= {q[1:0], q[63:2]};", "rotate-by-2"),
])
def test_790_noleak_genuine_rotate_still_flagged(body, desc):
    rtl = ("module top(input clk, input load, input [63:0] data, "
           "output reg [63:0] q);\n"
           f"  always @(posedge clk) if (load) q <= data; else {body}\n"
           "endmodule\n")
    assert SC._rtl_rotate_signatures(rtl), desc


def test_790_noleak_genuine_rotate_concat_blocks_under_shift_spec(tmp_path):
    rtl = ("module top(input clk, input load, input [63:0] data, "
           "output reg [63:0] q);\n"
           "  always @(posedge clk) if (load) q <= data; else q <= {q[0], q[63:1]};\n"
           "endmodule\n")
    r = _conf(tmp_path, rtl, spec=_LOGICAL_SPEC)
    assert r.returncode == 1 and "shift-implemented-as-rotate" in r.stdout, r.stdout


def test_790_noleak_or_of_opposite_shifts_still_blocks(tmp_path):
    rtl = ("module top(input [7:0] din, input [2:0] c, output [7:0] dout);\n"
           "  assign dout = (din >> c) | (din << (8-c));\nendmodule\n")
    r = _conf(tmp_path, rtl, spec=_LOGICAL_SPEC)
    assert r.returncode == 1 and "shift-implemented-as-rotate" in r.stdout, r.stdout


# ── the partition-check helper directly ──────────────────────────────────────
def test_790_partition_check_helper():
    sig = SC._rtl_rotate_signatures
    assert sig("x <= {x[0], x[7:1]};")          # disjoint + gap-free → rotate
    assert not sig("x <= {x[7], x[7:1]};")      # MSB dup (overlap) → arith shift
    assert not sig("x <= {x[3:0], x[3:0]};")    # full overlap → not a partition
    assert not sig("x <= {1'b0, x[7:1]};")      # literal fill → logical shift


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
