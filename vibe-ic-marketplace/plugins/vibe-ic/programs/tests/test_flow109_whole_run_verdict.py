import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark_evidence_publish as publish
import flow109
import flow_compliance_check as audit


def _carrier(tmp_path, statuses, fpga=None):
    rows = [{"id": i, "position": n, "name": i, "when": "always"} for n, i in enumerate(statuses)]
    rows += [{"id": i, "position": 100, "name": i, "when": "fpga_early"} for i in fpga or {}]
    root = tmp_path / "reports/flow109"
    (root / "default_rows").mkdir(parents=True)
    (root / "plan.json").write_text(json.dumps({"rows": rows}))
    for row_id, status in {**statuses, **(fpga or {})}.items():
        if status:
            (root / "default_rows" / (row_id + ".json")).write_text(json.dumps(
                {"default_row_status": status, "completed": status == "PASS"}))
    return tmp_path


def test_every_selected_row_pass_is_pass(tmp_path):
    assert flow109.whole_run_verdict(_carrier(tmp_path, {"D1": "PASS", "D2": "PASS"}))["verdict"] == "PASS"


@pytest.mark.parametrize("second, verdict", [("FAIL", "FAIL"), ("NOT_MEASURED", "NOT_MEASURED"),
                                             (None, "NOT_MEASURED")])
def test_a_row_short_of_pass_decides(tmp_path, second, verdict):
    answer = flow109.whole_run_verdict(_carrier(tmp_path, {"D1": "PASS", "D2": second}))
    assert answer["verdict"] == verdict


def test_fpga_rows_report_apart_and_do_not_count(tmp_path):
    answer = flow109.whole_run_verdict(_carrier(tmp_path, {"D1": "PASS"}, {"D18": None}))
    assert answer["verdict"] == "PASS"
    assert [row["id"] for row in answer["fpga_rows"]] == ["D18"]


def test_audit_writes_the_row_verdict_and_publish_reads_it(tmp_path):
    project = _carrier(tmp_path, {"D1": "PASS"})
    assert audit.main([str(project)]) == 0
    assert publish._audit_verdict(project, None)[0] == "PASS"


def test_a_row_short_of_pass_refuses_publish(tmp_path):
    project = _carrier(tmp_path, {"D1": None})
    assert audit.main([str(project)]) == 1
    assert publish._audit_verdict(project, None)[0] == "NOT_MEASURED"


def test_scoped_audit_keeps_the_scoped_path(tmp_path, monkeypatch):
    project = _carrier(tmp_path, {"D1": "PASS"})
    monkeypatch.setattr(flow109, "whole_run_verdict", lambda _: pytest.fail("scoped pass judged the run"))
    audit.main([str(project), "--stage", "4", "--lenient"])
