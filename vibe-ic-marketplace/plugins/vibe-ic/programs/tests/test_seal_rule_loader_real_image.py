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


@pytest.mark.parametrize("statements", [
    "spacing = rules['clearance'].to_f\nspacing += 1\n",
    'spacing = rules[\'clearance\'].to_f\nlogger.info("#{spacing = 12}")\n',
    "spacing = rules['clearance'].to_f\nrules.clear\n",
    "untrusted = rules['clearance'].to_f # comment\n .abs\nspacing = rules['clearance'].to_f\n",
    'untrusted = rules["#{unknown}"].to_f\nspacing = rules[\'clearance\'].to_f\n',
    "untrusted = rules['clearance'].to_i!\nspacing = rules['clearance'].to_f\n",
    "untrusted = rules['clearance'].to_i?\nspacing = rules['clearance'].to_f\n",
    "untrusted = rules['clearance'].to_f!\nspacing = rules['clearance'].to_f\n",
    "untrusted = rules['clearance'].to_i=3\nspacing = rules['clearance'].to_f\n",
    "untrusted = rules['clearance'].to_i = 3\nspacing = rules['clearance'].to_f\n",
    "untrusted = rules['clearance'].to_i += 3\nspacing = rules['clearance'].to_f\n",
    "untrusted = rules['clearance'].to_f *= 3\nspacing = rules['clearance'].to_f\n",
    "untrusted = rules['clearance'].to_i **= 3\nspacing = rules['clearance'].to_f\n",
    "untrusted = rules['clearance'].to_i&.unknown\nspacing = rules['clearance'].to_f\n",
    "untrusted = rules['clearance'].to_i::unknown\nspacing = rules['clearance'].to_f\n",
    "untrusted = rules['clearance'].to_f&.unknown\nspacing = rules['clearance'].to_f\n",
    "untrusted = rules['clearance'].to_i\n &.unknown\nspacing = rules['clearance'].to_f\n",
])
def test_numeric_lookup_rejects_intervening_or_hidden_mutation(tmp_path, statements):
    (tmp_path / "rules.json").write_text(json.dumps({"rules": {"clearance": 4.9}}))
    (tmp_path / "main.drc").write_text(
        "rules = JSON.parse(File.read(File.join(__dir__, 'rules.json')))['rules']\n"
        + statements
        + 'active.sep(guard_ring, spacing.um).output("clearance", "space")\n'
    )
    assert_unreadable(tmp_path)


REVIEW_PROBES = json.loads((FIXTURE.parent / "seal_rule_loader_review/PROBES.json").read_text())


@pytest.mark.parametrize("probe", REVIEW_PROBES, ids=lambda probe: probe["name"])
def test_review_numeric_expression_and_readonly_reuse(tmp_path, probe):
    rules = {} if probe["missing_key"] else {"clearance": 4.9}
    (tmp_path / "rules.json").write_text(json.dumps({"rules": rules}))
    (tmp_path / "main.drc").write_text(probe["source"])
    if probe["expected"] is None:
        assert_unreadable(tmp_path)
    else:
        value, basis = read(tmp_path)
        assert value == pytest.approx(probe["expected"]), basis


@pytest.mark.parametrize("statements,expected", [
    ("number = 4.9\nspacing = number()\n", None),
    ("number = rules['clearance'].to_f\nspacing = number()\n", None),
    ("area = rules['clearance'].to_f\nunit = area.um2\nspacing = rules['clearance'].to_f\n", 4.9),
    ("area = rules['clearance'].to_f\nspacing = area.um2\n", None),
    ("number = rules['clearance'].to_i\nspacing = number / 2\n", 2),
    ("number = rules['clearance'].to_f\nspacing = number / 2\n", 2.45),
], ids=["literal_call", "json_call", "area_read", "area_not_linear", "integer_division", "float_division"])
def test_numeric_model_calls_units_and_division(tmp_path, statements, expected):
    (tmp_path / "rules.json").write_text(json.dumps({"rules": {"clearance": 4.9}}))
    (tmp_path / "main.drc").write_text(
        "rules = JSON.parse(File.read(File.join(__dir__, 'rules.json')))['rules']\n"
        + statements
        + 'active.separation(guard_ring, spacing.um).output("seal", "space")\n'
    )
    if expected is None:
        assert_unreadable(tmp_path)
    else:
        value, basis = read(tmp_path)
        assert value == pytest.approx(expected), basis


@pytest.mark.parametrize("separator", ["# comment\n", "\n", "# comment\n\n# second comment\n"])
@pytest.mark.parametrize("method", ["ceil", "unknown"])
@pytest.mark.parametrize("receiver", ["(rules['clearance'].to_f)", "4.9"])
def test_review_receiver_continues_across_comments_and_blank_lines(
        tmp_path, separator, method, receiver):
    (tmp_path / "rules.json").write_text(json.dumps({"rules": {"clearance": 4.9}}))
    (tmp_path / "main.drc").write_text(
        "rules = JSON.parse(File.read(File.join(__dir__, 'rules.json')))['rules']\n"
        + f"spacing = {receiver}\n{separator} .{method}\n"
        + 'active.separation(guard_ring, spacing.um).output("clearance", "space")\n'
    )
    # Neither method is in the bounded numeric model. In particular ceil(4.9)
    # is 5, so accepting a declared 4.95 edge using the truncated 4.9 is unsafe.
    assert_unreadable(tmp_path)


@pytest.mark.parametrize("geometry", [
    "active.width(2.um)\n .output('width', 'minimum width')\n",
    "active.width(2.um)\n# comment\n\n .output('width', 'minimum width')\n",
    "active.width(\n 2.um\n)\n .output('width', 'minimum width')\n",
])
@pytest.mark.parametrize("before_binding", [True, False])
def test_review_unrelated_multiline_geometry_keeps_numeric_clearance(
        tmp_path, geometry, before_binding):
    binding = "spacing = rules['clearance'].to_f\n"
    (tmp_path / "rules.json").write_text(json.dumps({"rules": {"clearance": 4.9}}))
    (tmp_path / "main.drc").write_text(
        "rules = JSON.parse(File.read(File.join(__dir__, 'rules.json')))['rules']\n"
        + (geometry + binding if before_binding else binding + geometry)
        + 'active.separation(guard_ring, spacing.um).output("seal", "space")\n'
    )
    value, basis = read(tmp_path)
    assert value == pytest.approx(4.9), basis
    merged, _ = pads.apply_pdk_declarations(
        {"PAD_EDGE_SPACING": 4.95},
        SimpleNamespace(values={"PAD_EDGE_SPACING": 140}),
        seal_ring_placement="outside",
        seal_clearance_um=value,
        seal_clearance_basis=basis,
    )
    assert merged["PAD_EDGE_SPACING"] == 4.95


def test_unrelated_geometry_can_read_the_tracked_number_in_its_output(tmp_path):
    (tmp_path / "rules.json").write_text(json.dumps({"rules": {"clearance": 4.9}}))
    (tmp_path / "main.drc").write_text(
        "rules = JSON.parse(File.read(File.join(__dir__, 'rules.json')))['rules']\n"
        "spacing = rules['clearance'].to_f\n"
        'active.width(2.um)\n .output("width", "clearance #{spacing}")\n'
        'active.separation(guard_ring, spacing.um).output("seal", "space")\n'
    )
    value, basis = read(tmp_path)
    assert value == pytest.approx(4.9), basis


@pytest.mark.parametrize("receiver", ["(\n 4.9\n)", "(\n rules['clearance'].to_f\n)"])
@pytest.mark.parametrize("method", ["ceil", "unknown"])
def test_multiline_numeric_receiver_still_refuses_unsupported_continuation(
        tmp_path, receiver, method):
    (tmp_path / "rules.json").write_text(json.dumps({"rules": {"clearance": 4.9}}))
    (tmp_path / "main.drc").write_text(
        "rules = JSON.parse(File.read(File.join(__dir__, 'rules.json')))['rules']\n"
        + f"spacing = {receiver}\n# comment\n\n .{method}\n"
        + 'active.width(2.um)\n .output("width", "minimum width")\n'
        + 'active.separation(guard_ring, spacing.um).output("seal", "space")\n'
    )
    assert_unreadable(tmp_path)


@pytest.mark.parametrize("method", ["clear", "unknown"])
@pytest.mark.parametrize("separator", ["# comment\n", "\n"])
def test_json_binding_keeps_its_receiver_across_a_leading_dot(
        tmp_path, method, separator):
    (tmp_path / "rules.json").write_text(json.dumps({"rules": {"clearance": 4.9}}))
    (tmp_path / "main.drc").write_text(
        "rules = JSON.parse(File.read(File.join(__dir__, 'rules.json')))['rules']\n"
        + f"{separator} .{method}\n"
        + "spacing = rules['clearance'].to_f\n"
        + 'active.separation(guard_ring, spacing.um).output("seal", "space")\n'
    )
    assert_unreadable(tmp_path)


@pytest.mark.parametrize("method", ["to_f", "to_f()"])
@pytest.mark.parametrize("separator", ["\n", "\n# comment\n"])
@pytest.mark.parametrize("parentheses", ["(rules['clearance'].to_i)", "(\n rules['clearance'].to_i\n)"])
def test_post_parenthesis_conversion_is_part_of_the_numeric_binding(
        tmp_path, separator, parentheses, method):
    (tmp_path / "rules.json").write_text(json.dumps({"rules": {"clearance": 5}}))
    (tmp_path / "main.drc").write_text(
        "rules = JSON.parse(File.read(File.join(__dir__, 'rules.json')))['rules']\n"
        + f"number = {parentheses}{separator} .{method}\n"
        + "spacing = number / 2\n"
        + 'active.separation(guard_ring, spacing.um).output("seal", "space")\n'
    )
    value, basis = read(tmp_path)
    assert value == 2.5, basis
    with pytest.raises(pads.AssignmentError) as refusal:
        pads.apply_pdk_declarations(
            {"PAD_EDGE_SPACING": 2.25},
            SimpleNamespace(values={"PAD_EDGE_SPACING": 140}),
            seal_ring_placement="outside", seal_clearance_um=value,
            seal_clearance_basis=basis,
        )
    assert refusal.value.rule == "PAD_EDGE_SPACING_VIOLATES_SEAL_KEEPOUT"
