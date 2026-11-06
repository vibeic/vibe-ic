"""Native analog results retain engineering limits without authenticity stamps."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import analog_a3_netlist_emit as a3
import analog_a3_netlist_gen_check as netlist_check
import analog_a4_corner_sweep_check as a4
import analog_a5_layout_emit as a5
import analog_a6_block_pv_check as a6
import analog_a6_native_pv as pv
import analog_a7_post_layout_emit as a7
import analog_a7_post_layout_resim_check as resim
from _pad_ring import parse_spice_subckts


@pytest.fixture
def circuit(tmp_path):
    block = "cell"
    directory = tmp_path / "phase3/analog" / block
    directory.mkdir(parents=True)
    topology = {"block": block, "ports": ["d", "g", "s", "b"],
                "devices": [{"name": "M1", "role": "nmos",
                             "nets": ["d", "g", "s", "b"]}]}
    (directory / "topology.json").write_text(json.dumps(topology))
    (directory / "cell.sp").write_text(
        ".lib /unused/electrical.lib tt\n.options scale=1u\n"
        ".subckt cell d g s b\nxM1 d g s b nfet w=0.5u l=2u ng=4 m=3\n.ends cell\n")
    (directory / "cell.gds").write_bytes(b"boundary-only-layout")
    (directory / "layout_provenance.json").write_text(json.dumps({
        "result": "REFUSED", "netlist_content_sha256": "older-netlist"}))
    (directory / "lvs_provenance.json").write_text("invalid old metadata")
    return tmp_path, directory


def test_cdl_conversion_preserves_geometry_without_provenance(circuit):
    project, directory = circuit
    source = (directory / "cell.sp").read_bytes()
    report = a3.emit_lvs_view(project, "cell")
    (directory / "lvs_provenance.json").unlink()
    view = a3.validate_lvs_view(project, "cell")
    ports, body = parse_spice_subckts(view.read_text(), preserve_parameters=True)["cell"]
    assert ports == ["d", "g", "s", "b"]
    assert body == [["MM1", "d", "g", "s", "b", "nfet", "w=0.5u", "l=2u", "ng=4", "m=3"]]
    assert ".options scale=1u" in view.read_text()
    assert ".lib " not in view.read_text()
    assert (directory / "cell.sp").read_bytes() == source
    assert report["subcircuits"]["cell"]["body"] == body
    assert not any("sha256" in key for key in report)


@pytest.mark.parametrize("text", [
    ".subckt other a b\nR1 a b 1k\n.ends other\n",
    ".subckt cell a b\nR1 a b 1k\n.ends cell\n.subckt cell a b\nR2 a b 2k\n.ends cell\n",
])
def test_cdl_parser_still_rejects_missing_and_duplicate_blocks(circuit, text):
    project, directory = circuit
    (directory / "cell.lvs.cdl").write_text(text)
    with pytest.raises(ValueError):
        a3.validate_lvs_view(project, "cell")


def test_topology_port_mismatch_still_refuses_conversion(circuit):
    project, directory = circuit
    source = directory / "cell.sp"
    source.write_text(source.read_text().replace(".subckt cell d g s b", ".subckt cell g d s b"))
    with pytest.raises(ValueError, match="LVS_SOURCE_PORTS_DIFFER_FROM_TOPOLOGY"):
        a3.emit_lvs_view(project, "cell")


@pytest.mark.parametrize("violations,verdict,expected", [
    (0, "MATCH", "PASS"), (7, "MATCH", "FAIL"),
    (8, "MATCH", "FAIL"), (0, "MISMATCH", "FAIL"),
])
def test_native_boundary_runs_despite_changed_metadata(circuit, violations, verdict, expected):
    project, directory = circuit
    commands = []

    def drc(deck, layout, block, container):
        commands.append(("drc", deck, layout))
        return violations, {"method": "native-boundary", "rules_pass": 1}

    def lvs(layout, reference, block, container):
        commands.append(("lvs", layout, reference))
        assert "w=0.5u l=2u ng=4 m=3" in Path(reference).read_text()
        (directory / "lvs_provenance.json").write_text("metadata changed while tool ran")
        return verdict, {"method": "native-boundary", "source_devices": 1, "layout_devices": 1}

    result = pv.run_block_pv(project, "cell", {"drc_deck": "native.rule", "lvs_deck": "native.lvs"},
                             container="host", drc_runner=drc, lvs_runner=lvs,
                             second_engine_runner=lambda *args: (None, "outside boundary control"))
    assert [command[0] for command in commands] == ["drc", "lvs"]
    assert result["lvs"]["executed"] is True
    assert result["lvs"]["verdict"] == verdict.lower()
    assert result["drc"]["violations"] == violations
    assert a6._check_block(project, "cell")[0] == expected
    report = json.loads((directory / "comp.json").read_text())
    assert report["source_devices"] == report["layout_devices"] == 1
    assert "layout_sha256" not in report and "layout_netlist_identity" not in report


def test_missing_native_results_remain_missing(circuit):
    project, _ = circuit
    result = pv.run_block_pv(project, "cell", {"drc_deck": "native.rule", "lvs_deck": "native.lvs"},
                             container="host", drc_runner=lambda *args: (None, {"reason": "missing tool"}),
                             lvs_runner=lambda *args: (None, {"reason": "missing tool"}))
    assert result["ran"] is False
    assert result["lvs"]["executed"] is False
    assert a6._check_block(project, "cell")[0] == "FAIL"


@pytest.mark.parametrize("violations,expected", [(0, "PASS"), (7, "FAIL"), (8, "FAIL")])
def test_native_count_reader_ignores_hash_stamps(circuit, violations, expected):
    project, directory = circuit
    (directory / "drc.report").write_text(f"violations: {violations}\nlayout_sha256: {'0' * 64}\n")
    (directory / "comp.json").write_text(json.dumps({"result": "match", "layout_sha256": "older"}))
    (directory / "a6_librelane_drc.json").write_text(json.dumps({"gds_sha256": "older"}))
    assert a6._check_block(project, "cell")[0] == expected


def _native_width_rules():
    configuration = json.dumps({"drc_rules": {
        "Mn_e": 0.3, "Mn_e_w": 1.5, "Mn_e_cr": 2,
        "Mn_f": 0.5, "Mn_f_w": 3, "Mn_f_cr": 4}})
    source = "mets_lay = [metal1_drw, metal2_drw]\n"
    for suffix in ("e", "f"):
        stem, key = "mn_" + suffix, "Mn_" + suffix
        source += (f"{stem}_value = drc_rules['{key}'].to_f\n"
                   f"{stem}_width = drc_rules['{key}_w'].to_f / 2\n"
                   f"{stem}_length = drc_rules['{key}_cr'].to_f\n"
                   f"{stem}_l1 = met_lay.sized(-1 * {stem}_width.um).sized({stem}_width.um)\n"
                   f"met_lay.sep({stem}_l1, {stem}_value.um, projection_limits({stem}_length.um + 0.001.um, nil))\n")
    return configuration, source


@pytest.mark.parametrize("stamp", [None, "mismatched"])
def test_native_spacing_text_needs_no_transport_digest(stamp):
    configuration, source = _native_width_rules()

    class Stage:
        def sh(self, command, **kwargs):
            payload = {"tech_default.json": {"text": configuration},
                       "metaln.drc": {"text": source}}
            if stamp:
                for value in payload.values():
                    value["sha256"] = stamp
            return 0, json.dumps(payload), ""

    result = a5._read_width_prl_rules(Stage(), "/pdk/libs.tech/klayout/tech/drc/main.drc")
    assert result["status"] == "READ"
    assert result["rules"][1] == result["rules"][2]
    assert result["rules"][1][0] == {"source_rule": "Mn_e", "spacing_um": 0.3,
                                    "width_gt_um": 1.5, "parallel_gt_um": 2}
    with pytest.raises(ValueError, match="predicate"):
        a5._parse_width_prl_rules(configuration, source.replace("+ 0.001.um", "+ 0.01.um"))


@pytest.mark.parametrize("status,expected", [("PASS", "PASS"), ("FAIL", "FAIL")])
def test_corner_limits_survive_unrelated_hash_metadata(circuit, status, expected):
    project, directory = circuit
    (directory / "corner_results.json").write_text(json.dumps({
        "design_content": "structure_and_geometry", "netlist_sha256": "older",
        "netlist_source": "missing-old-input.sp", "netlist_testbench_sha256": "older",
        "corners": [{"process": "TT", "simulator_run": True}],
        "spec_results": [{"spec": "gain", "status": status}]}))
    assert a4._check_block(project, "cell")[0] == expected


@pytest.mark.parametrize("post,expected", [(110.0, "PASS"), (110.001, "FAIL")])
def test_post_layout_original_ten_percent_limit(circuit, post, expected):
    project, directory = circuit
    (directory / "corner_results.json").write_text(json.dumps({
        "design_content": "structure_and_geometry", "corners": [{"simulator_run": True}]}))
    (directory / "a7_post_layout.json").write_text("unreadable old receipt")
    (directory / "pre_vs_post.json").write_text(json.dumps({
        "pre": {"gain": 100}, "post": {"gain": post},
        "_provenance": {"layout_sha256": "older", "record": "old-record.json"}}))
    assert resim._check_block(project, "cell", resim.DEFAULT_MAX_DELTA_PCT)[0] == expected


@pytest.mark.skipif(shutil.which("klayout") is None, reason="requires native KLayout")
@pytest.mark.parametrize("violations", [0, 7, 8])
def test_native_klayout_drc_keeps_zero_limit(circuit, violations):
    import pya

    project, directory = circuit
    layout = pya.Layout()
    layout.dbu = 0.001
    cell = layout.create_cell("cell")
    metal = layout.layer(1, 0)
    for index in range(violations or 1):
        width = 100 if violations else 400
        cell.shapes(metal).insert(pya.Box(index * 1000, 0, index * 1000 + width, 1000))
    layout.write(str(directory / "cell.gds"))
    deck = directory / "native.drc"
    deck.write_text('source($input, $topcell)\nreport("width", $report)\ninput(1, 0).width(0.2.um).output("min_width")\n')
    count, metadata = pv._klayout_drc_runner(str(deck), str(directory / "cell.gds"),
                                            "cell", "host", directory / "native.lyrdb")
    assert metadata.get("rc") == 0, metadata
    assert count == violations
    pv._write_drc_report(directory, "cell", count, metadata)
    (directory / "comp.json").write_text('{"result": "match"}')
    assert a6._check_block(project, "cell")[0] == ("PASS" if violations == 0 else "FAIL")


@pytest.mark.skipif(shutil.which("ngspice") is None, reason="requires native ngspice")
def test_native_ngspice_runs_without_stamps(tmp_path):
    deck = tmp_path / "divider.sp"
    deck.write_text("Native divider\nV1 in 0 2\nR1 in out 1k\nR2 out 0 1k\n"
                    ".control\nop\nprint v(out)\nquit\n.endc\n.end\n")
    result = subprocess.run(["ngspice", "-b", str(deck)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "v(out) = 1.000000e+00" in result.stdout.lower()


def test_rcx_command_boundary_is_reached_without_layout_identity(circuit, tmp_path, monkeypatch):
    import _designs_root as designs
    import analog_real_corner_sweep as sweep
    import librelane_contract as contract

    project, directory = circuit
    tech = tmp_path / "pdkroot/neutral/libs.tech/magic/neutral.tech"
    tech.parent.mkdir(parents=True)
    tech.write_text("tech\nformat 35\nneutral\nend\n")
    (directory / "layout_provenance.json").write_text(json.dumps({
        "result": "OLD", "netlist_content_sha256": "older",
        "pdk_sources": {"magic_tech": str(tech)}}))
    (directory / "tb_cell.sp").write_text(".include cell.sp\n.op\n.end\n")
    commands = []
    monkeypatch.setattr(designs, "resolve_host_root", lambda *args: str(project))
    monkeypatch.setattr(sweep, "_container_path", lambda *args: str(args[-1]))
    monkeypatch.setattr(sweep, "_run_ngspice", lambda *args, **kwargs: (
        True, {"gain": 1.0}, "native boundary fixture", {}))

    def resolve(project, image, source, target, **kwargs):
        target.write_text(source.read_text())
        return target

    def run(project, image, steps, **kwargs):
        commands.extend(step[0] for step in steps)
        raise contract.Refusal("LL_IMAGE_INCAPABLE", "RCX unavailable in boundary control")

    monkeypatch.setattr(contract, "resolve_step_config", resolve)
    monkeypatch.setattr(contract, "run_chain", run)
    assert a7.run(project, "cell", "host", "boundary", styles=["ngspice()"]) == 69
    assert commands == [a7.RCX_STEP]
    report = json.loads((directory / "a7_post_layout.json").read_text())
    assert report["rule"] == "LL_IMAGE_INCAPABLE"
    assert "layout_netlist_identity" not in report and "layout_sha256" not in report


@pytest.mark.skipif(shutil.which("klayout") is None, reason="requires native KLayout")
@pytest.mark.parametrize("resistance,expected", [(1000, "match"), (2000, "mismatch")])
def test_native_klayout_netlist_comparison_preserves_mismatch(circuit, tmp_path, resistance, expected):
    import pya

    project, directory = circuit
    (directory / "topology.json").unlink()
    source = directory / "cell.sp"
    source.write_text(".subckt cell a b\nR1 a b 1000\n.ends cell\n")
    extracted = tmp_path / "extracted.sp"
    extracted.write_text(f".subckt cell a b\nR1 a b {resistance}\n.ends cell\n")

    def compare(layout, reference, block, container):
        native_source, native_extracted = pya.Netlist(), pya.Netlist()
        native_source.read(reference, pya.NetlistSpiceReader())
        native_extracted.read(str(extracted), pya.NetlistSpiceReader())
        matched = pya.NetlistComparer().compare(native_extracted, native_source)
        return ("MATCH" if matched else "MISMATCH"), {"method": "klayout_native_netlist_compare"}

    result = pv.run_block_pv(project, "cell", {"lvs_deck": "native.lvs"}, container="host",
                             lvs_runner=compare)
    assert result["lvs"]["executed"] is True
    assert result["lvs"]["verdict"] == expected
    (directory / "drc.report").write_text("violations: 0\n")
    assert a6._check_block(project, "cell")[0] == ("PASS" if expected == "match" else "FAIL")


def test_source_netlist_reader_ignores_result_stamps(circuit):
    project, directory = circuit
    source = directory / "cell.sp"
    source.write_text("* _provenance: topology_ir=phase3/analog/cell/topology.json "
                      f"sha256={'0' * 64} content_sha256={'1' * 64}\n" + source.read_text())
    (directory / "netlist_provenance.json").write_text(json.dumps({
        "provenance_ref": "old-run/missing.sp@000000000000",
        "_provenance": {"design_content": "structure_and_geometry"}}))
    assert netlist_check._check_block(project, "cell")[0] == "PASS"


def test_rcx_inventory_still_rejects_real_geometry_loss(circuit):
    _, directory = circuit
    source = (directory / "cell.sp").read_text()
    original = a7.device_instances(source, "cell")
    changed = a7.device_instances(source.replace("w=0.5u", "w=0.25u"), "cell")
    assert a7.device_inventory(original, original, set())["result"] == "MATCH"
    assert a7.device_inventory(original, changed, set())["result"] != "MATCH"
