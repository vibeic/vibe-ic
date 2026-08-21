#!/usr/bin/env python3
"""Step 29 — the SDF gate-level sim must be reachable on the OPEN PDKs.

Defect (HIGH, dimension 6 (skip discipline)): on the real completed digital run
(spm / ihp-sg13g2) `post_layout_sim_check` FAILed with
`NO_RESULTS: Neither results.log nor pass.flag found in sim_postlayout/`, yet
the step was audited as `SKIPPED-CONDITION` under
`capability_flag: cap:sdf_annotated_gatelevel_sim` — a gap that
`flow_compliance_check._PLATFORM_CAPABILITY_GAPS` itself records as CLOSED
("29 SDF -> iverilog $sdf_annotate gate sim").

Two mechanical causes, both in the PRODUCER, both covered here:

1. `_INST_RE` anchored the cell type to an UPPERCASE first letter — one
   library's naming convention (`DFFHQD1`, `INVD1`). Every open PDK names its
   cells in lowercase (`sg13g2_nand2_1`, `sky130_fd_sc_hd__inv_1`,
   `gf180mcu_fd_sc_mcu7t5v0__nand2_1`), so the used-cell set came back EMPTY:
   the model lookup scored 0 against every candidate and the physical-cell stub
   emitter emitted nothing.
2. `find_pdk_verilog` looked ONLY at `<project>/input/pdk/verilog/`, which the
   open-PDK flow never stages — while the very same container runs Step 11 ATPG
   off `/foss/pdks/.../verilog/*.v`. `resolve_cell_models` now falls back to
   those in-container models, host staging still first.

Direction-1 guards (must hold on BOTH trees) pin the commercial/host-staged
path: an uppercase netlist yields the SAME used-cell set as before, and a
host-staged model still wins.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sdf_gate_sim as sg  # noqa: E402


# A routed netlist in the shape OpenROAD writes for an open PDK: lowercase
# cell types, `_NNN_` instance names, fillers/spares with empty port lists.
OSS_NETLIST = """\
module spm (clk, reset, x, y, p);
 input clk;
 input reset;
 input [31:0] x;
 input y;
 output p;
 wire _001_;
 wire _002_;
 sg13g2_nand2_1 _100_ (.A(_001_), .B(_002_), .Y(p));
 sg13g2_inv_1 _101_ (.A(x[0]), .Y(_001_));
 sg13g2_dfrbp_1 _102_ (.CLK(clk), .D(y), .RESET_B(reset), .Q(_002_));
 sg13g2_fill_1 FILLER_10_378 ();
 sg13g2_decap_4 DECAP_3_12 ();
 sg13g2_inv_1 spare_inverter_0 ();
 assign p = _001_;
endmodule
"""

# Commercial / NDA-PDK shape: uppercase cell types. Behaviour here must not move.
COMMERCIAL_NETLIST = """\
module spm (clk, reset, x, y, p);
 input clk;
 input reset;
 input [31:0] x;
 input y;
 output p;
 wire n1;
 NAND2D1 U1 (.A1(n1), .A2(y), .ZN(p));
 INVD1 U2 (.I(x[0]), .ZN(n1));
 DFFHQD1 U3 (.CP(clk), .D(y), .Q(n1));
 FILL1 FILLER_0 ();
endmodule
"""

SG13G2_MODEL = """\
`timescale 1ns/1ps
module sg13g2_nand2_1 (A, B, Y);
 input A, B; output Y;
 specify (A => Y) = (0.1, 0.1); endspecify
endmodule
module sg13g2_inv_1 (A, Y); input A; output Y; endmodule
module sg13g2_dfrbp_1 (CLK, D, RESET_B, Q); input CLK, D, RESET_B; output Q; endmodule
"""


# ── discriminators: these FAIL on the pre-fix program ──────────────────────

def test_oss_lowercase_cells_are_detected():
    """The root cause: an uppercase-anchored instance regex saw ZERO cells."""
    used, ports = sg.netlist_cells_and_ports(OSS_NETLIST, "spm")
    assert "sg13g2_nand2_1" in used
    assert "sg13g2_dfrbp_1" in used
    assert "sg13g2_fill_1" in used
    assert len(used) == 5, sorted(used)
    # ...and no Verilog keyword leaked in as a phantom "cell"
    assert not (used & {"module", "assign", "input", "output", "wire"})
    # port detection is unaffected
    assert ports["x"]["width"] == 32 and ports["p"]["dir"] == "output"


def test_oss_physical_cell_stubs_are_emitted():
    """Fillers/decaps the PDK model does not define must be stubbed, else
    iverilog dies with 'Unknown module type'."""
    used, _ = sg.netlist_cells_and_ports(OSS_NETLIST, "spm")
    stubs = sg.missing_empty_cell_stubs(OSS_NETLIST, used, SG13G2_MODEL)
    assert stubs == ["sg13g2_decap_4", "sg13g2_fill_1"], stubs
    # a cell the PDK DOES model is never stubbed out (that would be a
    # functional hole: an empty module in place of a real inverter)
    assert "sg13g2_inv_1" not in stubs


def test_container_pdk_fallback_resolves_when_host_staging_absent(tmp_path,
                                                                  monkeypatch):
    """No <project>/input/pdk/verilog/ (the open-PDK reality) -> the model is
    read from the container instead of returning None."""
    used, _ = sg.netlist_cells_and_ports(OSS_NETLIST, "spm")
    assert not (tmp_path / "input/pdk/verilog").exists()

    seen = []

    class _R:
        returncode = 0

        def __init__(self, out):
            self.stdout = out
            self.stderr = ""

    def fake_docker(container, cmd, timeout=600):
        seen.append((container, cmd))
        return _R(SG13G2_MODEL)

    monkeypatch.setattr(sg, "_docker", fake_docker)
    models = sg.resolve_cell_models(tmp_path, used, "vibeic-eda-test")
    assert models is not None, "container PDK model was not resolved"
    assert models.source == "container_pdk"
    assert models.pdk_id == "ihp-sg13g2"
    # both files, UDP primitives FIRST (iverilog needs them before the cells)
    assert models.paths[0].endswith("sg13g2_udp.v")
    assert models.paths[1].endswith("sg13g2_stdcell.v")
    assert models.arg == " ".join(models.paths)
    assert all(c == "vibeic-eda-test" for c, _ in seen)


def test_container_fallback_refuses_a_model_for_a_different_library(tmp_path,
                                                                    monkeypatch):
    """A stale table entry must not hand iverilog the wrong library: the model
    has to define at least one cell the netlist actually instantiates."""
    used, _ = sg.netlist_cells_and_ports(OSS_NETLIST, "spm")

    class _R:
        returncode = 0
        stderr = ""
        stdout = "module some_other_lib__inv_1 (A, Y); endmodule\n"

    monkeypatch.setattr(sg, "_docker", lambda *a, **k: _R())
    assert sg.resolve_cell_models(tmp_path, used, "c") is None


def test_container_fallback_is_all_or_nothing_on_read_failure(tmp_path,
                                                              monkeypatch):
    """A partially-read model would produce WRONG stubs (a real cell replaced
    by an empty module), so any unreadable file aborts the resolution."""
    used, _ = sg.netlist_cells_and_ports(OSS_NETLIST, "spm")
    calls = {"n": 0}

    class _R:
        def __init__(self, rc, out):
            self.returncode = rc
            self.stdout = out
            self.stderr = ""

    def fake_docker(container, cmd, timeout=600):
        calls["n"] += 1
        return _R(0, SG13G2_MODEL) if calls["n"] == 1 else _R(1, "")

    monkeypatch.setattr(sg, "_docker", fake_docker)
    assert sg.resolve_cell_models(tmp_path, used, "c") is None


def test_unknown_library_still_reports_no_model(tmp_path, monkeypatch):
    """Not a silent success: an unrecognised library must still resolve to None
    so the caller discloses a REAL capability gap."""
    used, _ = sg.netlist_cells_and_ports(COMMERCIAL_NETLIST, "spm")
    monkeypatch.setattr(sg, "_docker",
                        lambda *a, **k: pytest.fail("must not shell out"))
    assert sg.resolve_cell_models(tmp_path, used, "c") is None


# ── the shared PDK table, and its anti-divergence guard ────────────────────

def test_detect_pdk_id_is_prefix_keyed_and_pure():
    import pdk_cell_models as pcm
    assert pcm.detect_pdk_id({"sg13g2_nand2_1", "sg13g2_inv_1"}) == "ihp-sg13g2"
    assert pcm.detect_pdk_id({"sky130_fd_sc_hd__inv_1"}) == "sky130"
    assert pcm.detect_pdk_id({"gf180mcu_fd_sc_mcu7t5v0__nand2_1"}) == "gf180"
    assert pcm.detect_pdk_id({"DFFHQD1", "INVD1"}) is None
    assert pcm.detect_pdk_id(set()) is None
    assert pcm.container_model_paths("nope") == []


def test_pdk_model_table_agrees_with_fault_atpg_run():
    """The two consumers of "where is this PDK's Verilog model" must not drift.
    fault_atpg_run (Step 11 ATPG) has always had the right paths; Step 29 had
    none, which is how this defect happened."""
    import pdk_cell_models as pcm
    try:
        import fault_atpg_run as fa
    except Exception as exc:                       # pragma: no cover
        pytest.skip(f"fault_atpg_run not importable here: {exc}")
    for pdk_id in pcm.known_pdk_ids():
        cfg = fa.PDK_CONFIG.get(pdk_id)
        assert cfg, f"fault_atpg_run has no PDK_CONFIG entry for {pdk_id}"
        assert str(cfg["cell_model"]).split() == pcm.container_model_paths(pdk_id), (
            f"{pdk_id}: sdf_gate_sim and fault_atpg_run disagree on the "
            f"in-container cell model path")


# ── direction-1 guards: must PASS on BOTH trees ───────────────────────────

def guard_commercial_uppercase_cells_unchanged():
    used, ports = sg.netlist_cells_and_ports(COMMERCIAL_NETLIST, "spm")
    assert used == {"NAND2D1", "INVD1", "DFFHQD1", "FILL1"}, sorted(used)
    assert ports["x"]["width"] == 32
    assert sg.missing_empty_cell_stubs(
        COMMERCIAL_NETLIST, used,
        "module INVD1 (I, ZN); endmodule\n") == ["FILL1"]


def guard_host_staged_model_still_wins(tmp_path):
    """The commercial-PDK path stages a model into the run dir; it must keep
    priority over anything in the container."""
    vdir = tmp_path / "input/pdk/verilog"
    vdir.mkdir(parents=True)
    (vdir / "nda_cells.v").write_text(
        "module NAND2D1 (A1, A2, ZN); specify endspecify endmodule\n"
        "module INVD1 (I, ZN); endmodule\n")
    used, _ = sg.netlist_cells_and_ports(COMMERCIAL_NETLIST, "spm")
    host = sg.find_pdk_verilog(tmp_path, used)
    assert host is not None and host.name == "nda_cells.v"


def guard_host_staged_model_prefers_the_one_with_specify(tmp_path):
    vdir = tmp_path / "input/pdk/verilog"
    vdir.mkdir(parents=True)
    (vdir / "a_no_timing.v").write_text("module INVD1 (I, ZN); endmodule\n")
    (vdir / "b_timing.v").write_text(
        "module INVD1 (I, ZN); specify (I => ZN) = (1,1); endspecify endmodule\n")
    used, _ = sg.netlist_cells_and_ports(COMMERCIAL_NETLIST, "spm")
    assert sg.find_pdk_verilog(tmp_path, used).name == "b_timing.v"


def guard_no_model_anywhere_still_returns_none(tmp_path):
    used, _ = sg.netlist_cells_and_ports(COMMERCIAL_NETLIST, "spm")
    assert sg.find_pdk_verilog(tmp_path, used) is None


test_guard_commercial_uppercase_cells_unchanged = guard_commercial_uppercase_cells_unchanged
test_guard_host_staged_model_still_wins = guard_host_staged_model_still_wins
test_guard_host_staged_model_prefers_the_one_with_specify = \
    guard_host_staged_model_prefers_the_one_with_specify
test_guard_no_model_anywhere_still_returns_none = guard_no_model_anywhere_still_returns_none
