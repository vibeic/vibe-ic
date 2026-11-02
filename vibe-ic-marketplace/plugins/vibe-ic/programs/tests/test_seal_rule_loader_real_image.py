import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import _pad_ring as pads
import _seal_ring_margin as margin


FIXTURE = Path(__file__).parent / "fixtures/seal_rule_loader_real_image"
DECK = Path("libs.tech/klayout/tech/drc/rule_decks/beol/6_10_sealring.drc")
DEFAULT = Path("libs.tech/klayout/tech/drc/rule_decks/sg13g2_tech_default.json")
TECH = Path("libs.tech/klayout/python/sg13g2_pycell_lib/sg13g2_tech_mod.json")
LOOKUP = "seal_b_value = drc_rules['Seal_b'].to_f"


def shell(command):
    process = subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=30)
    return process.returncode, process.stdout


@pytest.fixture
def real_pdk(tmp_path):
    manifest = json.loads((FIXTURE / "MANIFEST.json").read_text())
    pdk = tmp_path / "pdk"
    for record in manifest["files"]:
        source = FIXTURE / record["fixture_path"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == record["sha256"]
        destination = pdk / record["fixture_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    return pdk


def edit_deck(pdk, replacement):
    path = pdk / DECK
    text = path.read_text()
    assert text.count(LOOKUP) == 1
    path.write_text(text.replace(LOOKUP, replacement))


def read(pdk):
    return margin.guard_ring_clearance_um(str(pdk), shell)


def assert_unreadable(pdk):
    value, reason = read(pdk)
    assert value is None, reason
    assert "could not be read" in reason, reason
    with pytest.raises(pads.AssignmentError) as refusal:
        pads.apply_pdk_declarations(
            {"PAD_EDGE_SPACING": 5.5},
            SimpleNamespace(values={"PAD_EDGE_SPACING": 140}),
            seal_ring_placement="outside",
            seal_clearance_um=value,
            seal_clearance_basis=reason,
        )
    assert refusal.value.rule == "PAD_EDGE_SPACING_SEAL_KEEPOUT_UNREADABLE"


def test_real_image_deck_resolves_4_9_um_with_its_json_authority(real_pdk):
    value, basis = read(real_pdk)
    assert value == pytest.approx(4.9), basis
    for name in ["ihp-sg13g2.drc", "6_10_sealring.drc", "sg13g2_tech_default.json", "sg13g2_tech_mod.json"]:
        assert name in basis
    merged, _ = pads.apply_pdk_declarations(
        {"PAD_EDGE_SPACING": 5.5},
        SimpleNamespace(values={"PAD_EDGE_SPACING": 140}),
        seal_ring_placement="outside",
        seal_clearance_um=value,
        seal_clearance_basis=basis,
    )
    assert merged["PAD_EDGE_SPACING"] == 5.5


def test_real_image_to_i_conversion_truncates_the_declared_value(real_pdk):
    edit_deck(real_pdk, LOOKUP.replace(".to_f", ".to_i"))
    value, basis = read(real_pdk)
    assert value == 4, basis


def test_real_image_tech_value_overrides_default(real_pdk):
    path = real_pdk / TECH
    payload = json.loads(path.read_text())
    payload["drc_rules"]["Seal_b"] = 8.25
    path.write_text(json.dumps(payload))
    value, basis = read(real_pdk)
    assert value == pytest.approx(8.25), basis
    assert "sg13g2_tech_mod.json" in basis


@pytest.mark.parametrize("mutation", [
    "drc_rules['Seal_b'] = 3\n",
    "drc_rules.clear\n",
    "drc_rules.merge!({'Seal_b' => 3})\n",
])
def test_real_image_table_mutation_is_named_unreadable(real_pdk, mutation):
    edit_deck(real_pdk, mutation + LOOKUP)
    assert_unreadable(real_pdk)


@pytest.mark.parametrize("replacement", [
    LOOKUP.replace(".to_f", ".unknown_method"),
    LOOKUP.replace(".to_f", ".to_f.abs"),
    "untrusted = drc_rules['Seal_b'].to_f.abs\n" + LOOKUP,
])
def test_real_image_unknown_lookup_chain_is_named_unreadable(real_pdk, replacement):
    edit_deck(real_pdk, replacement)
    assert_unreadable(real_pdk)


def test_real_image_missing_key_is_named_unreadable(real_pdk):
    for relative in [DEFAULT, TECH]:
        path = real_pdk / relative
        payload = json.loads(path.read_text())
        payload["drc_rules"].pop("Seal_b", None)
        path.write_text(json.dumps(payload))
    assert_unreadable(real_pdk)


def test_real_image_reassigned_local_is_named_unreadable(real_pdk):
    edit_deck(real_pdk, LOOKUP + "\n  seal_b_value = 4.9")
    assert_unreadable(real_pdk)
