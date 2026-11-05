from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flow_engine_timing import timing_summary


def report():
    return {"started_at": 0, "updated_at": 250, "completed_at": 230,
            "native_common_started_at": 10, "native_common_completed_at": 20,
            "common_tools_complete": True, "budget_seconds": 15,
            "steps": [
                {"name": "native", "timing_group": "librelane", "tool_ran": True,
                 "started_at": 10, "completed_at": 20, "tool_seconds": 9,
                 "program_seconds": 1, "ai_seconds": 1, "reviewed_at": 20},
                {"name": "independent", "timing_group": "other", "tool_ran": True,
                 "started_at": 12, "completed_at": 212, "tool_seconds": 199,
                 "program_seconds": 1, "ai_seconds": 1, "reviewed_at": 220}]}


def test_independent_job_and_review_do_not_extend_common_window():
    measured = timing_summary(report())
    assert measured["common_wall_seconds"] == 10
    assert measured["other_execution_wall_seconds"] == 200
    assert measured["wall_seconds"] == 230
    assert measured["runtime_status"] == "IN_BUDGET"


def test_common_review_remains_in_budget_and_pending_review_is_incomplete():
    value = report()
    value["steps"][0]["reviewed_at"] = 30
    assert timing_summary(value)["runtime_status"] == "OVER_BUDGET"
    value["steps"][0].update(ai_seconds=None, reviewed_at=None)
    measured = timing_summary(value)
    assert measured["runtime_status"] == "NOT_MEASURED"
    assert measured["common_reviews_pending"] == ["native"]


def test_overlapping_intervals_and_unknown_timing_are_separate():
    value = report()
    value["steps"].append({"name": "unknown", "timing_group": "other", "tool_ran": False,
                           "started_at": 15, "completed_at": 25,
                           "timing_complete": False, "unclassified_seconds": 10,
                           "queue_seconds": 7, "ai_seconds": 0})
    measured = timing_summary(value)
    assert measured["other_execution_wall_seconds"] == 200
    assert measured["other_wall_span_seconds"] == 200
    assert measured["timing_groups"]["other"]["program_seconds"] == 1
    assert measured["timing_groups"]["other"]["unclassified_seconds"] == 10
    assert measured["timing_groups"]["other"]["queue_seconds"] == 7


def test_terminal_refresh_does_not_extend_run_and_missing_legacy_bounds_are_unmeasured():
    value = report()
    before = timing_summary(value)
    value["updated_at"] = 10000
    assert timing_summary(value) == before
    del value["native_common_started_at"]
    measured = timing_summary(value)
    assert measured["common_wall_seconds"] is None
    assert measured["runtime_status"] == "NOT_MEASURED"


def test_supplied_budget_boundary_and_pending_common_tools():
    value = report()
    value["budget_seconds"] = 10
    assert timing_summary(value)["runtime_status"] == "IN_BUDGET"
    value["common_tools_complete"] = False
    assert timing_summary(value)["runtime_status"] == "NOT_MEASURED"


def test_missing_common_adapter_cannot_qualify_timing_but_native_disabled_is_distinct():
    value = report()
    value["steps"].append({"name": "equivalence", "timing_group": "librelane",
                           "tool_kind": "adapter", "tool_ran": False,
                           "native_steps": [], "ai_seconds": 0})
    measured = timing_summary(value)
    assert measured["runtime_status"] == "NOT_MEASURED"
    assert measured["common_timing_unmeasured_steps"] == ["equivalence"]
    value["steps"][-1]["native_steps"] = [{"name": "native optional check", "ran": False,
                                           "native_config_disabled": True}]
    assert timing_summary(value)["runtime_status"] == "IN_BUDGET"
