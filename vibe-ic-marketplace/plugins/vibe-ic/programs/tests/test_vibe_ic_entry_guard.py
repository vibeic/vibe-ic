#!/usr/bin/env python3
"""Tests for vibe_ic_entry_guard.py.

Covers:
- PASS when any runner evidence file is present.
- FAIL when no evidence is present.
- --allow-direct-agent turns FAIL into WARN rc=0.
- --strict rc=1 vs default rc=0 on FAIL.
- missing project dir returns rc=2.
"""
from __future__ import annotations

import json
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
GUARD = PROGRAMS / "vibe_ic_entry_guard.py"
DISPATCH = PROGRAMS / "benchmark_dispatch.py"
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import l_doc_generator_stamp as generator_stamp
import _entry_attestation as entry_attestation
import vibe_ic_entry_guard as entry_guard
import phase1_one_shot_runner as phase1_runner
from _entry_guard_fixture import prompt_report_document

_GATES_SPEC = importlib.util.spec_from_file_location(
    "entry_attestation_gates_atomic",
    PROGRAMS.parent / "benchmark" / "gates_atomic.py")
assert _GATES_SPEC and _GATES_SPEC.loader
gates_atomic = importlib.util.module_from_spec(_GATES_SPEC)
_GATES_SPEC.loader.exec_module(gates_atomic)


def run(args, cwd=None, env=None):
    cp = subprocess.run([sys.executable, str(GUARD), *args],
                        capture_output=True, text=True,
                        cwd=str(cwd) if cwd else None, env=env)
    return cp.returncode, cp.stdout, cp.stderr


def _test_ledger(tmp_path: Path) -> Path:
    state = tmp_path / "external-state"
    state.mkdir(mode=0o700)
    return state / "entry.jsonl"


def _record_test_attestation(project: Path, ledger: Path,
                             rc: int = 0):
    return entry_attestation.record_completed_run(
        project, runner="phase1_one_shot_runner", completion_rc=rc,
        report=project / "reports" / "phase1_one_shot.json",
        ledger_path_override=ledger)


def _valid_orchestrator_report(project: Path):
    return {"phase": "vibe-ic", "project": str(project), "verdict": "PASS",
            "phases": [
                {"name": "phase1", "verdict": "PASS", "rc": 0},
                {"name": "phase2", "verdict": "SKIPPED", "rc": 0},
                {"name": "analog", "verdict": "SKIPPED", "rc": 0},
                {"name": "phase3", "verdict": "SKIPPED", "rc": 0},
                {"name": "mixed_signal", "verdict": "SKIPPED", "rc": 0},
            ]}


def _valid_phase1_report(project: Path):
    return {"phase": 1, "project": str(project), "verdict": "PASS",
            "mode": "docs", "delegated_to": "phase1_doc_one_shot_runner",
            "delegated_rc": 0}


def _valid_prompt_phase1_report(project: Path):
    """The envelope emitted by phase1_one_shot_runner's prompt branch."""
    return prompt_report_document(project)


def _valid_layer_doc(content=None,
                     emitter="phase1_one_shot_runner._seed_structural_ports"):
    doc = {
        "fields": {"ic_name": "TopModule"},
    }
    if content:
        doc.update(content)
    return generator_stamp.stamp(doc, emitter=emitter)


def test_pass_with_orchestrator_report():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "reports" / "orchestrator"
        rep.mkdir(parents=True)
        (rep / "vibe_ic_one_shot.json").write_text(
            json.dumps(_valid_orchestrator_report(td)))
        rc, out, err = run([str(td)])
        assert rc == 0
        assert "PASS" in out


@pytest.mark.parametrize("rel", [
    "reports/orchestrator/phase1_one_shot.json",
    "reports/phase1_one_shot.json",
])
def test_pass_with_phase1_report(rel):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / rel
        rep.parent.mkdir(parents=True)
        rep.write_text(json.dumps(_valid_phase1_report(td)))
        rc, out, err = run([str(td)])
        assert rc == 0


def test_pass_with_prompt_mode_phase1_report():
    """Prompt mode has producer-owned ``steps``, not docs delegation fields."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # Match phase1_one_shot_runner's actual output location as well as its
        # StepResult-derived envelope.
        rep = td / "reports" / "phase1_one_shot.json"
        rep.parent.mkdir(parents=True)
        rep.write_text(json.dumps(_valid_prompt_phase1_report(td)))
        rc, out, err = run([str(td)])
        assert rc == 0, err


def test_strict_rejects_handwritten_prompt_envelope_without_runner_attestation():
    """A reconstructable report in the run tree is not process provenance."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "reports" / "phase1_one_shot.json"
        rep.parent.mkdir(parents=True)
        rep.write_text(json.dumps(_valid_prompt_phase1_report(td)))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1, (out, err)


def test_pass_with_failed_docs_mode_phase1_report():
    """A failed run still proves the canonical runner was the entry point."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "reports" / "orchestrator" / "phase1_one_shot.json"
        rep.parent.mkdir(parents=True)
        report = _valid_phase1_report(td)
        report.update({"verdict": "FAIL", "delegated_rc": 1})
        rep.write_text(json.dumps(report))
        rc, out, err = run([str(td)])
        assert rc == 0, err


def test_pass_with_l1_datasheet():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gd = td / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L1_DATASHEET.json").write_text(json.dumps(_valid_layer_doc()))
        rc, out, err = run([str(td)])
        assert rc == 0


def test_strict_rejects_public_stamp_without_runner_attestation():
    """Calling the public stamp API cannot impersonate a completed runner."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gd = td / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        forged = generator_stamp.stamp(
            {"fields": {"ic_name": "TopModule"}},
            emitter="phase1_one_shot_runner._seed_structural_ports")
        (gd / "L1_DATASHEET.json").write_text(json.dumps(forged))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1, (out, err)


def test_strict_accepts_latest_external_runner_attestation(tmp_path):
    project = tmp_path / "project"
    report = project / "reports" / "phase1_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps(_valid_prompt_phase1_report(project)))
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(
        json.dumps(_valid_layer_doc()))
    ledger = _test_ledger(tmp_path)
    _record_test_attestation(project, ledger)

    verdict, findings = entry_guard.audit(
        project, strict=True, ledger_path_override=ledger)
    assert verdict == "PASS", findings


def test_strict_rejects_same_path_replacement_after_attestation(tmp_path):
    project = tmp_path / "project"
    report = project / "reports" / "phase1_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps(_valid_prompt_phase1_report(project)))
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    l1 = docs / "L1_DATASHEET.json"
    l1.write_text(json.dumps(_valid_layer_doc()))
    ledger = _test_ledger(tmp_path)
    _record_test_attestation(project, ledger)

    original = l1.read_text()
    l1.unlink()
    l1.write_text(original)
    verdict, findings = entry_guard.audit(
        project, strict=True, ledger_path_override=ledger)
    assert verdict == "FAIL"
    assert "stat identity changed" in findings[0].detail


def test_strict_rejects_replayed_nonce(tmp_path):
    project = tmp_path / "project"
    report = project / "reports" / "phase1_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps(_valid_prompt_phase1_report(project)))
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(
        json.dumps(_valid_layer_doc()))
    ledger = _test_ledger(tmp_path)
    _record_test_attestation(project, ledger)
    line = ledger.read_text()
    ledger.write_text(line + line)
    ledger.chmod(0o600)

    verdict, findings = entry_guard.audit(
        project, strict=True, ledger_path_override=ledger)
    assert verdict == "FAIL"
    assert "replayed nonce" in findings[0].detail


def test_strict_cli_ignores_home_and_xdg_ledger_redirects(tmp_path):
    project = tmp_path / "project"
    report = project / "reports" / "phase1_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps(_valid_prompt_phase1_report(project)))
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(
        json.dumps(_valid_layer_doc()))
    fake_ledger = _test_ledger(tmp_path)
    _record_test_attestation(project, fake_ledger)
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "fake-home")
    env["XDG_STATE_HOME"] = str(fake_ledger.parent)

    rc, out, err = run([str(project), "--strict"], env=env)
    assert rc == 1
    assert "ledger unavailable" in err


def test_strict_rejects_ledger_mode_and_symlink_anomalies(tmp_path):
    project = tmp_path / "project"
    report = project / "reports" / "phase1_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps(_valid_prompt_phase1_report(project)))
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(
        json.dumps(_valid_layer_doc()))
    ledger = _test_ledger(tmp_path)
    _record_test_attestation(project, ledger)
    ledger.chmod(0o644)
    verdict, findings = entry_guard.audit(
        project, strict=True, ledger_path_override=ledger)
    assert verdict == "FAIL"
    assert "mode 0600" in findings[0].detail

    ledger.chmod(0o600)
    ledger.parent.chmod(0o755)
    verdict, findings = entry_guard.audit(
        project, strict=True, ledger_path_override=ledger)
    assert verdict == "FAIL"
    assert "mode 0700" in findings[0].detail

    ledger.parent.chmod(0o700)
    target = ledger.with_name("target.jsonl")
    ledger.rename(target)
    ledger.symlink_to(target)
    verdict, findings = entry_guard.audit(
        project, strict=True, ledger_path_override=ledger)
    assert verdict == "FAIL"
    assert "ledger unavailable" in findings[0].detail


def test_phase1_attestation_write_failure_preserves_flow_rc_and_warns(
        tmp_path, monkeypatch, capsys):
    project = tmp_path / "project"
    report = project / "reports" / "phase1_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text("{}\n")
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text("{}\n")

    def fail(*args, **kwargs):
        raise entry_attestation.AttestationError("read-only user state")

    monkeypatch.setattr(entry_attestation, "record_completed_run", fail)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert phase1_runner._finalize_entry_attestation(project, report, 0) == 0
    assert "ENTRY_ATTESTATION_NOT_RECORDED" in capsys.readouterr().err


def test_real_phase1_front_door_writes_canonical_attestation_and_strict_passes(
        tmp_path):
    """Prove-by-run, with its originating-host test ledger cleaned afterward."""
    project = tmp_path / "project"
    prompt = project / "input" / "phase1_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# a 4-bit up counter with a synchronous reset\n")
    canonical = entry_attestation.ledger_path(project)
    env = os.environ.copy()
    env.pop("PYTEST_CURRENT_TEST", None)  # exercise the production writer path
    try:
        cp = subprocess.run(
            [sys.executable, str(PROGRAMS / "phase1_one_shot_runner.py"),
             str(project), "--mode", "prompt", "--ic-name", "TST_CHIP"],
            capture_output=True, text=True, env=env)
        assert cp.returncode == 0, cp.stderr
        guarded = subprocess.run(
            [sys.executable, str(GUARD), str(project), "--strict"],
            capture_output=True, text=True, env=env)
        assert guarded.returncode == 0, guarded.stderr
        assert "PASS" in guarded.stdout
    finally:
        canonical.unlink(missing_ok=True)


def test_shape_b_run_root_accepts_each_real_phase1_child_attestation(tmp_path):
    run_root = tmp_path / "run"
    project = run_root / "work" / "design_a"
    report = project / "reports" / "phase1_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps(_valid_prompt_phase1_report(project)))
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(
        json.dumps(_valid_layer_doc()))
    ledger = _test_ledger(tmp_path)
    _record_test_attestation(project, ledger)

    verdict, findings = entry_guard.audit(
        run_root, strict=True, ledger_path_override=ledger)
    assert verdict == "PASS", findings


def test_shape_c_actual_gate_producer_attests_and_new_doc_invalidates(tmp_path):
    run_root = tmp_path / "run"
    work = run_root / "work" / "Prob001"
    docs = work / "out" / "generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(
        _valid_layer_doc({"top_module": "TopModule"})))
    ledger = _test_ledger(tmp_path)
    step = {"verdict": "PASS", "rc": 0, "l9_rendered": True, "log": ""}
    gates_atomic.record_phase1_entry_attestation(
        work, "Prob001", 0, step, ledger_path_override=ledger)

    verdict, findings = entry_guard.audit(
        run_root, strict=True, ledger_path_override=ledger)
    assert verdict == "PASS", findings

    (docs / "L1_DATASHEET.json").write_text(json.dumps(_valid_layer_doc()))
    verdict, findings = entry_guard.audit(
        run_root, strict=True, ledger_path_override=ledger)
    assert verdict == "FAIL"
    assert "complete L-doc set differs" in findings[0].detail


@pytest.mark.parametrize("emitter", [
    "phase1_doc_one_shot_runner._write_l_doc",
    "render.render_layers",
    "cli._stub_l_docs_from_prose",
])
def test_pass_with_each_shipped_l_doc_writer_shape(emitter):
    """Accept direct, bundled-engine, and producer-owned re-export writers."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gd = td / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L1_DATASHEET.json").write_text(
            json.dumps(_valid_layer_doc(emitter=emitter)))
        rc, out, err = run([str(td)])
        assert rc == 0, err


def test_fail_strict():
    with tempfile.TemporaryDirectory() as td:
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1
        assert "no Vibe-IC runner evidence" in err


def test_fail_default_warn_rc0():
    with tempfile.TemporaryDirectory() as td:
        rc, out, err = run([str(td)])
        assert rc == 0
        assert "FAIL" in err


def test_allow_direct_agent_warn_rc0():
    with tempfile.TemporaryDirectory() as td:
        rc, out, err = run([str(td), "--allow-direct-agent"])
        assert rc == 0
        assert "WARN(direct-agent)" in out


def test_missing_dir_rc2():
    rc, out, err = run(["/tmp/nonexistent_vibe_ic_entry_guard_test"])
    assert rc == 2


def test_json_report():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        json_out = td / "report.json"
        rc, out, err = run([str(td), "--strict", "--json", str(json_out)])
        assert rc == 1
        data = json.loads(json_out.read_text())
        assert data["gate"] == "vibe_ic_entry_guard"
        assert data["verdict"] == "FAIL"
        assert data["findings_count"] == 1


# ---------------------------------------------------------------------------
# Shape-C per-problem phase1 evidence (open-benchmark-methodology § 7.5 rule 3).
#
# A Shape-C (atomic-micro-problem) run drives phase1_engine ONCE PER PROBLEM, so
# the fact-graph lands under <run>/work/<prob>/…/generated_docs/L*.json rather
# than at the run root. The guard originally had no branch for that layout and
# rejected fully-compliant Shape-C runs as direct-agent authoring.
#
# This is a guard-RELAXING branch, so per § 4.05 the NEGATIVE no-leak cases
# below are the load-bearing half: each sits JUST OUTSIDE the intended boundary
# and MUST still be caught.
# ---------------------------------------------------------------------------

def _shape_c(td: Path, rel: str, name: str, body: str | None = None):
    p = td / rel
    p.mkdir(parents=True, exist_ok=True)
    (p / name).write_text(body if body is not None
                          else json.dumps(_valid_layer_doc()))


# ---- POSITIVE: both layouts gates_atomic.py itself accepts ----

def test_pass_shape_c_out_generated_docs():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/Prob001_zero/out/generated_docs", "L1_DATASHEET.json")
        rc, out, err = run([str(td)])
        assert rc == 0, err
        assert "PASS" in out


def test_pass_shape_c_phase1_proj_layout():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/Prob153_gshare/phase1_proj/phase1/generated_docs",
                 "L9_INTEGRATION_SPEC.json",
                 json.dumps(_valid_layer_doc({"top_module": "TopModule"})))
        rc, out, err = run([str(td)])
        assert rc == 0, err


# ---- POSITIVE: Shape-B per-design layouts -------------------------------

def test_pass_shape_b_orchestrator_report():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "work" / "design_a" / "reports" / "orchestrator"
        rep.mkdir(parents=True)
        (rep / "vibe_ic_one_shot.json").write_text(
            json.dumps(_valid_orchestrator_report(rep.parents[1])))
        rc, out, err = run([str(td)])
        assert rc == 0, err


def test_pass_shape_b_phase1_layer_doc():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/design_a/phase1/generated_docs",
                 "L1_DATASHEET.json")
        rc, out, err = run([str(td)])
        assert rc == 0, err


# ---- NEGATIVE no-leak (§ 4.05): boundary-outside, must STILL be caught ----

def test_noleak_bare_work_dir_still_caught():
    """Direct-agent authoring: RTL in work/ but phase1 never ran."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "work" / "Prob001_zero").mkdir(parents=True)
        (td / "work" / "Prob001_zero" / "sample.sv").write_text("module TopModule(); endmodule")
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1
        assert "no Vibe-IC runner evidence" in err


def test_noleak_empty_generated_docs_still_caught():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "work" / "Prob001_zero" / "out" / "generated_docs").mkdir(parents=True)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_non_layer_json_still_caught():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/Prob001_zero/out/generated_docs", "notes.json", '{"faked":true}')
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_backup_layer_doc_still_caught():
    """A stale .bak is not live phase1 output."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/Prob001_zero/out/generated_docs", "L1_DATASHEET.json.bak")
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_unnumbered_layer_name_still_caught():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/Prob001_zero/out/generated_docs", "Lfoo.json")
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_layer_doc_at_wrong_depth_still_caught():
    """A layer doc at the run root (not under work/<prob>/) must not qualify."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "generated_docs", "L1_DATASHEET.json")
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_directory_named_like_layer_doc_still_caught():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "work" / "Prob001_zero" / "out" / "generated_docs" /
         "L1_DATASHEET.json").mkdir(parents=True)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_shape_b_empty_work_design_still_caught():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "work" / "design_a").mkdir(parents=True)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


@pytest.mark.parametrize("name", ["Lfoo.json", "L1.json", "notes.json"])
def test_noleak_shape_b_fake_layer_names_still_caught(name):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/design_a/phase1/generated_docs", name)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


@pytest.mark.parametrize("rel", [
    "work/design_a/reports/orchestrator/summary.json",
    "work/design_a/reports/vibe_ic_one_shot.json",
    "work/design_a/orchestrator/vibe_ic_one_shot.json",
])
def test_noleak_shape_b_arbitrary_json_at_similar_depth_is_rejected(rel):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = td / rel
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"verdict": "PASS"}))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


@pytest.mark.parametrize("body", [
    "",
    "not json",
    json.dumps({"verdict": "PASS"}),
    json.dumps({"verdict": "PASS", "project": "/tmp/p"}),
])
def test_noleak_shape_b_fake_exact_report_is_rejected(body):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = (td / "work" / "design_a" / "reports" / "orchestrator" /
             "vibe_ic_one_shot.json")
        p.parent.mkdir(parents=True)
        p.write_text(body)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


@pytest.mark.parametrize("rel", [
    "phase1/generated_docs",
    "work/design_a/phase1/generated_docs",
    "work/Prob001_zero/out/generated_docs",
    "work/Prob001_zero/phase1_proj/phase1/generated_docs",
])
@pytest.mark.parametrize("body", [
    "",
    "not json",
    "{}",
    json.dumps({
        "_generator": {
            "plugin": "vibe-ic",
            "plugin_version": "1.10.48",
            "l_doc_taxonomy_digest": "0123456789ab",
            "l_doc_taxonomy_docs": 28,
            "emitter": "phase1_engine.render",
        }
    }),
    json.dumps({
        "doc_id": "L1",
        "_generator": {
            "plugin": "not-vibe-ic",
            "plugin_version": "1.10.48",
            "l_doc_taxonomy_digest": "0123456789ab",
            "l_doc_taxonomy_docs": 28,
            "emitter": "phase1_engine.render",
        }
    }),
])
def test_noleak_layer_doc_requires_substantive_generator_evidence(rel, body):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, rel, "L1_DATASHEET.json", body)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


@pytest.mark.parametrize(("rel", "body"), [
    ("reports/orchestrator/vibe_ic_one_shot.json",
     json.dumps({"verdict": "PASS"})),
    ("reports/phase1_one_shot.json", json.dumps({"verdict": "PASS"})),
])
def test_noleak_root_report_requires_canonical_envelope(rel, body):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = td / rel
        p.parent.mkdir(parents=True)
        p.write_text(body)
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_phase1_report_rejects_self_authored_claims():
    """A report must bind to this project and the real producer taxonomy."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = td / "reports" / "phase1_one_shot.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({
            "phase": 1,
            "project": "/different/run",
            "verdict": "BANANA",
            "mode": "fake",
            "delegated_to": "fake",
            "delegated_rc": 999,
        }))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_invalid_entry_evidence_blocks_the_benchmark_score_front_door(tmp_path):
    """Prove-by-run: strict failure stops dispatch before downstream gates."""
    run_dir = tmp_path / "run"
    report = run_dir / "reports" / "orchestrator" / "phase1_one_shot.json"
    report.parent.mkdir(parents=True)
    body = _valid_phase1_report(run_dir)
    body["project"] = str(tmp_path / "different-run")
    report.write_text(json.dumps(body))
    dataset = tmp_path / "dataset"
    dataset.mkdir()

    cp = subprocess.run(
        [sys.executable, str(DISPATCH), "verilogeval-v2", "--score",
         "--run", str(run_dir), "--dataset", str(dataset)],
        capture_output=True, text=True)
    output = cp.stdout + cp.stderr
    assert cp.returncode != 0
    assert "Vibe-IC entry guard FAILed" in output
    assert "blindness_audit:" not in output


@pytest.mark.parametrize(("field", "invalid"), [
    ("project", "/different/run"),
    ("verdict", "BANANA"),
    ("mode", "fake"),
    ("delegated_to", "fake"),
    ("delegated_rc", 999),
    ("delegated_rc", True),
])
def test_noleak_phase1_report_rejects_each_invalid_claim(field, invalid):
    """Each producer-owned field is load-bearing, not one broad shape test."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = td / "reports" / "orchestrator" / "phase1_one_shot.json"
        p.parent.mkdir(parents=True)
        body = _valid_phase1_report(td)
        body[field] = invalid
        p.write_text(json.dumps(body))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_prompt_report_verdict_must_derive_from_its_steps():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = td / "reports" / "orchestrator" / "phase1_one_shot.json"
        p.parent.mkdir(parents=True)
        body = _valid_prompt_phase1_report(td)
        body["verdict"] = "FAIL"
        p.write_text(json.dumps(body))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_layer_doc_rejects_invented_generator_provenance():
    """Well-shaped but invented generator values are not runner evidence."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gd = td / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L1_DATASHEET.json").write_text(json.dumps({
            "doc_id": "L1",
            "_generator": {
                "plugin": "vibe-ic",
                "plugin_version": "999.999.999",
                "l_doc_taxonomy_digest": "deadbeefcafe",
                "l_doc_taxonomy_docs": 999,
                "emitter": "invented.writer",
            },
        }))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


@pytest.mark.parametrize(("field", "invalid"), [
    ("plugin", "not-vibe-ic"),
    ("plugin_version", "999.999.999"),
    ("l_doc_taxonomy_digest", "deadbeefcafe"),
    ("l_doc_taxonomy_docs", 999),
    ("emitter", "vibe_ic_entry_guard.audit"),
    # This is a real shipped function with a real ``json.dump`` call, but it
    # is not an L-document producer and must not satisfy provenance.
    ("emitter", "ic_expert_db_capture.validate"),
])
def test_noleak_layer_doc_rejects_each_invented_stamp_field(field, invalid):
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gd = td / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        body = _valid_layer_doc()
        body["_generator"][field] = invalid
        (gd / "L1_DATASHEET.json").write_text(json.dumps(body))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


def test_noleak_layer_doc_rejects_noncanonical_taxonomy_filename():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gd = td / "work" / "design_a" / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L1_FAKE.json").write_text(json.dumps(_valid_layer_doc()))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
