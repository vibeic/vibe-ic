from __future__ import annotations

import shutil
from pathlib import Path
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

from synth_handoff_netlist_check import _project_path_resolver

PRE_FIX_BASE = "59cd75606885b71ca7d11bbe34baf2541671be68"






























def test_backend_handoff_resolves_only_receipt_project_namespace(tmp_path):
    """A staged backend may rebase receipt project paths, never read ambient originals."""
    staged = tmp_path / "staged"
    folder = staged / "phase3/librelane/02-yosys-synthesis"
    folder.mkdir(parents=True)
    (staged / "phase3/stage1/rtl").mkdir(parents=True)
    source = staged / "phase3/librelane/02-yosys-synthesis/spm.nl.v"
    source.write_text("module spm; endmodule\n")
    original = Path("/original/project/phase3/librelane/02-yosys-synthesis/spm.nl.v")
    resolver = _project_path_resolver(
        staged, folder, {"nl": str(original)})
    assert resolver(original) == source.resolve()
    with pytest.raises(ValueError, match="absent"):
        resolver(Path("/original/project/phase3/librelane/02-yosys-synthesis/missing.v"))
    # A PDK path is external and stays external; it is subsequently checked
    # by the receipt's PDK mount validator rather than mapped to the project.
    assert resolver(Path("/pdk/gf180mcuD/config.tcl")) == Path("/pdk/gf180mcuD/config.tcl")












def test_cdc_native_citation_reader_accepts_carried_proof_and_rejects_changed_log(tmp_path):
    """The real CDC reader accepts the carried native proof set only as-is."""
    from programs.tests import test_t91_step3_cdc_netlist_front_end as cdc_fixture
    import _cdc_netlist as cdc_netlist
    import librelane_contract as ll

    source = cdc_fixture._project(
        tmp_path, "native_source", cdc_fixture.FIX / "multi_clock_sync.v",
        "librelane", cdc_fixture.FIX / "multi_clock_sync.json")
    isolated = tmp_path / "isolated_consumer"
    shutil.copytree(source / "phase2/stage1/rtl", isolated / "phase2/stage1/rtl")
    (isolated / "phase3").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / "phase3/librelane_switch.json",
                    isolated / "phase3/librelane_switch.json")
    for rel in (
        "reports/phase2/cdc/netlist.json",
        "reports/phase2/cdc/netlist_front_end.json",
        "reports/phase2/cdc/netlist.yosys.log",
        "reports/phase2/cdc/netlist.raw.json",
        "reports/phase2/cdc/netlist.normalize.yosys.log",
    ):
        target = isolated / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / rel, target)

    netlist = cdc_netlist.load(isolated / "reports/phase2/cdc/netlist.json")
    receipt = cdc_netlist.require_binding(
        isolated, isolated / "reports/phase2/cdc/netlist.json", netlist)
    assert receipt["producer"]["step"] == "Yosys.JsonHeader"
    assert receipt["sha256"]["netlist.yosys.log"] == ll.digest(
        isolated / "reports/phase2/cdc/netlist.yosys.log")
    assert receipt["sha256"]["netlist.raw.json"] == ll.digest(
        isolated / "reports/phase2/cdc/netlist.raw.json")
    assert receipt["sha256"]["netlist.normalize.yosys.log"] == ll.digest(
        isolated / "reports/phase2/cdc/netlist.normalize.yosys.log")

    log = isolated / "reports/phase2/cdc/netlist.yosys.log"
    log.write_bytes(log.read_bytes() + b"\nchanged-log-control\n")
    with pytest.raises(cdc_netlist.Refusal, match="CDC_NETLIST_STALE"):
        cdc_netlist.require_binding(
            isolated, isolated / "reports/phase2/cdc/netlist.json", netlist)










_STEP12_POST_DFT = "phase2/stage2/synth/post_dft_netlist.v"
_STEP12_NO_DFT = {
    "dft_present": False, "scan_chains": [], "bist_mbist": [], "jtag_tap": None,
}
























# Production API controls for BR2-001..006; fixtures never qualify native EDA.


























































# R4 controls extend the reviewed test module without changing earlier cases.














# Current canonical backend receipt projection; software controls only.




    # No Controller, observed process, sealed issuance, adoption or native tool
    # exists in this fixture. Projection alone does not authorize any of them.
