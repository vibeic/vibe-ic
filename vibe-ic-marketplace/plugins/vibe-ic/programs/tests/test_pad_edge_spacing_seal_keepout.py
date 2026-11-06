import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import _seal_ring_margin as margin


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
    deck.write_text("require 'json'\n"
                    "drc_rules = JSON.parse(File.read(File.join(__dir__, "
                    "'../../tech/neutral_tech_default.json')))['drc_rules']\n"
                    + SEAL_DECK)
    table = pdk / "libs.tech/klayout/tech/neutral_tech_default.json"
    table.parent.mkdir(parents=True, exist_ok=True)
    table.write_text(json.dumps({"drc_rules": {"Seal_b": 4.9}}, indent=2))
    return deck, table


def _assert_cited(basis, path):
    match = re.search(re.escape(str(path)) + r":([1-9][0-9]*)\b", basis)
    assert match, basis
    assert int(match.group(1)) <= len(path.read_text().splitlines()), basis


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


@pytest.mark.parametrize("binding", ["missing", "unsupported", "wrong-table", "reassigned"])
def test_unbound_rule_table_cannot_borrow_an_unused_json(tmp_path, binding):
    deck, table = _seal_technology(tmp_path)
    text = deck.read_text()
    if binding == "missing":
        text = SEAL_DECK
    elif binding == "unsupported":
        text = text.replace("File.join(__dir__, ", "unknown_path(")
    elif binding == "wrong-table":
        text = text.replace(")['drc_rules']", ")['unused_rules']")
    else:
        text = text.replace("unless PRECHECK_DRC", "drc_rules = other_table\nunless PRECHECK_DRC")
    deck.write_text(text)
    value, basis = margin.guard_ring_clearance_um(str(tmp_path), _shell)
    assert value is None, basis


def test_loaded_table_missing_key_cannot_borrow_nested_or_unused_table(tmp_path):
    deck, table = _seal_technology(tmp_path)
    table.write_text(json.dumps({"drc_rules": {"Other": 12},
                                 "unused": {"drc_rules": {"Seal_b": 4.9}}}))
    table.with_name("unused.json").write_text(json.dumps({"drc_rules": {"Seal_b": 4.9}}))
    value, basis = margin.guard_ring_clearance_um(str(tmp_path), _shell)
    assert value is None, basis
