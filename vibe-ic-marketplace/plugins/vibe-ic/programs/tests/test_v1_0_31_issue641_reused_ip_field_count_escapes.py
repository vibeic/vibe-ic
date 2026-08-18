"""ORGANIC #641 — reused-IP processor/CPU class L-doc structured-field-count
escape + counting gaps.

l_doc_structured_field_count_check.py is a NO-waiver gate. For the reused-IP
processor_cpu class (command_protocol_applicable==False AND rtl_gen==null in
the registry) three holes made an honestly-sparse phase-1 doc FAIL with no
escape:

  (a) L8 — the timing counter ignored a populated typed `waveforms[]` /
      `clock_domains[]` / `clocks[]` list-of-dicts (each is a list, so the
      dict/scalar loop skipped it and it was absent from the gather set). A
      doc with 3 real WaveDrom waveform dicts + a typed clock_domains entry
      scored only 2 (doc_class + ic_name strings), one short of the
      #605-relaxed floor of 3 — genuine timing content was invisible.
  (b) L10 — a reused-IP CPU honestly declares `no_test_cases_in_input: true`
      and documents power-on as a typed `bring_up_sequence[]`, but the gate
      scored 0 and FAILed the ≥2 floor.
  (c) L12 — a reused-IP CPU honestly emits `no_behavioral_sequences_in_input:
      true` with `no_calibration: false`, so neither legacy escape fired.

The fix is keyed on the registry predicate (_class_no_cmd_protocol →
command_protocol_applicable==False AND rtl_gen==null), fail-closed for
bare_fpga / unknown_protocol_class — NOT on any chip-name literal.

This test drives the REAL program: end-to-end via main() on a built
fixture (so detect_ic_class runs through the registry) for the positive
case, plus direct _check_l_doc unit cases for the load-bearing NEGATIVE
no-leak half.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROG = Path(__file__).parent.parent / "l_doc_structured_field_count_check.py"
_spec = importlib.util.spec_from_file_location("_l_doc_sfc_641", _PROG)
mod = importlib.util.module_from_spec(_spec)
sys.modules["_l_doc_sfc_641"] = mod
_spec.loader.exec_module(mod)

_check = mod._check_l_doc
main = mod.main


# WaveDrom waveforms[] + a typed clock_domains[] entry. Under the OLD counter
# these two LISTS were skipped, leaving only doc_class + ic_name == 2.
_L8_TIMING = {
    "schema_version": "1.0",
    "layer": 8,
    "doc_class": "L8_TIMING_WAVEFORM",
    "ic_name": "riscv_core",
    "waveforms": [
        {"name": "clk", "wave": "p......."},
        {"name": "fetch", "wave": "0.1..0.."},
        {"name": "decode", "wave": "0..1..0."},
    ],
    "clock_domains": [
        {"name": "core_clk", "freq_hz": 100000000,
         "period_ns": 10.0, "domain_kind": "synchronous"},
    ],
}

_L10_TESTCASES = {
    "schema_version": "1.0",
    "layer": 10,
    "doc_class": "L10_TESTCASES",
    "ic_name": "riscv_core",
    "no_test_cases_in_input": True,
    "test_cases": [],
    "bring_up_sequence": [
        {"step": 1, "action": "deassert reset"},
        {"step": 2, "action": "load boot rom"},
        {"step": 3, "action": "release fetch"},
        {"step": 4, "action": "observe pc advance"},
        {"step": 5, "action": "check wfi"},
    ],
}

_L12_CAL = {
    "schema_version": "1.0",
    "layer": 12,
    "doc_class": "L12_CALIBRATION",
    "ic_name": "riscv_core",
    "no_behavioral_sequences_in_input": True,
    "no_calibration": False,
}


def _build_project(tmp_path: Path, docs: dict[str, dict]) -> Path:
    """Write a runnable project with a persisted processor_cpu class so
    detect_ic_class returns deterministically through the registry."""
    proj = tmp_path / "riscv_proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "reports").mkdir(parents=True)
    (proj / "reports" / "ic_class.json").write_text(
        json.dumps({"ic_class": "processor_cpu", "confidence": 0.9}))
    for fname, data in docs.items():
        (proj / "phase1" / "generated_docs" / fname).write_text(
            json.dumps(data))
    return proj


# ---------------------------------------------------------------------------
# POSITIVE — end-to-end through the REAL main() entry point
# ---------------------------------------------------------------------------

def test_end_to_end_reused_ip_cpu_now_passes(tmp_path):
    """All three honestly-sparse reused-IP docs PASS via main() (exit 0)."""
    proj = _build_project(tmp_path, {
        "L8_TIMING.json": _L8_TIMING,
        "L10_TESTCASES.json": _L10_TESTCASES,
        "L12_CAL.json": _L12_CAL,
    })
    rc = main([str(proj)])
    assert rc == 0, "reused-IP CPU honestly-sparse docs must PASS"


# ---------------------------------------------------------------------------
# POSITIVE — per-layer unit assertions (ic_class=processor_cpu)
# ---------------------------------------------------------------------------

def test_l8_counts_waveforms_and_clock_domains():
    ok, reason = _check(8, _L8_TIMING, ic_class="processor_cpu")
    assert ok, reason


def test_l10_credits_bring_up_sequence():
    ok, reason = _check(10, _L10_TESTCASES, ic_class="processor_cpu")
    assert ok, reason


def test_l12_honest_no_behavioral_escape():
    ok, reason = _check(12, _L12_CAL, ic_class="processor_cpu")
    assert ok, reason


# ---------------------------------------------------------------------------
# NEGATIVE no-leak half (load-bearing) — empty / under-populated / foreign
# inputs MUST STILL be caught.
# ---------------------------------------------------------------------------

def test_l8_empty_still_fails():
    """No waveforms/clocks/timing at all → still FAIL (counter is additive,
    never a blanket pass)."""
    data = {"schema_version": "1.0", "layer": 8,
            "doc_class": "L8", "ic_name": "x"}
    ok, _ = _check(8, data, ic_class="processor_cpu")
    assert not ok


def test_l8_waveform_credit_is_class_agnostic_but_real_content_only():
    """The L8 list credit is genuine typed content, so it applies in any
    class — but an EMPTY waveforms[] earns nothing (no empty-list leak)."""
    data = {"schema_version": "1.0", "layer": 8, "doc_class": "L8",
            "ic_name": "x", "waveforms": [], "clock_domains": []}
    ok, _ = _check(8, data, ic_class="processor_cpu")
    assert not ok


def test_l10_empty_bring_up_still_fails():
    """no_test_cases_in_input:true but EMPTY bring_up_sequence → FAIL."""
    data = dict(_L10_TESTCASES, bring_up_sequence=[])
    ok, _ = _check(10, data, ic_class="processor_cpu")
    assert not ok


def test_l10_no_explicit_flag_still_fails():
    """bring_up_sequence populated but no_test_cases_in_input absent →
    floor stays in force → FAIL (double-key guard)."""
    data = {k: v for k, v in _L10_TESTCASES.items()
            if k != "no_test_cases_in_input"}
    ok, _ = _check(10, data, ic_class="processor_cpu")
    assert not ok


def test_l10_string_flag_does_not_masquerade():
    """A STRING 'true' (not a real bool) never counts as an honest
    declaration."""
    data = dict(_L10_TESTCASES, no_test_cases_in_input="true")
    ok, _ = _check(10, data, ic_class="processor_cpu")
    assert not ok


def test_l10_fail_closed_class_still_fails():
    """bare_fpga / unknown stay fail-closed: the escape never fires even
    with the flag + a full bring_up_sequence."""
    for cls in ("bare_fpga", "unknown_protocol_class"):
        ok, _ = _check(10, _L10_TESTCASES, ic_class=cls)
        assert not ok, f"{cls} must stay fail-closed"


def test_l12_empty_no_flag_still_fails():
    """No calibration content and no explicit no_behavioral flag → FAIL."""
    data = {"schema_version": "1.0", "layer": 12, "doc_class": "L12",
            "ic_name": "x", "no_calibration": False}
    ok, _ = _check(12, data, ic_class="processor_cpu")
    assert not ok


def test_l12_string_flag_does_not_masquerade():
    data = dict(_L12_CAL, no_behavioral_sequences_in_input="true")
    ok, _ = _check(12, data, ic_class="processor_cpu")
    assert not ok


def test_l12_fail_closed_class_still_fails():
    for cls in ("bare_fpga", "unknown_protocol_class"):
        ok, _ = _check(12, _L12_CAL, ic_class=cls)
        assert not ok, f"{cls} must stay fail-closed"


def test_end_to_end_empty_doc_still_fails(tmp_path):
    """An EMPTY reused-IP project (no honest content, no flags) must STILL
    FAIL end-to-end through main() — the relaxation never lets an empty doc
    pass."""
    proj = _build_project(tmp_path, {
        "L8_TIMING.json": {"schema_version": "1.0", "layer": 8,
                           "doc_class": "L8", "ic_name": "x"},
        "L10_TESTCASES.json": {"schema_version": "1.0", "layer": 10,
                               "doc_class": "L10", "ic_name": "x"},
        "L12_CAL.json": {"schema_version": "1.0", "layer": 12,
                         "doc_class": "L12", "ic_name": "x"},
    })
    rc = main([str(proj)])
    assert rc == 1, "empty reused-IP docs must still FAIL"
