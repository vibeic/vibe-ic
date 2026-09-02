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
from _entry_guard_fixture import prompt_report_document


def run(args, cwd=None):
    cp = subprocess.run([sys.executable, str(GUARD), *args],
                        capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    return cp.returncode, cp.stdout, cp.stderr


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
        rc, out, err = run([str(td), "--strict"])
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
        rc, out, err = run([str(td), "--strict"])
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
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0, err


def test_pass_with_failed_docs_mode_phase1_report():
    """A failed run still proves the canonical runner was the entry point."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "reports" / "orchestrator" / "phase1_one_shot.json"
        rep.parent.mkdir(parents=True)
        report = _valid_phase1_report(td)
        report.update({"verdict": "FAIL", "delegated_rc": 1})
        rep.write_text(json.dumps(report))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0, err


def test_pass_with_l1_datasheet():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        gd = td / "phase1" / "generated_docs"
        gd.mkdir(parents=True)
        (gd / "L1_DATASHEET.json").write_text(json.dumps(_valid_layer_doc()))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0


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
        rc, out, err = run([str(td), "--strict"])
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
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0, err
        assert "PASS" in out


def test_pass_shape_c_phase1_proj_layout():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/Prob153_gshare/phase1_proj/phase1/generated_docs",
                 "L9_INTEGRATION_SPEC.json",
                 json.dumps(_valid_layer_doc({"top_module": "TopModule"})))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0, err


# ---- POSITIVE: Shape-B per-design layouts -------------------------------

def test_pass_shape_b_orchestrator_report():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "work" / "design_a" / "reports" / "orchestrator"
        rep.mkdir(parents=True)
        (rep / "vibe_ic_one_shot.json").write_text(
            json.dumps(_valid_orchestrator_report(rep.parents[1])))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0, err


def test_pass_shape_b_phase1_layer_doc():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        _shape_c(td, "work/design_a/phase1/generated_docs",
                 "L1_DATASHEET.json")
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0, err


def test_pass_program_first_projects_orchestrator_report():
    """benchmark_dispatch stores per-problem one-shot projects under
    <run>/projects while candidates wait behind AI review."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        project = td / "projects" / "fixed_point_adder"
        rep = project / "reports" / "orchestrator"
        rep.mkdir(parents=True)
        (rep / "vibe_ic_one_shot.json").write_text(
            json.dumps(_valid_orchestrator_report(project)))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 0, err


def test_noleak_program_first_project_report_is_bound_to_its_project():
    """A copied report naming another project is not runner evidence."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        project = td / "projects" / "fixed_point_adder"
        rep = project / "reports" / "orchestrator"
        rep.mkdir(parents=True)
        other = td / "projects" / "different_design"
        (rep / "vibe_ic_one_shot.json").write_text(
            json.dumps(_valid_orchestrator_report(other)))
        rc, out, err = run([str(td), "--strict"])
        assert rc == 1
        assert "no Vibe-IC runner evidence" in err


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


#: The guard's OWN refusal line, as it prints it. Asserted alongside the
#: dispatcher's wrapper sentence so a refusal that came from somewhere ELSE in
#: `cmd_score` cannot be read as this guard having answered.
_GUARD_SAID = "no Vibe-IC runner evidence found"

#: `cmd_score`'s refusal when the clean-room metadata is absent. Named so the
#: test that keeps that path ALIVE reads as a pin rather than a coincidence.
_PRECONDITION_SAID = "canonical scoring requires the clean-room metadata"


def _canonical_solve_run(tmp_path, bench="verilogeval-v2", fmt="verilogeval"):
    """A run directory that satisfies `cmd_score`'s PRECONDITIONS, so the gates
    downstream of them are actually reached. Returns (run_dir, dataset).

    WHY THIS EXISTS. `cmd_score` requires `<run>/.bench_config.json` — the
    clean-room metadata `--solve` writes — and refuses before it asks any gate
    anything. That precondition landed in `e9ec0ce1c` (2026-08-31), AFTER this
    test (`f6b0e77dd`, v1.10.64), and the test's fixture was not updated. From
    then on it measured the MISSING-FILE path and never the entry guard:
    MEASURED at `104b97dfd0fa`, rc 1 with
    `canonical scoring requires the clean-room metadata written by --solve`
    and no mention of the guard at all.

    NOTHING IS SWITCHED OFF TO GET HERE. The envelope is built by the
    dispatcher's OWN producer, `_prepare_general_solve_run` with `limit=0`
    (`full_dataset = limit == 0`), so the schema string, the bench key and the
    full-dataset flag are the producer's and cannot drift from what
    `cmd_score` reads back. `test_a_missing_bench_config_still_refuses_before_
    any_gate` below keeps the precondition itself alive.
    """
    import benchmark_dispatch as dispatch

    dataset = tmp_path / "dataset"
    dataset.mkdir()
    run_dir = tmp_path / "run"
    dispatch._prepare_general_solve_run(bench, dataset, run_dir, fmt, 0)
    return run_dir, dataset


def _score(run_dir, dataset, bench="verilogeval-v2"):
    cp = subprocess.run(
        [sys.executable, str(DISPATCH), bench, "--score",
         "--run", str(run_dir), "--dataset", str(dataset)],
        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


def _write_phase1_report(run_dir, project):
    report = run_dir / "reports" / "orchestrator" / "phase1_one_shot.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    body = _valid_phase1_report(run_dir)
    body["project"] = str(project)
    report.write_text(json.dumps(body))
    return report


def test_invalid_entry_evidence_blocks_the_benchmark_score_front_door(tmp_path):
    """Prove-by-run: strict failure stops dispatch before downstream gates.

    The refusal must be THE GUARD'S. rc != 0 alone is satisfied by every
    precondition upstream of it, which is exactly how this test spent its time
    measuring a missing file.
    """
    run_dir, dataset = _canonical_solve_run(tmp_path)
    _write_phase1_report(run_dir, tmp_path / "different-run")

    rc, output = _score(run_dir, dataset)
    assert rc != 0
    assert _GUARD_SAID in output, (
        f"dispatch refused, but not because the entry guard refused — this "
        f"run did not exercise the guard:\n{output}")
    assert "Vibe-IC entry guard FAILed" in output
    assert _PRECONDITION_SAID not in output, (
        f"the refusal came from the clean-room-metadata precondition, "
        f"upstream of the guard:\n{output}")
    assert "blindness_audit:" not in output


def test_valid_entry_evidence_is_accepted_and_dispatch_continues(tmp_path):
    """THE OTHER DIRECTION, and the half that proves the guard was ASKED.

    A guard that refused everything satisfies the test above. Same envelope,
    same command, and the ONLY difference is that the phase-1 report names the
    run it actually belongs to: the guard must PASS and dispatch must go on
    past it. MEASURED at `104b97dfd0fa`: `PASS: Vibe-IC structural runner-entry
    evidence found`, then the clean-room guard passes, and the run stops later
    for an unrelated reason it names.
    """
    run_dir, dataset = _canonical_solve_run(tmp_path)
    _write_phase1_report(run_dir, run_dir)

    _rc, output = _score(run_dir, dataset)
    assert "Vibe-IC entry guard FAILed" not in output, output
    assert _GUARD_SAID not in output, output
    assert "structural runner-entry evidence found" in output, (
        f"the entry guard did not report a PASS, so this arm does not show "
        f"that it was asked:\n{output}")
    assert "clean-room run dir" in output, (
        f"dispatch did not reach the gate AFTER the entry guard, so 'it "
        f"continued' is not shown:\n{output}")


def test_a_missing_bench_config_still_refuses_before_any_gate(tmp_path):
    """THE PATH THAT MUST NOT BE SWITCHED OFF.

    The repair above is to SATISFY `cmd_score`'s precondition so the guard is
    reached, never to remove it. Without `.bench_config.json` scoring must
    still refuse, and refuse for that reason — the run carries no evidence of
    having been produced by `--solve` at all.
    """
    run_dir, dataset = _canonical_solve_run(tmp_path)
    _write_phase1_report(run_dir, run_dir)
    (run_dir / ".bench_config.json").unlink()

    rc, output = _score(run_dir, dataset)
    assert rc != 0
    assert _PRECONDITION_SAID in output, output
    assert "Vibe-IC entry guard FAILed" not in output


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
