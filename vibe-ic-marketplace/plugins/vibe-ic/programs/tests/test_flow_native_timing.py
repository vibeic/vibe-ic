import json
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow_native_timing as reader
import librelane_prelayout as native


CAL = Path(__file__).resolve().parents[1] / "calibration"
SOURCE = "/tmp/mig92/cal/cal_full.sdc"


def corner(root, name="tt", *, positive=False, checks=True):
    directory = root / name
    directory.mkdir(parents=True)
    log = "sta_prepnr_sdc_bad_port_positive.log" if positive else "sta_prepnr_linked_clean_negative.log"
    report = ("sta_prepnr_check_setup_clock_only_positive.rpt" if positive
              else "sta_prepnr_check_setup_clean_negative.rpt")
    shutil.copyfile(CAL / log, directory / "sta.log")
    if checks:
        shutil.copyfile(CAL / report, directory / "checks.rpt")
    return directory


@pytest.fixture(autouse=True)
def no_case_calibration(monkeypatch):
    def forbidden(_):
        raise AssertionError("Native report reading must not recalibrate the tool")
    monkeypatch.setattr(native.instrument_calibration, "assert_calibrated", forbidden)


def test_missing_reports_never_become_zero(tmp_path):
    result = reader.read_sta_reports(tmp_path, {})
    assert result["metrics"] == {}
    assert result["reports"] == []
    assert "No native STA corner reports" in result["detail"]


def test_log_without_check_setup_never_becomes_zero(tmp_path):
    directory = tmp_path / "tt"
    directory.mkdir()
    (directory / "sta.log").write_text(f"Reading design constraints file at '{SOURCE}'\n")
    assert reader.read_sta_reports(tmp_path, {"PNR_SDC_FILE": SOURCE})["metrics"] == {}


def test_native_empty_warning_sections_report_zero(tmp_path):
    directory = corner(tmp_path)
    result = reader.read_sta_reports(tmp_path, {"PNR_SDC_FILE": SOURCE})
    assert result["metrics"] == {"unconstrained_endpoints": 0,
                                  "unconstrained_required_paths": 0,
                                  "invalid_timing_exceptions": 0}
    assert set(result["reports"]) == {str(directory / "checks.rpt"), str(directory / "sta.log")}


def test_native_warning_counts_sum_across_corners(tmp_path):
    corner(tmp_path, "tt", positive=True)
    corner(tmp_path, "ss", positive=True)
    result = reader.read_sta_reports(tmp_path, {"PNR_SDC_FILE": "/tmp/mig92/cal/cal_bad_port.sdc"})
    assert result["metrics"] == {"unconstrained_endpoints": 4,
                                  "unconstrained_required_paths": 6,
                                  "invalid_timing_exceptions": 2}


def test_native_log_can_supply_the_reported_check_setup_section(tmp_path):
    corner(tmp_path, checks=False)
    result = reader.read_sta_reports(tmp_path, {"PNR_SDC_FILE": SOURCE})
    assert result["metrics"]["unconstrained_required_paths"] == 0


def test_a_missing_corner_section_cannot_publish_a_partial_zero(tmp_path):
    corner(tmp_path, "tt")
    directory = tmp_path / "ss"
    directory.mkdir()
    (directory / "sta.log").write_text(f"Reading design constraints file at '{SOURCE}'\n")
    result = reader.read_sta_reports(tmp_path, {"PNR_SDC_FILE": SOURCE})
    assert result["metrics"] == {}
    assert "ss: native check_setup section is missing" in result["detail"]


def test_a_missing_native_corner_directory_cannot_publish_a_partial_zero(tmp_path):
    corner(tmp_path, "tt")
    (tmp_path / "state_out.json").write_text(json.dumps({"metrics": {
        "timing__setup__ws__corner:tt": 1, "timing__setup__ws__corner:ss": 2}}))
    result = reader.read_sta_reports(tmp_path, {"PNR_SDC_FILE": SOURCE, "STA_CORNERS": ["tt", "ss"]})
    assert result["metrics"] == {}
    assert "ss: native check_setup section is missing" in result["detail"]


def test_native_output_supplies_the_deduplicated_corner_population(tmp_path):
    corner(tmp_path, "tt")
    config = {"PNR_SDC_FILE": SOURCE, "STA_CORNERS": ["tt", "min_tt", "max_tt"]}
    assert reader.read_sta_reports(tmp_path, config)["metrics"] == {}
    (tmp_path / "state_out.json").write_text(json.dumps({"metrics": {"timing__setup__ws__corner:tt": 1}}))
    assert reader.read_sta_reports(tmp_path, config)["metrics"]["unconstrained_endpoints"] == 0


def test_diagnostics_use_the_sdc_actually_read_not_a_matching_basename(tmp_path):
    directory = corner(tmp_path)
    with (directory / "sta.log").open("a") as stream:
        stream.write(f"\nWarning 366: /other/cal_full.sdc line 2, port 'foreign' not found.\n")
        stream.write(f"Warning 366: {SOURCE} line 3, port 'actual' not found.\n")
    result = reader.read_sta_reports(tmp_path, {"PNR_SDC_FILE": SOURCE})
    assert result["metrics"]["invalid_timing_exceptions"] == 1


def test_unknown_sdc_source_is_unmeasured_even_with_a_clean_report(tmp_path):
    corner(tmp_path)
    result = reader.read_sta_reports(tmp_path, {"PNR_SDC_FILE": "/another/cal_full.sdc"})
    assert "invalid_timing_exceptions" not in result["metrics"]
    assert result["metrics"]["unconstrained_endpoints"] == 0


def test_native_config_and_state_supply_the_actual_sdc_context(tmp_path):
    corner(tmp_path)
    (tmp_path / "config.json").write_text(json.dumps({"PNR_SDC_FILE": None, "FALLBACK_SDC": SOURCE}))
    (tmp_path / "state_in.json").write_text(json.dumps({"sdc": "/another/generated.sdc"}))
    result = reader.read_sta_reports(tmp_path, {})
    assert result["metrics"]["invalid_timing_exceptions"] == 0
    assert str(tmp_path / "config.json") in result["reports"]
    assert str(tmp_path / "state_in.json") in result["reports"]


def test_existing_parser_calls_keep_calibration_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(native.instrument_calibration, "assert_calibrated", calls.append)
    assert native.check_setup_counts("check_setup -verbose\n") == {}
    assert native.sdc_diagnostics("", Path(SOURCE)) == []
    assert calls == ["librelane_prelayout::check_setup_counts", "librelane_prelayout::sdc_diagnostics"]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Compare actual native STA reports with expected counts.")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--expected", type=json.loads, required=True)
    args = parser.parse_args()
    result = reader.read_sta_reports(args.directory, {})
    assert result["metrics"] == args.expected, result
    print(json.dumps(result, indent=2))
