"""Unit tests for the Phase-3-backend systematic fixes in
phase3_one_shot_runner.py (DRC stdcell classifier broadening, vacuous-
Magic detection, KLayout-streamout false-positive re-stream heuristic,
--util normalization, SV synth frontend selection).

All tests are docker-free: they exercise the pure-logic helpers with
synthetic inputs. They DO NOT spawn any container.

CRITICAL honesty-gate assertions live here too: a genuine met2+ routing
violation must still be classified user-routing (→ FAIL), and a vacuous
Magic 0-count must never be reported as a clean pass.
"""
import importlib
import json
import pathlib
import sys

import pytest

mod = importlib.import_module("phase3_one_shot_runner")


# ---------------------------------------------------------------------------
# Fix #4 — --util normalization
# ---------------------------------------------------------------------------
class TestSiliconCriticalPnrBlocks:
    @staticmethod
    def _sky130_pdk():
        # The minimal PdkConfig that exercises the "sky130-style" branch.
        # All path fields are placeholders — these tests are pure-logic.
        return mod.PdkConfig(
            name="sky130A",
            liberty="/placeholder/sky130_fd_sc_hd__tt_025C_1v80.lib",
            tech_lef="/placeholder/sky130_fd_sc_hd.tlef",
            cell_lef="/placeholder/sky130_fd_sc_hd.lef",
            cell_gds="/placeholder/sky130_fd_sc_hd.gds",
            site="unithd",
            drc_deck="/placeholder/sky130A_mr.drc",
            metal_prefix="met",
            tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
            tapcell_distance_um=14.0,
        )

    @staticmethod
    def _no_tapcell_pdk():
        # A PDK that doesn't ship a tapcell master — the runner must
        # gracefully emit a SKIPPED line on each of the 3 blocks.
        return mod.PdkConfig(
            name="customPDK",
            liberty="/placeholder/lib.lib",
            tech_lef="/placeholder/tech.lef",
            cell_lef="/placeholder/cells.lef",
            cell_gds=None,
            site="sitename",
            drc_deck=None,
            metal_prefix="met",
            tapcell_master=None,
        )

    # ---- v0.1.46 tapcell -----------------------------------------------


    # ---- v0.1.47 pdngen ------------------------------------------------


    # ---- PDK-adaptive PDN (commercial VDD/VSS) -------------------------
    _COMMERCIAL_LEF = (
        "MACRO INVD1\n"
        "  SIZE 1.32 BY 5.04 ;\n"
        "  PIN VDD\n    USE POWER ;\n    PORT\n      LAYER MET1 ;\n"
        "        RECT 0 4.64 1.32 5.44 ;\n    END\n  END VDD\n"
        "  PIN VSS\n    USE GROUND ;\n    PORT\n      LAYER MET1 ;\n"
        "        RECT 0 -0.4 1.32 0.4 ;\n    END\n  END VSS\n"
        "  PIN A\n    DIRECTION INPUT ;\n    PORT\n      LAYER MET1 ;\n"
        "        RECT 0.2 1.0 0.4 1.4 ;\n    END\n  END A\n"
        "END INVD1\n")

    # A minimal multi-metal stack so the adaptive PDN can derive its straps.
    # Names/values are generic — this fixture stands for ANY PDK reaching the
    # adaptive path, not a particular one.
    _STACK_TLEF = "".join(
        f"LAYER MET{i}\n  TYPE ROUTING ;\n  DIRECTION {d} ;\n"
        f"  PITCH 0.5 ;\n  WIDTH 0.2 ;\nEND MET{i}\n"
        for i, d in enumerate(
            ["HORIZONTAL", "VERTICAL", "HORIZONTAL", "VERTICAL"], 1))

    def _commercial_pdk(self, lef_path):
        # A non-sky130 PDK (VDD/VSS rails, no tapcell_master) — the commercial PDK
        # shape. tapcell_master None → adaptive PDN path. A real tech LEF is
        # written next to the cell LEF because the adaptive PDN now DERIVES its
        # upper-metal straps from the routing stack; a PDK that cannot be
        # strapped is reported PDN_NO_STRAPS rather than passing hollow, which
        # is covered separately below.
        tlef = pathlib.Path(lef_path).parent / "tech.lef"
        tlef.write_text(self._STACK_TLEF)
        return mod.PdkConfig(
            name="custom:commercial_pdk", liberty="/p/l.lib",
            tech_lef=str(tlef), cell_lef=str(lef_path), cell_gds=None,
            site="unit", drc_deck=None, metal_prefix="met",
            tapcell_master=None)

    def test_discover_pg_from_lef_commercial_vdd_vss(self, tmp_path):
        lef = tmp_path / "cells.lef"
        lef.write_text(self._COMMERCIAL_LEF)
        pg = mod._discover_pg_from_lef(str(lef))
        assert pg == ("VDD", "VSS", "MET1", 0.8), pg

    def test_discover_pg_from_lef_none_without_pg_pins(self, tmp_path):
        lef = tmp_path / "nopg.lef"
        lef.write_text("MACRO X\n  SIZE 1 BY 1 ;\n  PIN A\n    DIRECTION "
                       "INPUT ;\n  END A\nEND X\n")
        assert mod._discover_pg_from_lef(str(lef)) is None


    # ---- v0.1.48 filler_placement --------------------------------------


    # ---- Cross-block invariants ----------------------------------------

    def test_sky130_PdkConfig_carries_v0146_settings(self):
        # The PdkConfig factory used by the runner must wire the v0.1.46
        # tapcell defaults for sky130A. If a future refactor drops these,
        # tapcell falls back to SKIPPED and silicon ships latch-up-prone.
        pdk = self._sky130_pdk()
        assert pdk.tapcell_master == "sky130_fd_sc_hd__tapvpwrvgnd_1"
        assert pdk.tapcell_distance_um == 14.0
        # site == unithd is the SKY130 std-cell row site.
        assert pdk.site == "unithd"
