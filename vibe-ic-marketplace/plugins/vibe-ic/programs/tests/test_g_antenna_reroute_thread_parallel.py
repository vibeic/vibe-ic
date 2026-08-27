"""G-ANTENNA-REROUTE — parallelize the OpenROAD PnR session so the antenna-diode
reroute loop (and every routing step) is not single-threaded (chip/PDK-AGNOSTIC).

PROVE-FIRST floor (subservient RISC-V SoC on the commercial PDK, measured
in-container against `routed_preantenna.def` + `post_hold.def`):
  * OpenROAD DEFAULTS TO 1 THREAD (`ord::thread_count` == 1). The emitted pnr.tcl
    never called `set_thread_count`, so the WHOLE route — and EVERY antenna-diode
    reroute round — ran SINGLE-THREADED on a 32-core host.
  * Single-threaded: main detailed_route ~858 s + ~394 s PER antenna reroute
    round → 858 s + 2-4 rounds blew the 20-min per-step cap before GDS.
  * The reroute was ALREADY dirty-net incremental — its 0th detailed-route
    iteration starts at ~986 violations (~1/3 of a from-scratch route's ~2845),
    NOT a full re-route. The wall was purely the single-threaded execution.
  * At 8 threads the identical flow: main route 211 s, each reroute round 74 s,
    the escalating repair loop converges antenna-clean (0 net / 0 pin) AND
    DRC-clean (detailed_route_num_drvs == 0) in ~473 s — a routed-clean design
    reaches GDS well inside budget. (Bounding the reroute with `-droute_end_iter`
    was REJECTED: it left 85 DRC violations — a DRC-dirty signoff route.)

Fix: emit `set_thread_count N` as the FIRST command of the PnR Tcl (and the repair
reroute Tcl) so OpenROAD parallelizes global_route / detailed_route / the antenna
repair loop / CTS / resize. N = host CPUs (VIBEIC_OPENROAD_THREADS overrides).
These tests pin the helper + the emitted-Tcl placement (synthetic; a blind run
auto-covers it). NEVER skips or waives antenna repair.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")
_STUB = 'proc unknown {args} { return "" }\n'


# ── the thread-count helper ─────────────────────────────────────────────────

def test_thread_count_default_is_host_cpus(monkeypatch):
    monkeypatch.delenv("VIBEIC_OPENROAD_THREADS", raising=False)
    n = R._openroad_thread_count()
    assert isinstance(n, int) and n >= 1
    assert n == (os.cpu_count() or 4)


def test_thread_count_env_override_int(monkeypatch):
    monkeypatch.setenv("VIBEIC_OPENROAD_THREADS", "7")
    assert R._openroad_thread_count() == 7


def test_thread_count_env_override_max(monkeypatch):
    monkeypatch.setenv("VIBEIC_OPENROAD_THREADS", "max")
    assert R._openroad_thread_count() == (os.cpu_count() or 4)


@pytest.mark.parametrize("bad", ["abc", "0", "-4", "", "  "])
def test_thread_count_env_invalid_falls_back(monkeypatch, bad):
    monkeypatch.setenv("VIBEIC_OPENROAD_THREADS", bad)
    assert R._openroad_thread_count() == (os.cpu_count() or 4)


# ── fixture: the COMPLETE pnr.tcl exactly as step_pnr composes it ────────────

def _pdk() -> "R.PdkConfig":
    return R.PdkConfig(
        name="fixture_pdk",
        liberty="/pdk/lib.lib", tech_lef="/pdk/tech.lef",
        cell_lef="/pdk/cells.lef", cell_gds=None,
        site="unithd", drc_deck=None, metal_prefix="met",
        tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
        antenna_diode_cell="sky130_fd_sc_hd__diode_2",
        pnr_exclude_cell_file="/pdk/drc_exclude.cells",
    )


def _full_pnr_tcl(tmp_path: Path, threads: int) -> str:
    pdk = _pdk()
    out_dir_c = str(tmp_path / "out")
    (tmp_path / "out").mkdir(exist_ok=True)
    plan = R._build_spare_cells_plan(
        2000, 0.02, (10, 10, 290, 290), liberty_path="", container="")
    return R._build_pnr_tcl_text(
        tech_lef_c="/pdk/tech.lef", cell_lef_c="/pdk/cells.lef",
        macro_lefs_tcl="", liberty_c="/pdk/lib.lib",
        macro_libs_tcl="", netlist_c="/work/netlist.v", top="chip_top",
        sdc_c="/work/chip_top.sdc",
        dont_use_block=R._dont_use_tcl(pdk),
        metal_prefix=pdk.metal_prefix, die_w=300, die_h=300,
        core_pad=10, core_w=280, core_h=280, site=pdk.site,
        out_dir_c=out_dir_c,
        tapcell_block=R._build_tapcell_tcl(pdk),
        pdn_block=R._build_pdn_tcl(pdk), util=0.45,
        spare_protection_tcl=R._build_spare_protection_tcl(plan, out_dir_c),
        spare_postfix_tcl=R._build_spare_postfix_tcl(
            plan, tie_lo_cell="sky130_fd_sc_hd__conb_1", tie_lo_pin="LO"),
        clk_buf="sky130_fd_sc_hd__clkbuf_4",
        clk_buf_root="sky130_fd_sc_hd__clkbuf_16",
        routing_constraint_tcl="",
        pg_cleanup_block=R._pg_net_cleanup_tcl(),
        spef_repair_block="",
        antenna_repair_block=R._antenna_repair_tcl(pdk),
        filler_block="",
        openroad_threads=threads,
    )


# ── the emitted-Tcl placement (governs the whole route + antenna reroute) ────

def test_pnr_tcl_emits_set_thread_count(tmp_path):
    tcl = _full_pnr_tcl(tmp_path, threads=13)
    assert "set_thread_count 13" in tcl


def test_set_thread_count_precedes_all_routing(tmp_path):
    """MUST lead the session: set_thread_count comes BEFORE global_route,
    detailed_route AND the antenna repair loop, so every one runs threaded."""
    tcl = _full_pnr_tcl(tmp_path, threads=9)
    i_tc = tcl.index("set_thread_count 9")
    assert i_tc < tcl.index("global_route")
    assert i_tc < tcl.index("detailed_route")
    assert i_tc < tcl.index("repair_antennas")
    # first non-empty line of the script (governs the whole session)
    first = next(ln for ln in tcl.splitlines() if ln.strip())
    assert first.strip() == "set_thread_count 9"


def test_legacy_zero_threads_omits_line(tmp_path):
    """openroad_threads<=0 (only the legacy test-default) emits NOTHING —
    byte-identical to the pre-fix template."""
    tcl = _full_pnr_tcl(tmp_path, threads=0)
    assert "set_thread_count" not in tcl


def test_step_pnr_wires_a_positive_thread_count(tmp_path):
    """The production call path (_openroad_thread_count) yields a positive int,
    so the emitted pnr.tcl actually parallelizes (not the legacy 0)."""
    assert R._openroad_thread_count() >= 1
    tcl = _full_pnr_tcl(tmp_path, threads=R._openroad_thread_count())
    assert "set_thread_count" in tcl


@needs_tclsh
def test_full_pnr_tcl_with_threads_still_parses(tmp_path):
    """The set_thread_count line must not break the Tcl parse/eval (OpenROAD is
    a Tcl interpreter): the full template reaches its end."""
    full = _full_pnr_tcl(tmp_path, threads=16).replace(
        "\nexit\n", "\nputs PNR_TCL_END\n")
    script = tmp_path / "pnr.tcl"
    script.write_text(_STUB + full)
    res = subprocess.run([tclsh, str(script)],
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    assert "PNR_TCL_END" in res.stdout


# ── the repair reroute Tcl is parallelized too (it runs its own detailed_route) ──

def test_repair_reroute_tcl_parallelized_before_detailed_route(tmp_path):
    repair = R._build_postroute_timing_repair_tcl(
        "chip_top", "/pdk/tech.lef", "/pdk/cells.lef", "/pdk/lib.lib",
        "/work/pnr", "/work/repair", "met")
    assert "set_thread_count" in repair
    assert repair.index("set_thread_count") < repair.index("detailed_route")
