"""Default Step 24 binds the selected die route, without waiving operator inputs."""
import json
from pathlib import Path

import pytest

import _tapeout_declaration as td
import execution_backend_producers as producers
import execution_backend_worker as worker
import execution_policy as policy


def _write(root: Path, rel: str, text: str = "bound\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _project(tmp_path: Path, *, operator: bool = False) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    op = ({"path": "operator", "slot": "unit", "absent_reason": None}
          if operator else
          {"path": None, "slot": None,
           "absent_reason": "Owner selects an independent die tapeout; no operator applies."})
    answers = {
        "answers": {"deliverable": "DIE", "top_cell": "core"},
        "answer_provenance": {
            "deliverable": {"answered_by": "owner", "citation": "unit owner DIE route"},
            "top_cell": {"answered_by": "owner", "citation": "unit owner top"},
        },
        "operator_template": op,
    }
    declaration, refusals = td.merge_answers(
        td.blank_declaration(),
        {**answers["answers"], "answer_provenance": answers["answer_provenance"]})
    assert not refusals
    declaration["operator_template"] = op
    _write(root, "input/step_0_5ic_answers.json", json.dumps(answers))
    _write(root, td.DECLARATION_REL, json.dumps(declaration))
    if operator:
        _write(root, "input/submission_template/slots/unit.yaml", "slot: unit\n")
    else:
        _write(root, td.SELF_TAPEOUT_REL, td.SELF_TAPEOUT_MARKER + "\n")

    scanned = [
        "input/docs/L1.md",
        "input/submission_template/operator_answers.json",
        "input/submission_template/slots/unit.yaml",
    ]
    _write(root, "input/docs/L1.md", "owner design\n")
    _write(root, "reports/phase3/io_pad_chip_top.json", json.dumps({
        "verdict": "WROTE", "core_module": "core",
        "chip_top_module": "chip_top",
        "chip_top_verilog": "phase3/stage3/pnr/chip_top_io.v",
        "documents_scanned": scanned,
    }))
    _write(root, "phase3/stage3/pnr/chip_top.def",
           "VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n")
    _write(root, "phase3/stage3/pnr/core_pnr.v",
           "module chip_top; endmodule\n")
    _write(root, "phase3/stage3/pnr/chip_top_io.v",
           "module chip_top; endmodule\n")
    _write(root, "phase3/stage3/pnr/constraint.sdc", "create_clock -period 10 clk\n")
    _write(root, "phase3/stage3/pnr/pdn.done", "native PDN complete\n")
    _write(root, "phase3/librelane/32-unit/03-openroad-rcx/nom/chip_top.nom.spef",
           "*SPEF IEEE 1481-1998\n")
    return root


def _manifest(root: Path):
    params = {}
    policy._fixed_inputs(
        {"project": root, "policy": {"mode": "default"}}, "24",
        parameters=params)
    return params["resolved_input_manifest"]


def test_default_step24_self_tapeout_selects_actual_physical_inputs(tmp_path):
    root = _project(tmp_path)
    manifest = _manifest(root)
    assert manifest["missing"] == []
    assert "phase3/stage3/pnr/chip_top.def" in manifest["files"]
    assert "phase3/stage3/pnr/core_pnr.v" in manifest["files"]
    assert "phase3/stage3/pnr/constraint.sdc" in manifest["files"]
    assert "phase3/stage3/pnr/pdn.done" in manifest["files"]
    assert "phase3/librelane/32-unit/03-openroad-rcx/nom/chip_top.nom.spef" in manifest["files"]
    assert "phase3/stage3/pnr/routed.def" not in manifest["missing"]
    assert "input/submission_template/operator_answers.json" not in manifest["missing"]


def test_default_step24_self_tapeout_missing_subject_still_refuses(tmp_path):
    root = _project(tmp_path)
    (root / "phase3/stage3/pnr/chip_top.def").unlink()
    assert "phase3/stage3/pnr/chip_top.def" in _manifest(root)["missing"]


@pytest.mark.parametrize("rel", [
    "phase3/stage3/pnr/constraint.sdc",
    "phase3/stage3/pnr/pdn.done",
])
def test_default_step24_manifest_refuses_changed_issued_input(tmp_path, rel):
    root = _project(tmp_path)
    manifest = _manifest(root)
    with (root / rel).open("a") as stream:
        stream.write("changed after issuance\n")
    assert rel in worker.resolve_input_contract(root, manifest["declarations"], manifest)


def test_default_step24_self_tapeout_mapping_mismatch_refuses(tmp_path):
    root = _project(tmp_path)
    (root / "phase3/stage3/pnr/chip_top.def").write_text(
        "VERSION 5.8 ;\nDESIGN wrong_top ;\nEND DESIGN\n")
    with pytest.raises(ValueError, match="DEF DESIGN disagrees"):
        _manifest(root)


def test_default_step24_selected_rcx_missing_refuses_without_alias(tmp_path):
    root = _project(tmp_path)
    selected = root / "phase3/librelane/32-unit/03-openroad-rcx/nom/chip_top.nom.spef"
    selected.unlink()
    manifest = _manifest(root)
    assert "phase3/stage3/extracted/core.spef" in manifest["missing"]
    assert not (root / "phase3/stage3/extracted/core.spef").exists()


def test_default_step24_selected_rcx_ambiguity_refuses(tmp_path):
    root = _project(tmp_path)
    _write(root, "phase3/librelane/32-other/03-openroad-rcx/nom/chip_top.nom.spef",
           "*SPEF second candidate\n")
    with pytest.raises(ValueError, match="native SPEF selection is ambiguous"):
        _manifest(root)


def test_default_step24_selected_rcx_digest_change_refuses(tmp_path):
    root = _project(tmp_path)
    manifest = _manifest(root)
    rel = "phase3/librelane/32-unit/03-openroad-rcx/nom/chip_top.nom.spef"
    with (root / rel).open("a") as stream:
        stream.write("changed after issuance\n")
    assert rel in worker.resolve_input_contract(
        root, manifest["declarations"], manifest)


def test_default_step24_true_operator_route_keeps_operator_requirements(tmp_path):
    root = _project(tmp_path, operator=True)
    manifest = _manifest(root)
    assert "phase3/stage3/pnr/routed.def" in manifest["missing"]
    assert "input/submission_template/operator_answers.json" in manifest["missing"]
    assert "phase3/stage3/pnr/chip_top.def" not in manifest["declarations"]


def test_default_step24_producer_uses_the_issued_physical_subject(tmp_path, monkeypatch):
    """The Default producer must consume the same selection the issuer froze."""
    root = _project(tmp_path)
    seen = {}

    class Runner:
        _LL_IR_RECORD = "ir_drop_librelane.json"

        @staticmethod
        def _librelane_step24_record(project, top, pdk, mode, spef, written,
                                     *, routed_def=None, netlist=None, sdc=None):
            seen.update(top=top, spef=Path(spef), routed_def=Path(routed_def),
                        netlist=Path(netlist), sdc=Path(sdc))
            _write(project, "reports/phase3/ir_drop_librelane.json", json.dumps({
                "judgment": {"verdict": "NOT_MEASURED"}, "record": None}))

        @staticmethod
        def _librelane_step24_refusal_publish(*_args):
            return None

    monkeypatch.setattr(producers, "_parameters", lambda *_: (
        Runner, None, type("Pdk", (), {"name": "neutral"})(), ""))
    result = producers.produce_signoff(root, {
        "step_id": "24", "top": "core", "pdk_name": "neutral",
        "pdk_root": str(tmp_path), "image_id": "SOURCE_CONTROL_ONLY",
        "execution_mode": "default",
    })
    assert result["verdict"] == "PASS"
    assert seen == {
        "top": "core",
        "routed_def": root / "phase3/stage3/pnr/chip_top.def",
        "netlist": root / "phase3/stage3/pnr/core_pnr.v",
        "sdc": root / "phase3/stage3/pnr/constraint.sdc",
        "spef": root / "phase3/librelane/32-unit/03-openroad-rcx/nom/chip_top.nom.spef",
    }
