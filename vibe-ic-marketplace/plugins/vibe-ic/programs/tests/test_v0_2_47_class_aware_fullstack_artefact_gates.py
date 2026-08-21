"""v0.2.47 class-aware full-stack-artefact gate regressions.

Pins ORGANIC-20260605-fullstack-byte-oracle-inapplicable-to-datapath-
primitive (#419): the final-audit P0 set applied byte-protocol artefact
gates (byte-oracle golden vectors, regmap field depth/bit layout,
submodule conformance, metadata substance) to EVERY class — structurally
unsatisfiable for a no-protocol datapath/combinational primitive, so a
functionally perfect design carried a guaranteed overall FAIL.

The fix is DOUBLE-KEYED and fail-closed: the five artefact gates SKIP
(with an explicit N/A reason) only when the registry-matched class says
command_protocol_applicable=false AND the L docs positively record a
no-opcode / no-regmap input. Either key absent -> every gate runs.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flow_compliance_check as fcc  # noqa: E402
import ic_class_profile as icp  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402

GATES = fcc._CLASS_SKIPPABLE_FULLSTACK_ARTEFACT_GATES


# ── _ldocs_record_no_opcodes evidence helper ──────────────────────────────

def _stage(tmp_path, l3=None, l4=None, legacy=False):
    # #419 REOPEN: the CANONICAL runner layout is phase1/generated_docs/
    # (_path_layout.generated_docs_dir). The original fixtures self-built
    # the root generated_docs/ path and thereby MIRRORED the helper's
    # wrong-path bug — fixtures must match the runner's real layout.
    gd = (tmp_path / "generated_docs") if legacy \
        else (tmp_path / "phase1" / "generated_docs")
    gd.mkdir(parents=True, exist_ok=True)
    if l3 is not None:
        (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(l3))
    if l4 is not None:
        (gd / "L4_REGMAP.json").write_text(json.dumps(l4))
    return tmp_path


def test_no_generated_docs_is_fail_closed(tmp_path):
    assert fcc._ldocs_record_no_opcodes(tmp_path) is False


def test_no_opcodes_no_registers_is_positive_evidence(tmp_path):
    p = _stage(tmp_path, l3={"opcodes": []}, l4={"registers": []})
    assert fcc._ldocs_record_no_opcodes(p) is True


def test_opcodes_present_keeps_gates(tmp_path):
    p = _stage(tmp_path, l3={"opcodes": [{"op": "0x05"}]},
               l4={"registers": []})
    assert fcc._ldocs_record_no_opcodes(p) is False


def test_registers_present_keeps_gates_unless_explicit_flag(tmp_path):
    p = _stage(tmp_path, l3={"opcodes": []},
               l4={"registers": [{"name": "CTRL"}]})
    assert fcc._ldocs_record_no_opcodes(p) is False
    p2 = _stage(tmp_path, l3={"opcodes": []},
                l4={"registers": [{"name": "CTRL"}],
                    "register_map_present": False})
    assert fcc._ldocs_record_no_opcodes(p2) is True


def test_unreadable_ldoc_is_fail_closed(tmp_path):
    p = _stage(tmp_path, l3={"opcodes": []}, l4={"registers": []})
    (tmp_path / "phase1" / "generated_docs" / "L3_extra.json").write_text(
        "{not json")
    assert fcc._ldocs_record_no_opcodes(p) is False


def test_legacy_root_layout_still_supported(tmp_path):
    p = _stage(tmp_path, l3={"opcodes": []}, l4={"registers": []},
               legacy=True)
    assert fcc._ldocs_record_no_opcodes(p) is True


def test_real_runner_arbiter_project_skips_artefact_gates():
    """#419 REOPEN acceptance — assert against a REAL runner output
    layout, not a hand-built fixture (the original fixtures mirrored the
    wrong-path bug). Skips honestly when the local artifact is absent."""
    import pytest
    real = require_corpus("cvdp_example_cleanroom_v0244/work/cvdp_agentic_fixed_arbiter_0001")
    if not (real / "phase1" / "generated_docs").is_dir():
        pytest.skip("real runner artifact not present on this machine")
    skips = fcc._class_skipped_gates(real)
    for g in GATES:
        assert g in skips, g
        assert "#419" in skips[g]


def test_nested_command_lists_are_counted(tmp_path):
    p = _stage(tmp_path,
               l3={"protocol": {"command_set": [{"cmd": "READ"}]}},
               l4={"registers": []})
    assert fcc._ldocs_record_no_opcodes(p) is False


# ── _class_skipped_gates double-keyed skip ────────────────────────────────

def _prim_profile(project):
    return {"ic_class": "digital_arithmetic_primitive"}


def _pin_icp(monkeypatch):
    # the suite contains tests that evict 'ic_class_profile' from
    # sys.modules; pin OUR module object so fcc's call-time inner import
    # resolves the same object the patch landed on.
    monkeypatch.setitem(sys.modules, "ic_class_profile", icp)


def test_primitive_class_plus_no_opcode_docs_skips_artefact_gates(
        tmp_path, monkeypatch):
    p = _stage(tmp_path, l3={"opcodes": []}, l4={"registers": []})
    _pin_icp(monkeypatch)
    monkeypatch.setattr(icp, "detect_ic_class", _prim_profile)
    skips = fcc._class_skipped_gates(p)
    for g in GATES:
        assert g in skips, g
        assert "#419" in skips[g]
        assert "no opcodes" in skips[g] or "no-opcode" in skips[g]


def test_primitive_class_with_opcode_docs_keeps_artefact_gates(
        tmp_path, monkeypatch):
    p = _stage(tmp_path, l3={"opcodes": [{"op": "0x01"}]},
               l4={"registers": []})
    _pin_icp(monkeypatch)
    monkeypatch.setattr(icp, "detect_ic_class", _prim_profile)
    skips = fcc._class_skipped_gates(p)
    for g in GATES:
        assert g not in skips, g


def test_unknown_class_keeps_every_gate(tmp_path, monkeypatch):
    p = _stage(tmp_path, l3={"opcodes": []}, l4={"registers": []})
    _pin_icp(monkeypatch)
    monkeypatch.setattr(icp, "detect_ic_class",
                        lambda project: {"ic_class": "unknown"})
    assert fcc._class_skipped_gates(p) == {}


def test_protocol_class_keeps_artefact_gates(tmp_path, monkeypatch):
    # a class with command_protocol_applicable=True must keep all five
    p = _stage(tmp_path, l3={"opcodes": []}, l4={"registers": []})
    reg = json.loads(
        (Path(fcc.__file__).parent / "ic_class_registry.json").read_text())
    proto = next(c["name"] for c in reg["classes"]
                 if c.get("command_protocol_applicable") is True)
    _pin_icp(monkeypatch)
    monkeypatch.setattr(icp, "detect_ic_class",
                        lambda project: {"ic_class": proto})
    skips = fcc._class_skipped_gates(p)
    for g in GATES:
        assert g not in skips, (proto, g)


def test_functional_gates_never_in_artefact_skip_set():
    # the primitive-appropriate set must keep gating: lint/synth/latch/
    # conformance core gates are not skippable via this mechanism
    for core in ("rtl_hygiene_lint", "spec_conformance_check"):
        assert core not in GATES
