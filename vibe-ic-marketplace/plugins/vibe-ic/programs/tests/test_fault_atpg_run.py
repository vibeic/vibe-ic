"""Unit tests for fault_atpg_run.py.

Fault runs inside a Docker container so the heavy integration path cannot
be unit-tested without the image. These tests cover:
  - Argument parsing and PDK config validation
  - IO-error handling (missing project dir, missing netlist, bad pdk)

Full end-to-end Fault-in-Docker run is validated by the aon_timer pilot
(see reports/dft/coverage.json); no need to re-run in unit tests.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "fault_atpg_run.py"
assert SCRIPT.exists()

sys.path.insert(0, str(SCRIPT.parent))
import fault_atpg_run as far  # noqa: E402


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_missing_project_dir(tmp_path):
    r = _run(str(tmp_path / "nope"), "--clock", "clk")
    assert r.returncode == 2
    assert "not a directory" in r.stderr.lower()


def test_missing_netlist(tmp_path):
    r = _run(str(tmp_path), "--netlist", "synth/missing.v", "--clock", "clk")
    assert r.returncode == 2
    assert "netlist not found" in r.stderr.lower()


def test_unsupported_pdk(tmp_path):
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (tmp_path / "phase2" / "stage2" / "synth" / "netlist.v").write_text("module top; endmodule\n")
    r = _run(str(tmp_path), "--clock", "clk", "--pdk", "nonexistent_pdk")
    # Program imports fine and gets to run_fault which returns exit 2 for bad pdk
    assert r.returncode in (1, 2)


def test_clock_arg_required(tmp_path):
    r = _run(str(tmp_path))
    assert r.returncode != 0
    assert "clock" in r.stderr.lower() or "required" in r.stderr.lower()


# --- image-resolution pinning ------------------------------------------------
# The fork fallback tags must be PINNED (vibeic-eda:X.Y.Z), never :latest — a
# floating tag can silently resolve to a stale local image whose tool behavior
# no longer matches what the plugin was verified against. The pinned value is
# kept in sync with tools/vibeic-eda/VERSION by sync_image_version.py (this
# file is registered in its INSTALL_DOC_CANDIDATES).

def _find_version_file():
    for up in Path(__file__).resolve().parents:
        c = up / "tools" / "vibeic-eda" / "VERSION"
        if c.is_file():
            return c
    return None


def test_no_floating_fork_image_tag():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "vibeic-eda:latest" not in src, (
        "fork image fallback must be pinned to vibeic-eda:X.Y.Z, not :latest"
    )
    # the pinned fork tags must still be present (resolver not gutted)
    assert re.search(r"ghcr\.io/vibeic/vibeic-eda:\d+\.\d+\.\d+", src)


def test_pinned_tag_matches_version_source_of_truth():
    vf = _find_version_file()
    if vf is None:
        pytest.skip("tools/vibeic-eda/VERSION not present (packaged plugin)")
    version = vf.read_text(encoding="utf-8").strip()
    src = SCRIPT.read_text(encoding="utf-8")
    tags = re.findall(r"vibeic-eda:(\d+\.\d+\.\d+)", src)
    assert tags, "expected pinned vibeic-eda:X.Y.Z tags in fault_atpg_run.py"
    assert set(tags) == {version}, (
        f"pinned tags {sorted(set(tags))} drifted from VERSION={version}; "
        "run tools/vibeic-eda/sync_image_version.py --set/--bump"
    )


# --- pure helpers: dff-cell detection / merge / cell-model resolution -------
# These back the HP18E80 fix where the PDK-config seed (DFFRQD1,DFFSQD1) did
# NOT match the netlist's real flop cell (DFFHQD1); auto-detect + union fixes
# it chip-AGNOSTICally, and the cell-model resolver lets the commercial Verilog
# sim model be supplied explicitly (the proprietary PDK ships only a liberty in
# the run dir).

def test_detect_dff_cells_hp18e80_dffhqd1():
    # 64 DFFHQD1 instances as emitted by yosys for the spm HP18E80 netlist.
    nl = "\n".join(f"  DFFHQD1 _{n}_ ( .CK(clk), .D(d{n}), .Q(q{n}) );"
                   for n in range(3))
    assert far.detect_dff_cells(nl) == "DFFHQD1"


def test_detect_dff_cells_sorted_unique_union():
    nl = ("  DFFSQD1 a ( .Q(x) );\n"
          "  DFFHQD1 b ( .Q(y) );\n"
          "  SDFFHQD1 c ( .Q(z) );\n"
          "  DFFHQD1 d ( .Q(w) );\n")
    assert far.detect_dff_cells(nl) == "DFFHQD1,DFFSQD1,SDFFHQD1"


def test_detect_dff_cells_ignores_wire_decls():
    # A wire/reg named dff_* must NOT be picked up as a cell instantiation.
    nl = ("  wire dff_out;\n"
          "  reg  dffstate;\n"
          "  NAND2D1 g0 ( .A(a), .B(b), .Y(y) );\n")
    assert far.detect_dff_cells(nl) == ""


def test_detect_dff_cells_sky130_infix(tmp_path=None):
    # v1.4.21 REGRESSION — sky130 flops are `sky130_fd_sc_hd__dfxtp_1` (lowercase
    # `__df` INFIX, not a DFF prefix). The auto-detect previously returned "" on
    # sky130 → `fault cut` got the wrong seed → cut NOTHING → 64 un-cut flops →
    # a FALSE NOT_APPLICABLE (a sequential design silently skipping TDF ATPG).
    nl = ("  sky130_fd_sc_hd__dfxtp_1 \\creg_reg[0]  (.CLK(clk), .D(d0), .Q(q0));\n"
          "  sky130_fd_sc_hd__dfrtp_1 \\creg_reg[1]  (.CLK(clk), .D(d1), .Q(q1));\n"
          "  sky130_fd_sc_hd__sdfxtp_1 u2 (.CLK(clk), .D(d2), .Q(q2));\n")
    got = far.detect_dff_cells(nl)
    assert "sky130_fd_sc_hd__dfxtp_1" in got
    assert "sky130_fd_sc_hd__dfrtp_1" in got
    assert "sky130_fd_sc_hd__sdfxtp_1" in got


def test_detect_dff_cells_gf180_infix():
    nl = ("  gf180mcu_fd_sc_mcu7t5v0__dffq_1 u0 (.D(x), .Q(y));\n"
          "  gf180mcu_fd_sc_mcu7t5v0__sdffq_1 u1 (.D(a), .Q(b));\n")
    got = far.detect_dff_cells(nl)
    assert "gf180mcu_fd_sc_mcu7t5v0__dffq_1" in got
    assert "gf180mcu_fd_sc_mcu7t5v0__sdffq_1" in got


def test_detect_dff_cells_infix_no_false_positive_on_non_flops():
    # non-flop std cells that merely contain letters — buf/dly/mux/inv — must NOT
    # be mistaken for flops (only the `__[s][e]df…` D-flop family matches).
    # LATCHES (`__dl*`, `__lat*`) and delay (`__dly*`) never reach `df`.
    nl = ("  sky130_fd_sc_hd__buf_1 u0 (.A(a), .X(x));\n"
          "  sky130_fd_sc_hd__dlygate4sd3_1 u1 (.A(a), .X(x));\n"
          "  sky130_fd_sc_hd__dlrtp_1 u2 (.RESET_B(r), .D(d), .GATE(g), .Q(q));\n"
          "  sky130_fd_sc_hd__mux2_1 u3 (.A0(a), .A1(b), .S(s), .X(x));\n"
          "  sky130_fd_sc_hd__inv_1 u4 (.A(a), .Y(y));\n"
          "  gf180mcu_fd_sc_mcu7t5v0__latq_1 u5 (.D(d), .Q(q));\n")
    assert far.detect_dff_cells(nl) == ""


def test_detect_dff_cells_sky130_enable_flop_family(tmp_path=None):
    # v1.4.21 STEP-2.7 REGRESSION — the ENABLE-flop (`edf*`) and scan-enable-flop
    # (`sedf*`) families are the MOST common flop on real sky130 synth (yosys maps
    # `$_DFFE_*` → `edfxtp`; subservient has 1024 `edfxtp_1`). Missing them left a
    # clock-enabled sequential design with detect=="" → a FALSE NOT_APPLICABLE the
    # coverage gate silently passed (gate-gaming). `__s?e?df` must catch them.
    nl = ("  sky130_fd_sc_hd__edfxtp_1 \\r0  (.CLK(clk), .DE(e), .D(d0), .Q(q0));\n"
          "  sky130_fd_sc_hd__edfxbp_1 \\r1  (.CLK(clk), .DE(e), .D(d1), .Q(q1));\n"
          "  sky130_fd_sc_hd__sedfxtp_1 u2 (.CLK(clk), .DE(e), .D(d2), .Q(q2));\n")
    got = far.detect_dff_cells(nl)
    assert "sky130_fd_sc_hd__edfxtp_1" in got
    assert "sky130_fd_sc_hd__edfxbp_1" in got
    assert "sky130_fd_sc_hd__sedfxtp_1" in got
    # a pure-enable-flop sequential design is NEVER classified combinational —
    # this is the anti-gaming invariant the false-N/A guard relies on
    assert far.detect_dff_cells(nl) != ""


def test_merge_dff_cells_unions_seed_and_detected():
    # seed misses the real cell (DFFHQD1); union must still include it.
    assert far.merge_dff_cells("DFFRQD1,DFFSQD1", "DFFHQD1") == \
        "DFFHQD1,DFFRQD1,DFFSQD1"
    assert far.merge_dff_cells(None, "DFFHQD1") == "DFFHQD1"
    assert far.merge_dff_cells("DFFRQD1", "") == "DFFRQD1"
    assert far.merge_dff_cells("", "") == ""
    # de-dups overlapping tokens with surrounding whitespace
    assert far.merge_dff_cells(" DFFHQD1 , DFFRQD1 ", "DFFHQD1") == \
        "DFFHQD1,DFFRQD1"


def test_resolve_cell_model_container_absolute_passthrough():
    assert far.resolve_cell_model("/pdk/verilog/x.v", None) == "/pdk/verilog/x.v"
    assert far.resolve_cell_model("/foss/pdks/y.v",
                                  {"cell_model": "/z.v"}) == "/foss/pdks/y.v"


def test_resolve_cell_model_project_relative_under_work():
    assert far.resolve_cell_model("input/pdk/verilog/m.v", None) == \
        "/work/input/pdk/verilog/m.v"
    assert far.resolve_cell_model("./a/b.v", None) == "/work/a/b.v"


def test_resolve_cell_model_falls_back_to_pdk_config_then_none():
    assert far.resolve_cell_model(None, {"cell_model": "/pdk/c.v"}) == "/pdk/c.v"
    assert far.resolve_cell_model(None, None) is None


def test_env_override_wins_over_pinned_candidates():
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, sys.argv[1]); "
         "import fault_atpg_run as f; print(f.DOCKER_IMAGE)",
         str(SCRIPT.parent)],
        capture_output=True, text=True,
        env={**os.environ, "VIBEIC_EDA_IMAGE": "example/override:9.9.9"},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == "example/override:9.9.9"
