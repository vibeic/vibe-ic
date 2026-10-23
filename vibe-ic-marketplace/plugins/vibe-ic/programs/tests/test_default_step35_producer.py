"""Real Default35 -> declared DFM producer -> complete content consumer.

Only neutral input files and explicit post-producer corruption are used;
no EDA/native/IC acquisition or physical signoff is claimed.
"""
import json
from pathlib import Path

import pytest
import phase3_one_shot_runner as R
import flow_declared_producer_run as D


DEF = """VERSION 5.8 ;
DESIGN neutral ;
VIAS 2 ;
- via_single + VIARULE vr + CUTSIZE 200 200 + ROWCOL 1 1 ;
- via_dual + VIARULE vr + CUTSIZE 200 200 + ROWCOL 1 2 ;
END VIAS
NETS 2 ;
- n1 ( u1 A ) + ROUTED met1 ( 0 0 ) via_single ( 10 10 ) {extra} ;
- n2 ( u2 B ) + ROUTED met2 ( 5 5 ) via_dual ;
END NETS
END DESIGN
"""


def _write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.mark.parametrize("case", [
    "current", "advisory", "missing_inputs", "missing_report",
    "malformed_report", "failed_report",
])
def test_default_step35_invokes_its_declared_advisory_producer(tmp_path, monkeypatch, case):
    project = tmp_path / "project"
    body = DEF.format(extra=" ".join("via_single ( 10 10 )" for _ in range(18)) if case == "advisory" else "")
    _write(project, "phase3/stage3/pnr/routed.def", body)
    _write(project, "phase3/stage3/pnr/filled.def", body + "# neutral filler placement\n")
    _write(project, "reports/phase3/density.json", '{"filler_instances":4,"row_utilization_pct":99.0}\n')
    _write(project, "reports/phase3/density.rpt", "neutral density instrument record\n")
    _write(project, "reports/phase2/gates/metal_fill_density.json", '{"summary":{"pass":true,"errors_count":0}}\n')
    observed = []
    actual = D.run_for_step

    def record(root, step, *args, **kwargs):
        result = actual(root, step, *args, **kwargs)
        observed.append(result)
        report = root / "reports/phase3/dfm_screen.json"
        if case == "missing_report":
            report.unlink(missing_ok=True)
        elif case == "malformed_report":
            report.write_text('{"verdict":"PASS"}\n')
        elif case == "failed_report":
            failed = json.loads(report.read_text())
            failed["verdict"] = "FAIL"
            report.write_text(json.dumps(failed) + "\n")
        return result

    monkeypatch.setattr(D, "run_for_step", record)
    if case == "missing_inputs":
        (project / "reports/phase3/density.rpt").unlink()
    row = R._default_pnr_rows(project, "neutral", None, "SOURCE_CONTROL_ONLY", ["35"])
    report = project / "reports/phase3/dfm_screen.json"
    document = json.loads(report.read_text()) if report.is_file() else None
    _write(project, "API_OBSERVATION.json", json.dumps({
        "case": case, "status": row.status, "detail": row.detail,
        "producer_census": observed, "document": document,
        "scope": "neutral source-only Default DFM activation and full content consumer"}, indent=2))
    if case == "missing_inputs":
        assert row.status == "NOT_MEASURED", row.detail
        assert observed == [], "required input absence must stop before the producer"
        return
    assert len(observed) == 1
    producer = observed[0]
    assert producer["population"] == 1, producer
    assert producer["executed"] == 1, producer
    assert producer["results"][0]["program"] == "dfm_screen_check"
    assert producer["results"][0]["executed"] is True
    if case in {"missing_report", "malformed_report", "failed_report"}:
        assert row.status != "PASS", row.detail
        receipt = json.loads(
            (project / "reports/phase3/default_steps/35/backend_result.json").read_text())
        assert receipt["verdict"] != "PASS", receipt
        if case == "failed_report":
            assert receipt["canonical_step_result"]["status"] == "FAIL", receipt
    else:
        assert row.status == "PASS", row.detail
        assert document["verdict"] == ("PASS_WITH_ADVISORIES" if case == "advisory" else "PASS")
        assert all(item["status"] == "FOUNDRY_SIDE" for item in document["foundry_side"])
        assert producer["results"][0]["rc"] == (1 if case == "advisory" else 0)
        assert producer["results"][0]["enforcement"] == "advisory"
        receipt = json.loads((project / "reports/phase3/default_steps/35/backend_result.json").read_text())
        assert receipt["canonical_step_result"]["status"] == "PASS", receipt
