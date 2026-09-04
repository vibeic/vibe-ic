"""Post-layout LEC must prove the routed physical wrapper hierarchy."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as R  # noqa: E402
import lec_post_layout_check as L  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path):
    gold = tmp_path / "phase2/stage2/synth/post_dft_netlist.v"
    gold.parent.mkdir(parents=True)
    gold.write_text(
        "module core(input a, output y); assign y = ~a; endmodule\n")
    wrapper = tmp_path / "phase3/stage3/pnr/chip_top_io.v"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text(
        "module chip_top(input a, output y); core u_core(.a(a), .y(y)); "
        "endmodule\n")
    report = tmp_path / "reports/phase3/io_pad_chip_top.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({
        "verdict": "WROTE", "chip_top_module": "chip_top",
        "core_module": "core",
        "chip_top_verilog": "phase3/stage3/pnr/chip_top_io.v",
    }))
    return gold, wrapper, report


def test_physical_top_gold_is_exact_core_plus_recorded_wrapper(tmp_path):
    gold, wrapper, report = _fixture(tmp_path)
    combined, provenance = R._lec_physical_top_gold(
        tmp_path, "core", "chip_top", gold, tmp_path / "reports/phase3")
    assert combined.read_text() == gold.read_text() + "\n" + wrapper.read_text()
    assert provenance["logical_top"] == "core"
    assert provenance["physical_top"] == "chip_top"
    assert provenance["core_gold_sha256"] == _sha(gold)
    assert provenance["wrapper_sha256"] == _sha(wrapper)
    assert provenance["wrapper_record_sha256"] == _sha(report)
    assert provenance["combined_gold_sha256"] == _sha(combined)


def test_wrapper_identity_mismatch_refuses_instead_of_guessing(tmp_path):
    gold, _wrapper, report = _fixture(tmp_path)
    doc = json.loads(report.read_text())
    doc["core_module"] = "some_other_core"
    report.write_text(json.dumps(doc))
    with pytest.raises(RuntimeError, match="identity does not match"):
        R._lec_physical_top_gold(
            tmp_path, "core", "chip_top", gold, tmp_path / "reports/phase3")


def test_no_wrapper_is_added_when_logical_and_physical_top_are_equal(tmp_path):
    gold = tmp_path / "core.v"
    gold.write_text("module core(input a, output y); assign y=a; endmodule\n")
    selected, provenance = R._lec_physical_top_gold(
        tmp_path, "core", "core", gold, tmp_path / "reports/phase3")
    assert selected == gold
    assert provenance["wrapper"] is None
    assert provenance["combined_gold"] is None


def test_exact_netlist_stub_precedes_distribution_blackboxes_in_emitter():
    source = Path(R.__file__).read_text()
    emit = source[source.index("def _emit_lec_post_layout("):]
    emit = emit[:emit.index("# --- POST-LAYOUT EQUIVALENCE")]
    assert "blackbox = [stub_c] + blackbox" in emit
    assert "blackbox = blackbox + [stub_c]" not in emit


def test_gold_only_supply_ports_are_symmetric_and_functional_ports_stay(tmp_path):
    gate = tmp_path / "gate.v"
    gold = gate.parent / "gold.v"
    gate.write_text("module chip_top(input clk, output y); endmodule\n")
    gold.write_text(
        "module chip_top(input clk, input VDD, input VSS, input debug, "
        "output y); endmodule\n")
    assert R._gold_only_supply_ports(gate, gold, "chip_top") == ["VDD", "VSS"]
    assert R._gate_only_supply_ports(gate, gold, "chip_top") == []
    assert R._module_port_names(gold.read_text(), "chip_top") == [
        "clk", "VDD", "VSS", "debug", "y"]


def _aux_normalization_fixture(tmp_path: Path):
    gate = tmp_path / "phase3/stage3/pnr/core_pnr.v"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text(
        "module chip_top(input a, output y); "
        "PAD u_pad(.PAD(a), .Y(y)); endmodule\n")
    final_def = gate.parent / "core.def"
    final_def.write_text("""VERSION 5.8 ;
DESIGN chip_top ;
SPECIALNETS 2 ;
- VDD ( u_pad OE ) + USE POWER ;
- VSS ( u_pad PU ) + USE GROUND ;
END SPECIALNETS
END DESIGN
""")
    report = tmp_path / "reports/phase3/io_pad_chip_top.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "verdict": "WROTE", "chip_top_module": "chip_top",
        "power_pad_plan": {
            "domain_topology": "single_domain",
            "power_net": "VDD", "ground_net": "VSS"},
        "aux_pin_rail_connections": [
            {"instance": "u_pad", "pin": "OE", "rail": "VDD", "level": 1},
            {"instance": "u_pad", "pin": "PU", "rail": "VSS", "level": 0},
        ],
    }))
    return gate, final_def, report


def test_aux_control_restoration_requires_record_and_exact_def_specialnet(tmp_path):
    gate, final_def, _report = _aux_normalization_fixture(tmp_path)
    out, provenance, constants = R._lec_restore_aux_connections(
        tmp_path, "chip_top", gate, final_def,
        tmp_path / "reports/phase3", L)
    assert ".OE(VDD)" in out.read_text() and ".PU(VSS)" in out.read_text()
    assert provenance["connections"] == 2
    assert provenance["method"] == (
        "producer-declared and final-DEF-SPECIALNET-proven")
    assert constants == {"VDD": 1, "VSS": 0}
    assert R._def_specialnet_iterm_map(final_def.read_text()) == {
        ("u_pad", "OE"): "VDD", ("u_pad", "PU"): "VSS"}


def test_aux_control_restoration_refuses_old_record_and_wrong_def_rail(tmp_path):
    gate, final_def, report = _aux_normalization_fixture(tmp_path)
    doc = json.loads(report.read_text())
    doc.pop("aux_pin_rail_connections")
    report.write_text(json.dumps(doc))
    with pytest.raises(RuntimeError, match="old tie decisions"):
        R._lec_restore_aux_connections(
            tmp_path, "chip_top", gate, final_def,
            tmp_path / "reports/phase3", L)

    _gate, final_def, report = _aux_normalization_fixture(tmp_path)
    final_def.write_text(final_def.read_text().replace(
        "- VDD ( u_pad OE )", "- VSS2 ( u_pad OE )"))
    with pytest.raises(RuntimeError, match="does not prove u_pad/OE"):
        R._lec_restore_aux_connections(
            tmp_path, "chip_top", gate, final_def,
            tmp_path / "reports/phase3", L)


@pytest.mark.parametrize("functional", [True, False])
def test_gold_supply_strip_is_confined_to_gold_half(functional):
    ys = L.build_yosys_equiv_script(
        "gold.v", "gate.v", "lib.lib", "chip_top",
        strip_gold_ports=["VDD", "VSS"], functional_lib=functional)
    gold_half, gate_half = ys.split("design -stash gold", 1)
    assert "delete chip_top/w:VDD" in gold_half
    assert "delete chip_top/w:VSS" in gold_half
    assert "delete chip_top/w:VDD" not in gate_half
    assert "delete chip_top/w:VSS" not in gate_half
