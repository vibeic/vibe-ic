"""Tests for flow_compliance_check.py — 33-step master gate."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "flow_compliance_check.py"


def _run(proj: Path, extra_args=()):
    r = subprocess.run(
        [sys.executable, str(PROG), str(proj), *extra_args],
        capture_output=True, text=True,
    )
    return r.returncode, r.stdout, r.stderr


def test_help_works():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "project_dir" in r.stdout.lower()


def test_empty_project_fails(tmp_path):
    """Empty project → many missing steps → strict should fail."""
    code, out, _ = _run(tmp_path, ("--strict",))
    assert code != 0


def test_strict_vs_lenient(tmp_path):
    """strict and lenient should differ in exit code tolerance."""
    strict_code, _, _ = _run(tmp_path, ("--strict",))
    lenient_code, _, _ = _run(tmp_path, ("--lenient",))
    # strict at least as strict as lenient
    assert strict_code >= lenient_code or strict_code != 0


def test_json_output_structure(tmp_path):
    j = tmp_path / "report.json"
    _run(tmp_path, ("--strict", "--json", str(j)))
    if j.exists():
        data = json.loads(j.read_text())
        assert isinstance(data, dict)


def test_nonexistent_project_errors(tmp_path):
    code, _, _ = _run(tmp_path / "does_not_exist")
    assert code != 0


# ---------------------------------------------------------------------------
# v0.55: optional_program_exit_zero predicate
# ---------------------------------------------------------------------------
sys.path.insert(0, str(PROG.parent))
import flow_compliance_check as _flow  # noqa: E402


def test_optional_predicate_skipped_when_condition_files_absent(tmp_path):
    """If none of the `condition_files_exist` paths exist, the program is NOT
    invoked — and W4 changed what that means for the verdict.

    This test used to assert `passed is True` for the clause below, with no
    `absent_condition_reason` on it. That was the property W4 reversed: an
    unmet condition means the clause CONCLUDED NOTHING, and until W4 it left
    no marker and no reason, so it was indistinguishable in the record from a
    clause that ran and found nothing.

    Both arms are kept here, because the pair is the actual contract: the
    program still does not run either way (that part never changed), and what
    decides the verdict is whether the clause DECLARED, at its wiring site, why
    an absent input is a genuine not-applicable.
    """
    undeclared = {
        "optional_program_exit_zero": {
            "command": "false",   # would always exit non-zero
            "condition_files_exist": ["never_exists.json"],
        }
    }
    passed, reasons = _flow._evaluate_gate(tmp_path, undeclared)
    assert passed is False, (
        "an unmet condition with no `absent_condition_reason` must FAIL: "
        "nothing to check is not a pass")
    assert "never_exists.json" in " ".join(reasons), (
        f"the FAIL must name the corpus that was empty: {reasons}")

    declared = {
        "optional_program_exit_zero": {
            **undeclared["optional_program_exit_zero"],
            "absent_condition_reason": (
                "Fixture clause: the trigger is a claim file a clean run "
                "legitimately never writes."),
        }
    }
    passed, reasons = _flow._evaluate_gate(tmp_path, declared)
    assert passed is True, "a declared not-applicable is still a pass"
    assert any(r.startswith(_flow._NOT_APPLICABLE_HINT_PREFIX)
               for r in reasons), (
        f"and it must leave a record saying it examined nothing: {reasons}")
    # `false` would have exited non-zero; neither arm ran it.
    assert not any(r.startswith(_flow._RAN_HINT_PREFIX) for r in reasons)


def test_optional_predicate_runs_when_condition_files_present(tmp_path,
                                                              monkeypatch):
    """Condition file exists → program runs → its exit code matters."""
    (tmp_path / "trigger.json").write_text("{}")
    spec_pass = {
        "optional_program_exit_zero": {
            "command": "any_program some args",
            "condition_files_exist": ["trigger.json"],
        }
    }
    spec_fail = {
        "optional_program_exit_zero": {
            "command": "any_program some args",
            "condition_files_exist": ["trigger.json"],
        }
    }
    # Mock the program runner so the test doesn't require a real plugin
    # program on disk. First call returns pass; second returns fail.
    calls = {"n": 0}

    def fake_run(project, cmd):
        calls["n"] += 1
        if calls["n"] == 1:
            return True, "ok"
        return False, "stub failure"
    monkeypatch.setattr(_flow, "_check_program_exit_zero", fake_run)
    p1, _ = _flow._evaluate_gate(tmp_path, spec_pass)
    p2, _ = _flow._evaluate_gate(tmp_path, spec_fail)
    assert p1 is True
    assert p2 is False
    assert calls["n"] == 2  # both invocations actually ran


def test_optional_predicate_glob_condition(tmp_path, monkeypatch):
    """Glob pattern in condition_files_exist resolves correctly."""
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "stuff.json").write_text("{}")
    spec = {
        "optional_program_exit_zero": {
            "command": "any_program",
            "condition_files_exist": ["reports/*.json"],
        }
    }
    monkeypatch.setattr(_flow, "_check_program_exit_zero",
                        lambda project, cmd: (True, "ok"))
    passed, _ = _flow._evaluate_gate(tmp_path, spec)
    assert passed is True


def test_optional_predicate_missing_command_fails(tmp_path):
    spec = {
        "optional_program_exit_zero": {
            "condition_files_exist": ["something.json"],
        }
    }
    passed, reasons = _flow._evaluate_gate(tmp_path, spec)
    assert passed is False
    assert any("missing" in r.lower() and "command" in r.lower() for r in reasons)


def test_optional_predicate_missing_condition_fails(tmp_path):
    """Without condition_files_exist the gate is malformed — refuse it.
    Otherwise authors might forget the condition list and turn an
    intentional skip into a silent always-pass."""
    spec = {
        "optional_program_exit_zero": {
            "command": "true",
        }
    }
    passed, reasons = _flow._evaluate_gate(tmp_path, spec)
    assert passed is False


# ---------------------------------------------------------------------------
# v0.70 Item 1: Pre-PnR Yosys auditor gate.
# ---------------------------------------------------------------------------
_GOOD_YS = """\
read_verilog -sv rtl/top.sv
hierarchy -check -top top
proc; opt; fsm; opt
memory; opt
techmap
hilomap -hicell TIEHI Y -locell TIELO Y
synth -flatten
write_verilog synth/netlist.v
"""

_BAD_YS_NO_HILOMAP = """\
read_verilog -sv rtl/top.sv
hierarchy -check -top top
techmap
synth -flatten
write_verilog synth/netlist.v
"""

_BAD_YS_WRONG_ORDER = """\
read_verilog -sv rtl/top.sv
hilomap -hicell TIEHI Y -locell TIELO Y
techmap
synth -flatten
write_verilog synth/netlist.v
"""


def test_find_synth_ys_prefers_scripts_over_root(tmp_path):
    """`scripts/synth.ys` wins over a root-level `.ys` file."""
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "synth.ys").write_text("# scripts version\n")
    (tmp_path / "synth.ys").write_text("# root version\n")
    found = _flow._find_synth_ys(tmp_path)
    assert found is not None
    assert found.name == "synth.ys"
    assert "scripts" in str(found)


def test_find_synth_ys_returns_none_when_absent(tmp_path):
    assert _flow._find_synth_ys(tmp_path) is None


def test_yosys_gate_pass_when_ys_is_well_formed(tmp_path):
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "synth.ys").write_text(_GOOD_YS)
    passed, reasons = _flow._run_yosys_gates(tmp_path)
    assert passed is True
    assert reasons == []


def test_yosys_gate_skipped_when_no_ys_file(tmp_path):
    """A project with no .ys at all is not a FAIL — some flows don't use
    Yosys. Returned reasons list is empty so the synthetic result isn't
    injected."""
    passed, reasons = _flow._run_yosys_gates(tmp_path)
    assert passed is True
    assert reasons == []


def test_yosys_gate_fail_on_missing_hilomap(tmp_path):
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "synth.ys").write_text(_BAD_YS_NO_HILOMAP)
    passed, reasons = _flow._run_yosys_gates(tmp_path)
    assert passed is False
    # Remediation must mention hilomap + DRT-0305 + the tie-cell rationale.
    joined = "\n".join(reasons)
    assert "hilomap" in joined
    assert "DRT-0305" in joined
    assert "scripts/synth.ys" in joined


def test_yosys_gate_fail_on_wrong_order(tmp_path):
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "synth.ys").write_text(_BAD_YS_WRONG_ORDER)
    passed, reasons = _flow._run_yosys_gates(tmp_path)
    assert passed is False
    # Auditor output should propagate line numbers / ordering complaints.
    joined = "\n".join(reasons)
    assert "hilomap" in joined.lower() or "techmap" in joined.lower()


def test_flow_compliance_skip_yosys_gates_flag(tmp_path):
    """`--skip-yosys-gates` suppresses the synthetic step even when the
    .ys would otherwise fail. The rest of the flow still runs (and will
    fail on missing artefacts)."""
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "synth.ys").write_text(_BAD_YS_NO_HILOMAP)
    # With the flag: the synthetic "Pre-PnR Yosys auditor gate" row must
    # NOT appear in the output.
    code_skip, out_skip, _ = _run(tmp_path, ("--strict",
                                             "--skip-yosys-gates"))
    assert "Pre-PnR Yosys auditor gate" not in out_skip
    # Without the flag: the synthetic row MUST appear.
    code_nosk, out_nosk, _ = _run(tmp_path, ("--strict",))
    assert "Pre-PnR Yosys auditor gate" in out_nosk
    # Either way the empty-project flow fails overall (many missing
    # stage-3 steps), so we only assert the visibility difference.
    assert code_nosk != 0


def test_flow_compliance_skip_yosys_gates_on_stage1(tmp_path):
    """--stage 1 never reaches PnR, so the Yosys gate must be auto-off
    even when a broken .ys is present. This prevents legitimate Phase-1
    drafts from being blocked by a missing hilomap."""
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "synth.ys").write_text(_BAD_YS_NO_HILOMAP)
    code, out, _ = _run(tmp_path, ("--strict", "--stage", "1"))
    assert "Pre-PnR Yosys auditor gate" not in out


def test_flow_compliance_yosys_gate_injects_fail_row(tmp_path):
    """End-to-end: a project with a broken .ys must cause
    flow_compliance_check itself to return FAIL at the synthetic row,
    carrying the specific hilomap remediation text."""
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "synth.ys").write_text(_BAD_YS_NO_HILOMAP)
    code, out, err = _run(tmp_path, ("--strict",))
    assert code != 0
    combined = out + err
    assert "Pre-PnR Yosys auditor gate" in combined
    assert "DRT-0305" in combined  # remediation string must surface


def test_flow_compliance_yosys_gate_help_lists_flag():
    """--help must document the new escape hatch."""
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "--skip-yosys-gates" in r.stdout


def test_missing_required_hint_resolves_phase1_layout(tmp_path):
    """spm clean-run (2026-07-11) — the completion-audit's
    `missing_required_artifacts` HINT must resolve Phase-1 artifacts at their
    canonical phase1/ (reports/phase1/) locations, not only the legacy root
    layout. Before the fix, a from-scratch run whose Phase 1 wrote
    generated_docs → phase1/generated_docs, extraction_patterns.json → phase1/,
    and the coverage reports → reports/phase1/ was FALSELY told those 3 were
    'missing'. Only the genuinely-absent optional waivers.json should remain."""
    (tmp_path / "phase1" / "generated_docs").mkdir(parents=True)
    (tmp_path / "reports" / "phase1").mkdir(parents=True)
    (tmp_path / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text("{}")
    (tmp_path / "phase1" / "extraction_patterns.json").write_text("{}")
    (tmp_path / "reports" / "phase1"
     / "extraction_coverage_report.md").write_text("# coverage\n")
    (tmp_path / "reports" / "phase1"
     / "extraction_coverage_report.json").write_text("{}")

    _run(tmp_path, ("--strict",))  # verdict is FAIL (sparse project) — irrelevant
    audit = tmp_path / "reports" / "audit" / "phase23_completion_audit.json"
    assert audit.is_file(), "completion audit JSON must be emitted"
    missing = json.loads(audit.read_text())["missing_required_artifacts"]
    # The 3 artifacts that DO exist under phase1/ must NOT be flagged missing.
    assert "generated_docs" not in missing
    assert "extraction_patterns.json" not in missing
    assert "reports/extraction_coverage_report.md" not in missing
    assert "reports/extraction_coverage_report.json" not in missing
    # waivers.json is genuinely absent (root-only, optional) → still listed.
    assert "waivers.json" in missing


def test_missing_required_hint_flags_genuinely_absent(tmp_path):
    """Complement: when a Phase-1 artifact exists at NEITHER the phase1/ nor the
    root layout, the hint MUST still flag it (the fix widens WHERE we look, it
    does not suppress a genuine absence)."""
    _run(tmp_path, ("--strict",))  # empty project — nothing present
    audit = tmp_path / "reports" / "audit" / "phase23_completion_audit.json"
    assert audit.is_file()
    missing = json.loads(audit.read_text())["missing_required_artifacts"]
    for label in ("generated_docs", "extraction_patterns.json", "waivers.json",
                  "reports/extraction_coverage_report.md"):
        assert label in missing
