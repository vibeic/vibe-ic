"""Substance tests for power_domain_signal_crossing_check.py — the M2
cross-power-domain SIGNAL-crossing DERIVATION engine.

Distinct from the three M2 auditors (which consume a pre-enumerated crossing
list with per-record voltage / power-down annotations and check inserted-cell
sidecars): this engine DERIVES the protection requirement from the domain
model (nominal voltage + OFF power state) and audits the UPF STRATEGY scope.

The hazard proven with teeth:
  * a net crossing PD_SW -> PD_ON where PD_SW can power down, with NO
    set_isolation strategy  -> FLAGGED
  * add set_isolation -domain PD_ON                                -> PASS
  * a net crossing a 1.0V/1.8V boundary with NO set_level_shifter  -> FLAGGED
  * add set_level_shifter -domain ...                              -> PASS
"""
import json
import sys
from pathlib import Path

PROG = Path(__file__).parent.parent
sys.path.insert(0, str(PROG))

import power_domain_signal_crossing_check as pdsc  # noqa: E402


# =========================================================================
# pure helpers: UPF parse
# =========================================================================
_UPF_UNPROTECTED = """\
# synthetic 2-domain UPF (PD_ON always-on 1.8V, PD_SW switchable 1.8V)
upf_version 2.1
set_design_top chip_top
create_power_domain PD_ON -elements {u_core}
create_supply_net VDD_ON -domain PD_ON -voltage 1.8
add_power_state PD_ON.primary -state {ON -supply_expr {power == `{FULL_ON, 1.8}`}}
create_power_domain PD_SW -elements {u_periph}
create_supply_net VDD_SW -domain PD_SW -voltage 1.8
add_power_state PD_SW.primary -state {ON -supply_expr {power == `{FULL_ON, 1.8}`}} \
    -state {OFF -simstate CORRUPT}
"""

_UPF_PROTECTED = _UPF_UNPROTECTED + \
    "set_isolation ISO_SW -domain PD_ON -isolation_power_net VDD_ON " \
    "-clamp_value 0 -applies_to inputs\n"


def test_parse_upf_domains_voltage_and_off_state():
    dom, iso, ls = pdsc.parse_upf(_UPF_UNPROTECTED)
    assert set(dom) == {"on", "sw"}
    assert dom["on"]["voltage"] == 1.8
    assert dom["sw"]["voltage"] == 1.8
    assert dom["on"]["off_capable"] is False
    assert dom["sw"]["off_capable"] is True          # OFF/CORRUPT state
    assert dom["on"]["elements"] == {"u_core"}
    assert iso == set() and ls == set()


def test_parse_upf_picks_up_strategy_domains():
    dom, iso, ls = pdsc.parse_upf(_UPF_PROTECTED)
    assert iso == {"on"}
    assert ls == set()


# =========================================================================
# pure helpers: requirement derivation (from domain model, not annotations)
# =========================================================================
def test_required_protection_from_domain_model():
    domains = {
        "on": {"voltage": 1.8, "off_capable": False, "elements": set()},
        "sw": {"voltage": 1.8, "off_capable": True, "elements": set()},
        "lv": {"voltage": 1.0, "off_capable": False, "elements": set()},
    }
    # SW <-> ON : same voltage, SW off-capable -> isolation only
    assert pdsc.required_protection("sw", "on", domains) == (True, False)
    # LV <-> ON : voltage differs, neither off-capable -> level shifter only
    assert pdsc.required_protection("lv", "on", domains) == (False, True)
    # LV <-> SW : voltage differs AND sw off-capable -> both
    assert pdsc.required_protection("lv", "sw", domains) == (True, True)


def test_crossing_missing_detects_uncovered_strategy():
    domains = {
        "on": {"voltage": 1.8, "off_capable": False, "elements": set()},
        "sw": {"voltage": 1.8, "off_capable": True, "elements": set()},
    }
    x = {"net": "req", "driver_domain": "sw", "receiver_domain": "on"}
    # no strategies -> isolation missing
    assert pdsc.crossing_missing(x, domains, set(), set()) == ["isolation"]
    # iso strategy scoping either domain -> covered
    assert pdsc.crossing_missing(x, domains, {"on"}, set()) == []
    # intra-domain is never a crossing
    y = {"net": "n", "driver_domain": "on", "receiver_domain": "on"}
    assert pdsc.crossing_missing(y, domains, set(), set()) == []


# =========================================================================
# pure helpers: connectivity normalisation + netlist derivation
# =========================================================================
def test_crossing_records_fan_out_receivers():
    conn = {"nets": [{"net": "a", "driver_domain": "PD_SW",
                      "receiver_domains": ["PD_ON", "PD_ON"]}]}
    recs = pdsc._crossing_records(conn, None)
    assert len(recs) == 2
    assert recs[0] == {"net": "a", "driver_domain": "sw",
                       "receiver_domain": "on"}


def test_derive_crossings_from_netlist():
    netlist = """
    module top;
      buf u_drv (.A(w1), .Z(sig));
      buf u_rcv (.A(sig), .Z(w2));
    endmodule
    """
    inst_domain = {"u_drv": "PD_SW", "u_rcv": "PD_ON"}
    output_ports = {"buf": {"Z"}}
    recs = pdsc.derive_crossings_from_netlist(netlist, inst_domain, output_ports)
    assert recs == [{"net": "sig", "driver_domain": "sw",
                     "receiver_domain": "on"}]
    # without port directions the engine refuses to guess
    assert pdsc.derive_crossings_from_netlist(netlist, inst_domain, {}) == []


# =========================================================================
# end-to-end: synthetic fixture proves the check has TEETH
# =========================================================================
def _fixture(tmp_path, upf_text):
    (tmp_path / "phase2" / "stage2" / "constraints").mkdir(parents=True)
    (tmp_path / "phase2" / "stage2" / "constraints" / "chip_top.upf").write_text(
        upf_text)
    conn = tmp_path / "reports" / "analog" / "mixed_signal" / "pd_connectivity.json"
    conn.parent.mkdir(parents=True)
    conn.write_text(json.dumps({"nets": [
        {"net": "periph_req", "driver_domain": "PD_SW",
         "receiver_domain": "PD_ON"}]}))
    return tmp_path


def _run(tmp_path):
    out = tmp_path / "out.json"
    rc = pdsc.main([str(tmp_path), "--json", str(out)])
    return rc, json.loads(out.read_text())


def test_e2e_unprotected_crossing_is_flagged(tmp_path):
    _fixture(tmp_path, _UPF_UNPROTECTED)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert rep["inter_domain_crossings"] == 1
    rules = [f["rule"] for f in rep["findings"]]
    assert "UNPROTECTED_SIGNAL_CROSSING" in rules
    msg = next(f["message"] for f in rep["findings"]
               if f["rule"] == "UNPROTECTED_SIGNAL_CROSSING")
    assert "periph_req" in msg and "isolation" in msg


def test_e2e_protected_crossing_passes(tmp_path):
    _fixture(tmp_path, _UPF_PROTECTED)
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["isolation_strategy_domains"] == ["on"]


def test_e2e_voltage_mismatch_needs_level_shifter(tmp_path):
    upf = """\
upf_version 2.1
create_power_domain PD_ON
create_supply_net VDD_ON -domain PD_ON -voltage 1.8
create_power_domain PD_LV
create_supply_net VDD_LV -domain PD_LV -voltage 1.0
"""
    (tmp_path / "phase2" / "stage2" / "constraints").mkdir(parents=True)
    (tmp_path / "phase2" / "stage2" / "constraints" / "t.upf").write_text(upf)
    conn = tmp_path / "reports" / "analog" / "mixed_signal" / "pd_connectivity.json"
    conn.parent.mkdir(parents=True)
    conn.write_text(json.dumps({"nets": [
        {"net": "d", "driver_domain": "PD_LV", "receiver_domain": "PD_ON"}]}))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert any("level_shifter" in f["message"]
               for f in rep["findings"] if f["severity"] == "ERROR")
    # now add the level-shifter strategy -> PASS
    with open(tmp_path / "phase2" / "stage2" / "constraints" / "t.upf", "a") as fh:
        fh.write("set_level_shifter LS -domain PD_ON -applies_to both\n")
    rc2, rep2 = _run(tmp_path)
    assert rc2 == 0 and rep2["verdict"] == "PASS"


# =========================================================================
# honest verdicts: single-domain / absent
# =========================================================================
def test_single_domain_is_not_applicable_pass(tmp_path):
    upf = "create_power_domain PD_ONLY\ncreate_supply_net V -domain PD_ONLY -voltage 1.8\n"
    (tmp_path / "phase2" / "stage2" / "constraints").mkdir(parents=True)
    (tmp_path / "phase2" / "stage2" / "constraints" / "s.upf").write_text(upf)
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["findings"][0]["rule"] == "NOT_APPLICABLE"


def test_no_power_intent_skips(tmp_path):
    rc, rep = _run(tmp_path)
    assert rc == 2
    assert rep["verdict"] == "SKIP"


def test_l21_fallback_when_no_upf(tmp_path):
    l21 = tmp_path / "phase1" / "generated_docs" / "L21_POWER_INTENT.json"
    l21.parent.mkdir(parents=True)
    l21.write_text(json.dumps({"fields": {
        "power_domains": [
            {"name": "ON", "voltage": 1.8},
            {"name": "SW", "voltage": 1.8, "switchable": True}],
        "isolation_cells": [],
        "signal_crossings": [
            {"net": "x", "driver_domain": "SW", "receiver_domain": "ON"}]}}))
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["power_intent_source"].endswith("L21_POWER_INTENT.json")
    assert rep["inter_domain_crossings"] == 1


# ── #312-family: an absent statement is not a statement of absence ──────────
# `isolation_cells` / `level_shifters` are read on the L21 fallback path and
# populated by NO producer (311 real L-docs: key present in 27, valued in 0).
# Both sets are therefore always empty there, and `crossing_missing` reads an
# empty set as "no strategy scopes this domain" -> every protected crossing
# reported UNPROTECTED. A false FAIL, firing only on the designs that reach
# this path.

import power_domain_signal_crossing_check as _PD  # noqa: E402


def _l21(power_domains, **extra):
    f = {"power_domains": power_domains}
    f.update(extra)
    return f


_TWO_DOMAINS = [{"name": "PD_CORE", "voltage": 0.9, "off_capable": False},
                {"name": "PD_AON", "voltage": 1.8, "off_capable": True}]
# NOTE: `_norm` STRIPS a leading `PD_`, so a crossing's domain tokens are the
# stripped, lowercased form. A fixture using "pd_core" looks up nothing and
# silently produces no findings — that was a fixture bug here, not a code bug.
_CROSSING = {"net": "n1", "driver_domain": "core",
             "receiver_domain": "aon"}


def test_312_silent_layer_is_not_reported_as_unprotected():
    """The layer says NOTHING about protection. Reporting UNPROTECTED states
    a fact the input never provided."""
    dom, iso, ls = _PD.parse_l21(_l21(_TWO_DOMAINS))
    assert not _PD.l21_states_protection()
    findings, _, _ = _PD.audit(dom, iso, ls, [_CROSSING])
    assert findings, "the crossing must still be surfaced, not dropped"
    assert all(f["rule"] == "PROTECTION_UNSTATED" for f in findings), findings
    assert all(f["severity"] == "WARNING" for f in findings)


def test_312_a_stated_strategy_that_misses_the_crossing_still_FAILs():
    """NO-LEAK: once the layer DOES state a strategy, a crossing it fails to
    cover is a real unprotected crossing and must still be an ERROR."""
    dom, iso, ls = _PD.parse_l21(
        _l21(_TWO_DOMAINS, isolation_cells=[{"domain": "PD_OTHER"}]))
    assert _PD.l21_states_protection()
    findings, _, _ = _PD.audit(dom, iso, ls, [_CROSSING])
    assert findings
    assert any(f["rule"] == "UNPROTECTED_SIGNAL_CROSSING"
               and f["severity"] == "ERROR" for f in findings), findings


def test_312_a_stated_strategy_that_covers_the_crossing_passes():
    """Both protections must be stated: these domains differ in voltage AND
    one is power-down capable, so isolation alone leaves the level-shifter
    requirement uncovered — an earlier version of this test expected a pass
    from isolation only and was simply wrong about the requirement."""
    dom, iso, ls = _PD.parse_l21(
        _l21(_TWO_DOMAINS, isolation_cells=[{"domain": "PD_AON"}],
             level_shifters=[{"from": "PD_CORE", "to": "PD_AON"}]))
    findings, _, _ = _PD.audit(dom, iso, ls, [_CROSSING])
    assert not [f for f in findings
                if f["rule"] == "UNPROTECTED_SIGNAL_CROSSING"], findings
