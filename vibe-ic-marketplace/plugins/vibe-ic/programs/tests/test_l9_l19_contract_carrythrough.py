from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import l9_l19_contract_carrythrough as C  # noqa: E402
import phase1_doc_one_shot_runner as R  # noqa: E402


def _write_consumers(project: Path) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"doc_class": "integration_spec", "ports": []}) + "\n")
    (gd / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({
        "fields": {"constraint_declarations": [{
            "token": "CLOCK_PERIOD", "value": "20", "scope": "slow",
            "source": "input/docs/L9_constraints.md",
        }]}
    }) + "\n")


def _write_doc(project: Path, name: str, text: str) -> None:
    root = project / "input" / "docs"
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")


def test_io_default_is_bound_to_its_numeric_clause(tmp_path):
    _write_consumers(tmp_path)
    _write_doc(tmp_path, "L9_constraints.md", """layer: L9
# I/O delay
Corner coverage target is 100%.
Input and output delay default to 20% of the clock period.
The plugin may override this default; an override must be recorded in declaration.json.
""")
    C.run(tmp_path)
    actual = json.loads((tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text())["constraints"]["io_delay"]
    assert actual["default_fraction_percent"] == 20, actual
    assert actual["derived_defaults"][0]["delay_ns"] == 4, actual
    assert "100%" in actual["evidence"]
    assert actual["override_requires_declaration"] is True


def test_nested_condition_keeps_its_three_owned_clauses(tmp_path):
    _write_consumers(tmp_path)
    _write_doc(tmp_path, "L8_submodule_integration.md", """layer: L8
## 8.4 假如 Plugin 產生多個 sub-module
### 完整性
- 每個 sub-module **必須**內部完整、無懸空 port、無未連接的 input
### 例化
- Top module **必須**例化所有有用的 sub-module,**禁止**留 stub
### 命名
- 命名空間 **不得**與 PDK std-cell 命名衝突(避免 link 階段被誤認)
""")
    C.run(tmp_path)
    actual = json.loads((tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").read_text())
    architecture = actual.get("integration", {}).get("architecture", [])
    combined = "\n".join(row["evidence"] for row in architecture)
    for clause in ("無懸空 port", "禁止**留 stub", "命名空間 **不得**"):
        assert clause in combined, architecture
    assert "假如 Plugin 產生多個 sub-module" in combined


def test_submodule_core_and_wrapper_interfaces_reach_architecture(tmp_path):
    _write_consumers(tmp_path)
    _write_doc(tmp_path, "L8_submodule.md", """\
layer: L8
# Structural block contracts
## Compute core
Separate instruction bus, data bus, and RF interface are required.
## Bus wrapper
The wrapper exposes instruction bus and data bus after adapting the RF interface.
""")
    report = C.run(tmp_path)
    assert report["status"] == "OK"
    l9 = json.loads((tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").read_text())
    architecture = l9.get("integration", {}).get("architecture", [])
    assert len(architecture) == 2, architecture
    assert all("instruction bus" in item["evidence"] and
               "data bus" in item["evidence"] for item in architecture)
    assert all(item["source"] == "input/docs/L8_submodule.md" for item in architecture)
    before = (tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").read_bytes()
    C.run(tmp_path)
    assert (tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").read_bytes() == before


def test_source_submodule_roles_survive_native_l9_generation(tmp_path):
    from programs.tests._hostpaths import require_repo
    root = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                        "tests", "fixtures", "subservient_input_docs")
    text = (root / "L8_submodule_integration.md").read_text()
    result = R.gen_l9_integration_spec(
        tmp_path, {"L8_submodule_integration.md": text}, {})
    doc = json.loads(result.path.read_text())
    roles = [s.get("implementation_requirement", "required")
             for s in doc["submodules"]]
    assert roles == ["optional"], roles
    optional = doc["submodules"][-1]
    assert optional["low_confidence"] is True
    assert "可選包入" in optional["requirement_evidence"][0]["evidence"]


def test_io_delay_override_and_disclosure_keep_their_common_scope(tmp_path):
    _write_consumers(tmp_path)
    _write_doc(tmp_path, "L9_constraints.md", """layer: L9
# I/O delay
Input and output delay default to 20% of the selected clock period.
The plugin may override this default; an override must be recorded in declaration.json.
""")
    C.run(tmp_path)
    l19 = json.loads((tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text())
    actual = l19.get("constraints", {}).get("io_delay", {})
    assert "override must be recorded in declaration.json" in actual.get("evidence", ""), actual
    assert actual["override_allowed"] is True
    assert actual["override_requires_declaration"] is True


def test_scope_and_default_qualifiers_reach_owning_layers(tmp_path):
    _write_consumers(tmp_path)
    _write_doc(tmp_path, "L8_integration.md", """layer: L8
# Hierarchy freedom
The implementation may flatten modules and choose file organization.
# Not constrained
Source language and generate blocks are implementation choices.
""")
    _write_doc(tmp_path, "L7_verification.md", """layer: L7
# Out of scope
Gate simulation is recommended, not mandatory; leakage corners are required only for production.
""")
    _write_doc(tmp_path, "L9_constraints.md", """layer: L9
# Synthesis fanout
Fanout uses the declared PDK defaults, with no override.
# Core utilization
Memory occupies approximately 50-70% in the composed configuration; this is an estimate.
# Not constrained by SDC
Multi-cycle paths may be added only with an equivalence proof in L7.
# Power network
Unlisted PDN settings use the selected PDK defaults.
""")
    C.run(tmp_path)
    l9 = json.loads((tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").read_text())
    l19 = json.loads((tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json").read_text())
    architecture = str(l9["integration"]["architecture"])
    verification = str(l9["integration"]["verification"])
    constraints = str(l19["constraints"]["implementation_constraints"])
    assert "flatten modules" in architecture and "generate blocks" in architecture
    assert "required only for production" in verification
    assert "50-70%" in constraints and "this is an estimate" in constraints
    assert "only with an equivalence proof" in constraints
    assert "Unlisted PDN settings" in constraints
    policy = l19["constraints"]["timing_exceptions"]
    assert policy["allow_automatic"] is False
    assert policy["requires_l7_equivalence"] is True


def test_denied_or_untyped_core_contracts_are_not_promoted(tmp_path):
    _write_consumers(tmp_path)
    _write_doc(tmp_path, "L8_submodule.md", """\
layer: L8
## No compute core
This design does not need an instruction bus or data bus.
""")
    _write_doc(tmp_path, "notes.md", """\
## Compute core
An instruction bus and data bus are only a discussion example.
""")
    C.run(tmp_path)
    l9 = json.loads((tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").read_text())
    assert l9.get("integration", {}).get("architecture", []) == []


def test_positive_cross_layer_contracts_reach_their_consumers(tmp_path):
    """Positive: explicit layer contracts land in L9/L19 with provenance."""
    _write_consumers(tmp_path)
    _write_doc(tmp_path, "L2_architecture.md", """\
layer: L2
status: draft
# Architecture
The system uses a shared memory for I-mem and D-mem.
# ISA and bit-serial execution
The base ISA is mandatory and the implementation is bit-serial.
# Reset and boot
Reset is synchronous active-high; SRAM contents retained until first instruction.
""")
    _write_doc(tmp_path, "L3_interface.md", """\
layer: L3
status: draft
# External interface and parameters
write_data (or write_data_alias), read_data (or read_data_alias), WIDTH_PARAM
# Physical pad placement
North carries data; South carries address; East carries clocks; West carries GPIO.
""")
    _write_doc(tmp_path, "L4_protocol.md", """\
layer: L4
status: not-applicable
# Applicability
There is no external command interface.
""")
    _write_doc(tmp_path, "L5_regmap.md", """\
layer: L5
status: not-applicable
# Applicability
There are no software-visible registers.
""")
    _write_doc(tmp_path, "L6_calibration.md", """\
layer: L6
status: not-applicable
# Applicability
There is no calibration controller.
""")
    _write_doc(tmp_path, "L7_verification.md", """\
layer: L7
status: draft
# Plugin Declaration Requirements
top_module, feature_set, memory_bytes, reset_polarity, clock_port_name
# Functional Verification
Execute boot firmware and observe output; verify SRAM retention.
# Quality Metrics — Acceptance Range
| metric | acceptance |
|---|---|
| setup slack (all corners) | >= 0 |
| hold slack | >= 0 |
| max_slew/max_cap/max_fanout | 0 |
""")
    _write_doc(tmp_path, "L9_constraints.md", """\
layer: L9
status: draft
# I/O delay
Input and output delay default to 20% of the selected clock period.
# Signoff
SS/TT/FF setup and hold must pass; DRC, LVS, antenna and GDS XOR clean.
""")
    decl = tmp_path / "input" / "submission_template"
    decl.mkdir(parents=True)
    (decl / "tapeout_declaration.json").write_text(json.dumps({
        "schema": "vibe-ic/tapeout_declaration/1",
        "answers": {"deliverable": "DIE", "top_cell": "neutral_top",
                    "die_area_um": [0, 0, 100, 100],
                    "database_unit_um": 0.001,
                    "pad_site_name": "NOT_DETERMINED"},
        "forbidden_layers": "NOT_DETERMINED",
    }) + "\n")
    (tmp_path / "input" / "step_0_5ic_answers.json").write_text(json.dumps({
        "operator_template": {
            "absent_reason": "No operator template or live run contract was supplied."
        }
    }) + "\n")

    report = C.run(tmp_path)
    assert report["status"] == "OK"
    assert report["emitted_count"] == 14
    l9 = json.loads((tmp_path / "phase1" / "generated_docs" /
                     "L9_INTEGRATION_SPEC.json").read_text())
    l19 = json.loads((tmp_path / "phase1" / "generated_docs" /
                      "L19_CONSTRAINTS_PDK.json").read_text())
    assert l9["integration"]["reset_boot"]["normalized_semantics"][0][
        "normalized"] == "synchronous active-high"
    assert l9["integration"]["applicability"][0]["status"] == "not-applicable"
    assert l19["constraints"]["io_delay"]["derived_defaults"][0][
        "display"] == "4 ns"
    assert l19["constraints"]["unresolved"]["fields"] == [
        "answers.pad_site_name", "forbidden_layers"]
    assert l19["constraints"]["operator_template"]["operator_precheck"] == \
        "not claimed"
    normalized = [row["normalized"]
                  for row in l19["constraints"]["ppa_acceptance"][
                      "normalized_metrics"]]
    assert normalized == [
        "setup slack >= 0",
        "hold slack >= 0",
        "max_slew/max_cap/max_fanout 0",
    ]


def test_false_positive_denied_or_untyped_prose_emits_nothing(tmp_path):
    """Control: mentions and denied behaviour are not design contracts."""
    _write_consumers(tmp_path)
    _write_doc(tmp_path, "notes.md", """\
# Discussion only
The words declaration requirements, signoff, pad placement, and 20% I/O delay
are examples. Reset is not synchronous or active-high and SRAM contents are not
retained. This document has no L-layer role.
""")
    before_l9 = (tmp_path / "phase1" / "generated_docs" /
                 "L9_INTEGRATION_SPEC.json").read_bytes()
    before_l19 = (tmp_path / "phase1" / "generated_docs" /
                  "L19_CONSTRAINTS_PDK.json").read_bytes()
    report = C.run(tmp_path)
    assert report["status"] == "OK"
    assert report["emitted_count"] == 0
    assert (tmp_path / "phase1" / "generated_docs" /
            "L9_INTEGRATION_SPEC.json").read_bytes() == before_l9
    assert (tmp_path / "phase1" / "generated_docs" /
            "L19_CONSTRAINTS_PDK.json").read_bytes() == before_l19


def test_not_applicable_normalization_requires_explicit_status(tmp_path):
    """Control: an active L4 discussion must not become an absence claim."""
    _write_consumers(tmp_path)
    _write_doc(tmp_path, "L4_protocol.md", """\
layer: L4
status: draft
# Command protocol
The command decoder is required.
""")
    report = C.run(tmp_path)
    assert report["emitted_count"] == 0


def test_runner_adapter_degrades_loudly_when_consumers_are_absent(
        tmp_path, capsys):
    assert R._post_emit_l9_l19_contract_carrythrough(tmp_path) == 0
    out = capsys.readouterr().out
    assert "L9/L19 contract carry-through: SKIPPED" in out


def test_idempotent_existing_consumer_fields_win(tmp_path):
    _write_consumers(tmp_path)
    _write_doc(tmp_path, "L7_verification.md", """\
layer: L7
status: draft
# Plugin Declaration Requirements
top_module and feature_set are required.
""")
    first = C.run(tmp_path)
    assert first["emitted_count"] == 1
    second = C.run(tmp_path)
    assert second["emitted_count"] == 0
