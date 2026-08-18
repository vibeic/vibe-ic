"""Substance tests for the M2 power-domain gate checkers.

Covers all three M2 checkers:
  * power_domain_crossing_check.py
  * level_shifter_required_check.py
  * isolation_cell_required_check.py

Each checker must INDEPENDENTLY verify that every power-domain crossing
enumerated in power_domain.json is protected by a matching level-shifter /
isolation entry, FAIL on any unprotected crossing, SKIP on genuinely-absent
data, and reject a producer's self-asserted PASS boolean that contradicts the
recomputed substance.

The exact silicon hazard these gates guard:
  * a voltage-mismatched crossing with NO level shifter
  * a power-gate-bordered crossing with NO isolation cell
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).parent.parent
sys.path.insert(0, str(PROG))

import power_domain_crossing_check as pdc  # noqa: E402
import level_shifter_required_check as lsr  # noqa: E402
import isolation_cell_required_check as icr  # noqa: E402

_DIR = "reports/analog/mixed_signal"


def _write(root, rel, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))
    return p


def _write_raw(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


# A power_domain.json with two crossings:
#   sig_ls : voltage mismatch (1.8 -> 1.0)            -> needs level shifter
#   sig_iso: into a power-gate-able domain            -> needs isolation
def _pd_two_crossings():
    return {
        "all_crossings_protected": True,
        "crossings": [
            {"net": "sig_ls", "from": "AON", "to": "ANALOG",
             "vdd_from": 1.8, "vdd_to": 1.0},
            {"net": "sig_iso", "from": "AON", "to": "GATED",
             "vdd_from": 1.8, "vdd_to": 1.8, "to_power_down": True},
        ],
    }


# =========================================================================
# power_domain_crossing_check
# =========================================================================
def test_pdc_pass_all_protected(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/level_shifter.json",
           {"all_required_inserted": True,
            "level_shifters": [{"net": "sig_ls", "cell": "LS_HL"}]})
    _write(tmp_path, f"{_DIR}/isolation.json",
           {"all_required_inserted": True,
            "isolation_cells": [{"net": "sig_iso", "cell": "ISO_AND"}]})
    rc = pdc.main([str(tmp_path), "--json", str(tmp_path / "out.json")])
    assert rc == 0
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["verdict"] == "PASS"


def test_pdc_fail_unprotected_voltage_crossing(tmp_path):
    # The exact silicon hazard: voltage-mismatched crossing, NO level shifter.
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    # level_shifter.json present but EMPTY (no cell for sig_ls)
    _write(tmp_path, f"{_DIR}/level_shifter.json",
           {"all_required_inserted": True, "level_shifters": []})
    _write(tmp_path, f"{_DIR}/isolation.json",
           {"all_required_inserted": True,
            "isolation_cells": [{"net": "sig_iso"}]})
    rc = pdc.main([str(tmp_path), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["verdict"] == "FAIL"
    rules = {f["rule"] for f in out["findings"]}
    assert "UNPROTECTED_CROSSING" in rules
    # producer lied (all_crossings_protected=true) -> contradiction reported
    assert "CONTRADICTS_PRODUCER" in rules


def test_pdc_fail_unprotected_isolation_crossing(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/level_shifter.json",
           {"level_shifters": [{"net": "sig_ls"}]})
    # isolation.json missing the sig_iso cell entirely
    _write(tmp_path, f"{_DIR}/isolation.json", {"isolation_cells": []})
    rc = pdc.main([str(tmp_path), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["verdict"] == "FAIL"
    assert any(f["rule"] == "UNPROTECTED_CROSSING" for f in out["findings"])


def test_pdc_skip_when_absent(tmp_path):
    # No power_domain.json, no waiver -> honest SKIP, never a vacuous PASS.
    rc = pdc.main([str(tmp_path), "--json", str(tmp_path / "out.json")])
    assert rc == 2
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["verdict"] == "SKIP"


def test_pdc_fail_malformed(tmp_path):
    _write_raw(tmp_path, f"{_DIR}/power_domain.json", "{ not json ]")
    rc = pdc.main([str(tmp_path)])
    assert rc == 1


def test_pdc_fail_no_crossing_list(tmp_path):
    # File present but no 'crossings' list => cannot verify => honest FAIL.
    _write(tmp_path, f"{_DIR}/power_domain.json",
           {"all_crossings_protected": True})
    rc = pdc.main([str(tmp_path)])
    assert rc == 1


def test_pdc_waived(tmp_path):
    _write(tmp_path, "waivers.json",
           {"waived_steps": [{"id": "power_domain", "ticket": "JIRA-1",
                              "reason": "no mixed-signal blocks"}]})
    rc = pdc.main([str(tmp_path)])
    assert rc == 0


def test_pdc_pass_no_protection_needed(tmp_path):
    # Crossing exists but same voltage + not power-gated => needs nothing.
    _write(tmp_path, f"{_DIR}/power_domain.json",
           {"crossings": [{"net": "sig", "vdd_from": 1.8, "vdd_to": 1.8}]})
    rc = pdc.main([str(tmp_path)])
    assert rc == 0


# =========================================================================
# level_shifter_required_check
# =========================================================================
def test_lsr_pass(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/level_shifter.json",
           {"all_required_inserted": True,
            "level_shifters": [{"net": "sig_ls"}]})
    rc = lsr.main([str(tmp_path), "--json", str(tmp_path / "out.json")])
    assert rc == 0
    assert json.loads((tmp_path / "out.json").read_text())["verdict"] == "PASS"


def test_lsr_fail_missing_shifter(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/level_shifter.json",
           {"all_required_inserted": True, "level_shifters": []})
    rc = lsr.main([str(tmp_path), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    out = json.loads((tmp_path / "out.json").read_text())
    rules = {f["rule"] for f in out["findings"]}
    assert "MISSING_LEVEL_SHIFTER" in rules
    assert "CONTRADICTS_PRODUCER" in rules


def test_lsr_fail_no_shifter_file_but_required(tmp_path):
    # level_shifter.json entirely absent, but a voltage-mismatch crossing
    # exists -> required shifter is missing -> honest FAIL (no vacuous PASS).
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    rc = lsr.main([str(tmp_path)])
    assert rc == 1


def test_lsr_skip_when_absent(tmp_path):
    rc = lsr.main([str(tmp_path)])
    assert rc == 2


def test_lsr_fail_malformed_shifter(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write_raw(tmp_path, f"{_DIR}/level_shifter.json", "broken{")
    rc = lsr.main([str(tmp_path)])
    assert rc == 1


def test_lsr_pass_no_mismatch(tmp_path):
    # No voltage-mismatched crossing => zero shifters required => PASS even
    # with no level_shifter.json.
    _write(tmp_path, f"{_DIR}/power_domain.json",
           {"crossings": [{"net": "s", "vdd_from": 1.8, "vdd_to": 1.8,
                           "to_power_down": True}]})
    rc = lsr.main([str(tmp_path)])
    assert rc == 0


def test_lsr_waived(tmp_path):
    _write(tmp_path, "waivers.json",
           {"waived_steps": [{"id": "level_shifter", "ticket": "T-2",
                              "reason": "single supply"}]})
    rc = lsr.main([str(tmp_path)])
    assert rc == 0


# =========================================================================
# isolation_cell_required_check
# =========================================================================
def test_icr_pass(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/isolation.json",
           {"all_required_inserted": True,
            "isolation_cells": [{"net": "sig_iso"}]})
    rc = icr.main([str(tmp_path), "--json", str(tmp_path / "out.json")])
    assert rc == 0
    assert json.loads((tmp_path / "out.json").read_text())["verdict"] == "PASS"


def test_icr_fail_missing_isolation(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/isolation.json",
           {"all_required_inserted": True, "isolation_cells": []})
    rc = icr.main([str(tmp_path), "--json", str(tmp_path / "out.json")])
    assert rc == 1
    out = json.loads((tmp_path / "out.json").read_text())
    rules = {f["rule"] for f in out["findings"]}
    assert "MISSING_ISOLATION_CELL" in rules
    assert "CONTRADICTS_PRODUCER" in rules


def test_icr_fail_no_iso_file_but_required(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    rc = icr.main([str(tmp_path)])
    assert rc == 1


def test_icr_skip_when_absent(tmp_path):
    rc = icr.main([str(tmp_path)])
    assert rc == 2


def test_icr_fail_malformed_iso(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write_raw(tmp_path, f"{_DIR}/isolation.json", "]]nope")
    rc = icr.main([str(tmp_path)])
    assert rc == 1


def test_icr_pass_no_power_gate(tmp_path):
    # No power-gate-able domain => zero isolation required => PASS.
    _write(tmp_path, f"{_DIR}/power_domain.json",
           {"crossings": [{"net": "s", "vdd_from": 1.8, "vdd_to": 1.0}]})
    rc = icr.main([str(tmp_path)])
    assert rc == 0


def test_icr_waived(tmp_path):
    _write(tmp_path, "waivers.json",
           {"waived_steps": [{"id": "isolation", "ticket": "T-3",
                              "reason": "no power gating"}]})
    rc = icr.main([str(tmp_path)])
    assert rc == 0


# =========================================================================
# cross-checker: the same protected fixture passes ALL THREE (gate all_of)
# =========================================================================
def test_all_three_agree_on_protected_design(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/level_shifter.json",
           {"level_shifters": [{"net": "sig_ls"}]})
    _write(tmp_path, f"{_DIR}/isolation.json",
           {"isolation_cells": [{"net": "sig_iso"}]})
    assert pdc.main([str(tmp_path)]) == 0
    assert lsr.main([str(tmp_path)]) == 0
    assert icr.main([str(tmp_path)]) == 0


def test_all_three_catch_unprotected_design(tmp_path):
    # Nothing inserted -> every checker must FAIL the gate.
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/level_shifter.json", {"level_shifters": []})
    _write(tmp_path, f"{_DIR}/isolation.json", {"isolation_cells": []})
    assert pdc.main([str(tmp_path)]) == 1
    assert lsr.main([str(tmp_path)]) == 1
    assert icr.main([str(tmp_path)]) == 1
