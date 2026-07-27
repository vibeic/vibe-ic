"""Unit tests for eda_report_audit.py.

Tests verify correct detection of EDA reports across all modes:
DRC, LVS, power, EM, IR-drop, and STA.

Updated 2026-04-22: reports must now include a tool signature AND meet a
minimum size (MIN_REPORT_BYTES per mode) to pass. Hand-typed stubs are
rejected. See `TOOL_SIGNATURES` / `MIN_REPORT_BYTES` in eda_report_audit.py.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'eda_report_audit.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import eda_report_audit as era  # noqa: E402

# Padding to satisfy MIN_REPORT_BYTES thresholds
_PAD = "# " + ("=" * 78 + "\n") * 40  # ~3.2 KB


# ---------------------------------------------------------------------------
# DRC mode
# ---------------------------------------------------------------------------
def test_drc_report_pass(tmp_path):
    """A genuinely CLEAN report (0 real violations) passes.

    Fixed from a fixture that said "3 violations total" and asserted
    `passed is True` — a real defect in the fixture, not a defect this test
    was checking: `_check_drc` used to gate on rule-CATEGORY VOCABULARY
    presence only, so it could not tell "3 violations" from "0 violations"
    as long as the word "spacing" appeared somewhere. Kept the vocabulary
    (categories_found must still populate) but made the report say what a
    real clean signoff report says: an explicit zero count.
    """
    rpt = tmp_path / "run_drc.rpt"
    rpt.write_text(
        "[INFO drt-0012] OpenROAD detailed_route\n"
        "spacing check: clean\n"
        "via enclosure check: clean\n"
        "0 violations total\n" + _PAD
    )
    result = era._check_drc(tmp_path)
    assert result.passed is True
    assert "spacing" in result.summary["categories_found"]
    assert result.summary["has_count"] is True
    assert result.summary["tool_authentic"] is True
    assert result.summary["real_violation_total"] == 0


def test_drc_report_with_real_violations_fails(tmp_path):
    """DIRECTION 2, the case the old fixture accidentally exercised backwards:
    a report that genuinely states violations occurred must FAIL, not pass
    because the rule-category words happen to appear in the same text."""
    rpt = tmp_path / "run_drc.rpt"
    rpt.write_text(
        "[INFO drt-0012] OpenROAD detailed_route\n"
        "spacing violation at M1\n"
        "via enclosure error at M2\n"
        "3 violations total\n" + _PAD
    )
    result = era._check_drc(tmp_path)
    assert result.passed is False
    assert result.summary["real_violation_total"] == 3


_KLAYOUT_RDB_HEADER = (
    "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
    "<report-database>\n"
    " <generator>klayout drc: script='foo.drc'</generator>\n"
    " <categories>\n"
    "  <category><name>spacing</name></category>\n"
    "  <category><name>enclosure</name></category>\n"
    " </categories>\n"
)


# `_PAD` must sit INSIDE the document (as a comment), never appended raw
# after `</report-database>` — trailing non-whitespace content after the
# root element's close tag is not well-formed XML, so ET.fromstring would
# raise and these tests would silently exercise the TEXT fallback path
# instead of the XML <items>-counting path they exist to pin. (Caught by
# running this exact case: the padding-after-close variant made the "prose
# injected" test read 9999 from the fallback regex instead of 0 from the
# real <items> count — a bug in the FIXTURE, not in `_check_drc`.)
_PAD_AS_COMMENT = "<!-- " + _PAD.replace("--", "- -") + " -->\n"


def test_drc_klayout_real_item_gates_fail(tmp_path):
    """A real klayout RDB <item> under <items> is a real violation and must
    FAIL — the counting path distinct from the magic-style text regex
    exercised by test_drc_report_with_real_violations_fails above."""
    rpt = tmp_path / "drc_signoff.rpt"
    rpt.write_text(
        _KLAYOUT_RDB_HEADER +
        " <items>\n"
        "  <item><category-name>spacing</category-name>"
        "<cell><name>top</name></cell></item>\n"
        " </items>\n" +
        _PAD_AS_COMMENT +
        "</report-database>\n"
    )
    result = era._check_drc(tmp_path)
    assert result.passed is False
    assert result.summary["real_violation_total"] == 1


def test_drc_prose_injected_into_a_clean_klayout_report_does_not_flip_pass(tmp_path):
    """THE ORGANIC EXPLOIT this fix closes, stated as a precision guard: a
    genuinely clean klayout report (0 real <item> elements under <items>)
    hand-edited to ALSO contain a comment describing a massive violation
    count must still PASS — the injected sentence is prose, not a real
    <item>, and the fix must read the STRUCTURE, not the vocabulary, in
    either direction. (This is the real drc_signoff.rpt mutation used to
    demonstrate the original defect: same report, same edit, different
    verdict once <items> is actually counted instead of grepped.)
    """
    rpt = tmp_path / "drc_signoff.rpt"
    rpt.write_text(
        _KLAYOUT_RDB_HEADER +
        " <items>\n"
        " </items>\n"
        " <!-- 9999 spacing violations found. Total: 9999 violations. "
        "DRC FAILED -->\n" +
        _PAD_AS_COMMENT +
        "</report-database>\n"
    )
    result = era._check_drc(tmp_path)
    assert result.passed is True
    assert result.summary["real_violation_total"] == 0


def test_drc_stub_rejected(tmp_path):
    """Anti-fabrication: hand-typed tiny report without tool sig must FAIL."""
    rpt = tmp_path / "drc.rpt"
    rpt.write_text("spacing: 0\nwidth: 0\ntotal: 0 violations\n")  # 40 B
    result = era._check_drc(tmp_path)
    assert result.passed is False
    assert result.summary.get("tool_authentic") is False


def test_drc_no_report_fail(tmp_path):
    result = era._check_drc(tmp_path)
    assert result.passed is False
    assert result.summary["files_found"] == 0


# ---------------------------------------------------------------------------
# LVS mode
# ---------------------------------------------------------------------------
def test_lvs_report_pass(tmp_path):
    rpt = tmp_path / "chip_lvs.rpt"
    # #507: a CLEAN netgen report — carries the instance/net/device
    # category keywords (for categories_found) via NON-mismatch phrasing
    # and netgen's REAL terminal PASS token 'Circuits match uniquely.'
    # (the prior fixture's 'net mismatch: VDD' / 'unmatched instance' +
    # bare 'Circuits match.' were not a clean report — the gate now
    # correctly reads those as a mismatch).
    rpt.write_text(
        "Netgen LVS comparison\n"
        "Subcircuit instance summary: 567 instances compared\n"
        "NET count: 1234\ndevice count: 567\n"
        "Number of topologically valid matches: 567\n"
        "Final result: Circuits match uniquely.\n" + _PAD
    )
    result = era._check_lvs(tmp_path)
    assert result.passed is True
    assert result.summary["terminal_verdict"] == "MATCH"
    cats = result.summary["categories_found"]
    assert "instance" in cats
    assert "net" in cats
    assert result.summary["tool_authentic"] is True


def test_lvs_stub_rejected(tmp_path):
    rpt = tmp_path / "lvs.rpt"
    rpt.write_text("net: OK\ndevice: OK\n")
    result = era._check_lvs(tmp_path)
    assert result.passed is False


def test_lvs_no_report_fail(tmp_path):
    result = era._check_lvs(tmp_path)
    assert result.passed is False
    assert result.summary["files_found"] == 0


# ---------------------------------------------------------------------------
# Power mode
# ---------------------------------------------------------------------------
def test_power_report_pass(tmp_path):
    rpt = tmp_path / "power_analysis.rpt"
    rpt.write_text(
        "OpenROAD Power Report\n"
        "Group: sequential   Internal Power: 0.12 mW\n"
        "Group: combinational\n"
        "leakage power: 0.05 mW static\n"
        "dynamic power: 3.5 mW switching\n"
        "Total Power: 3.67 mW\n" + _PAD
    )
    result = era._check_power(tmp_path)
    assert result.passed is True
    assert result.summary["has_leakage"] is True
    assert result.summary["has_dynamic"] is True


def test_power_stub_rejected(tmp_path):
    rpt = tmp_path / "power.rpt"
    rpt.write_text("leakage: 1 mW\ndynamic: 3 mW\n")
    result = era._check_power(tmp_path)
    assert result.passed is False


def test_power_missing_dynamic_fail(tmp_path):
    rpt = tmp_path / "power_analysis.rpt"
    rpt.write_text(
        "OpenROAD Power Report\nleakage power: 1.2 uW static\ntotal: 1.2 uW\n" + _PAD
    )
    result = era._check_power(tmp_path)
    assert result.passed is False
    assert result.summary["has_leakage"] is True
    assert result.summary["has_dynamic"] is False


# --------------------------------------------------------------------------
# Power substance — a NAMED CATEGORY IS NOT A VALUE (PR #462 follow-up).
#
# `phase3_one_shot_runner._emit_power_report` writes this exact shape when
# the OpenSTA `report_power` invocation fails: real tool signature, all
# three category names, every wattage the literal string `not_computed`.
# Measured on main before this fix: passed=true, tool_authentic=true.
# The sibling gate thermal_screen_check SKIPs the same bytes.
# --------------------------------------------------------------------------
_RUNNER_NOT_COMPUTED_FALLBACK = (
    "# OpenROAD/OpenSTA report_power - fallback emitted by\n"
    "# phase3_one_shot_runner because the live invocation returned rc=1.\n"
    "# Tool: openroad (sta).\n"
    "# === Power Report (categories) ===\n"
    "# Group: sequential\n"
    "#   leakage power: not_computed (OpenSTA rc=1)\n"
    "#   dynamic power: not_computed\n"
    "#   internal power: not_computed\n"
    "# Group: combinational\n"
    "#   leakage power: not_computed\n"
    "#   dynamic power: not_computed\n"
    "#   internal power: not_computed\n"
    "# Total Power: not_computed\n"
)


def test_power_not_computed_fallback_is_not_certified(tmp_path):
    rpt = tmp_path / "power.rpt"
    rpt.write_text(_RUNNER_NOT_COMPUTED_FALLBACK + _PAD)
    result = era._check_power(tmp_path)
    assert result.passed is False
    # The categories ARE named — that is exactly why word-matching passed it.
    assert result.summary["has_leakage"] is True
    assert result.summary["has_dynamic"] is True
    assert result.summary["tool_authentic"] is True
    assert result.summary["values_not_computed"] is True
    assert result.summary["has_numeric_value"] is False
    assert {f.rule for f in result.findings} >= {"POWER_VALUES_NOT_COMPUTED",
                                                 "POWER_VALUE_NUMERIC"}


def test_power_categories_without_any_value_fail(tmp_path):
    """No `not_computed` marker either — just labels and a tool banner."""
    rpt = tmp_path / "power.rpt"
    rpt.write_text(
        "OpenROAD Power Report\n"
        "Group: sequential\nleakage power\ndynamic power\ninternal power\n"
        + _PAD)
    result = era._check_power(tmp_path)
    assert result.passed is False
    assert result.summary["has_numeric_value"] is False
    assert "POWER_VALUE_NUMERIC" in {f.rule for f in result.findings}


def test_power_opensta_table_still_passes(tmp_path):
    """Direction-1: OpenSTA's real report_power table must stay green.

    This is the shape the completed ihp-sg13g2 digital run emits; the gate
    was re-run against that artefact and returned rc=0 after the fix.

    Asserts only the observable verdict, deliberately not the new summary
    keys, so it holds on the pre-fix program too — a direction-1 guard has
    to survive the mutant it is guarding against.
    """
    rpt = tmp_path / "power.rpt"
    rpt.write_text(
        "# OpenSTA report_power — automatic emission by\n"
        "# phase3_one_shot_runner (canonicalize_artefacts step).\n"
        "# Tool: openroad / sta (OpenSTA Power Report).\n"
        "# === Begin OpenSTA Power Report ===\n"
        "OpenSTA 3.1.0 Copyright (c) 2026, Parallax Software, Inc.\n"
        "POWER_ANALYSIS_MODE: vectorless_sdc\n"
        "Group                  Internal  Switching    Leakage      Total\n"
        "                          Power      Power      Power      Power (Watts)\n"
        "----------------------------------------------------------------\n"
        "Sequential             3.70e-04   7.05e-06   3.02e-08   3.77e-04  92.5%\n"
        "Combinational          1.71e-05   1.36e-05   2.95e-08   3.06e-05   7.5%\n"
        "Total                  3.87e-04   2.07e-05   5.97e-08   4.08e-04 100.0%\n"
        + _PAD)
    result = era._check_power(tmp_path)
    assert result.passed is True


def test_power_declared_capability_gap_still_waives(tmp_path):
    """Direction-1: a DECLARED gap is still the sanctioned green path — the
    fix must not have turned the waiver route red along with the fake one."""
    import json as _json
    (tmp_path / "waivers.json").write_text(_json.dumps({
        "power_report_unavailable_reason":
            "no OpenSTA in this container image; power deferred to sign-off"}))
    rpt = tmp_path / "power.rpt"
    rpt.write_text(_RUNNER_NOT_COMPUTED_FALLBACK + _PAD)
    result = era._check_power(tmp_path)
    assert result.passed is True
    assert result.summary["waived"] is True


# ---------------------------------------------------------------------------
# EM mode
# ---------------------------------------------------------------------------
def test_em_report_pass(tmp_path):
    rpt = tmp_path / "em_check.rpt"
    rpt.write_text(
        "OpenROAD Electromigration analysis\n"
        "EM lifetime: 10 years\n"
        "Wire M3: Javg 2.5 mA, current density limit 5.0 mA/um\n"
        "Jpeak 8.1 mA/um, RMS current 3.2 mA/um\n" + _PAD
    )
    result = era._check_em(tmp_path)
    assert result.passed is True
    assert result.summary["has_density"] is True


def test_em_stub_rejected(tmp_path):
    rpt = tmp_path / "em.rpt"
    rpt.write_text("Javg=1 OK\n")
    result = era._check_em(tmp_path)
    assert result.passed is False


# ---------------------------------------------------------------------------
# STA mode
# ---------------------------------------------------------------------------
def test_sta_report_pass(tmp_path):
    """A genuinely CLEAN report (non-negative WNS/TNS) passes.

    Fixed from a fixture that said `WNS = -0.05 ns` / `TNS = -1.2 ns` — both
    NEGATIVE, i.e. real (if small) timing violations — and asserted
    `passed is True`. That was a real defect in the fixture: `_check_sta`
    used to gate on WNS/TNS-shaped VOCABULARY presence only, never on the
    sign of the value, so it could not tell a violated design from a clean
    one as long as the report used the right words. Kept the report shape,
    made the numbers what a real clean signoff report reports.
    """
    rpt = tmp_path / "sta_final.rpt"
    rpt.write_text(
        "OpenSTA timing report\n"
        "Startpoint: clk_i\nEndpoint: out_q\n"
        "WNS = 0.05 ns\nTNS = 0.0 ns\n"
        "setup slack: 0.1 ns\nhold slack: 0.02 ns\n"
        "data arrival time: 2.34 ns\n" + _PAD
    )
    result = era._check_sta(tmp_path)
    assert result.passed is True
    assert result.summary["has_wns_tns"] is True
    assert result.summary["has_setup_hold"] is True
    assert result.summary["any_verdict_determined"] is True
    assert result.summary["real_violation_found"] is False


def test_sta_report_with_negative_wns_fails(tmp_path):
    """DIRECTION 2, the case the old fixture accidentally exercised
    backwards: a report that genuinely states a negative WNS/TNS — a real
    timing violation — must FAIL, not pass because the summary carries the
    right vocabulary. This is the exact fixture the old test used."""
    rpt = tmp_path / "sta_final.rpt"
    rpt.write_text(
        "OpenSTA timing report\n"
        "Startpoint: clk_i\nEndpoint: out_q\n"
        "WNS = -0.05 ns\nTNS = -1.2 ns\n"
        "setup slack: 0.1 ns\nhold slack: 0.02 ns\n"
        "data arrival time: 2.34 ns\n" + _PAD
    )
    result = era._check_sta(tmp_path)
    assert result.passed is False
    assert result.summary["real_violation_found"] is True


def test_sta_pathtable_violated_entry_fails_even_with_clean_summary_words(tmp_path):
    """THE ORGANIC EXPLOIT this fix closes: a real OpenSTA per-path table
    whose only path is genuinely VIOLATED must FAIL — even though the
    report legitimately contains "setup"/"hold" vocabulary elsewhere, which
    is all the old check required."""
    rpt = tmp_path / "sta_pathtable.rpt"
    rpt.write_text(
        "Startpoint: clk_i (rising edge-triggered flip-flop clock clk)\n"
        "Endpoint: out_q (rising edge-triggered flip-flop clock clk)\n"
        "Path Type: max\n"
        "  data arrival time    6.65\n"
        "  data required time   0.10\n"
        "           6.65   slack (VIOLATED)\n"
        "setup/hold analysis complete\n" + _PAD
    )
    result = era._check_sta(tmp_path)
    assert result.passed is False
    assert result.summary["real_violation_found"] is True


def test_sta_pathtable_all_met_passes(tmp_path):
    """DIRECTION 1 sibling: the same path-table shape with a genuinely MET
    verdict must still pass — this fix must not become a blanket path-table
    rejection."""
    rpt = tmp_path / "sta_pathtable.rpt"
    rpt.write_text(
        "Startpoint: clk_i (rising edge-triggered flip-flop clock clk)\n"
        "Endpoint: out_q (rising edge-triggered flip-flop clock clk)\n"
        "Path Type: max\n"
        "  data arrival time    0.10\n"
        "  data required time   6.65\n"
        "           6.55   slack (MET)\n"
        "setup/hold analysis complete\n" + _PAD
    )
    result = era._check_sta(tmp_path)
    assert result.passed is True
    assert result.summary["real_violation_found"] is False


def test_sta_stub_rejected(tmp_path):
    rpt = tmp_path / "sta.rpt"
    rpt.write_text("WNS=0 setup: OK hold: OK\n")
    result = era._check_sta(tmp_path)
    assert result.passed is False


def test_sta_missing_setup_hold_fail(tmp_path):
    rpt = tmp_path / "sta_final.rpt"
    rpt.write_text(
        "OpenSTA\nStartpoint: clk\nEndpoint: out\n"
        "WNS = -0.05 ns\nTNS = -1.2 ns\nslack summary\n" + _PAD
    )
    result = era._check_sta(tmp_path)
    assert result.passed is False
    assert result.summary["has_wns_tns"] is True
    assert result.summary["has_setup_hold"] is False


# ---------------------------------------------------------------------------
# IR-drop mode
# ---------------------------------------------------------------------------
def test_ir_drop_pass(tmp_path):
    rpt = tmp_path / "ir_drop.rpt"
    rpt.write_text(
        "OpenROAD PSM IR-drop analysis\n"
        "power grid mesh nodes: 12458\n"
        "max IR drop: 15 mV drop on VDD rail\n"
        "worst voltage drop 0.5% Vdd\nstatic IR: 12 mV\ndynamic IR: 15 mV\n" + _PAD
    )
    result = era._check_ir_drop(tmp_path)
    assert result.passed is True
    assert result.summary["has_drop_value"] is True


def test_ir_drop_stub_rejected(tmp_path):
    rpt = tmp_path / "ir.rpt"
    rpt.write_text("IR: 6 mV OK\n")
    result = era._check_ir_drop(tmp_path)
    assert result.passed is False


# ---------------------------------------------------------------------------
# CLI: --mode is required
# ---------------------------------------------------------------------------
def test_cli_mode_required():
    with pytest.raises(SystemExit) as exc_info:
        era.main(["some_dir"])
    assert exc_info.value.code == 2  # argparse error
