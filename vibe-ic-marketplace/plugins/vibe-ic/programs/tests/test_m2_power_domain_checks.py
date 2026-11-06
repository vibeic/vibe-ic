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
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["verdict"] == "FAIL"
    assert any(f["rule"] == "UNPROTECTED_CROSSING" for f in out["findings"])


def test_pdc_skip_when_absent(tmp_path):
    # No power_domain.json, no waiver -> honest SKIP, never a vacuous PASS.
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["verdict"] == "SKIP"










# =========================================================================
# level_shifter_required_check
# =========================================================================
def test_lsr_pass(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/level_shifter.json",
           {"all_required_inserted": True,
            "level_shifters": [{"net": "sig_ls"}]})
    assert json.loads((tmp_path / "out.json").read_text())["verdict"] == "PASS"


def test_lsr_fail_missing_shifter(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/level_shifter.json",
           {"all_required_inserted": True, "level_shifters": []})
    out = json.loads((tmp_path / "out.json").read_text())
    rules = {f["rule"] for f in out["findings"]}
    assert "MISSING_LEVEL_SHIFTER" in rules
    assert "CONTRADICTS_PRODUCER" in rules












# =========================================================================
# isolation_cell_required_check
# =========================================================================
def test_icr_pass(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/isolation.json",
           {"all_required_inserted": True,
            "isolation_cells": [{"net": "sig_iso"}]})
    assert json.loads((tmp_path / "out.json").read_text())["verdict"] == "PASS"


def test_icr_fail_missing_isolation(tmp_path):
    _write(tmp_path, f"{_DIR}/power_domain.json", _pd_two_crossings())
    _write(tmp_path, f"{_DIR}/isolation.json",
           {"all_required_inserted": True, "isolation_cells": []})
    out = json.loads((tmp_path / "out.json").read_text())
    rules = {f["rule"] for f in out["findings"]}
    assert "MISSING_ISOLATION_CELL" in rules
    assert "CONTRADICTS_PRODUCER" in rules












# =========================================================================
# cross-checker: the same protected fixture passes ALL THREE (gate all_of)
# =========================================================================




import pytest

@pytest.mark.parametrize('code',[0,7,199])
def test_allocated_m2_container_tool_supervision(tmp_path,monkeypatch,code):
    import mixed_signal_power_domain_run as producer
    import subprocess
    calls=[]
    def observed(container,command,**kw):
        calls.append((container,command,kw))
        return subprocess.CompletedProcess([],code,'retained output','WATCHDOG_STALLED' if code==199 else 'retained stderr')
    monkeypatch.setattr(producer.ce,'run_in_container_supervised',observed)
    monkeypatch.setattr(producer.ce,'run_in_container',lambda *a,**k:subprocess.CompletedProcess([],7,'raw','raw'))
    script=tmp_path/'neutral.ys';script.write_text('# neutral source-only input\n')
    got=producer.run_tool(script,tmp_path,'neutral-container')
    assert got==code and (tmp_path/'yosys.log').read_text()=='retained output'+('WATCHDOG_STALLED' if code==199 else 'retained stderr')
    assert calls==[('neutral-container','yosys -T -s '+str(script),{'ceiling_s':120})]
