"""Current Default D1 entrance and honest expert-handoff controls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

PROGRAMS = Path(__file__).resolve().parents[1]


def _raw_docs_project(project):
    source = PROGRAMS / "tests/fixtures/r0929_dieid_basis_self_tapeout_die/input/step_0_5ic_answers.json"
    answers = json.loads(source.read_text())
    answers["answer_provenance"]["synthesis_area_budget"] = {
        "answered_by": "owner", "citation": "Neutral front-door input for D1 entrance control"}
    answers["operator_template"] = {"path": "input/submission_template_source", "slot": "s1"}
    path = project / "input/step_0_5ic_answers.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(answers, sort_keys=True) + "\n")
    template = project / "input/submission_template_source"
    template.mkdir()
    (template / "s1.yaml").write_text(
        "DIE_AREA: [0, 0, 1000, 2000]\nCORE_AREA: [26, 26, 974, 1974]\n"
        "SEAL_RING_WIDTH: 26\nFP_SIZING: absolute\npads: [pad_n0, pad_n1, pad_s0]\n")
    docs = project / "input/docs"
    docs.mkdir()
    (docs / "design.md").write_text("# design\n")


def test_canonical_default_frontdoor_produces_d1_and_waits_for_expert(tmp_path):
    project = tmp_path / "subject"
    _raw_docs_project(project)
    environment = {k: v for k, v in os.environ.items()
                   if not k.startswith("VIBEIC_EXECUTION")}
    command = [sys.executable, "-I", str(PROGRAMS / "vibe_ic_one_shot_runner.py"),
               str(project), "--route", "ic", "--execution-mode", "default",
               "--skip-analog", "--no-dashboard", "--exit-step", "D1"]
    measurement = {"argv": command}
    started = time.monotonic()
    try:
        with (tmp_path / "frontdoor.log").open("w") as log:
            completed = subprocess.run(command, env=environment, stdout=log,
                                       stderr=subprocess.STDOUT, text=True, timeout=240)
        measurement["returncode"] = completed.returncode
    except subprocess.TimeoutExpired:
        measurement["timed_out"] = True
        raise
    finally:
        measurement["elapsed_s"] = time.monotonic() - started
        (tmp_path / "frontdoor-command.json").write_text(
            json.dumps(measurement, indent=2) + "\n")
    phase1 = json.loads((project / "reports/orchestrator/phase1_one_shot.json").read_text())
    docs = sorted((project / "phase1/generated_docs").glob("L*.json"))
    assert len(docs) >= 13, phase1
    assert phase1["step_0_5ic"] == "ran", phase1
    # Default owns the 0.5ic producer directly.  Its canonical reports and
    # gate receipts are published in the project tree; there is no Controller
    # arm or adoption receipt to consume.
    adoption = list((project / "reports/execution").glob("*/0.5ic/adoption.json"))
    assert adoption == []
    for name in ("submission_template", "tapeout_declaration"):
        report = project / "reports/phase1" / (name + ".json")
        assert report.is_file() and report.stat().st_size
        gate = project / ".vibeic-state/audit_receipts"
        assert any(path.is_file() for path in gate.rglob("*.json"))
    assert (project / "phase1/step_identity.json").is_file()
    expert = json.loads((project / "reports/audit/phase1/expert_parse_track.json").read_text())
    assert expert["ai_subtrack"]["status"] == "HANDOFF_EMITTED", expert
    assert phase1["verdict"] not in ("PASS", "PASS_WITH_WAIVERS"), phase1
    assert completed.returncode != 0
    frontdoor = json.loads((project / "reports/orchestrator/vibe_ic_one_shot.json").read_text())
    assert frontdoor["halted_at"] == "phase1", frontdoor
    assert frontdoor["verdict"] not in ("PASS", "PASS_WITH_WAIVERS")
    # The specific advisory belongs to the awaiting-signed-judgement branch;
    # a current canonical rejection may halt earlier. Assert the actual
    # downstream dispatch account in either case, not that branch's prose.
    downstream = [row for row in frontdoor["phases"]
                  if row["name"] in ("phase2", "phase3")]
    assert downstream == [{"name": "phase2", "verdict": "SKIPPED", "rc": 0},
                          {"name": "phase3", "verdict": "SKIPPED", "rc": 0}]
    for report in ("phase2_one_shot.json", "phase3_one_shot.json"):
        assert not (project / "reports/orchestrator" / report).exists()
    assert not (project / "phase2").exists()
    assert not (project / "phase3").exists()
    assert not list((project / "reports/execution").glob("*/*/plan.json"))
    disclosure = phase1["canonical_producer"]
    assert disclosure["step_id"] == "D1"
    assert disclosure["controller_qualification"] == "NOT_MEASURED"
    assert disclosure["mode"] == "default"
    assert disclosure["execution"] == "single-local-driver"
    assert "NO_REGISTERED_PROVIDER" not in json.dumps(phase1)
    assert not list((project / "reports/execution").glob("*/D1/adoption.json"))
