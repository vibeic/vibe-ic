"""ORGANIC #677 — l_doc_structured_field_count_check typed-field floors FAIL a
MINIMAL bus_peripheral SoC (no class-aware floor / no `no_*_in_input:true` honest-
absence escape for L4/L7/L10).

現象 (field/benchmark agent, caravel 7th IC round-5, public tree v1.0.45): a
genuinely minimal register-mapped peripheral (e.g. a Wishbone-mapped counter with
no regmap, no opcodes, no analog, no chip-level test scenarios / cases) FAILs P0
on the L4 regmap floor (≥5), the L7 test/debug floor (≥3) and the L10 test-case
floor (≥2) even though the docs HONESTLY declare the absence
(`no_register_map_in_input: true` / `no_test_scenarios_in_input: true` /
`no_test_cases_in_input: true`). L5 already had a `no_analog: true` escape;
L4/L7/L10 had no equivalent honest-absence escape, and the #641 L10 bring-up
harvest only fires when there is something to harvest.

Fix (Bucket A, chip-AGNOSTIC) — a dedicated registry SEMANTIC flag
`minimal_honest_absence_ok` (set on bus_peripheral + bus_interconnect_protocol)
keys three new honest-absence N/A escapes in l_doc_structured_field_count_check:
  - L4: `no_register_map_in_input: true` (or register_map_present:false /
        no_register_map:true) waives the ≥5 regmap floor.
  - L7: an explicit no_test_scenarios_in_input / no_verification_strategy_in_input
        / no_test_modes_in_input / no_test_debug_in_input == true + zero typed
        scenarios waives the ≥3 floor.
  - L10: an explicit no_test_cases_in_input == true + zero typed cases (after the
        #641 bring-up harvest) waives the floor.

The flag is DELIBERATELY NARROWER than `_class_no_cmd_protocol`: a reused-IP
processor_cpu / crypto_accelerator is ALSO command_protocol_applicable==false +
rtl_gen==null, but ORGANIC #641 holds those classes to a POPULATED
bring_up_sequence — so they do NOT get the new flag and their #641 doctrine is
preserved.

NEGATIVE no-leak (load-bearing — the floors keep their teeth):
  (a) a rich class (digital_cmd_driven) with empty typed lists and NO honest flag
      still FAILs L4/L7/L10;
  (b) a rich class WITH a (mis-set) honest flag still FAILs (it lacks the
      minimal_honest_absence_ok flag);
  (c) a flagged class but a BARE / false / string honest flag (not boolean True)
      still FAILs — only an explicit boolean True counts;
  (d) a flagged class with PARTIAL typed content (1+ entries, below the floor)
      still FAILs — the escape fires only on a genuinely-empty doc;
  (e) bare_fpga / unknown_protocol_class stay fail-closed even with the flag set;
  (f) the #641 processor_cpu doctrine (empty bring_up + no_test_cases_in_input ==
      true → FAIL) is preserved because processor_cpu lacks the flag.

chip-AGNOSTIC: a registry semantic flag + the doc's own honest no_*_in_input
declaration; NO chip / vendor / SKU literal.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).parent.parent / "l_doc_structured_field_count_check.py"
_spec = importlib.util.spec_from_file_location("_l_doc_sfc_677", _PROG)
mod = importlib.util.module_from_spec(_spec)
sys.modules["_l_doc_sfc_677"] = mod
_spec.loader.exec_module(mod)

_check = mod._check_l_doc
main = mod.main

_MINIMAL_CLASS = "bus_peripheral"          # flagged minimal_honest_absence_ok
_FLAGGED_CLASSES = ("bus_peripheral", "bus_interconnect_protocol")
# classes that are _class_no_cmd_protocol but NOT flagged → must keep teeth
_REUSED_IP_CLASS = "processor_cpu"
_RICH_CLASS = "digital_cmd_driven"
_FAIL_CLOSED = ("bare_fpga", "unknown_protocol_class")


# ── registry wiring: the dedicated semantic flag is present + correctly scoped ─

def test_registry_flag_scoped_to_minimal_peripheral_classes():
    for cls in _FLAGGED_CLASSES:
        assert mod._class_minimal_honest_absence(cls), \
            f"{cls} must carry minimal_honest_absence_ok"
    # reused-IP / rich / fail-closed classes do NOT get the flag
    for cls in (_REUSED_IP_CLASS, "crypto_accelerator",
                _RICH_CLASS, *_FAIL_CLOSED):
        assert not mod._class_minimal_honest_absence(cls), \
            f"{cls} must NOT carry minimal_honest_absence_ok"


# ── ACCEPTANCE: minimal honest bus_peripheral PASSes L4 / L7 / L10 ────────────

def test_l4_honest_no_regmap_in_input_passes():
    for cls in _FLAGGED_CLASSES:
        ok, msg = _check(4, {"registers": [],
                             "no_register_map_in_input": True}, ic_class=cls)
        assert ok, f"L4 honest no-regmap minimal {cls} should PASS: {msg}"


def test_l7_honest_no_test_debug_in_input_passes():
    for flag in ("no_test_scenarios_in_input",
                 "no_verification_strategy_in_input",
                 "no_test_modes_in_input", "no_test_debug_in_input"):
        ok, msg = _check(7, {"test_scenarios": [], flag: True},
                         ic_class=_MINIMAL_CLASS)
        assert ok, f"L7 honest {flag} minimal should PASS: {msg}"


def test_l10_honest_no_test_cases_in_input_passes():
    for cls in _FLAGGED_CLASSES:
        ok, msg = _check(10, {"test_cases": [], "no_test_cases_in_input": True,
                              "bring_up_sequence": []}, ic_class=cls)
        assert ok, f"L10 honest no-test-cases minimal {cls} should PASS: {msg}"


def test_end_to_end_minimal_bus_peripheral_passes(tmp_path):
    """Whole-program main() on a built minimal bus_peripheral project (so
    detect_ic_class routes through the registry) returns exit 0."""
    proj = tmp_path / "minimal_periph"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "reports").mkdir(parents=True)
    (proj / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": "bus_peripheral", "confidence": 0.9}))

    def _w(name, data):
        (proj / "phase1" / "generated_docs" / name).write_text(
            json.dumps(data))

    # L1/L2 carry enough typed fields to clear their counts; L4/L7/L10 are the
    # honest-minimal docs under test; other layers use their existing escapes.
    _w("L1_DATASHEET.json", {"layer": 1, "overview": {"x": 1},
        **{f"f{i}": i for i in range(12)}})
    _w("L2_FRS.json", {"layer": 2, **{f"f{i}": i for i in range(18)}})
    _w("L4_REGMAP.json", {"layer": 4, "registers": [],
                          "no_register_map_in_input": True})
    _w("L5_ADI.json", {"layer": 5, "no_analog": True})
    _w("L6_CONTROL.json", {"layer": 6,
        "fsm_states": [{"name": s} for s in
                       ("idle", "load", "count", "read", "done")]})
    _w("L7_TEST_DEBUG.json", {"layer": 7, "test_scenarios": [],
                              "no_test_scenarios_in_input": True})
    _w("L8_TIMING.json", {"layer": 8,
        "timing_parameters": {f"t{i}": i for i in range(12)}})
    _w("L9_INTEGRATION.json", {"layer": 9, "top_module": "periph",
        "submodules": [],
        "top_ports": [{"name": "clk"}, {"name": "rst"}, {"name": "wb"}]})
    _w("L10_TESTCASES.json", {"layer": 10, "test_cases": [],
                              "no_test_cases_in_input": True,
                              "bring_up_sequence": []})
    _w("L11_BEHAVIORAL.json", {"layer": 11, "applicable": False})
    _w("L12_CAL.json", {"layer": 12, "no_calibration": True})
    _w("L13_LAB.json", {"layer": 13, "lab_calibration_present": False})

    rc = main([str(proj)])
    assert rc == 0, "minimal honest bus_peripheral project must PASS (exit 0)"


# ── NEGATIVE no-leak (load-bearing) ───────────────────────────────────────────

def test_noleak_rich_class_empty_no_flag_fails():
    """(a) A rich command class with empty typed lists and NO honest flag still
    FAILs L4 / L7 / L10 — the floor keeps its teeth."""
    assert not _check(7, {"test_scenarios": []}, ic_class=_RICH_CLASS)[0]
    assert not _check(10, {"test_cases": []}, ic_class=_RICH_CLASS)[0]
    # L4: a blob-only doc with NO honest register key still FAILs
    assert not _check(4, {"foo": "bar"}, ic_class=_RICH_CLASS)[0]


def test_noleak_rich_class_with_flag_still_fails():
    """(b) A rich command class that (wrongly) carries a no_*_in_input flag still
    FAILs — it lacks the minimal_honest_absence_ok registry flag."""
    assert not _check(7, {"test_scenarios": [],
                          "no_test_modes_in_input": True},
                      ic_class=_RICH_CLASS)[0]
    assert not _check(10, {"test_cases": [], "no_test_cases_in_input": True},
                      ic_class=_RICH_CLASS)[0]
    assert not _check(4, {"registers": [], "no_register_map_in_input": True},
                      ic_class=_RICH_CLASS)[0]


def test_noleak_flagged_class_bare_or_false_flag_fails():
    """(c) A flagged class but a BARE / false / string honest flag (not boolean
    True) still FAILs — only an explicit boolean True counts."""
    # bare / absent
    assert not _check(7, {"test_scenarios": []}, ic_class=_MINIMAL_CLASS)[0]
    assert not _check(10, {"test_cases": []}, ic_class=_MINIMAL_CLASS)[0]
    # explicit False
    assert not _check(7, {"test_scenarios": [],
                          "no_test_modes_in_input": False},
                      ic_class=_MINIMAL_CLASS)[0]
    # string "true" must NOT masquerade as a boolean
    assert not _check(7, {"test_scenarios": [],
                          "no_test_modes_in_input": "true"},
                      ic_class=_MINIMAL_CLASS)[0]
    assert not _check(10, {"test_cases": [],
                          "no_test_cases_in_input": "true"},
                      ic_class=_MINIMAL_CLASS)[0]


def test_noleak_flagged_class_partial_content_still_fails():
    """(d) A flagged class with PARTIAL typed content (below the floor, n>=1)
    still FAILs — the honest-absence escape requires a genuinely EMPTY doc, so
    an under-populated doc can never ride the flag into a pass."""
    assert not _check(7, {"test_scenarios": [{"a": 1}],
                          "no_test_modes_in_input": True},
                      ic_class=_MINIMAL_CLASS)[0]
    assert not _check(10, {"test_cases": [{"a": 1}],
                          "no_test_cases_in_input": True},
                      ic_class=_MINIMAL_CLASS)[0]


def test_noleak_fail_closed_classes_stay_failing():
    """(e) bare_fpga / unknown_protocol_class stay fail-closed even with the
    honest flag set."""
    for cls in _FAIL_CLOSED:
        assert not _check(7, {"test_scenarios": [],
                              "no_test_modes_in_input": True}, ic_class=cls)[0]
        assert not _check(10, {"test_cases": [],
                              "no_test_cases_in_input": True}, ic_class=cls)[0]
        assert not _check(4, {"registers": [],
                              "no_register_map_in_input": True}, ic_class=cls)[0]


def test_noleak_641_processor_cpu_doctrine_preserved():
    """(f) The #641 processor_cpu doctrine is preserved: an empty bring_up_
    sequence + no_test_cases_in_input == true must STILL FAIL for processor_cpu
    (it carries harvestable verification intent — an empty bring-up means the
    harvest failed). processor_cpu lacks minimal_honest_absence_ok, so the new
    #677 L10 escape never fires for it."""
    l10 = {"test_cases": [], "no_test_cases_in_input": True,
           "bring_up_sequence": []}
    ok, _ = _check(10, l10, ic_class=_REUSED_IP_CLASS)
    assert not ok, "#641 processor_cpu empty-bring-up FAIL must be preserved"
    # a POPULATED bring-up still PASSes via the #641 harvest path (unchanged)
    l10_full = dict(l10, bring_up_sequence=[
        {"step": 1, "action": "deassert reset"},
        {"step": 2, "action": "load boot rom"},
    ])
    ok2, msg2 = _check(10, l10_full, ic_class=_REUSED_IP_CLASS)
    assert ok2, f"#641 populated-bring-up PASS must be preserved: {msg2}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-v"]))
