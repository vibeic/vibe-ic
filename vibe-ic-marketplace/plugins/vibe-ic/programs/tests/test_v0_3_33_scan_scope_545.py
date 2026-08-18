"""ORGANIC #545 — shared rtl_scan_scope policy: exclude input/ vendor staging,
dot-dirs, sim*/oracle_run intermediates by component prefix (not exact match).
cdc_async_input_check adopts it.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import rtl_scan_scope as S          # noqa: E402
import cdc_async_input_check as CDC  # noqa: E402


def test_excluded_component_prefix_and_dotdir():
    # the exact-match bug: sim_full_stack must be excluded by the sim prefix
    assert S.is_excluded_component("sim")
    assert S.is_excluded_component("sim_full_stack")
    assert S.is_excluded_component("sim_work")
    assert S.is_excluded_component(".fpga_stash")   # dot-dir
    assert S.is_excluded_component(".git")
    assert S.is_excluded_component("input")          # vendor staging
    assert S.is_excluded_component("oracle_run")
    assert S.is_excluded_component("build")
    # authoritative dirs are NOT excluded
    assert not S.is_excluded_component("rtl")
    assert not S.is_excluded_component("stage1")
    # the sim family matches `sim` / `sim_*` ONLY — an unrelated dir like
    # 'simba'/'similar' is NOT over-excluded.
    assert not S.is_excluded_component("simba")
    assert not S.is_excluded_component("similar")


def test_authoritative_rtl_files_filters(tmp_path):
    # authoritative
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.sv").write_text("module dut(input a); endmodule\n")
    # excluded: vendor staging, sim intermediates, dot-dir, oracle_run
    for rel in ("input/vendor_rtl/ip.sv",
                "phase2/stage1/sim_full_stack/_sv2v_converted.v",
                ".fpga_stash/ibex_rtl_conv.v",
                "oracle_run/_sv2v_converted.v",
                "build/synth/netlist.v"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("module x(input b); endmodule\n")
    found = {f.name for f in S.authoritative_rtl_files(tmp_path)}
    assert found == {"dut.sv"}


def test_cdc_uses_shared_scope(tmp_path):
    # the cdc gate's file finder must apply the same exclusions
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.sv").write_text("module dut(input a); endmodule\n")
    inter = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    inter.mkdir(parents=True)
    (inter / "flat.v").write_text("module flat(input b); endmodule\n")
    names = {f.name for f in CDC.find_rtl_files(tmp_path)}
    assert "dut.sv" in names
    assert "flat.v" not in names  # the #545 leak is closed
