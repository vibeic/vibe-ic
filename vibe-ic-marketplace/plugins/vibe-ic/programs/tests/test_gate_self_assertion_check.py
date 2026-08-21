"""v0.2.24 — anti-fabrication gate-hole detector (Bucket A capture from M1).

Pins: a gate that PASSes on a self-produced json_field_true WITH NO
program_exit_zero is flagged (FAIL); the same boolean PAIRED with a real
program_exit_zero is fine (PASS); a json_field_true on a file the step does
NOT produce is not flagged; and the canonical in-tree flow YAML is clean.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gate_self_assertion_check as G  # noqa: E402

_FLOW = (Path(__file__).resolve().parent.parent.parent
         / "flow" / "phase1_phase2_phase3.yaml")


def _write(tmp_path, doc):
    import yaml
    p = tmp_path / "flow.yaml"
    p.write_text(yaml.safe_dump(doc))
    return p


def test_canonical_flow_is_clean():
    """corpus-sweep: the shipped flow must have zero self-assertion holes
    (M1 hardened them all to program_exit_zero)."""
    assert G.find_self_assertion_holes(_FLOW) == []


def test_self_assertion_hole_flagged(tmp_path):
    doc = {"steps": [{
        "id": 99, "name": "Bogus self-assert",
        "required_outputs": ["reports/x/result.json"],
        "gate": {"json_field_true": {"file": "reports/x/result.json",
                                     "field": "ok", "expect": True}},
    }]}
    holes = G.find_self_assertion_holes(_write(tmp_path, doc))
    assert len(holes) == 1 and holes[0]["step"] == 99


def test_self_assert_in_all_of_without_checker_flagged(tmp_path):
    doc = {"steps": [{
        "id": 100, "name": "all_of self-assert",
        "required_outputs": ["reports/y/r.json"],
        "gate": {"all_of": [
            {"files_exist": ["reports/y/r.json"]},
            {"json_field_true": {"file": "reports/y/r.json", "field": "shippable"}},
        ]},
    }]}
    holes = G.find_self_assertion_holes(_write(tmp_path, doc))
    assert len(holes) == 1


def test_boolean_paired_with_program_exit_zero_is_ok(tmp_path):
    doc = {"steps": [{
        "id": 101, "name": "Backed gate",
        "required_outputs": ["reports/z/r.json"],
        "gate": {"all_of": [
            {"json_field_true": {"file": "reports/z/r.json", "field": "all_proved"}},
            {"program_exit_zero": "real_substance_check . --json reports/z/audit.json"},
        ]},
    }]}
    assert G.find_self_assertion_holes(_write(tmp_path, doc)) == []


def test_boolean_on_non_produced_file_not_flagged(tmp_path):
    # json_field_true on a file the step does NOT produce (set by another step)
    # is not a self-assertion hole.
    doc = {"steps": [{
        "id": 102, "name": "Reads upstream file",
        "required_outputs": ["reports/own/out.json"],
        "gate": {"json_field_true": {"file": "reports/upstream/other.json",
                                     "field": "ready"}},
    }]}
    assert G.find_self_assertion_holes(_write(tmp_path, doc)) == []


def test_cli_pass_on_clean_flow():
    assert G.main([str(_FLOW)]) == 0


def test_cli_fail_on_hole(tmp_path):
    doc = {"steps": [{
        "id": 103, "name": "hole",
        "required_outputs": ["r.json"],
        "gate": {"json_field_true": {"file": "r.json", "field": "ok"}},
    }]}
    assert G.main([str(_write(tmp_path, doc))]) == 1


def test_cli_skip_on_missing_flow(tmp_path):
    assert G.main([str(tmp_path / "nope.yaml")]) == 2
