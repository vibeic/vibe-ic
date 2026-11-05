import json
from pathlib import Path
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow_engine as engine


def command_row(name, value=0, code=0, inputs=()):
    script = ("import json,pathlib,sys; "
              f"pathlib.Path(sys.argv[1]).write_text(json.dumps({{'errors': {value}}})); "
              f"sys.exit({code})")
    return {"name": name, "title": name, "when": "always", "legacy_id": {},
            "tool": {"kind": "command", "command": [sys.executable, "-c", script,
                                                       "{step}/metrics.json"], "inputs": list(inputs)},
            "checks": [{"metric": "errors", "operator": "<=", "limit": 0,
                        "source": {"file": "test tool limit", "line": 1}}]}


def execute(project, rows, **kwargs):
    route = {"entry_step": rows[0]["name"], "verify_through": rows[-1]["name"],
             "delivery_target": "rtl", "input_contract": "original"}
    return engine.run(project, table={"steps": rows}, route=route, **kwargs)


@pytest.mark.parametrize("code,value,inputs,status", [
    (3, 0, (), "FAIL"), (0, 2, (), "FAIL"),
    (0, 0, ("absent.v",), "NOT_MEASURED"), (0, 0, (), "PASS"),
])
def test_tool_result_against_original_limit(tmp_path, code, value, inputs, status):
    report = execute(tmp_path, [command_row("measure", value, code, inputs)])
    actual = json.loads((tmp_path / "steps/measure/result.json").read_text())
    assert actual["status"] == status
    assert report["steps"][0]["status"] == status
    assert actual["metrics"][0]["limit"] == 0


def test_failed_step_does_not_block_independent_tool(tmp_path):
    report = execute(tmp_path, [command_row("bad", 2), command_row("good")])
    assert [row["status"] for row in report["steps"]] == ["FAIL", "PASS"]


def test_from_preserves_earlier_folder_and_clears_later_results(tmp_path):
    rows = [command_row(name) for name in ("first", "middle", "last")]
    execute(tmp_path, rows)
    prior = (tmp_path / "steps/first/result.json").read_bytes()
    execute(tmp_path, rows, from_name="middle", to_name="middle")
    assert (tmp_path / "steps/first/result.json").read_bytes() == prior
    assert not (tmp_path / "steps/last/result.json").exists()
    assert json.loads((tmp_path / "steps/middle/result.json").read_text())["status"] == "PASS"


def test_added_table_entry_runs_without_runner_change(tmp_path):
    report = execute(tmp_path, [command_row("existing"), command_row("new_step")])
    assert report["pass"] == 2
    assert (tmp_path / "steps/new_step/tool.log").is_file()


def test_router_window_remains_bounded(tmp_path):
    import task_nature_route as router
    decision = router.route_decision_receipt(
        "Generate a combinational RTL inverter and lint it.",
        nature="spec_generation", delivery_target="rtl", requested_evidence="lint_validated")
    rows = [command_row(name) for name in ("requirements", "author", "lint", "floorplan")]
    for row, native in zip(rows, ("D1", "1", "2", "15")):
        row["legacy_id"] = {"registry": "", "native": [native]}
    report = engine.run(tmp_path, table={"steps": rows}, route=decision)
    assert [row["name"] for row in report["steps"]] == ["author", "lint"]
    assert report["route"] == decision
    with pytest.raises(ValueError, match="outside"):
        engine.run(tmp_path, table={"steps": rows}, route=decision, to_name="floorplan")


def test_missing_limit_never_becomes_pass(tmp_path):
    row = command_row("unlimited")
    row["checks"][0]["limit"] = None
    assert execute(tmp_path, [row])["steps"][0]["status"] == "NOT_MEASURED"


def test_native_decimal_and_infinite_path_group_values(tmp_path):
    checks = [{"metric": "slack", "operator": ">=", "limit": Decimal("0")}]
    measured = engine.measure(checks, {"slack": Decimal("1.2")}, {}, {"always": True})
    assert measured[0]["status"] == "PASS"
    infinite = engine.measure(checks, {"slack": float("inf")}, {}, {"always": True})
    assert infinite[0]["status"] == "NOT_MEASURED"
    path = tmp_path / "result.json"
    engine.write_json(path, {"metrics": measured, "absent_path_group": float("inf")})
    assert json.loads(path.read_text())["absent_path_group"] == "Infinity"
