import pytest

from flow_ppa_comparison import compare_fields, trial_fields


def test_report_keeps_losses_ties_and_signed_slack_delta():
    rows = compare_fields({"area": 90, "power": 3, "setup_slack": -.1, "cpu_hours": 2},
                          {"area": 100, "power": 2, "setup_slack": -.3, "cpu_hours": 2})
    assert rows["area"]["verdict"] == "SUBJECT_BETTER"
    assert rows["area"]["delta_pct"] == -10
    assert rows["power"]["verdict"] == "BASELINE_BETTER"
    assert rows["power"]["delta_pct"] == 50
    assert rows["setup_slack"]["delta"] == pytest.approx(.2)
    assert rows["setup_slack"]["delta_pct"] is None
    assert rows["cpu_hours"]["verdict"] == "TIE"
    assert rows["hold_slack"]["verdict"] == "NOT_MEASURED"


@pytest.mark.parametrize("value", [None, True, float("inf"), float("nan")])
def test_unavailable_measurement_never_becomes_zero_or_a_win(value):
    row = compare_fields({"power": value}, {"power": 2})["power"]
    assert row["verdict"] == "NOT_MEASURED"
    assert row["delta"] is None


def test_native_zero_denominator_and_missing_cpu_are_explicit():
    values = trial_fields({"metrics": {"power__total": 0}})
    row = compare_fields(values, {"power": 0, "cpu_hours": 3})
    assert row["power"]["verdict"] == "TIE"
    assert row["power"]["delta_pct"] is None
    assert row["cpu_hours"]["verdict"] == "NOT_MEASURED"
