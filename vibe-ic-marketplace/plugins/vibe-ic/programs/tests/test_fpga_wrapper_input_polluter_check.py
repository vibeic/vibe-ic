"""Tests for fpga_wrapper_input_polluter_check.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAM = Path(__file__).parent.parent / "fpga_wrapper_input_polluter_check.py"


def _run(args: list[str]) -> tuple[int, dict]:
    r = _pr.run(
        [sys.executable, str(PROGRAM), *args, "--json"],
        capture_output=True, text=True)
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        out = {}
    return r.returncode, out


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


# -------------------------------------------------------------------------
# CLI / argument handling
# -------------------------------------------------------------------------

def test_help_works():
    r = _pr.run(
        [sys.executable, str(PROGRAM), "--help"],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert "fpga" in r.stdout.lower()
    assert "inout" in r.stdout.lower()


def test_missing_rtl_arg_returns_2():
    r = _pr.run(
        [sys.executable, str(PROGRAM)],
        capture_output=True, text=True)
    assert r.returncode == 2
    assert "--rtl" in r.stderr


def test_missing_dir_returns_2(tmp_path):
    code, _ = _run(["--rtl", str(tmp_path / "does-not-exist")])
    assert code == 2


def test_empty_dir_returns_2(tmp_path):
    code, _ = _run(["--rtl", str(tmp_path)])
    assert code == 2


def test_qsf_missing_returns_2(tmp_path):
    _write(tmp_path / "top.v", "module top(); endmodule\n")
    code, _ = _run(["--rtl", str(tmp_path), "--qsf", str(tmp_path / "no.qsf")])
    assert code == 2


# -------------------------------------------------------------------------
# Clean cases pass
# -------------------------------------------------------------------------

def test_clean_single_inout_passes(tmp_path):
    _write(tmp_path / "top.v", """
module top(input clk, inout id_bus_v10);
    wire in = id_bus_v10;
    assign id_bus_v10 = 1'bz;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert code == 0, out
    assert out["verdict"] == "PASS"
    assert out["total_errors"] == 0
    assert out["total_warnings"] == 0


def test_clean_two_inouts_no_combine_passes(tmp_path):
    _write(tmp_path / "top.v", """
module top(input clk, inout sda, inout scl);
    wire sda_in = sda;
    wire scl_in = scl;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert code == 0, out
    assert out["total_warnings"] == 0


def test_module_without_inouts_skipped(tmp_path):
    _write(tmp_path / "top.v", """
module purelogic(input a, input b, output c);
    wire combo = a & b;
    assign c = combo;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert code == 0
    assert out["total_warnings"] == 0


def test_and_of_non_inout_signals_ignored(tmp_path):
    _write(tmp_path / "top.v", """
module top(input a, input b, inout sda);
    wire combo = a & b;       // both regular inputs, not inouts
    wire sda_in = sda;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert code == 0
    assert out["total_warnings"] == 0


# -------------------------------------------------------------------------
# Polluter pattern is flagged
# -------------------------------------------------------------------------

POLLUTER_RTL = """
module wrapper(
    inout id_bus_v10,
    inout id_bus_w9,
    inout id_bus_v9,
    inout id_bus_w10,
    inout id_bus_w8
);
    wire id_in = id_bus_v10 & id_bus_w9 & id_bus_v9 & id_bus_w10 & id_bus_w8;
    wire drv_low;
    assign id_bus_v10 = drv_low ? 1'b0 : 1'bz;
    assign id_bus_w9  = drv_low ? 1'b0 : 1'bz;
    assign id_bus_v9  = drv_low ? 1'b0 : 1'bz;
    assign id_bus_w10 = drv_low ? 1'b0 : 1'bz;
    assign id_bus_w8  = drv_low ? 1'b0 : 1'bz;
endmodule
"""


def test_polluter_pattern_warns_by_default(tmp_path):
    _write(tmp_path / "wrapper.v", POLLUTER_RTL)
    code, out = _run(["--rtl", str(tmp_path)])
    assert code == 0  # WARN, not ERROR
    assert out["total_warnings"] == 1
    assert out["total_errors"] == 0
    f = out["findings"][0]
    assert f["rule"] == "multi_inout_combine"
    assert f["module"] == "wrapper"
    assert set(f["pins"]) == {
        "id_bus_v10", "id_bus_w9", "id_bus_v9", "id_bus_w10", "id_bus_w8"}


def test_polluter_pattern_errors_with_strict(tmp_path):
    _write(tmp_path / "wrapper.v", POLLUTER_RTL)
    code, out = _run(["--rtl", str(tmp_path), "--strict"])
    assert code == 1
    assert out["total_errors"] == 1
    assert out["verdict"] == "FAIL"


def test_or_of_inouts_also_flagged(tmp_path):
    _write(tmp_path / "wrapper.v", """
module wrapper(inout a, inout b, inout c);
    wire any_low = a | b | c;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert code == 0
    assert out["total_warnings"] == 1
    assert "'|'" in out["findings"][0]["detail"]


def test_two_inout_combine_flagged(tmp_path):
    _write(tmp_path / "wrapper.v", """
module w(inout a, inout b);
    wire c = a & b;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert out["total_warnings"] == 1


def test_assign_form_also_flagged(tmp_path):
    _write(tmp_path / "wrapper.v", """
module w(inout a, inout b, output o);
    assign o = a & b;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert out["total_warnings"] == 1


def test_legacy_inout_decl_form(tmp_path):
    _write(tmp_path / "wrapper.v", """
module wrapper(a, b, c);
    inout a;
    inout b;
    inout c;
    wire combined = a & b & c;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert out["total_warnings"] == 1
    assert set(out["findings"][0]["pins"]) == {"a", "b", "c"}


# -------------------------------------------------------------------------
# Allowlist marker
# -------------------------------------------------------------------------

def test_allowlist_marker_exempts(tmp_path):
    _write(tmp_path / "wrapper.v", """
module w(inout a, inout b);
    // fpga-input-polluter-allow: bench has both pins genuinely tied
    wire c = a & b;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert code == 0
    assert out["total_warnings"] == 0
    assert out["total_errors"] == 0


def test_allowlist_marker_two_lines_above_with_blank(tmp_path):
    _write(tmp_path / "wrapper.v", """
module w(inout a, inout b);
    // fpga-input-polluter-allow: see above

    wire c = a & b;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert out["total_warnings"] == 0


# -------------------------------------------------------------------------
# QSF-aware mode
# -------------------------------------------------------------------------

def _qsf(pin_to_sig: dict[str, str]) -> str:
    lines = ["# auto"]
    for pin, sig in pin_to_sig.items():
        lines.append(f"set_location_assignment {pin} -to {sig}")
    return "\n".join(lines) + "\n"


def test_qsf_all_bound_keeps_warn(tmp_path):
    _write(tmp_path / "wrapper.v", """
module w(inout a, inout b, inout c);
    wire x = a & b & c;
endmodule
""")
    qsf = _write(tmp_path / "p.qsf", _qsf(
        {"PIN_V10": "a", "PIN_W9": "b", "PIN_V9": "c"}))
    code, out = _run(["--rtl", str(tmp_path / "wrapper.v"),
                      "--qsf", str(qsf)])
    assert code == 0  # WARN only
    assert out["total_warnings"] == 1
    assert out["total_errors"] == 0


def test_qsf_partial_bound_escalates_to_error(tmp_path):
    _write(tmp_path / "wrapper.v", """
module w(inout a, inout b, inout c);
    wire x = a & b & c;
endmodule
""")
    qsf = _write(tmp_path / "p.qsf", _qsf({"PIN_V10": "a"}))
    code, out = _run(["--rtl", str(tmp_path / "wrapper.v"),
                      "--qsf", str(qsf)])
    assert code == 1
    assert out["total_errors"] == 1
    assert out["verdict"] == "FAIL"
    assert "QSF binds only 1 of 3" in out["findings"][0]["detail"]


def test_qsf_bound_signals_reported(tmp_path):
    _write(tmp_path / "w.v", "module w(inout a); endmodule\n")
    qsf = _write(tmp_path / "p.qsf", _qsf({"PIN_V10": "clk", "PIN_B8": "rst"}))
    _, out = _run(["--rtl", str(tmp_path / "w.v"), "--qsf", str(qsf)])
    assert set(out["qsf_bound_signals"]) == {"clk", "rst"}


# -------------------------------------------------------------------------
# Multi-file / recursive scan
# -------------------------------------------------------------------------

def test_recursive_dir_scan(tmp_path):
    _write(tmp_path / "a/clean.v", "module c(inout x); endmodule\n")
    _write(tmp_path / "b/dirty.sv", """
module dirty(inout p, inout q);
    wire r = p & q;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert out["files_scanned"] == 2
    assert out["total_warnings"] == 1


def test_repeated_rtl_args(tmp_path):
    _write(tmp_path / "x.v", "module x(inout a, inout b); wire y = a&b; endmodule\n")
    _write(tmp_path / "y.v", "module y(inout a); endmodule\n")
    code, out = _run([
        "--rtl", str(tmp_path / "x.v"),
        "--rtl", str(tmp_path / "y.v"),
    ])
    assert out["files_scanned"] == 2
    assert out["total_warnings"] == 1


# -------------------------------------------------------------------------
# Comment handling
# -------------------------------------------------------------------------

def test_inout_in_block_comment_ignored(tmp_path):
    _write(tmp_path / "w.v", """
module w(input a, input b);
    /* inout x; inout y; wire z = x & y; */
    wire c = a & b;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert out["total_warnings"] == 0


def test_combine_in_line_comment_ignored(tmp_path):
    _write(tmp_path / "w.v", """
module w(inout a, inout b);
    // wire c = a & b;   -- example only
    wire d = a;
endmodule
""")
    code, out = _run(["--rtl", str(tmp_path)])
    assert out["total_warnings"] == 0
