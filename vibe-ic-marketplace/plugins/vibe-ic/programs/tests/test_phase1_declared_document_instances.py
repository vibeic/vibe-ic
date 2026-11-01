"""Declared components retain typed port/net bindings through normal L9 emission."""
import json
from pathlib import Path

import pytest

import phase1_doc_one_shot_runner as runner


INTERFACE = """# Neutral analog unit

## External Interface
Top module name: `example_shell`

| Signal | Direction | Width | Description |
|---|---|---|---|
| rail_a | input | 1 | analog input |
| rail_b | input | 1 | analog input |
| common | inout | 1 | analog return |

"""


def emit(tmp_path, declaration):
    text = INTERFACE + declaration
    source = tmp_path / "input/docs/contract.md"
    source.parent.mkdir(parents=True)
    source.write_text(text)
    docs = {source.name: text}
    runner.gen_l1_datasheet(tmp_path, docs)
    result = runner.gen_l9_integration_spec(tmp_path, docs, {})
    return json.loads(Path(result.path).read_text()), docs


def test_declared_passive_instance_reaches_l9_with_bindings(tmp_path):
    l9, _ = emit(tmp_path, """## Instance c_filter (mim_capacitor)
Capacitance: 12 pF

| Port | Direction | Type | Net |
|---|---|---|---|
| p | inout | analog | rail_a |
| n | inout | analog | common |
""")
    instances = l9.get("instances", [])
    assert len(instances) == 1
    row = instances[0]
    assert (row["name"], row["block_type"]) == ("c_filter", "mim_capacitor")
    assert row["port_map"] == {"p": "rail_a", "n": "common"}
    assert {p["name"]: p["type"] for p in row["ports"]} == {"p": "analog", "n": "analog"}
    assert row["parameters"]["capacitance_pf"] == 12
    assert row["evidence"]["doc"] == "input/docs/contract.md"
    assert row["evidence"]["line"] == len(INTERFACE.splitlines()) + 1
    bindings = {(wire.get("child_inst"), wire.get("child_port"), wire.get("net"))
                for wire in l9["internal_wires"]}
    assert bindings == {("c_filter", "p", "rail_a"), ("c_filter", "n", "common")}
    assert l9["no_internal_wires_in_input"] is False


def test_generic_typed_block_is_not_restricted_to_passives(tmp_path):
    l9, _ = emit(tmp_path, """## Instance gain_unit (voltage_stage)
| Port | Direction | Type | Net |
|---|---|---|---|
| sense | input | analog | rail_a |
| drive | output | analog | rail_b |
""")
    instances = l9.get("instances", [])
    assert len(instances) == 1
    assert instances[0]["port_map"] == {"sense": "rail_a", "drive": "rail_b"}


def test_explicit_each_declaration_emits_two_passives(tmp_path):
    l9, docs = emit(tmp_path, """## Current decoupling requirement
12 pF of on-chip MIM decap on EACH of rail_a and rail_b: two instances, each between the core-side rail_a (or rail_b) net and common.
No buffer is required.
""")
    instances = l9.get("instances", [])
    assert len(instances) == 2
    assert {tuple(row["port_map"].values()) for row in instances} == {
        ("rail_a", "common"), ("rail_b", "common")}
    assert all(row["parameters"]["capacitance_pf"] == 12 for row in instances)
    assert all(row["block_type"] == "mim_capacitor" for row in instances)
    # The ordinary post-emit naming guard must retain the existing module
    # definitions; component instance identities live in their own container.
    runner._post_emit_l9_drop_uninstantiated_submodule_names(tmp_path, docs)
    reread = json.loads((tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").read_text())
    assert reread["instances"] == instances


@pytest.mark.parametrize("declaration", [
    "## Historical comparison\n12 pF MIM capacitor between rail_a and common.\n",
    "## Current requirement\nNo 12 pF MIM capacitor between rail_a and common.\n",
    "## Current requirement\n12 pF MIM capacitor between absent_net and common.\n",
    "## Current requirement\n12 pF MIM capacitor between rail_a (or rail_b) and common.\n",
    "## Instance c_filter (mim_capacitor)\n| Port | Type | Net |\n|---|---|---|\n| p | analog | absent_net |\n| n | analog | common |\n",
])
def test_undeclared_or_noncurrent_bindings_are_not_invented(tmp_path, declaration):
    l9, _ = emit(tmp_path, declaration)
    assert l9.get("instances", []) == []
