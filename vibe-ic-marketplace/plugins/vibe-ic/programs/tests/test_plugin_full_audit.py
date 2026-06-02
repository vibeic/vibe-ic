"""Tests for plugin_full_audit (deterministic D1 + D2 of the have-full-test audit).

Pins: D1 flags an untested non-synth program but NOT an overlay-covered synth;
D2 flags a file-presence-only gate WITHOUT a by-design note but NOT one WITH it,
and flags a dangling program_exit_zero target.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import plugin_full_audit as A  # noqa: E402


def _mk_plugin(tmp_path, programs, tests, flow_yaml=None):
    plug = tmp_path / "plug"
    (plug / "programs" / "tests").mkdir(parents=True)
    (plug / "flow").mkdir(parents=True)
    for name, body in programs.items():
        (plug / "programs" / f"{name}.py").write_text(body or "x = 1\n")
    for name, body in tests.items():
        (plug / "programs" / "tests" / f"{name}.py").write_text(body or "")
    (plug / "flow" / "phase1_phase2_phase3.yaml").write_text(
        flow_yaml if flow_yaml is not None else "steps: []\n")
    return plug


# ---- D1 ----
def test_d1_untested_nonsynth_is_a_gap(tmp_path):
    plug = _mk_plugin(tmp_path, {"foo_check": None}, {})  # no test for foo_check
    d1 = A.audit_d1(plug)
    assert d1["passed"] is False
    assert "foo_check" in d1["untested_gaps"]


def test_d1_tested_program_passes(tmp_path):
    plug = _mk_plugin(tmp_path, {"foo_check": None},
                      {"test_foo_check": "import foo_check\n"})
    d1 = A.audit_d1(plug)
    assert d1["passed"] is True
    assert d1["untested_gaps"] == []


def test_d1_synth_without_test_is_overlay_covered_not_gap(tmp_path):
    plug = _mk_plugin(tmp_path, {"zigbee_protocol_synth": None}, {})
    d1 = A.audit_d1(plug)
    assert d1["passed"] is True
    assert "zigbee_protocol_synth" in d1["synth_overlay_covered"]
    assert d1["untested_gaps"] == []


# ---- D2 ----
_FLOW_PRESENCE_ONLY = """\
steps:
  - id: 1
    name: "Bare presence gate"
    gate:
      files_exist: ["out/x.def"]
"""

_FLOW_PRESENCE_BY_DESIGN = """\
steps:
  - id: 1
    name: "Documented presence gate"
    # AUDIT NOTE (by-design, not a gap): substance verified downstream.
    gate:
      files_exist: ["out/x.def"]
"""

_FLOW_DANGLING = """\
steps:
  - id: 1
    name: "Dangling checker"
    gate:
      program_exit_zero: "does_not_exist_check . --json r.json"
"""


def test_d2_presence_only_without_note_is_gap(tmp_path):
    plug = _mk_plugin(tmp_path, {}, {}, flow_yaml=_FLOW_PRESENCE_ONLY)
    d2 = A.audit_d2(plug)
    assert d2["passed"] is False
    assert any(f["check"] == "file_presence_only_gate" for f in d2["findings"])


def test_d2_presence_only_with_by_design_note_passes(tmp_path):
    plug = _mk_plugin(tmp_path, {}, {}, flow_yaml=_FLOW_PRESENCE_BY_DESIGN)
    d2 = A.audit_d2(plug)
    assert not any(f["check"] == "file_presence_only_gate" for f in d2["findings"])


def test_d2_dangling_gate_target_is_gap(tmp_path):
    plug = _mk_plugin(tmp_path, {}, {}, flow_yaml=_FLOW_DANGLING)
    d2 = A.audit_d2(plug)
    assert any(f["check"] == "dangling_gate_target" for f in d2["findings"])


# ---- canonical: the shipped plugin passes D1 (no non-synth untested) + D2 ----
def test_shipped_plugin_d2_clean():
    plugin = Path(__file__).resolve().parent.parent.parent
    # D2 must be clean on the shipped tree (D1 may transiently show new
    # programs mid-development; D2 is the structural invariant).
    d2 = A.audit_d2(plugin)
    assert d2["passed"], d2["findings"]
