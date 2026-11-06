"""The repair and precheck must consume the same sign-off evidence as STA/antenna."""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import general_precheck as precheck  # noqa: E402
from antenna_report_check import main as antenna_main, build_argv  # noqa: E402
from eda_report_audit import _check_antenna  # noqa: E402




def test_tapeout_antenna_delegate_reads_canonical_signed_report(tmp_path):
    reports = tmp_path / "reports/phase3"
    reports.mkdir(parents=True)
    (reports / "antenna.rpt").write_text(
        "# OpenROAD check_antennas\n"
        "antenna check: 2 net violations, 2 pin violations\n"
        "antenna clean: NO\n"
        "[INFO ANT-0002] Found 2 net violations.\n"
        "[INFO ANT-0001] Found 2 pin violations.\n"
        "# tail of the same tool log\n"
        "[INFO ANT-0002] Found 2 net violations.\n"
        "[INFO ANT-0001] Found 2 pin violations.\n"
        + "# tool output\n" * 20)
    (reports / "antenna_violations.rpt").write_text(
        "Net: signal\n  Pin: gate/I\n  Layer: Metal2\n" * 20)
    step = next(s for s in precheck.LADDER
                if s.step_id == "Checker.KLayoutAntenna")
    out = reports / "verdict.json"
    rc = antenna_main(build_argv([str(tmp_path), *step.delegate.argv_tail,
                                  "--json", str(out)]))
    verdict = json.loads(out.read_text())
    assert rc != 0
    assert verdict["summary"]["violations"] == 4
    assert all(f["rule"] != "ANTENNA_NO_TOOL_SIGNATURE"
               for f in verdict["findings"])
    assert verdict["summary"]["files_found"] == 1


def test_antenna_report_log_tail_does_not_double_count(tmp_path):
    reports = tmp_path / "reports/phase3"
    reports.mkdir(parents=True)
    (reports / "antenna.rpt").write_text(
        "# OpenROAD check_antennas\n"
        "antenna check: 1 net violations, 1 pin violations\n"
        "antenna clean: NO\n"
        "[INFO ANT-0002] Found 1 net violations.\n"
        "[INFO ANT-0001] Found 1 pin violations.\n"
        "# full log tail\n"
        "[INFO ANT-0002] Found 1 net violations.\n"
        "[INFO ANT-0001] Found 1 pin violations.\n"
        + "# tool output\n" * 20)
    out = reports / "verdict.json"
    assert antenna_main(build_argv([str(tmp_path), "--under",
                                    "reports/phase3/antenna.rpt",
                                    "--json", str(out)])) != 0
    assert json.loads(out.read_text())["summary"]["violations"] == 2


def test_antenna_denial_sentences_cannot_declare_zero_or_clean(tmp_path):
    reports = tmp_path / "reports/phase3"
    reports.mkdir(parents=True)
    (reports / "antenna.rpt").write_text(
        "# OpenROAD check_antennas diagnostic transcript\n"
        "Not Found 0 net violations.\n"
        "Not Found 0 pin violations.\n"
        "antenna not clean: YES\n"
        "Antenna check: not 0 net violations, 0 pin violations\n"
        + "# tool output\n" * 20)
    result = _check_antenna(tmp_path)
    assert result.passed is False
    assert result.summary["violations"] is None
    assert any(f.rule == "ANTENNA_VIOLATION_COUNT" for f in result.findings)
