"""Native advisory ASIL floors and unmeasured diagnostic coverage."""
from pathlib import Path
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fmeda_fault_injection_coverage as fi
import fmeda_coverage_check as reader


@pytest.mark.parametrize("asil,detected,expected", [("A", 0, "PASS"), ("QM", 0, "PASS"),
    ("B", 89, "FAIL"), ("B", 90, "PASS"), ("C", 96, "FAIL"), ("C", 97, "PASS"),
    ("D", 98, "FAIL"), ("D", 99, "PASS")])
def test_original_asil_floors(asil, detected, expected):
    report = {"measured": True, "injected_faults": 100, "detected_faults": detected,
              "baseline_valid": True}
    result = reader.check(report, asil, None)
    assert result["verdict"] == expected
    assert result["recomputed_dc_pct"] == detected


def test_no_native_faults_is_unmeasured_even_with_advisory_floor():
    spec = fi.MechanismSpec("parity", "encode", "d", "c", "decode", "c", None, "err", 1, 2)
    results = fi.parse_injection_results("GOLDEN DATA 0 DETECT 0 MATCH NA CODE_KNOWN 1\n")
    report = fi.build_report(spec, results, "A", None)
    assert report["verdict"] == "NOT_MEASURED" and report["diagnostic_coverage_pct"] is None
