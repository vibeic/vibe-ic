import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import test_pad_ring as pads
import _seal_ring_margin as margin
import _tapeout_declaration as declaration


SEAL_DECK = '''# Copyright 2025 IHP PDK Authors. Apache-2.0.
unless PRECHECK_DRC
  seal_b_lays = [metal1_drw, metal2_drw, metal3_drw, metal4_drw, metal5_drw, topmetal1_drw, topmetal2_drw,
                   activ_drw, psd_drw]
  seal_b_names = %w[metal1 metal2 metal3 metal4 metal5 topmetal1 topmetal2 activ psd]
  seal_b_value = drc_rules['Seal_b'].to_f
  seal_b_names.zip(seal_b_lays).each do |seal_b_lay, lay|
    seal_b_l1 = lay.and(edgeseal_drw)
    seal_b_l = activ_drw.sep(seal_b_l1, seal_b_value.um, euclidian)
    seal_b_l.output("Seal.b_#{seal_b_lay}",
                  "6.10. Seal.b_#{seal_b_lay} : Min. Activ space to EdgeSeal-#{seal_b_lay} is #{seal_b_value} um")
    seal_b_l1.forget
    seal_b_l.forget
  end
end
'''


def _shell(command):
    proc = subprocess.run(["sh", "-c", command], capture_output=True, text=True)
    return proc.returncode, proc.stdout


def _seal_technology(pdk):
    deck = pdk / "libs.tech/klayout/drc/rule_decks/6_10_sealring.drc"
    deck.parent.mkdir(parents=True, exist_ok=True)
    deck.write_text(SEAL_DECK)
    table = pdk / "libs.tech/klayout/tech/neutral_tech_default.json"
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(json.dumps({"drc_rules": {"Seal_b": 4.9}}, indent=2))
    return deck, table


def _project(tmp_path, *, spacing=5.5, placement="outside", deck=True,
             overrides=None):
    cfg = pads._config(PAD_EDGE_SPACING=spacing,
                       PAD_FILLERS=["pad_fill196", "pad_fill9", "pad_fill1"])
    cfg.update(overrides or {})
    root = pads._project(tmp_path, config=cfg, site_w=0.5,
                         floorplan=pads._floorplan(die=2_001_000))
    lef = root / "pdk/proc/libs.ref/proc_io/lef/io.lef"
    lef.write_text(lef.read_text().replace("SIZE 1 BY 350 ;", "SIZE 0.5 BY 350 ;"))
    config = root / "pdk/proc/libs.tech/someflow/proc_io/config.tcl"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        'set ::env(PAD_SITE_NAME) "io_site"\n'
        'set ::env(PAD_CORNER_SITE_NAME) "io_corner_site"\n'
        'set ::env(PAD_EDGE_SPACING) "140"\n'
        'set ::env(PAD_CORNER) "pad_corner"\n'
        'set ::env(PAD_FILLERS) "pad_fill196 pad_fill9 pad_fill1"\n')
    if placement is not ...:
        path = root / declaration.DECLARATION_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"answers": {"seal_ring_placement": placement}}))
    if deck:
        _seal_technology(root / "pdk/proc")
    return root


def _assert_cited(basis, path):
    match = re.search(re.escape(str(path)) + r":([1-9][0-9]*)\b", basis)
    assert match, basis
    assert int(match.group(1)) <= len(path.read_text().splitlines()), basis


def test_outside_5_5_um_is_placed_and_reports_the_4_9_um_deck_basis(tmp_path):
    root = _project(tmp_path)
    assert pads._gen(root) == 0, pads._report(root)
    report = pads._report(root)
    assert report["verdict"] == "PASS"
    assert report["config"]["PAD_EDGE_SPACING"] == 5.5
    exception = report["edge_spacing_seal_keepout"]
    assert exception["accepted_spacing_um"] == 5.5
    assert exception["clearance_um"] == pytest.approx(4.9)
    assert "Seal.b" in exception["basis"]
    _assert_cited(exception["basis"], root / "pdk/proc/libs.tech/klayout/drc/rule_decks/6_10_sealring.drc")
    _assert_cited(exception["basis"], root / "pdk/proc/libs.tech/klayout/tech/neutral_tech_default.json")
    assert report["abutment"]["abuts"] is True
    assert pads._ring_def(root).is_file()


def test_outside_4_um_is_refused_with_both_distances_and_the_deck_citation(tmp_path):
    root = _project(tmp_path, spacing=4)
    assert pads._gen(root) == 1
    report = pads._report(root)
    assert "PAD_EDGE_SPACING_VIOLATES_SEAL_KEEPOUT" in pads._rules(root), report
    assert "4.9" in report["reason"]
    assert re.search(r"\b4(?:\.0)?\b", report["reason"]), report
    assert "Seal.b" in report["reason"]
    _assert_cited(report["reason"], root / "pdk/proc/libs.tech/klayout/drc/rule_decks/6_10_sealring.drc")
    assert not pads._ring_def(root).exists()


@pytest.mark.parametrize("placement", ["inside", ..., "OUTSIDE", ["outside"]],
                         ids=["inside", "absent", "invalid-string", "invalid-list"])
def test_only_the_raw_outside_answer_can_relax_a_pdk_declaration(tmp_path, placement):
    root = _project(tmp_path, placement=placement)
    assert pads._gen(root) == 1
    report = pads._report(root)
    assert pads._rules(root) == {"PAD_CONFIG_CONTRADICTS_PDK"}, report
    assert "5.5" in report["reason"] and "140" in report["reason"]
    assert "PAD_EDGE_SPACING" in report["reason"]
    assert not pads._ring_def(root).exists()


@pytest.mark.parametrize("broken", ["missing-deck", "malformed-table"])
def test_outside_spacing_with_unreadable_clearance_is_refused_by_name(tmp_path, broken):
    root = _project(tmp_path, deck=broken != "missing-deck")
    if broken == "malformed-table":
        (root / "pdk/proc/libs.tech/klayout/tech/neutral_tech_default.json").write_text("{")
    assert pads._gen(root) == 1
    report = pads._report(root)
    assert "PAD_EDGE_SPACING_SEAL_KEEPOUT_UNREADABLE" in pads._rules(root), report
    assert not pads._ring_def(root).exists()


def test_the_pdk_default_still_places_outside_without_any_seal_deck(tmp_path):
    root = _project(tmp_path, spacing=140, deck=False)
    assert pads._gen(root) == 0, pads._report(root)
    report = pads._report(root)
    assert report["config"]["PAD_EDGE_SPACING"] == 140
    assert report["abutment"]["abuts"] is True
    assert pads._ring_def(root).is_file()


@pytest.mark.parametrize("variable,value", [
    ("PAD_SITE_NAME", "other_site"),
    ("PAD_CORNER_SITE_NAME", "other_corner_site"),
    ("PAD_CORNER", "pad_bidir"),
    ("PAD_FILLERS", ["pad_fill9"]),
])
def test_outside_does_not_relax_any_other_pdk_variable(tmp_path, variable, value):
    root = _project(tmp_path, spacing=140, overrides={variable: value})
    assert pads._gen(root) == 1
    report = pads._report(root)
    assert pads._rules(root) == {"PAD_CONFIG_CONTRADICTS_PDK"}, report
    assert variable in report["reason"]
    assert not pads._ring_def(root).exists()


def test_the_actual_deck_expression_resolves_its_json_rule_value(tmp_path):
    deck, table = _seal_technology(tmp_path / "neutral")
    value, basis = margin.guard_ring_clearance_um(str(tmp_path / "neutral"), _shell)
    assert value == pytest.approx(4.9), basis
    assert "Seal.b" in basis
    _assert_cited(basis, deck)
    _assert_cited(basis, table)


def test_literal_guard_ring_separation_still_resolves_10_um(tmp_path):
    deck = tmp_path / "legacy.drc"
    deck.write_text('comp.separation(guard_ring_mk, 10.um).output("GR.1", "space")\n')
    value, basis = margin.guard_ring_clearance_um(str(tmp_path), _shell)
    assert value == 10, basis
    assert "GR.1" in basis


def test_feature_to_marker_rules_do_not_replace_seal_conductor_keepout(tmp_path):
    deck = tmp_path / "rules.drc"
    deck.write_text(
        'clearance = substrate.sep(conductor.and(edge_seal_marker), 4.9.um)\n'
        'clearance.output("seal-conductor", "space")\n'
        'other = optional_feature.sep(edge_seal_marker, 150.um)\n'
        'other.output("feature-marker", "space")\n')
    value, basis = margin.guard_ring_clearance_um(str(tmp_path), _shell)
    assert value == pytest.approx(4.9), basis
    assert "seal-conductor" in basis
    assert "feature-marker" not in basis


@pytest.mark.parametrize("intersection", [
    "conductor.and(mk)", "conductor.and(\n  mk)",
])
def test_marker_aliases_cannot_hide_a_stricter_keepout(tmp_path, intersection):
    deck = tmp_path / "rules.drc"
    deck.write_text(
        'low = substrate.sep(conductor.and(edge_seal_marker), 4.9.um)\n'
        'low.output("lower", "space")\n'
        'mk = edge_seal_marker\n'
        f'ring_metal = {intersection}\n'
        'high = substrate.sep(ring_metal, 10.um)\n'
        'high.output("higher", "space")\n')
    value, basis = margin.guard_ring_clearance_um(str(tmp_path), _shell)
    assert value == 10, basis
    assert "higher" in basis


def test_escaped_json_rule_key_keeps_its_exact_source_citation(tmp_path):
    deck, table = _seal_technology(tmp_path)
    table.write_text('{"drc_rules": {"\\u0053eal_b": 4.9}}\n')
    value, basis = margin.guard_ring_clearance_um(str(tmp_path), _shell)
    assert value == pytest.approx(4.9), basis
    _assert_cited(basis, deck)
    _assert_cited(basis, table)


def test_direct_multiline_intersection_cannot_hide_a_stricter_keepout(tmp_path):
    deck = tmp_path / "rules.drc"
    deck.write_text(
        'low = substrate.sep(conductor.and(edge_seal_marker), 4.9.um)\n'
        'low.output("lower", "space")\n'
        'high = substrate.sep(conductor.and(\n  edge_seal_marker), 10.um)\n'
        'high.output("higher", "space")\n')
    value, basis = margin.guard_ring_clearance_um(str(tmp_path), _shell)
    assert value == 10, basis
    assert "higher" in basis


def test_the_full_pdk_resolves_the_seal_conductor_keepout():
    pdk = os.environ.get("VIBEIC_SEAL_KEEP_OUT_PDK")
    if not pdk:
        pytest.skip("Set VIBEIC_SEAL_KEEP_OUT_PDK to the full PDK directory")
    value, basis = margin.guard_ring_clearance_um(pdk, _shell)
    assert value == pytest.approx(4.9), basis
    assert "Seal.b" in basis
    assert re.search(r"6_10_sealring[.]drc:[1-9][0-9]*", basis)


def test_copied_real_pdk_artifacts_resolve_4_9_um_without_a_named_pdk(tmp_path):
    evidence = os.environ.get("VIBEIC_SEAL_KEEP_OUT_EVIDENCE")
    if not evidence:
        pytest.skip("Set VIBEIC_SEAL_KEEP_OUT_EVIDENCE to the PDK evidence directory")
    source = Path(evidence)
    destination = tmp_path / "anonymous_process"
    destination.mkdir()
    for name in ("6_10_sealring.drc", "sg13g2_tech_default.json"):
        shutil.copyfile(source / name, destination / name)
    value, basis = margin.guard_ring_clearance_um(str(destination), _shell)
    assert value == pytest.approx(4.9), basis
    assert "Seal.b" in basis
    _assert_cited(basis, destination / "6_10_sealring.drc")
    _assert_cited(basis, destination / "sg13g2_tech_default.json")
