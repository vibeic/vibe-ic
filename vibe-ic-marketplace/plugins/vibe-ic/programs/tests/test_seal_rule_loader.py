import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import _seal_ring_margin as margin

FIXTURE = Path(__file__).parent / "fixtures/seal_rule_loader"


def shell(command):
    result = subprocess.run(["sh", "-c", command], capture_output=True, text=True, timeout=30)
    return result.returncode, result.stdout


@pytest.fixture
def real_loader(tmp_path):
    hashes = json.loads((FIXTURE / "SHA256.json").read_text())
    for name, digest in hashes.items():
        assert hashlib.sha256((FIXTURE / name).read_bytes()).hexdigest() == digest
    pdk = tmp_path / "pdk"
    deck_dir = pdk / "libs.tech/klayout/tech/drc"
    for name in hashes:
        if name == "sg13g2_tech_mod.json":
            destination = deck_dir / "../../python/sg13g2_pycell_lib/sg13g2_tech_mod.json"
        else:
            destination = deck_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE / name, destination)
    return pdk, deck_dir


def read(real_loader):
    return margin.guard_ring_clearance_um(str(real_loader[0]), shell)


def edit_rule(path, value):
    payload = json.loads(path.read_text())
    if value is None:
        payload["drc_rules"].pop("Seal_b", None)
    else:
        payload["drc_rules"]["Seal_b"] = value
    path.write_text(json.dumps(payload, indent=2))


def test_real_loader_and_include_read_the_reviewed_4_9_um(real_loader):
    value, basis = read(real_loader)
    assert value == pytest.approx(4.9), basis
    assert "sg13g2_tech_default.json" in basis
    assert "sg13g2_tech_mod.json" in basis
    assert "ihp-sg13g2.drc" in basis
    assert "6_10_sealring.drc" in basis


def test_tech_override_wins_over_default(real_loader):
    _, deck_dir = real_loader
    edit_rule(deck_dir / "../../python/sg13g2_pycell_lib/sg13g2_tech_mod.json", 12)
    value, basis = read(real_loader)
    assert value == 12, basis
    assert "sg13g2_tech_mod.json" in basis


def test_missing_tech_key_uses_the_explicit_default_merge(real_loader):
    _, deck_dir = real_loader
    edit_rule(deck_dir / "../../python/sg13g2_pycell_lib/sg13g2_tech_mod.json", None)
    value, basis = read(real_loader)
    assert value == pytest.approx(4.9), basis
    assert "sg13g2_tech_default.json" in basis


def test_unloaded_json_cannot_fill_both_missing_keys(real_loader):
    _, deck_dir = real_loader
    edit_rule(deck_dir / "../../python/sg13g2_pycell_lib/sg13g2_tech_mod.json", None)
    edit_rule(deck_dir / "rule_decks/sg13g2_tech_default.json", None)
    (deck_dir / "unused.json").write_text(json.dumps({"drc_rules": {"Seal_b": 4.9}}))
    value, basis = read(real_loader)
    assert value is None, basis


def test_missing_loaded_file_cannot_borrow_a_matching_basename(real_loader):
    _, deck_dir = real_loader
    tech = deck_dir / "../../python/sg13g2_pycell_lib/sg13g2_tech_mod.json"
    shutil.move(tech, deck_dir / tech.name)
    value, basis = read(real_loader)
    assert value is None, basis


def test_parent_loader_without_the_seal_include_is_not_authority(real_loader):
    _, deck_dir = real_loader
    main = deck_dir / "ihp-sg13g2.drc"
    text = main.read_text()
    text = text.replace("# %include rule_decks/beol/6_10_sealring.drc", "# seal include removed")
    main.write_text(text)
    value, basis = read(real_loader)
    assert value is None, basis


def test_malformed_loaded_tech_table_refuses(real_loader):
    _, deck_dir = real_loader
    (deck_dir / "../../python/sg13g2_pycell_lib/sg13g2_tech_mod.json").write_text("{")
    value, basis = read(real_loader)
    assert value is None, basis


@pytest.mark.parametrize("table", [{}, {"drc_rules": None}, {"drc_rules": False}])
def test_loader_empty_table_fallback_preserves_default(real_loader, table):
    _, deck_dir = real_loader
    (deck_dir / "../../python/sg13g2_pycell_lib/sg13g2_tech_mod.json").write_text(json.dumps(table))
    value, basis = read(real_loader)
    assert value == pytest.approx(4.9), basis


def test_conditional_loader_definition_is_not_authority(real_loader):
    _, deck_dir = real_loader
    main = deck_dir / "ihp-sg13g2.drc"
    text = main.read_text().replace("def get_drc_values(logger)", "if false\ndef get_drc_values(logger)")
    text = text.replace("# Extract DRC rules values", "end\n# Extract DRC rules values")
    main.write_text(text)
    value, basis = read(real_loader)
    assert value is None, basis


def neutral_loader(tmp_path):
    (tmp_path / "active.json").write_text(json.dumps({"rules": {"clearance": 4.9}}))
    (tmp_path / "binding.drc").write_text(
        "rules = JSON.parse(File.read(File.join(__dir__, 'active.json')))['rules']\n")
    (tmp_path / "child.drc").write_text(
        "spacing = rules['clearance'].to_f\n"
        'active.separation(guard_ring_mk, spacing.um).output("keepout", "space")\n')
    (tmp_path / "main.drc").write_text("# %include binding.drc\n# %include child.drc\n")


def test_preceding_included_binding_is_in_scope(tmp_path):
    neutral_loader(tmp_path)
    value, basis = margin.guard_ring_clearance_um(str(tmp_path), shell)
    assert value == pytest.approx(4.9), basis
    assert "binding.drc" in basis and "child.drc" in basis


def test_preceding_included_mutation_is_not_ignored(tmp_path):
    neutral_loader(tmp_path)
    (tmp_path / "mutate.drc").write_text("rules['clearance'] = 12\n")
    (tmp_path / "main.drc").write_text(
        "# %include binding.drc\n# %include mutate.drc\n# %include child.drc\n")
    value, basis = margin.guard_ring_clearance_um(str(tmp_path), shell)
    assert value is None, basis


def test_competing_include_contexts_do_not_choose_a_table(tmp_path):
    neutral_loader(tmp_path)
    (tmp_path / "second.json").write_text(json.dumps({"rules": {"clearance": 12}}))
    (tmp_path / "second.drc").write_text(
        "rules = JSON.parse(File.read(File.join(__dir__, 'second.json')))['rules']\n"
        "# %include child.drc\n")
    value, basis = margin.guard_ring_clearance_um(str(tmp_path), shell)
    assert value is None, basis


def test_winning_key_citation_ignores_an_unrelated_nested_key(tmp_path):
    neutral_loader(tmp_path)
    (tmp_path / "active.json").write_text(
        '{"unused": {"clearance": 999},\n "rules": {\n "clearance": 4.9}}\n')
    value, basis = margin.guard_ring_clearance_um(str(tmp_path), shell)
    assert value == pytest.approx(4.9), basis
    assert str(tmp_path / "active.json") + ":3" in basis


@pytest.mark.parametrize("payload", [[], None, 42])
def test_nonobject_loaded_json_is_not_an_empty_rule_table(real_loader, payload):
    _, deck_dir = real_loader
    (deck_dir / "../../python/sg13g2_pycell_lib/sg13g2_tech_mod.json").write_text(json.dumps(payload))
    value, basis = read(real_loader)
    assert value is None, basis



def test_source_global_override_inside_interpolation_is_not_ignored(real_loader):
    _, deck_dir = real_loader
    main = deck_dir / "ihp-sg13g2.drc"
    text = main.read_text().replace(
        "drc_rules = get_drc_values(logger)",
        "logger.info(\"#{$drc_json = '/different.json'}\")\n"
        "drc_rules = get_drc_values(logger)")
    main.write_text(text)
    value, basis = read(real_loader)
    assert value is None, basis
