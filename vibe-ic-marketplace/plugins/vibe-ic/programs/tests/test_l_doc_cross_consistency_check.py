"""tests/test_l_doc_cross_consistency_check.py

D3 program-first capture of the phase1-output-verify "Cross-doc
consistency" checklist (item 3). Two structural set-membership relations:

  R_pin_table_subset_ports     L1.pin_table names ⊆ L9 port names
  R_otp_bytes_subset_layout    L11.otp_bytes addrs ⊆ L4.otp_layout addrs

Coverage:
  * PASS                — every L1 pin lands in L9 ports (real corpus + fixture)
  * real FAIL           — an L1 pin absent from L9 ports (the 2nd__serv corpus
                          divergence, reproduced as a fixture)
  * FAIL                — an L11 OTP byte targets an address L4 never declares
  * escape-valve N/A    — empty L9 ports + no_top_module_in_input is NOT a FAIL
  * missing-data honesty— generated_docs absent => VACUOUS_PASS, never a silent
                          clean PASS
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.l_doc_cross_consistency_check import check, main


def _w(proj: Path, layer_file: str, payload: dict) -> None:
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / layer_file).write_text(json.dumps(payload, ensure_ascii=False))


# ---------------------------------------------------------------------------
# PASS
# ---------------------------------------------------------------------------
def test_pin_table_subset_ports_pass(tmp_path: Path) -> None:
    _w(tmp_path, "L1_DATASHEET.json", {
        "ic_name": "demo",
        "pin_table": [
            {"name": "clk", "rtl_name": "clk"},
            {"name": "rst_n", "rtl_name": "rst_n"},
            {"name": "data_o", "rtl_name": "data_o", "aliases": ["dout"]},
        ],
    })
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", {
        "ic_name": "demo",
        "ports": [
            {"name": "clk"}, {"name": "rst_n"}, {"name": "data_o"},
            {"name": "extra_internal"},
        ],
    })
    verdict, findings, _ = check(tmp_path)
    assert verdict == "PASS", findings
    rel = {f.relation: f for f in findings}
    assert rel["R_pin_table_subset_ports"].verdict == "PASS"


def test_pin_alias_matches_port(tmp_path: Path) -> None:
    # L1 pin's primary name differs from L9, but an alias matches.
    _w(tmp_path, "L1_DATASHEET.json", {
        "pin_table": [{"name": "BUS", "aliases": ["bus_rx"], "rtl_name": "bus_rx"}],
    })
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", {"ports": [{"name": "bus_rx"}]})
    verdict, findings, _ = check(tmp_path)
    assert verdict == "PASS"


# ---------------------------------------------------------------------------
# real FAIL — reproduces the 2nd__serv corpus divergence
# ---------------------------------------------------------------------------
def test_pin_table_subset_ports_real_fail(tmp_path: Path) -> None:
    # L1 declares the full SoC pinout; L9 lists only the bare core ports.
    _w(tmp_path, "L1_DATASHEET.json", {
        "pin_table": [
            {"name": "clk"}, {"name": "i_rst"},
            {"name": "o_wb_ext_adr"}, {"name": "o_wb_ext_dat"},
            {"name": "o_rreg0"}, {"name": "o_rreg1"},
        ],
    })
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", {
        # No escape flag -> the missing pins are a genuine inconsistency.
        "no_top_module_in_input": False,
        "no_integration_in_input": False,
        "ports": [{"name": "clk"}, {"name": "i_rst"}],
    })
    verdict, findings, summary = check(tmp_path)
    assert verdict == "FAIL", findings
    rel = {f.relation: f for f in findings}
    f = rel["R_pin_table_subset_ports"]
    assert f.verdict == "FAIL"
    # The four SoC-only pins are reported as violations.
    assert set(f.violations) >= {"o_wb_ext_adr", "o_wb_ext_dat",
                                 "o_rreg0", "o_rreg1"}
    # exit code path
    assert main([str(tmp_path)]) == 1


def test_otp_bytes_undeclared_address_fail(tmp_path: Path) -> None:
    _w(tmp_path, "L11_OTP_CONTENT.json", {
        "otp_bytes": [
            {"address": 0, "value": 1},
            {"address": 8, "value": 2},   # 8 is NOT declared in L4 below
        ],
    })
    _w(tmp_path, "L4_REGMAP.json", {
        "otp_layout": {
            "fields": [{"name": "lot", "offset": 0}, {"name": "wafer", "offset": 4}],
        },
    })
    verdict, findings, _ = check(tmp_path)
    assert verdict == "FAIL", findings
    rel = {f.relation: f for f in findings}
    assert rel["R_otp_bytes_subset_layout"].verdict == "FAIL"
    assert 8 in rel["R_otp_bytes_subset_layout"].violations


def test_otp_bytes_subset_layout_pass(tmp_path: Path) -> None:
    _w(tmp_path, "L11_OTP_CONTENT.json", {
        "otp_bytes": [{"address": 0}, {"address": "0x04"}],
    })
    _w(tmp_path, "L4_REGMAP.json", {
        "otp_layout": {"fields": [{"name": "a", "offset": 0},
                                  {"name": "b", "offset": 4}]},
    })
    verdict, findings, _ = check(tmp_path)
    assert verdict == "PASS"


# ---------------------------------------------------------------------------
# Escape-valve N/A (the no_<field>_in_input convention) — must NOT FAIL
# ---------------------------------------------------------------------------
def test_empty_l9_ports_with_escape_flag_is_na(tmp_path: Path) -> None:
    # 4th__serv shape: L1 has pins, L9 ports empty but flagged absent.
    _w(tmp_path, "L1_DATASHEET.json", {
        "pin_table": [{"name": "clk"}, {"name": "i_clk"}],
    })
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", {
        "no_top_module_in_input": True,
        "ports": [],
    })
    verdict, findings, _ = check(tmp_path)
    # N/A does not FAIL the gate — but with the other relation also N/A the
    # gate judged nothing, so it must not claim the plain-PASS tier either.
    assert verdict == "VACUOUS_PASS"
    rel = {f.relation: f for f in findings}
    assert rel["R_pin_table_subset_ports"].verdict == "N/A"


def test_empty_l9_ports_without_flag_fails(tmp_path: Path) -> None:
    # No escape flag + L1 has pins + L9 empty -> the pins cannot land => FAIL.
    _w(tmp_path, "L1_DATASHEET.json", {"pin_table": [{"name": "clk"}]})
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", {"ports": []})
    verdict, findings, _ = check(tmp_path)
    assert verdict == "FAIL"


def test_otp_empty_with_escape_flag_is_na(tmp_path: Path) -> None:
    _w(tmp_path, "L11_OTP_CONTENT.json", {
        "no_otp_in_input": True, "otp_bytes": [],
    })
    _w(tmp_path, "L4_REGMAP.json", {"otp_layout": {"fields": []}})
    verdict, findings, _ = check(tmp_path)
    assert verdict == "VACUOUS_PASS"   # both relations N/A — nothing judged
    rel = {f.relation: f for f in findings}
    assert rel["R_otp_bytes_subset_layout"].verdict == "N/A"


# ---------------------------------------------------------------------------
# missing-data honesty
# ---------------------------------------------------------------------------
def test_no_generated_docs_is_vacuous_pass(tmp_path: Path) -> None:
    verdict, findings, summary = check(tmp_path)
    assert verdict == "VACUOUS_PASS"
    assert findings == []
    assert summary["generated_docs"] is None
    assert main([str(tmp_path)]) == 0


def test_layers_absent_relations_na(tmp_path: Path) -> None:
    # generated_docs exists but only an unrelated L doc present.
    _w(tmp_path, "L2_FRS.json", {"ic_name": "x"})
    verdict, findings, _ = check(tmp_path)
    assert verdict == "VACUOUS_PASS"  # both relations N/A
    assert all(f.verdict == "N/A" for f in findings)


def test_bad_target_returns_2(tmp_path: Path) -> None:
    assert main([str(tmp_path / "does_not_exist")]) == 2


# ---------------------------------------------------------------------------
# vibe-ic#693 — a gate that judged NOTHING must not be credited a plain PASS.
#
# Both relations can legitimately be N/A at once (an IC with no pin_table and
# no OTP — reachable via the documented `no_*_in_input` escape valves). The
# driver used to return `"FAIL" if fails else "PASS"`, so that corpus printed
# `PASS: … pass=0 fail=0 na=2` and exited 0: the ordinary verdict tier awarded
# over zero relations examined. rc stays 0 (this is not a failure); what
# changes is the tier, signalled by the `VACUOUS_PASS` line-start sentinel
# that `flow_compliance_check._stdout_signals_vacuous` reads.
# ---------------------------------------------------------------------------
def test_all_relations_na_is_vacuous_not_plain_pass(tmp_path: Path) -> None:
    _w(tmp_path, "L1_DATASHEET.json", {"pin_table": [],
                                       "no_pin_table_in_input": True})
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", {"ports": [],
                                              "no_top_module_in_input": True})
    _w(tmp_path, "L11_OTP_CONTENT.json", {"otp_bytes": [],
                                          "no_otp_in_input": True})
    _w(tmp_path, "L4_REGMAP.json", {"otp_layout": {},
                                    "no_otp_layout_in_input": True})
    verdict, findings, summary = check(tmp_path)
    assert verdict == "VACUOUS_PASS"
    assert summary["pass"] == 0 and summary["fail"] == 0 and summary["na"] == 2
    assert all(f.verdict == "N/A" for f in findings)


def test_all_relations_na_prints_the_vacuous_sentinel_and_exits_0(
        tmp_path: Path, capsys) -> None:
    """The tier is only real if the CONSUMER can see it. flow_compliance_check
    promotes on a line that STARTS with `VACUOUS_PASS`; assert that shape, not
    merely the returned verdict string."""
    _w(tmp_path, "L1_DATASHEET.json", {"pin_table": [],
                                       "no_pin_table_in_input": True})
    _w(tmp_path, "L11_OTP_CONTENT.json", {"otp_bytes": [],
                                          "no_otp_in_input": True})
    assert main([str(tmp_path)]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("VACUOUS_PASS"), first


def test_one_relation_judged_is_still_a_plain_pass(tmp_path: Path) -> None:
    """Guard the other direction: the vacuous tier must NOT swallow a real
    PASS just because the OTHER relation was N/A."""
    _w(tmp_path, "L1_DATASHEET.json", {"pin_table": [{"name": "clk"}]})
    _w(tmp_path, "L9_INTEGRATION_SPEC.json", {"ports": [{"name": "clk"}]})
    verdict, _, summary = check(tmp_path)
    assert verdict == "PASS"
    assert summary["pass"] == 1 and summary["na"] == 1
