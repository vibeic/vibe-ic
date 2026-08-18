"""Unit tests for `asap7_finfet_lvs.py` (B1/#174 ASAP7 device-level LVS).

The extraction + NetlistComparer core needs KLayout's `pya` and the staged ASAP7
GDS + CDL golden (only inside vibeic-eda), so it is NOT exercised on a CI host.
This file pins the pure-Python, deterministic helpers that run WITHOUT `pya`:
  * `split_cdl_subckts`   — CDL text -> {cell: subckt-block};
  * `subckt_device_count` — M-card count (0 = physical-only cell);
  * `_net_name`           — net-name sanitisation + UNCONN counter;
  * `ASAP7_LAYERS`        — the FEOL layer-map contract (incl. the GATE_CUT unlock);
  * `_require_pya`        — the disclosed exit-3 fallback (only when pya is absent);
and the pdk_registry.json ASAP7 device-LVS WIRING added alongside the program
(cdl_netlist / spice_models / klayout_lvs_tech / device_lvs_verified).

Chip- and PDK-AGNOSTIC: the layer map is data, the CDL parse is generic SPICE.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

mod = importlib.import_module("asap7_finfet_lvs")


class _FakeNet:
    def __init__(self, name=None, expanded="0"):
        self.name = name
        self._expanded = expanded

    def expanded_name(self):
        return self._expanded


# --------------------------------------------------------------- split_cdl_subckts
_CDL = """* header comment
.SUBCKT INVx1_ASAP7_75t_R A VDD VSS Y
MM0 Y A VSS VSS nmos_rvt w=81.0n l=20n nfin=3
MM1 Y A VDD VDD pmos_rvt w=81.0n l=20n nfin=3
.ENDS
.SUBCKT FILLER_ASAP7_75t_R VDD VSS
.ENDS
.subckt nand2x1_asap7_75t_R A B VDD VSS Y
MM0 Y A n1 VSS nmos_rvt w=81n l=20n nfin=3
MM1 n1 B VSS VSS nmos_rvt w=81n l=20n nfin=3
MM2 Y A VDD VDD pmos_rvt w=81n l=20n nfin=3
MM3 Y B VDD VDD pmos_rvt w=81n l=20n nfin=3
.ends
"""


class TestSplitCdl:
    def test_splits_from_file(self, tmp_path):
        p = tmp_path / "x.cdl"
        p.write_text(_CDL)
        b = mod.split_cdl_subckts(str(p))
        assert set(b) == {"INVx1_ASAP7_75t_R", "FILLER_ASAP7_75t_R",
                          "nand2x1_asap7_75t_R"}
        # each block is bounded by its own .SUBCKT / .ENDS (case-insensitive)
        assert b["INVx1_ASAP7_75t_R"].strip().startswith(".SUBCKT INVx1_ASAP7_75t_R")
        assert b["INVx1_ASAP7_75t_R"].strip().lower().endswith(".ends")
        assert "nand2x1" in b["nand2x1_asap7_75t_R"]

    def test_device_count(self, tmp_path):
        p = tmp_path / "x.cdl"
        p.write_text(_CDL)
        b = mod.split_cdl_subckts(str(p))
        assert mod.subckt_device_count(b["INVx1_ASAP7_75t_R"]) == 2
        assert mod.subckt_device_count(b["nand2x1_asap7_75t_R"]) == 4
        # a physical-only cell (filler/tap/decap) has zero transistor cards
        assert mod.subckt_device_count(b["FILLER_ASAP7_75t_R"]) == 0


# --------------------------------------------------------------- _net_name
class TestNetName:
    def test_none_yields_unconn_and_increments(self):
        c = [0]
        assert mod._net_name(None, c) == "UNCONN_1"
        assert mod._net_name(None, c) == "UNCONN_2"
        assert c[0] == 2

    def test_named_net_is_used_verbatim(self):
        assert mod._net_name(_FakeNet("VDD"), [0]) == "VDD"

    def test_unnamed_net_falls_back_to_expanded(self):
        assert mod._net_name(_FakeNet(None, "7"), [0]) == "n7"


# --------------------------------------------------------------- layer-map contract
class TestLayerMap:
    def test_asap7_feol_layer_keys_present(self):
        lm = mod.ASAP7_LAYERS
        # the device-recognition + GATE_CUT-unlock + MOL/routing keys the
        # extractor relies on (each is (layer, datatype))
        for k in ("gate", "gate_cut", "active", "nselect", "pselect",
                  "lig", "lisd", "v0", "m1", "m1txt"):
            assert k in lm, f"ASAP7_LAYERS missing {k!r}"
            assert isinstance(lm[k], tuple) and len(lm[k]) == 2

    def test_gate_cut_is_the_documented_unlock_layer(self):
        # GATE_CUT (10/0) severs the drawn poly — the ASAP7-specific unlock.
        assert mod.ASAP7_LAYERS["gate_cut"] == (10, 0)
        assert mod.ASAP7_LAYERS["gate"] == (7, 0)
        assert mod.ASAP7_LAYERS["active"] == (11, 0)


# --------------------------------------------------------------- disclosed exit-3
class TestRequirePya:
    def test_exit3_when_pya_absent(self, monkeypatch):
        try:
            import pya  # noqa: F401
            pytest.skip("pya present in this environment; exit-3 path not taken")
        except Exception:
            pass
        with pytest.raises(SystemExit) as ei:
            mod._require_pya()
        assert ei.value.code == 3


# --------------------------------------------------------------- registry wiring
class TestRegistryWiring:
    def _asap7(self):
        reg = json.loads((PROGRAMS / "pdk_registry.json").read_text())
        return next(p for p in reg["pdks"] if p["name"] == "asap7")

    def test_asap7_declares_device_lvs_source_of_truth(self):
        a = self._asap7()
        # the staged golden CDL + FinFET models + KLayout LVS tech, mirrored in
        # the image at libs.tech/{cdl,hspice,klayout/lvs}
        assert a["cdl_netlist"] == "libs.tech/cdl/asap7sc7p5t_28_R.cdl"
        assert a["spice_models"].startswith("libs.tech/hspice/")
        assert a["klayout_lvs_tech"].startswith("libs.tech/klayout/lvs/")
        assert a["device_lvs_program"] == "asap7_finfet_lvs.py"

    def test_asap7_device_lvs_verified_is_honest(self):
        a = self._asap7()
        v = a["device_lvs_verified"]
        # the recorded number must be internally consistent + proven-negative
        assert 0 < v["match"] <= v["compared"]
        assert abs(v["match"] / v["compared"] - v["match_rate"]) < 0.01
        assert v["proven_negative"] is True

    def test_asap7_lvs_deck_stays_null_not_a_netgen_deck(self):
        # the ASAP7 device-LVS is the geometric KLayout path, NOT a netgen setup
        # TCL — lvs_deck stays null so no consumer mistakes it for one.
        assert self._asap7()["lvs_deck"] is None
