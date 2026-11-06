"""T73 controls for declared outputs and measured gate evidence."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

PROGRAMS = Path(__file__).resolve().parent.parent
ROOT = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS / "tests"))

import flow_compliance_check as flow
import matrix_d7_artifact_graph as d7


def _steps():
    return {str(row["id"]): row for row in yaml.safe_load(
        (ROOT / "flow/phase1_phase2_phase3.yaml").read_text())["steps"]}




def test_missing_promised_rtl_fails_p0(tmp_path):
    assert flow._p0_umbrella_status(None, [])[0] == "FAIL"
    audit = tmp_path / "reports/audit/phase23_completion_audit.json"
    proc = subprocess.run([sys.executable, str(PROGRAMS / "flow_compliance_check.py"),
                           str(tmp_path), "--strict", "--json", str(audit)],
                          capture_output=True, text=True, timeout=180)
    assert proc.returncode != 0
    p0 = next(s for s in json.loads(audit.read_text())["steps"]
              if s["id"] == "P0")
    assert p0["status"] == "NOT_APPLICABLE"
    assert p0["declared_by"].startswith("ASKED_BEFORE_PRODUCER:")




def test_phase1_dynamic_l_docs_are_declared_and_seen_by_d7():
    names = ("L14_PROTOCOL_VERSIONING", "L15_ENCODING_TABLES",
             "L16_COMPLIANCE_PROPERTIES", "L17_CHANNEL_SIGNAL_CATALOG",
             "L18_INTERCONNECT_TOPOLOGY", "L20_DFT_SCAN_TOPOLOGY",
             "L23_SECURITY_REQUIREMENTS", "L24_SIGNOFF",
             "L25_RELIABILITY_MISSION_PROFILE",
             "L26_MECHANICAL_TRANSDUCTION", "L27_MEMORY_MODULE_SPD")
    declared = {r["path"] for r in _steps()["D1"]["program_outputs"]}
    import ast
    written = {"/".join(p) for p in d7._collect_writes(ast.parse(
        (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()))}
    for name in names:
        path = f"phase1/generated_docs/{name}.json"
        assert path in declared
        assert path in written


def test_step1_names_all_declaration_producers():
    producers = {r["program"] for r in _steps()["1"]["program_outputs"]
                 if r["path"] == "plugin_output/declaration.json"}
    assert {"ip_catalog_pull", "spec_declaration_emit",
            "arith_declaration_emit"} <= producers


def test_synthesis_inputs_match_runner_order():
    inputs = _steps()["9"]["required_inputs"]
    assert not any(str(r.get("from")) == "7" and
                   "constraints/*.sdc" in r.get("path", "") for r in inputs)
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    assert src.index('step_yosys_synth, project') < src.index(
        'plan.append(step_sdc_gen(project, args.top_name, ic_class))')


def test_step7_orders_the_stage1_population_it_audits():
    steps = _steps()
    assert {"1", "3"} <= {str(x) for x in steps["7"]["blocks_on"]}
    assert "6" not in {str(x) for x in steps["7"]["blocks_on"]}
    assert any("stage1_compliance" in str(clause) for clause in
               steps["7"]["gate"]["all_of"])




def test_phase3_strict_failure_is_not_reported_as_info():
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    start = src.index('if _fc.returncode != 0:')
    end = src.index('except Exception as _fc_exc:', start)
    block = src[start:end]
    assert '_audit_tier == "FAIL"' in block
    assert '"ERROR"' in block
    assert '[INFO] flow_compliance refresh returned' not in block
