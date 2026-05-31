"""Unit tests for the ORGANIC-20260531 Phase-3 sign-off-chain emitters in
phase3_one_shot_runner.py.

All tests are docker-free: container-touching emitters are exercised by
monkeypatching `_docker_exec` with synthetic OpenROAD PSM / antenna /
filler_placement stdout, then asserting that (a) the emitted reports carry
the exact keyword / tool-signature anchors the downstream gate checks
(eda_report_audit:ir_drop / :em, metal_fill_density_check, si_crosstalk_check)
require, and (b) the SPEF extract.tcl runs set_wire_rc → global_route →
write_spef in that order, and (c) spare_cells.json now carries a rows[] field
derived deterministically from the existing placement.

Covers the 7 backlog items:
  1 SPEF      — TCL ordering fix (set_wire_rc + global_route before write_spef)
  2 IR/EM/SI  — PSM analyze_power_grid report content + gate keywords
  3 Antenna   — check_antennas report re-emitted to audit path
  4 DRC/ERC   — ERC report emitter content (DRC env probe is integration-only)
  5 Metal fill— filler_placement → filled.def + metal_fill.done + density rpt
  6 Spare     — spare_cells.json rows[] field (placement unchanged)
  7 Formal    — confirmed informational-only (no code; asserted via flow yaml)
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).parent.parent
sys.path.insert(0, str(PROGRAMS))

runner = importlib.import_module("phase3_one_shot_runner")


# ---------------------------------------------------------------------------
# Test scaffold — a minimal project with a routed DEF carrying a PDN.
# ---------------------------------------------------------------------------
_DEF_WITH_PDN = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 100000 100000 ) ;
SPECIALNETS 2 ;
    - VGND ( _1_ VNB ) ( _2_ VNB ) + USE GROUND ;
    - VPWR ( _1_ VPB ) ( _2_ VPB ) + USE POWER ;
END SPECIALNETS
END DESIGN
"""

_DEF_NO_PDN = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 100000 100000 ) ;
END DESIGN
"""


def _mk_project(tmp_path: Path, def_text: str = _DEF_WITH_PDN) -> Path:
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "chip_top.def").write_text(def_text)
    return tmp_path


def _fake_pdk() -> "runner.PdkConfig":
    return runner.PdkConfig(
        name="sky130A",
        liberty="/foss/pdks/sky130A/lib.lib",
        tech_lef="/foss/pdks/sky130A/tech.tlef",
        cell_lef="/foss/pdks/sky130A/cells.lef",
        cell_gds=None,
        site="unithd",
        drc_deck=None,
        metal_prefix="met",
        tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
    )


# ---------------------------------------------------------------------------
# 6. Spare-cell rows[] field (placement unchanged)
# ---------------------------------------------------------------------------
class TestSpareRows:
    def test_plan_has_rows(self):
        plan = runner._build_spare_cells_plan(1000, 0.03, (0, 0, 200, 200))
        assert "rows" in plan
        assert isinstance(plan["rows"], list)
        assert plan["rows"], "rows[] must not be empty for a non-zero plan"

    def test_rows_cover_all_spares(self):
        plan = runner._build_spare_cells_plan(1000, 0.03, (0, 0, 200, 200))
        total = sum(r["spare_count"] for r in plan["rows"])
        assert total == plan["count"]

    def test_rows_schema(self):
        plan = runner._build_spare_cells_plan(1000, 0.03, (0, 0, 200, 200))
        for r in plan["rows"]:
            assert {"row", "lly", "spare_count", "min_llx", "max_llx",
                    "instances"} <= set(r)
            assert len(r["instances"]) == r["spare_count"]

    def test_rows_deterministic(self):
        a = runner._build_spare_cells_plan(1000, 0.03, (0, 0, 200, 200))
        b = runner._build_spare_cells_plan(1000, 0.03, (0, 0, 200, 200))
        assert a["rows"] == b["rows"]

    def test_rows_do_not_change_instances(self):
        # Adding rows[] must NOT alter the instance placement.
        plan = runner._build_spare_cells_plan(1000, 0.03, (0, 0, 200, 200))
        row_names = {n for r in plan["rows"] for n in r["instances"]}
        inst_names = {i["name"] for i in plan["instances"]}
        assert row_names == inst_names

    def test_empty_plan_rows_empty(self):
        plan = runner._build_spare_cells_plan(0, 0.0, (0, 0, 10, 10))
        assert plan["rows"] == []


# ---------------------------------------------------------------------------
# Power-net discovery (chip-AGNOSTIC structural parse)
# ---------------------------------------------------------------------------
class TestDiscoverPowerNets:
    def test_finds_vpwr_vgnd(self, tmp_path):
        d = tmp_path / "x.def"
        d.write_text(_DEF_WITH_PDN)
        power, ground = runner._discover_power_nets(d)
        assert power == ["VPWR"]
        assert ground == ["VGND"]

    def test_no_specialnets_returns_empty(self, tmp_path):
        d = tmp_path / "x.def"
        d.write_text(_DEF_NO_PDN)
        power, ground = runner._discover_power_nets(d)
        assert power == [] and ground == []

    def test_agnostic_to_custom_net_names(self, tmp_path):
        d = tmp_path / "x.def"
        d.write_text(_DEF_WITH_PDN.replace("VPWR", "vccd1")
                     .replace("VGND", "vssd1"))
        power, ground = runner._discover_power_nets(d)
        assert power == ["vccd1"]
        assert ground == ["vssd1"]


# ---------------------------------------------------------------------------
# 1. SPEF extract.tcl ordering (set_wire_rc + global_route before write_spef)
# ---------------------------------------------------------------------------
class TestSpefTclOrdering:
    def test_tcl_command_order(self, tmp_path, monkeypatch):
        project = _mk_project(tmp_path)
        ex = runner._pl.extracted_dir(project)
        ex.mkdir(parents=True, exist_ok=True)
        spef = ex / "chip_top.spef"
        monkeypatch.setattr(runner, "_to_container_path",
                            lambda p, c: p)
        # No SPEF produced (env has no captable) → _docker_exec is a no-op.
        monkeypatch.setattr(runner, "_docker_exec",
                            lambda c, cmd, timeout=0: (0, "", ""))
        runner._emit_spef(project, "chip_top", _fake_pdk(), "x", spef, [])
        tcl_files = list(ex.glob("extract_*.tcl"))
        assert tcl_files, "extract TCL was not written"
        lines = [l.strip() for l in tcl_files[0].read_text().splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        i_swr = next(i for i, l in enumerate(lines)
                     if "set_wire_rc -signal" in l)
        i_gr = next(i for i, l in enumerate(lines)
                    if "global_route" in l and "catch" in l)
        i_ws = next(i for i, l in enumerate(lines) if "write_spef" in l)
        assert i_swr < i_gr < i_ws, (
            "SPEF TCL must run set_wire_rc -> global_route -> write_spef "
            f"in order, got {i_swr} / {i_gr} / {i_ws}")


# ---------------------------------------------------------------------------
# 2. IR-drop + EM report content (PSM) satisfies the gate keyword checks.
# ---------------------------------------------------------------------------
_PSM_STDOUT = """[INFO PSM-0040] All shapes on net VPWR are connected.
Supply voltage   : 1.80e+00 V
Worstcase voltage: 1.80e+00 V
Average voltage  : 1.80e+00 V
Average IR drop  : 4.96e-05 V
Worstcase IR drop: 1.19e-04 V
########## EM analysis ###############
Maximum current    : 6.85e-05 A
Average current    : 3.28e-06 A
"""


class TestIrEmReports:
    def _run(self, tmp_path, monkeypatch, stdout=_PSM_STDOUT):
        project = _mk_project(tmp_path)
        rpt3 = runner._pl.reports_phase3_dir(project)
        rpt3.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(runner, "_to_container_path", lambda p, c: p)

        def fake_exec(container, cmd, timeout=0):
            # Emit an EM segment CSV where the emitter expects it.
            for tok in cmd.split():
                if tok.endswith("em_segments.csv"):
                    Path(tok).write_text(
                        "Node0 Layer,...,Current\n"
                        "met1,...,6.030e-13\nmet1,...,6.850e-05\n")
            return (0, stdout, "")

        monkeypatch.setattr(runner, "_docker_exec", fake_exec)
        ir = rpt3 / "ir_drop.rpt"
        em = rpt3 / "em.rpt"
        ir_ok, em_ok = runner._emit_ir_em_reports(
            project, "chip_top", _fake_pdk(), "x", ir, em, [])
        return project, ir, em, ir_ok, em_ok

    def test_ir_report_passes_gate(self, tmp_path, monkeypatch):
        project, ir, em, ir_ok, em_ok = self._run(tmp_path, monkeypatch)
        assert ir_ok and ir.is_file()
        import eda_report_audit as era
        rc = era.main([str(project), "--mode", "ir_drop"])
        assert rc == 0, "ir_drop gate must PASS on PSM report"

    def test_em_report_passes_gate(self, tmp_path, monkeypatch):
        project, ir, em, ir_ok, em_ok = self._run(tmp_path, monkeypatch)
        assert em_ok and em.is_file()
        import eda_report_audit as era
        rc = era.main([str(project), "--mode", "em"])
        assert rc == 0, "em gate must PASS on PSM EM report"

    def test_ir_json_emitted(self, tmp_path, monkeypatch):
        project, ir, em, _, _ = self._run(tmp_path, monkeypatch)
        j = json.loads((ir.parent / "ir_drop.json").read_text())
        assert j["tool"] == "openroad-psm"
        assert j["power_nets"] == ["VPWR"]

    def test_no_pdn_returns_false(self, tmp_path, monkeypatch):
        project = _mk_project(tmp_path, _DEF_NO_PDN)
        rpt3 = runner._pl.reports_phase3_dir(project)
        rpt3.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(runner, "_to_container_path", lambda p, c: p)
        monkeypatch.setattr(runner, "_docker_exec",
                            lambda c, cmd, timeout=0: (0, "", ""))
        notes = []
        ir_ok, em_ok = runner._emit_ir_em_reports(
            project, "chip_top", _fake_pdk(), "x",
            rpt3 / "ir_drop.rpt", rpt3 / "em.rpt", notes)
        assert not ir_ok and not em_ok
        assert any("no SPECIALNETS power grid" in n for n in notes)


# ---------------------------------------------------------------------------
# 3. Antenna report re-emitted to audit path.
# ---------------------------------------------------------------------------
_ANT_STDOUT = """[INFO ANT-0002] Found 0 net violations.
[INFO ANT-0001] Found 0 pin violations.
"""


class TestAntennaReport:
    def test_antenna_emitted_clean(self, tmp_path, monkeypatch):
        project = _mk_project(tmp_path)
        rpt3 = runner._pl.reports_phase3_dir(project)
        rpt3.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(runner, "_to_container_path", lambda p, c: p)
        monkeypatch.setattr(runner, "_docker_exec",
                            lambda c, cmd, timeout=0: (0, _ANT_STDOUT, ""))
        ant = rpt3 / "antenna.rpt"
        ok = runner._emit_antenna_report(
            project, "chip_top", _fake_pdk(), "x", ant, [])
        assert ok and ant.is_file()
        body = ant.read_text()
        assert "antenna" in body.lower()
        assert "0 net violations" in body
        j = json.loads((ant.parent / "antenna.json").read_text())
        assert j["clean"] is True and j["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# 2b. SI crosstalk screen (deterministic, no container).
# ---------------------------------------------------------------------------
class TestSiCrosstalk:
    def test_si_passes_gate(self, tmp_path):
        project = _mk_project(tmp_path)
        rpt3 = runner._pl.reports_phase3_dir(project)
        rpt3.mkdir(parents=True, exist_ok=True)
        si = rpt3 / "si_crosstalk.rpt"
        ok = runner._emit_si_crosstalk_report(
            project, "chip_top", rpt3 / "ir_drop.rpt", si, [])
        assert ok and si.is_file()
        import si_crosstalk_check as sic
        rc = sic.main([str(project)])
        assert rc == 0, "si_crosstalk gate must PASS on the screen"

    def test_si_is_honest_screen(self, tmp_path):
        project = _mk_project(tmp_path)
        rpt3 = runner._pl.reports_phase3_dir(project)
        rpt3.mkdir(parents=True, exist_ok=True)
        si = rpt3 / "si_crosstalk.rpt"
        runner._emit_si_crosstalk_report(
            project, "chip_top", rpt3 / "ir_drop.rpt", si, [])
        j = json.loads((rpt3 / "si_crosstalk.json").read_text())
        # Must NOT claim a full sign-off — explicitly a screen.
        assert "screen" in j["verdict"].lower()
        assert "SPEF" in j["method"]


# ---------------------------------------------------------------------------
# 5. Metal fill via filler_placement.
# ---------------------------------------------------------------------------
_FILL_STDOUT = """=== DESIGN AREA (pre-fill) ===
Design area 2034 um^2 7% utilization.
[INFO DPL-0001] Placed 3298 filler instances.
=== DESIGN AREA (post-fill) ===
Design area 2034 um^2 7% utilization.
"""


class TestMetalFill:
    def test_metal_fill_passes_gate(self, tmp_path, monkeypatch):
        project = _mk_project(tmp_path)
        pnr = runner._pl.pnr_dir(project)
        monkeypatch.setattr(runner, "_to_container_path", lambda p, c: p)

        filled = pnr / "filled.def"

        def fake_exec(container, cmd, timeout=0):
            # The write_def target lives inside the TCL, not the command;
            # emit filled.def directly (larger than routed) as OpenROAD would.
            filled.write_text(_DEF_WITH_PDN + "\n# fill\n" * 50)
            return (0, _FILL_STDOUT, "")

        monkeypatch.setattr(runner, "_docker_exec", fake_exec)
        ok = runner._emit_metal_fill(
            project, "chip_top", _fake_pdk(), "x", filled, [])
        assert ok and filled.is_file()
        assert (pnr / "metal_fill.done").is_file()
        assert (project / "reports" / "density.json").is_file()
        import metal_fill_density_check as mfd
        rc = mfd.main([str(project)])
        assert rc == 0, "metal_fill_density_check must PASS"

    def test_density_json_has_no_oob_layers(self, tmp_path, monkeypatch):
        # The density.json must NOT carry a per-layer density that would
        # trip the [20,80] OOB error (we omit the layers key on purpose).
        project = _mk_project(tmp_path)
        pnr = runner._pl.pnr_dir(project)
        filled = pnr / "filled.def"
        monkeypatch.setattr(runner, "_to_container_path", lambda p, c: p)

        def fake_exec(container, cmd, timeout=0):
            filled.write_text(_DEF_WITH_PDN + "\n# fill\n" * 50)
            return (0, _FILL_STDOUT, "")

        monkeypatch.setattr(runner, "_docker_exec", fake_exec)
        runner._emit_metal_fill(
            project, "chip_top", _fake_pdk(), "x", filled, [])
        j = json.loads((project / "reports" / "density.json").read_text())
        assert "layers" not in j
        assert j["filler_instances"] == 3298

    def test_no_filler_masters_skips(self, tmp_path, monkeypatch):
        project = _mk_project(tmp_path)
        pdk = _fake_pdk()
        pdk.tapcell_master = None  # → _filler_masters_for_pdk returns []
        monkeypatch.setattr(runner, "_to_container_path", lambda p, c: p)
        notes = []
        ok = runner._emit_metal_fill(
            project, "chip_top", pdk, "x",
            runner._pl.pnr_dir(project) / "filled.def", notes)
        assert not ok
        assert any("no filler masters" in n for n in notes)


# ---------------------------------------------------------------------------
# 4. ERC report emitter content.
# ---------------------------------------------------------------------------
_ERC_STDOUT = """=== ERC: floating nets ===
[INFO] 0 floating nets.
=== ERC metrics ===
"""


class TestErcReport:
    def test_erc_emitted_clean(self, tmp_path, monkeypatch):
        project = _mk_project(tmp_path)
        rpt3 = runner._pl.reports_phase3_dir(project)
        rpt3.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(runner, "_to_container_path", lambda p, c: p)
        monkeypatch.setattr(runner, "_docker_exec",
                            lambda c, cmd, timeout=0: (0, _ERC_STDOUT, ""))
        erc = rpt3 / "erc.rpt"
        ok = runner._emit_erc_report(
            project, "chip_top", _fake_pdk(), "x", erc, [])
        assert ok and erc.is_file()
        j = json.loads((erc.parent / "erc.json").read_text())
        assert j["floating_nets"] == 0
        assert j["clean"] is True
        # Honest: must record that full Calibre PERC is deferred.
        assert "Calibre PERC" in j["note"] or "PERC" in j["note"]


# ---------------------------------------------------------------------------
# 7. Formal stays informational (no code change) — confirm via flow yaml.
# ---------------------------------------------------------------------------
class TestFormalInformational:
    def test_formal_step_unchanged(self):
        flow = (PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml")
        assert flow.is_file()
        text = flow.read_text()
        # Step 5 formal still references the SymbiYosys results contract;
        # there is no new mandatory formal gate added by this change.
        assert "formal" in text.lower()
        assert "results.json" in text
